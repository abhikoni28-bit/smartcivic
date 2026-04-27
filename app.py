from flask import Flask, render_template, request, redirect, url_for, session, flash, g, jsonify
import sqlite3, os, uuid, json, random, smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta
from urllib.parse import quote_plus
from functools import wraps

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "civic_pulse_major_2026_secret")

# ── EMAIL CONFIG (stored in DB — configure via Admin → Email Settings) ────────
OTP_EXPIRY_MINUTES = 5

def get_email_config():
    """Load SMTP config from DB at runtime."""
    db = sqlite3.connect(os.path.join(os.path.dirname(os.path.abspath(__file__)), "database.db"))
    db.row_factory = sqlite3.Row
    row = db.execute("SELECT * FROM email_config WHERE id=1").fetchone()
    db.close()
    if row:
        return dict(row)
    return {"smtp_host":"smtp.gmail.com","smtp_port":587,"sender_email":"","sender_password":"","sender_name":"CivicPulse Portal","is_configured":0}

# ── FIX 1: Use absolute path so uploads always land in the right folder ──────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# On Render (and similar hosts) use the mounted persistent disk at /data so
# the SQLite file and uploads survive deploys.  Fall back to the project
# directory for local development.
PERSISTENT_DIR = "/data" if os.path.isdir("/data") else BASE_DIR

UPLOAD_FOLDER = os.path.join(PERSISTENT_DIR, "uploads")
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024
ALLOWED_EXT = {"png", "jpg", "jpeg", "gif", "webp"}
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

DATABASE = os.path.join(PERSISTENT_DIR, "database.db")

COMPLAINT_TYPES = ["Road Damage", "Water Supply", "Electricity", "Sewage/Drainage", "Street Light",
                   "Garbage Collection", "Noise Pollution", "Public Property Damage", "Other"]

DEPARTMENTS = ["Public Works", "Water Board", "Electricity Board", "Sanitation", "Municipal Corporation"]

# ─── DB ───────────────────────────────────────────────────────────────────────
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(e=None):
    db = g.pop("db", None)
    if db: db.close()

def init_db():
    db = sqlite3.connect(DATABASE)
    db.row_factory = sqlite3.Row
    db.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        phone TEXT,
        address TEXT,
        ward TEXT,
        profile_pic TEXT,
        is_admin INTEGER DEFAULT 0,
        is_staff INTEGER DEFAULT 0,
        department TEXT,
        is_active INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS complaints (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        complaint_id TEXT UNIQUE NOT NULL,
        type TEXT NOT NULL,
        subject TEXT NOT NULL,
        description TEXT NOT NULL,
        location TEXT NOT NULL,
        ward TEXT,
        latitude TEXT,
        longitude TEXT,
        priority TEXT DEFAULT 'Normal',
        image_path TEXT,
        status TEXT DEFAULT 'Pending',
        assigned_to INTEGER,
        department TEXT,
        admin_remarks TEXT,
        resolved_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id),
        FOREIGN KEY (assigned_to) REFERENCES users(id)
    );
    CREATE TABLE IF NOT EXISTS complaint_updates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        complaint_id INTEGER NOT NULL,
        updated_by INTEGER NOT NULL,
        old_status TEXT,
        new_status TEXT,
        remarks TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (complaint_id) REFERENCES complaints(id),
        FOREIGN KEY (updated_by) REFERENCES users(id)
    );
    CREATE TABLE IF NOT EXISTS notices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        content TEXT NOT NULL,
        posted_by INTEGER NOT NULL,
        is_active INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (posted_by) REFERENCES users(id)
    );
    CREATE TABLE IF NOT EXISTS feedback (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        complaint_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        rating INTEGER,
        comment TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (complaint_id) REFERENCES complaints(id),
        FOREIGN KEY (user_id) REFERENCES users(id)
    );
    CREATE TABLE IF NOT EXISTS otp_tokens (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT NOT NULL,
        otp TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        expires_at TIMESTAMP NOT NULL,
        is_used INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS email_config (
        id INTEGER PRIMARY KEY CHECK (id=1),
        smtp_host TEXT DEFAULT 'smtp.gmail.com',
        smtp_port INTEGER DEFAULT 587,
        sender_email TEXT DEFAULT '',
        sender_password TEXT DEFAULT '',
        sender_name TEXT DEFAULT 'CivicPulse Portal',
        is_configured INTEGER DEFAULT 0
    );
    INSERT OR IGNORE INTO email_config (id) VALUES (1);
    """)
    # Seed admin
    if not db.execute("SELECT id FROM users WHERE email='admin@civic.gov.in'").fetchone():
        db.execute("INSERT INTO users (name,email,password,is_admin,department) VALUES (?,?,?,?,?)",
            ("Super Admin","admin@civic.gov.in",generate_password_hash("Admin@123"),1,"Municipal Corporation"))
    # Seed staff
    if not db.execute("SELECT id FROM users WHERE email='staff@civic.gov.in'").fetchone():
        db.execute("INSERT INTO users (name,email,password,is_staff,department) VALUES (?,?,?,?,?)",
            ("Field Officer","staff@civic.gov.in",generate_password_hash("Staff@123"),1,"Public Works"))
    # Seed a second staff for round-robin demo
    if not db.execute("SELECT id FROM users WHERE email='staff2@civic.gov.in'").fetchone():
        db.execute("INSERT INTO users (name,email,password,is_staff,department) VALUES (?,?,?,?,?)",
            ("Field Officer 2","staff2@civic.gov.in",generate_password_hash("Staff@123"),1,"Sanitation"))
    # Seed notices
    if not db.execute("SELECT id FROM notices").fetchone():
        admin_row = db.execute("SELECT id FROM users WHERE is_admin=1 LIMIT 1").fetchone()
        admin_id = admin_row["id"] if admin_row else None
        db.execute("INSERT INTO notices (title,content,posted_by) VALUES (?,?,?)",
            ("Welcome to CivicPulse 2.0","Our upgraded complaint portal is now live. Report civic issues 24×7 and track real-time resolution.", admin_id))
        db.execute("INSERT INTO notices (title,content,posted_by) VALUES (?,?,?)",
            ("Scheduled Maintenance Alert","Water supply will be interrupted on 15 Apr 2026 from 9 AM–2 PM in Wards 4, 7 & 12.", admin_id))
    db.commit()
    db.close()

def allowed_file(f):
    return "." in f and f.rsplit(".", 1)[1].lower() in ALLOWED_EXT

def gen_cid():
    return "CMP-" + uuid.uuid4().hex[:8].upper()

@app.context_processor
def utility_processor():
    return {"quote_plus": quote_plus}

# Serve uploaded complaint images from the persistent-disk folder
@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    from flask import send_from_directory
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)

# ─── DECORATORS ───────────────────────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            flash("Please login to continue.", "warning")
            return redirect(url_for("citizen_login"))
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("is_admin"):
            flash("Superadmin access required.", "danger")
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return decorated

def staff_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not (session.get("is_admin") or session.get("is_staff")):
            flash("Staff access required.", "danger")
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return decorated

# ─── FIX 3: Auto-assignment helper (round-robin load balancing) ───────────────
def auto_assign_officer(db):
    """
    Returns the Field Officer id with the fewest currently open (non-resolved/rejected)
    complaints. Ties are broken by user id (oldest account first).
    Only staff (is_staff=1, is_admin=0) are eligible.
    """
    row = db.execute("""
        SELECT u.id
        FROM users u
        LEFT JOIN complaints c
            ON c.assigned_to = u.id
            AND c.status NOT IN ('Resolved', 'Rejected')
        WHERE u.is_staff = 1
          AND u.is_admin = 0
          AND u.is_active = 1
        GROUP BY u.id
        ORDER BY COUNT(c.id) ASC, u.id ASC
        LIMIT 1
    """).fetchone()
    return row["id"] if row else None

# ─── PUBLIC ROUTES ─────────────────────────────────────────────────────────
@app.route("/")
def index():
    db = get_db()
    stats = {
        "total": db.execute("SELECT COUNT(*) FROM complaints").fetchone()[0],
        "resolved": db.execute("SELECT COUNT(*) FROM complaints WHERE status='Resolved'").fetchone()[0],
        "pending": db.execute("SELECT COUNT(*) FROM complaints WHERE status='Pending'").fetchone()[0],
        "users": db.execute("SELECT COUNT(*) FROM users WHERE is_admin=0 AND is_staff=0").fetchone()[0],
    }
    notices = db.execute("SELECT n.*,u.name as poster FROM notices n JOIN users u ON n.posted_by=u.id WHERE n.is_active=1 ORDER BY n.created_at DESC LIMIT 3").fetchall()
    recent = db.execute("SELECT c.complaint_id,c.type,c.location,c.status,c.created_at FROM complaints c ORDER BY c.created_at DESC LIMIT 5").fetchall()
    return render_template("index.html", stats=stats, notices=notices, recent=recent)

@app.route("/track", methods=["GET","POST"])
def track():
    result = None
    history = []
    cid = request.args.get("cid","")
    if cid:
        db = get_db()
        result = db.execute(
            "SELECT c.*,u.name as citizen_name FROM complaints c JOIN users u ON c.user_id=u.id WHERE c.complaint_id=?", (cid,)
        ).fetchone()
        if result:
            history = db.execute(
                "SELECT cu.*,u.name as by_name FROM complaint_updates cu JOIN users u ON cu.updated_by=u.id WHERE cu.complaint_id=? ORDER BY cu.created_at ASC", (result["id"],)
            ).fetchall()
        else:
            flash("Complaint ID not found.", "danger")
    return render_template("track.html", complaint=result, history=history, cid=cid)

@app.route("/about")
def about():
    return render_template("about.html")

# ─── CITIZEN AUTH ──────────────────────────────────────────────────────────
@app.route("/citizen/login", methods=["GET","POST"])
def citizen_login():
    if session.get("user_id"):
        return redirect(url_for("citizen_dashboard"))
    if request.method == "POST":
        db = get_db()
        user = db.execute("SELECT * FROM users WHERE email=? AND is_admin=0 AND is_staff=0", (request.form["email"],)).fetchone()
        if user and check_password_hash(user["password"], request.form["password"]):
            if not user["is_active"]:
                flash("Your account is suspended. Contact admin.", "danger")
                return redirect(url_for("citizen_login"))
            session.update({"user_id":user["id"],"user_name":user["name"],"is_admin":0,"is_staff":0})
            flash(f"Welcome back, {user['name']}! 👋", "success")
            return redirect(url_for("citizen_dashboard"))
        flash("Invalid email or password.", "danger")
    return render_template("citizen_login.html")

@app.route("/citizen/register", methods=["GET","POST"])
def citizen_register():
    if request.method == "POST":
        db = get_db()
        email = request.form["email"]
        if db.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone():
            flash("Email already registered.", "danger")
            return redirect(url_for("citizen_register"))
        db.execute("INSERT INTO users (name,email,password,phone,address,ward) VALUES (?,?,?,?,?,?)",
            (request.form["name"], email, generate_password_hash(request.form["password"]),
             request.form.get("phone",""), request.form.get("address",""), request.form.get("ward","")))
        db.commit()
        flash("Registration successful! Please login.", "success")
        return redirect(url_for("citizen_login"))
    return render_template("citizen_register.html")

@app.route("/citizen/logout")
def citizen_logout():
    session.clear()
    flash("Logged out successfully.", "info")
    return redirect(url_for("index"))

# ─── CITIZEN PORTAL ────────────────────────────────────────────────────────
@app.route("/citizen/dashboard")
@login_required
def citizen_dashboard():
    db = get_db()
    uid = session["user_id"]
    complaints = db.execute("SELECT * FROM complaints WHERE user_id=? ORDER BY created_at DESC LIMIT 5", (uid,)).fetchall()
    stats = {
        "total": db.execute("SELECT COUNT(*) FROM complaints WHERE user_id=?", (uid,)).fetchone()[0],
        "pending": db.execute("SELECT COUNT(*) FROM complaints WHERE user_id=? AND status='Pending'", (uid,)).fetchone()[0],
        "progress": db.execute("SELECT COUNT(*) FROM complaints WHERE user_id=? AND status='In Progress'", (uid,)).fetchone()[0],
        "resolved": db.execute("SELECT COUNT(*) FROM complaints WHERE user_id=? AND status='Resolved'", (uid,)).fetchone()[0],
    }
    notices = db.execute("SELECT * FROM notices WHERE is_active=1 ORDER BY created_at DESC LIMIT 3").fetchall()
    return render_template("citizen_dashboard.html", complaints=complaints, stats=stats, notices=notices)

# ─── FIX 1 + FIX 3: file_complaint ────────────────────────────────────────────
@app.route("/citizen/complaint/new", methods=["GET","POST"])
@login_required
def file_complaint():
    if request.method == "POST":
        # ── FIX 1: Save image with absolute path; store only the relative
        #            static-subfolder path so url_for('static', filename=...) works.
        img_path = None
        if "image" in request.files:
            f = request.files["image"]
            if f and f.filename and allowed_file(f.filename):
                fn = secure_filename(f"{uuid.uuid4().hex}_{f.filename}")
                save_path = os.path.join(app.config["UPLOAD_FOLDER"], fn)
                f.save(save_path)
                # Store path relative to the /uploads/ route
                img_path = fn

        priority = request.form.get("priority", "Normal")
        cid = gen_cid()
        db = get_db()

        # ── FIX 3: Auto-assign High / Urgent; leave Normal in the unassigned pool
        assigned_to = None
        initial_status = "Pending"
        if priority in ("High", "Urgent"):
            assigned_to = auto_assign_officer(db)
            if assigned_to:
                initial_status = "In Progress"

        db.execute("""INSERT INTO complaints
            (user_id,complaint_id,type,subject,description,location,ward,priority,
             image_path,assigned_to,status)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (session["user_id"], cid, request.form["type"], request.form["subject"],
             request.form["description"], request.form["location"],
             request.form.get("ward",""), priority, img_path, assigned_to, initial_status))

        # Log the auto-assignment in the audit trail
        if assigned_to:
            new_row = db.execute("SELECT id FROM complaints WHERE complaint_id=?", (cid,)).fetchone()
            db.execute(
                "INSERT INTO complaint_updates (complaint_id,updated_by,old_status,new_status,remarks) VALUES (?,?,?,?,?)",
                (new_row["id"], session["user_id"], "Pending", "In Progress",
                 "Auto-assigned to Field Officer based on High/Urgent priority."))
            # ── EMAIL NOTIFICATION: citizen gets "In Progress" email on auto-assign
            user = get_db().execute("SELECT email FROM users WHERE id=?", (session["user_id"],)).fetchone()
            if user:
                send_status_email(user["email"], cid, request.form["subject"], "In Progress")

        db.commit()
        flash(f"Complaint <strong>{cid}</strong> filed successfully! Keep this ID for tracking.", "success")
        return redirect(url_for("my_complaints"))
    return render_template("file_complaint.html", types=COMPLAINT_TYPES)

@app.route("/citizen/complaints")
@login_required
def my_complaints():
    db = get_db()
    status_f = request.args.get("status","")
    q = "SELECT * FROM complaints WHERE user_id=?"
    params = [session["user_id"]]
    if status_f:
        q += " AND status=?"; params.append(status_f)
    q += " ORDER BY created_at DESC"
    complaints = db.execute(q, params).fetchall()
    return render_template("my_complaints.html", complaints=complaints, status_f=status_f)

@app.route("/citizen/complaint/<int:cid>")
@login_required
def view_complaint(cid):
    db = get_db()
    c = db.execute("SELECT * FROM complaints WHERE id=? AND user_id=?", (cid, session["user_id"])).fetchone()
    if not c:
        flash("Complaint not found.", "danger")
        return redirect(url_for("my_complaints"))
    history = db.execute(
        "SELECT cu.*,u.name as by_name FROM complaint_updates cu JOIN users u ON cu.updated_by=u.id WHERE cu.complaint_id=? ORDER BY cu.created_at ASC", (cid,)
    ).fetchall()
    fb = db.execute("SELECT * FROM feedback WHERE complaint_id=? AND user_id=?", (cid, session["user_id"])).fetchone()
    return render_template("view_complaint.html", c=c, history=history, feedback=fb)

@app.route("/citizen/complaint/<int:cid>/feedback", methods=["POST"])
@login_required
def submit_feedback(cid):
    db = get_db()
    if not db.execute("SELECT id FROM feedback WHERE complaint_id=? AND user_id=?", (cid, session["user_id"])).fetchone():
        db.execute("INSERT INTO feedback (complaint_id,user_id,rating,comment) VALUES (?,?,?,?)",
            (cid, session["user_id"], request.form.get("rating"), request.form.get("comment","")))
        db.commit()
        flash("Thank you for your feedback!", "success")
    return redirect(url_for("view_complaint", cid=cid))

@app.route("/citizen/profile", methods=["GET","POST"])
@login_required
def citizen_profile():
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id=?", (session["user_id"],)).fetchone()
    if request.method == "POST":
        db.execute("UPDATE users SET name=?,phone=?,address=?,ward=? WHERE id=?",
            (request.form["name"], request.form.get("phone",""), request.form.get("address",""),
             request.form.get("ward",""), session["user_id"]))
        db.commit()
        session["user_name"] = request.form["name"]
        flash("Profile updated successfully!", "success")
        return redirect(url_for("citizen_profile"))
    return render_template("citizen_profile.html", user=user)

# ─── ADMIN AUTH ────────────────────────────────────────────────────────────
@app.route("/admin/login", methods=["GET","POST"])
def admin_login():
    if session.get("is_admin") or session.get("is_staff"):
        return redirect(url_for("admin_dashboard"))
    if request.method == "POST":
        db = get_db()
        user = db.execute("SELECT * FROM users WHERE email=? AND (is_admin=1 OR is_staff=1)", (request.form["email"],)).fetchone()
        if user and check_password_hash(user["password"], request.form["password"]):
            session.update({"user_id":user["id"],"user_name":user["name"],
                           "is_admin":user["is_admin"],"is_staff":user["is_staff"],"department":user["department"]})
            flash(f"Welcome, {user['name']}!", "success")
            return redirect(url_for("admin_dashboard"))
        flash("Invalid admin credentials.", "danger")
    return render_template("admin_login.html")

@app.route("/admin/logout")
def admin_logout():
    session.clear()
    return redirect(url_for("admin_login"))

# ─── ADMIN DASHBOARD ───────────────────────────────────────────────────────
@app.route("/admin/dashboard")
@staff_required
def admin_dashboard():
    db = get_db()
    stats = {
        "total": db.execute("SELECT COUNT(*) FROM complaints").fetchone()[0],
        "pending": db.execute("SELECT COUNT(*) FROM complaints WHERE status='Pending'").fetchone()[0],
        "progress": db.execute("SELECT COUNT(*) FROM complaints WHERE status='In Progress'").fetchone()[0],
        "resolved": db.execute("SELECT COUNT(*) FROM complaints WHERE status='Resolved'").fetchone()[0],
        "citizens": db.execute("SELECT COUNT(*) FROM users WHERE is_admin=0 AND is_staff=0").fetchone()[0],
        "rejected": db.execute("SELECT COUNT(*) FROM complaints WHERE status='Rejected'").fetchone()[0],
    }
    type_data = db.execute("SELECT type, COUNT(*) as cnt FROM complaints GROUP BY type ORDER BY cnt DESC").fetchall()

    # ── FIX 2: Show different recent-complaint views per role
    if session.get("is_admin"):
        # Superadmin sees everything
        recent = db.execute("""SELECT c.*,u.name as citizen_name,
            off.name as officer_name
            FROM complaints c
            JOIN users u ON c.user_id=u.id
            LEFT JOIN users off ON c.assigned_to=off.id
            ORDER BY c.created_at DESC LIMIT 8""").fetchall()
    else:
        # Field Officer sees only their assigned complaints
        recent = db.execute("""SELECT c.*,u.name as citizen_name,
            off.name as officer_name
            FROM complaints c
            JOIN users u ON c.user_id=u.id
            LEFT JOIN users off ON c.assigned_to=off.id
            WHERE c.assigned_to=?
            ORDER BY c.created_at DESC LIMIT 8""", (session["user_id"],)).fetchall()

    daily = []
    for i in range(6, -1, -1):
        d = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        cnt = db.execute("SELECT COUNT(*) FROM complaints WHERE DATE(created_at)=?", (d,)).fetchone()[0]
        daily.append({"date": (datetime.now()-timedelta(days=i)).strftime("%d %b"), "count": cnt})
    return render_template("admin_dashboard.html", stats=stats, recent=recent,
                           type_data=type_data, daily=json.dumps(daily))

@app.route("/admin/complaints")
@staff_required
def admin_complaints():
    db = get_db()
    status_f = request.args.get("status","")
    type_f = request.args.get("type","")
    priority_f = request.args.get("priority","")
    search = request.args.get("q","")

    q = """SELECT c.*,u.name as citizen_name,u.email as citizen_email,
               off.name as officer_name
           FROM complaints c
           JOIN users u ON c.user_id=u.id
           LEFT JOIN users off ON c.assigned_to=off.id"""
    params, wheres = [], []

    # ── FIX 2: Field Officers only see their own assigned complaints
    if session.get("is_staff") and not session.get("is_admin"):
        wheres.append("c.assigned_to=?"); params.append(session["user_id"])

    if status_f: wheres.append("c.status=?"); params.append(status_f)
    if type_f: wheres.append("c.type=?"); params.append(type_f)
    if priority_f: wheres.append("c.priority=?"); params.append(priority_f)
    if search:
        wheres.append("(c.complaint_id LIKE ? OR c.description LIKE ? OR u.name LIKE ? OR c.location LIKE ?)")
        params += [f"%{search}%"]*4
    if wheres: q += " WHERE " + " AND ".join(wheres)
    q += " ORDER BY c.created_at DESC"
    complaints = db.execute(q, params).fetchall()

    # Staff list only passed to Superadmin for assignment
    staff_list = []
    if session.get("is_admin"):
        staff_list = db.execute("SELECT id,name,department FROM users WHERE is_staff=1 AND is_admin=0 AND is_active=1").fetchall()

    return render_template("admin_complaints.html", complaints=complaints, staff_list=staff_list,
                           status_f=status_f, type_f=type_f, priority_f=priority_f, search=search,
                           types=COMPLAINT_TYPES)

# ── FIX 2: admin_view_complaint — role-gated form panels ─────────────────────
@app.route("/admin/complaint/<int:cid>", methods=["GET","POST"])
@staff_required
def admin_view_complaint(cid):
    db = get_db()
    is_superadmin = bool(session.get("is_admin"))
    is_field_officer = bool(session.get("is_staff") and not session.get("is_admin"))

    # Field Officers can only touch complaints assigned to them
    if is_field_officer:
        c = db.execute(
            """SELECT c.*,u.name as citizen_name,u.email as citizen_email,u.phone as citizen_phone
               FROM complaints c JOIN users u ON c.user_id=u.id
               WHERE c.id=? AND c.assigned_to=?""",
            (cid, session["user_id"])).fetchone()
    else:
        c = db.execute(
            """SELECT c.*,u.name as citizen_name,u.email as citizen_email,u.phone as citizen_phone
               FROM complaints c JOIN users u ON c.user_id=u.id WHERE c.id=?""",
            (cid,)).fetchone()

    if not c:
        flash("Complaint not found or not assigned to you.", "danger")
        return redirect(url_for("admin_complaints"))

    if request.method == "POST":
        old_status = c["status"]

        if is_field_officer:
            # ── FIX 2: Field Officers can ONLY update status and add remarks.
            #            They cannot reassign or change department.
            allowed_transitions = {
                "Pending": ["In Progress"],
                "In Progress": ["Resolved"],
            }
            new_status = request.form.get("status", old_status)
            if new_status not in allowed_transitions.get(old_status, []):
                flash(f"Invalid status transition: {old_status} → {new_status}.", "danger")
                return redirect(url_for("admin_view_complaint", cid=cid))
            remarks = request.form.get("remarks","")
            resolved_at = datetime.now() if new_status == "Resolved" else None
            db.execute("UPDATE complaints SET status=?,admin_remarks=?,updated_at=?,resolved_at=? WHERE id=?",
                (new_status, remarks, datetime.now(), resolved_at, cid))
            db.execute("INSERT INTO complaint_updates (complaint_id,updated_by,old_status,new_status,remarks) VALUES (?,?,?,?,?)",
                (cid, session["user_id"], old_status, new_status, remarks))
            # ── EMAIL NOTIFICATION: notify citizen of status change ──────────
            send_status_email(c["citizen_email"], c["complaint_id"], c["subject"], new_status)

        else:
            # ── Superadmin can update everything including assignment
            new_status = request.form["status"]
            remarks = request.form.get("remarks","")
            assigned = request.form.get("assigned_to") or None
            resolved_at = datetime.now() if new_status == "Resolved" else None
            db.execute(
                "UPDATE complaints SET status=?,admin_remarks=?,assigned_to=?,department=?,updated_at=?,resolved_at=? WHERE id=?",
                (new_status, remarks, assigned, request.form.get("department",""), datetime.now(), resolved_at, cid))
            db.execute("INSERT INTO complaint_updates (complaint_id,updated_by,old_status,new_status,remarks) VALUES (?,?,?,?,?)",
                (cid, session["user_id"], old_status, new_status, remarks))
            # ── EMAIL NOTIFICATION: notify citizen of status change ──────────
            send_status_email(c["citizen_email"], c["complaint_id"], c["subject"], new_status)

        db.commit()
        flash("Complaint updated successfully!", "success")
        return redirect(url_for("admin_view_complaint", cid=cid))

    history = db.execute(
        "SELECT cu.*,u.name as by_name FROM complaint_updates cu JOIN users u ON cu.updated_by=u.id WHERE cu.complaint_id=? ORDER BY cu.created_at",
        (cid,)).fetchall()
    # Only Superadmin gets the full staff list for reassignment
    staff_list = []
    if is_superadmin:
        staff_list = db.execute(
            "SELECT id,name,department FROM users WHERE is_staff=1 AND is_admin=0 AND is_active=1").fetchall()
    feedback = db.execute("SELECT * FROM feedback WHERE complaint_id=?", (cid,)).fetchone()
    return render_template("admin_view_complaint.html", c=c, history=history,
                           staff_list=staff_list, feedback=feedback,
                           departments=DEPARTMENTS,
                           is_superadmin=is_superadmin,
                           is_field_officer=is_field_officer)

@app.route("/admin/users")
@admin_required
def admin_users():
    db = get_db()
    search = request.args.get("q","")
    role_f = request.args.get("role","")
    q = "SELECT u.*,(SELECT COUNT(*) FROM complaints WHERE user_id=u.id) as complaint_count FROM users u"
    params, wheres = [], []
    if search:
        wheres.append("(u.name LIKE ? OR u.email LIKE ?)"); params += [f"%{search}%"]*2
    if role_f == "admin": wheres.append("u.is_admin=1")
    elif role_f == "staff": wheres.append("u.is_staff=1")
    elif role_f == "citizen": wheres.append("u.is_admin=0 AND u.is_staff=0")
    if wheres: q += " WHERE " + " AND ".join(wheres)
    q += " ORDER BY u.created_at DESC"
    users = db.execute(q, params).fetchall()
    return render_template("admin_users.html", users=users, search=search, role_f=role_f)

@app.route("/admin/users/add", methods=["POST"])
@admin_required
def admin_add_user():
    db = get_db()
    email = request.form["email"]
    if db.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone():
        flash("Email already exists.", "danger")
        return redirect(url_for("admin_users"))
    role = request.form.get("role","citizen")
    is_admin = 1 if role == "admin" else 0
    is_staff = 1 if role == "staff" else 0
    db.execute("INSERT INTO users (name,email,password,phone,department,is_admin,is_staff) VALUES (?,?,?,?,?,?,?)",
        (request.form["name"], email, generate_password_hash(request.form["password"]),
         request.form.get("phone",""), request.form.get("department",""), is_admin, is_staff))
    db.commit()
    flash("User added successfully!", "success")
    return redirect(url_for("admin_users"))

@app.route("/admin/users/<int:uid>/toggle")
@admin_required
def toggle_user(uid):
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if user:
        db.execute("UPDATE users SET is_active=? WHERE id=?", (0 if user["is_active"] else 1, uid))
        db.commit()
        flash("User status updated.", "success")
    return redirect(url_for("admin_users"))

@app.route("/admin/users/<int:uid>/delete")
@admin_required
def delete_user(uid):
    db = get_db()
    db.execute("DELETE FROM users WHERE id=? AND is_admin=0", (uid,))
    db.commit()
    flash("User deleted.", "success")
    return redirect(url_for("admin_users"))

@app.route("/admin/notices", methods=["GET","POST"])
@admin_required
def admin_notices():
    db = get_db()
    if request.method == "POST":
        db.execute("INSERT INTO notices (title,content,posted_by) VALUES (?,?,?)",
            (request.form["title"], request.form["content"], session["user_id"]))
        db.commit()
        flash("Notice posted!", "success")
        return redirect(url_for("admin_notices"))
    notices = db.execute("SELECT n.*,u.name as poster FROM notices n JOIN users u ON n.posted_by=u.id ORDER BY n.created_at DESC").fetchall()
    return render_template("admin_notices.html", notices=notices)

@app.route("/admin/notices/<int:nid>/toggle")
@admin_required
def toggle_notice(nid):
    db = get_db()
    n = db.execute("SELECT * FROM notices WHERE id=?", (nid,)).fetchone()
    if n:
        db.execute("UPDATE notices SET is_active=? WHERE id=?", (0 if n["is_active"] else 1, nid))
        db.commit()
    return redirect(url_for("admin_notices"))

@app.route("/admin/reports")
@staff_required
def admin_reports():
    db = get_db()
    type_data = db.execute("SELECT type, COUNT(*) as cnt FROM complaints GROUP BY type").fetchall()
    status_data = db.execute("SELECT status, COUNT(*) as cnt FROM complaints GROUP BY status").fetchall()
    priority_data = db.execute("SELECT priority, COUNT(*) as cnt FROM complaints GROUP BY priority").fetchall()
    ward_data = db.execute("SELECT ward, COUNT(*) as cnt FROM complaints WHERE ward!='' GROUP BY ward ORDER BY cnt DESC LIMIT 10").fetchall()
    monthly = db.execute("""SELECT strftime('%Y-%m',created_at) as month, COUNT(*) as cnt
        FROM complaints GROUP BY month ORDER BY month DESC LIMIT 6""").fetchall()
    avg_resolution = db.execute("""SELECT AVG(JULIANDAY(resolved_at)-JULIANDAY(created_at)) as avg_days
        FROM complaints WHERE status='Resolved' AND resolved_at IS NOT NULL""").fetchone()
    return render_template("admin_reports.html",
        type_data=json.dumps([{"type":r["type"],"cnt":r["cnt"]} for r in type_data]),
        status_data=json.dumps([{"status":r["status"],"cnt":r["cnt"]} for r in status_data]),
        priority_data=json.dumps([{"priority":r["priority"],"cnt":r["cnt"]} for r in priority_data]),
        ward_data=ward_data, monthly=json.dumps([{"month":r["month"],"cnt":r["cnt"]} for r in monthly]),
        avg_days=round(avg_resolution["avg_days"] or 0, 1))

# ─── API ───────────────────────────────────────────────────────────────────
@app.route("/api/stats")
def api_stats():
    db = get_db()
    return jsonify({
        "total": db.execute("SELECT COUNT(*) FROM complaints").fetchone()[0],
        "resolved": db.execute("SELECT COUNT(*) FROM complaints WHERE status='Resolved'").fetchone()[0],
        "pending": db.execute("SELECT COUNT(*) FROM complaints WHERE status='Pending'").fetchone()[0],
    })


# ═══════════════════════════════════════════════════════════════════════════════
# ─── OTP AUTHENTICATION SYSTEM ────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════

def generate_otp():
    """Generate a secure 6-digit OTP."""
    return str(random.randint(100000, 999999))

def send_otp_email(recipient_email, otp_code, recipient_name="Citizen"):
    """Send OTP email via SMTP. Returns (success: bool, error_msg: str)."""
    cfg = get_email_config()
    if not cfg.get("is_configured") or not cfg.get("sender_email"):
        return False, "Email not configured. Please set up SMTP in Admin → Email Settings."
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"Your CivicPulse Login OTP: {otp_code}"
        msg["From"]    = f"{cfg['sender_name']} <{cfg['sender_email']}>"
        msg["To"]      = recipient_email

        html_body = f"""<!DOCTYPE html>
<html>
<body style="margin:0;padding:0;background:#0f1117;font-family:'Segoe UI',Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#0f1117;padding:40px 20px;">
    <tr><td align="center">
      <table width="540" cellpadding="0" cellspacing="0"
             style="background:linear-gradient(135deg,#1a1d2e,#141622);border-radius:20px;
                    border:1px solid rgba(99,102,241,0.3);overflow:hidden;">
        <tr>
          <td style="background:linear-gradient(135deg,#6366f1,#8b5cf6);padding:32px 40px;text-align:center;">
            <h1 style="margin:0;color:#fff;font-size:28px;">CivicPulse</h1>
            <p style="margin:6px 0 0;color:rgba(255,255,255,0.85);font-size:14px;">Smart Civic Management Portal</p>
          </td>
        </tr>
        <tr>
          <td style="padding:40px;">
            <p style="color:#a0aec0;font-size:16px;margin:0 0 8px;">Hello, <strong style="color:#e2e8f0;">{recipient_name}</strong></p>
            <p style="color:#718096;font-size:14px;margin:0 0 32px;line-height:1.6;">
              Use the OTP below to complete your login. It expires in <strong style="color:#fbbf24;">{OTP_EXPIRY_MINUTES} minutes</strong>.
            </p>
            <div style="background:rgba(99,102,241,0.1);border:2px solid rgba(99,102,241,0.4);
                        border-radius:16px;padding:28px;text-align:center;margin-bottom:28px;">
              <p style="margin:0 0 8px;color:#718096;font-size:13px;letter-spacing:2px;text-transform:uppercase;">Your One-Time Password</p>
              <div style="font-size:48px;font-weight:800;letter-spacing:14px;color:#fff;
                          font-family:'Courier New',monospace;">{otp_code}</div>
            </div>
            <div style="background:rgba(251,191,36,0.08);border-left:3px solid #fbbf24;
                        border-radius:8px;padding:14px 18px;margin-bottom:28px;">
              <p style="margin:0;color:#fbbf24;font-size:13px;">
                Security Notice: Never share this OTP with anyone. CivicPulse staff will never ask for your OTP.
              </p>
            </div>
            <p style="color:#4a5568;font-size:13px;margin:0;line-height:1.6;">
              If you did not request this OTP, please ignore this email.
            </p>
          </td>
        </tr>
        <tr>
          <td style="background:rgba(0,0,0,0.3);padding:20px 40px;text-align:center;border-top:1px solid rgba(99,102,241,0.15);">
            <p style="margin:0;color:#4a5568;font-size:12px;">2026 CivicPulse Smart Civic Portal - Automated message, do not reply</p>
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""

        text_body = f"Your CivicPulse OTP is: {otp_code}\nExpires in {OTP_EXPIRY_MINUTES} minutes.\nDo not share this OTP with anyone."
        msg.attach(MIMEText(text_body, "plain"))
        msg.attach(MIMEText(html_body, "html"))

        with smtplib.SMTP(cfg["smtp_host"], int(cfg["smtp_port"])) as server:
            server.ehlo()
            server.starttls()
            server.login(cfg["sender_email"], cfg["sender_password"])
            server.sendmail(cfg["sender_email"], recipient_email, msg.as_string())
        return True, ""
    except Exception as e:
        return False, str(e)


def send_status_email(user_email, complaint_id, title, status):
    """
    Send a complaint status-update notification email to the citizen.
    Called whenever admin/staff updates a complaint's status.
    Returns (success: bool, error_msg: str).
    """
    cfg = get_email_config()
    if not cfg.get("is_configured") or not cfg.get("sender_email"):
        app.logger.warning("[STATUS EMAIL] Email not configured — skipping notification.")
        return False, "Email not configured."

    # Human-friendly status labels and messages
    status_meta = {
        "Pending": {
            "color": "#f59e0b",
            "icon": "⏳",
            "badge_bg": "rgba(245,158,11,0.15)",
            "badge_border": "rgba(245,158,11,0.4)",
            "message": "Your complaint has been received and is currently pending review by our team.",
            "action": "We will assign an officer shortly.",
        },
        "In Progress": {
            "color": "#6366f1",
            "icon": "🔧",
            "badge_bg": "rgba(99,102,241,0.15)",
            "badge_border": "rgba(99,102,241,0.4)",
            "message": "Great news! Your complaint is now being actively worked on by our field team.",
            "action": "We are working to resolve this as quickly as possible.",
        },
        "Resolved": {
            "color": "#10b981",
            "icon": "✅",
            "badge_bg": "rgba(16,185,129,0.15)",
            "badge_border": "rgba(16,185,129,0.4)",
            "message": "Your complaint has been resolved successfully. We hope the issue has been addressed to your satisfaction.",
            "action": "Please log in to submit your feedback and rate our service.",
        },
        "Rejected": {
            "color": "#ef4444",
            "icon": "❌",
            "badge_bg": "rgba(239,68,68,0.15)",
            "badge_border": "rgba(239,68,68,0.4)",
            "message": "After review, your complaint could not be processed at this time.",
            "action": "Please log in to view the admin remarks or file a new complaint if needed.",
        },
    }

    meta = status_meta.get(status, {
        "color": "#718096",
        "icon": "📋",
        "badge_bg": "rgba(113,128,150,0.15)",
        "badge_border": "rgba(113,128,150,0.4)",
        "message": f"The status of your complaint has been updated to: {status}.",
        "action": "Log in to the portal to view full details.",
    })

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"Complaint Update [{complaint_id}] — {status} | CivicPulse"
        msg["From"]    = f"{cfg['sender_name']} <{cfg['sender_email']}>"
        msg["To"]      = user_email

        html_body = f"""<!DOCTYPE html>
<html>
<body style="margin:0;padding:0;background:#0f1117;font-family:'Segoe UI',Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#0f1117;padding:40px 20px;">
    <tr><td align="center">
      <table width="560" cellpadding="0" cellspacing="0"
             style="background:linear-gradient(135deg,#1a1d2e,#141622);border-radius:20px;
                    border:1px solid rgba(99,102,241,0.3);overflow:hidden;">
        <!-- Header -->
        <tr>
          <td style="background:linear-gradient(135deg,#6366f1,#8b5cf6);padding:28px 40px;text-align:center;">
            <h1 style="margin:0;color:#fff;font-size:26px;letter-spacing:1px;">CivicPulse</h1>
            <p style="margin:4px 0 0;color:rgba(255,255,255,0.85);font-size:13px;">Smart Civic Management Portal</p>
          </td>
        </tr>
        <!-- Body -->
        <tr>
          <td style="padding:36px 40px;">
            <p style="color:#a0aec0;font-size:15px;margin:0 0 24px;">
              {meta['icon']} Your complaint status has been updated.
            </p>

            <!-- Complaint Info Card -->
            <div style="background:rgba(255,255,255,0.04);border:1px solid rgba(99,102,241,0.2);
                        border-radius:14px;padding:22px 24px;margin-bottom:24px;">
              <table width="100%" cellpadding="6" cellspacing="0">
                <tr>
                  <td style="color:#718096;font-size:13px;width:140px;">Complaint ID</td>
                  <td style="color:#e2e8f0;font-size:13px;font-weight:600;
                             font-family:'Courier New',monospace;">{complaint_id}</td>
                </tr>
                <tr>
                  <td style="color:#718096;font-size:13px;">Title</td>
                  <td style="color:#e2e8f0;font-size:13px;">{title}</td>
                </tr>
                <tr>
                  <td style="color:#718096;font-size:13px;">New Status</td>
                  <td>
                    <span style="background:{meta['badge_bg']};border:1px solid {meta['badge_border']};
                                 color:{meta['color']};font-size:13px;font-weight:700;
                                 padding:4px 14px;border-radius:20px;display:inline-block;">
                      {meta['icon']} {status}
                    </span>
                  </td>
                </tr>
              </table>
            </div>

            <!-- Status Message -->
            <div style="background:{meta['badge_bg']};border-left:4px solid {meta['color']};
                        border-radius:10px;padding:16px 20px;margin-bottom:24px;">
              <p style="margin:0 0 6px;color:{meta['color']};font-size:14px;font-weight:600;">
                What this means for you
              </p>
              <p style="margin:0 0 8px;color:#a0aec0;font-size:13px;line-height:1.6;">{meta['message']}</p>
              <p style="margin:0;color:#718096;font-size:12px;">{meta['action']}</p>
            </div>

            <p style="color:#4a5568;font-size:12px;margin:0;line-height:1.6;">
              You can track your complaint at any time using the complaint ID above at the CivicPulse portal.
            </p>
          </td>
        </tr>
        <!-- Footer -->
        <tr>
          <td style="background:rgba(0,0,0,0.3);padding:18px 40px;text-align:center;
                     border-top:1px solid rgba(99,102,241,0.15);">
            <p style="margin:0;color:#4a5568;font-size:12px;">
              © 2026 CivicPulse Smart Civic Portal — Automated notification, do not reply.
            </p>
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""

        text_body = (
            f"CivicPulse — Complaint Status Update\n\n"
            f"Complaint ID : {complaint_id}\n"
            f"Title        : {title}\n"
            f"New Status   : {status}\n\n"
            f"{meta['message']}\n{meta['action']}\n\n"
            f"Track your complaint using the ID above on the CivicPulse portal.\n"
            f"(This is an automated message — do not reply.)"
        )

        msg.attach(MIMEText(text_body, "plain"))
        msg.attach(MIMEText(html_body, "html"))

        with smtplib.SMTP(cfg["smtp_host"], int(cfg["smtp_port"])) as server:
            server.ehlo()
            server.starttls()
            server.login(cfg["sender_email"], cfg["sender_password"])
            server.sendmail(cfg["sender_email"], user_email, msg.as_string())

        app.logger.info(f"[STATUS EMAIL] Sent '{status}' notification → {user_email} for {complaint_id}")
        return True, ""

    except Exception as e:
        app.logger.error(f"[STATUS EMAIL ERROR] {complaint_id} → {user_email}: {e}")
        return False, str(e)


def store_otp(db, email, otp):
    """Invalidate old OTPs and store a new one with expiry."""
    db.execute("UPDATE otp_tokens SET is_used=1 WHERE email=? AND is_used=0", (email,))
    expires_at = datetime.now() + timedelta(minutes=OTP_EXPIRY_MINUTES)
    db.execute(
        "INSERT INTO otp_tokens (email, otp, expires_at) VALUES (?, ?, ?)",
        (email, otp, expires_at.strftime("%Y-%m-%d %H:%M:%S"))
    )
    db.commit()


def verify_otp_token(db, email, otp_input):
    """Returns True and marks OTP used if valid and not expired."""
    row = db.execute(
        """SELECT id FROM otp_tokens
           WHERE email=? AND otp=? AND is_used=0
             AND expires_at > datetime('now','localtime')
           ORDER BY id DESC LIMIT 1""",
        (email, otp_input)
    ).fetchone()
    if row:
        db.execute("UPDATE otp_tokens SET is_used=1 WHERE id=?", (row["id"],))
        db.commit()
        return True
    return False


@app.route("/otp/send", methods=["POST"])
def otp_send():
    data  = request.get_json(silent=True) or {}
    email = data.get("email", "").strip().lower()
    if not email:
        return jsonify({"success": False, "message": "Email is required."}), 400

    db   = get_db()
    user = db.execute(
        "SELECT name FROM users WHERE email=? AND is_admin=0 AND is_staff=0 AND is_active=1",
        (email,)
    ).fetchone()
    if not user:
        return jsonify({"success": True, "message": "If that email is registered, an OTP has been sent."})

    otp = generate_otp()
    store_otp(db, email, otp)
    ok, err = send_otp_email(email, otp, user["name"])
    if not ok:
        app.logger.error(f"[EMAIL ERROR] Could not send OTP to {email}: {err}")
        not_configured = "not configured" in err.lower() or "sender_email" in err.lower()
        if not_configured:
            return jsonify({
                "success": False,
                "message": "Email is not configured. Please ask the admin to set up email in Admin → Email Settings."
            }), 503
        return jsonify({
            "success": False,
            "message": f"Failed to send OTP email. Please try again or contact admin. ({err})"
        }), 500

    return jsonify({"success": True, "message": "OTP sent! Check your email inbox."})


@app.route("/otp/verify", methods=["POST"])
def otp_verify():
    data  = request.get_json(silent=True) or {}
    email = data.get("email", "").strip().lower()
    otp   = "".join(str(data.get("otp", "")).split())
    if not email or not otp:
        return jsonify({"success": False, "message": "Email and OTP are required."}), 400

    db   = get_db()
    user = db.execute(
        "SELECT * FROM users WHERE email=? AND is_admin=0 AND is_staff=0 AND is_active=1",
        (email,)
    ).fetchone()
    if not user:
        return jsonify({"success": False, "message": "Invalid request."}), 400

    if verify_otp_token(db, email, otp):
        session.update({
            "user_id":   user["id"],
            "user_name": user["name"],
            "is_admin":  0,
            "is_staff":  0,
        })
        return jsonify({"success": True, "redirect": url_for("citizen_dashboard")})

    return jsonify({"success": False, "message": "Invalid or expired OTP. Please try again."})


@app.route("/citizen/login/otp")
def citizen_otp_login():
    if session.get("user_id"):
        return redirect(url_for("citizen_dashboard"))
    return render_template("otp_login.html")

# ── ADMIN: Email Settings ────────────────────────────────────────────────────
@app.route("/admin/email-settings", methods=["GET", "POST"])
@admin_required
def admin_email_settings():
    db = get_db()
    cfg = db.execute("SELECT * FROM email_config WHERE id=1").fetchone()
    if request.method == "POST":
        smtp_host      = request.form.get("smtp_host", "smtp.gmail.com").strip()
        smtp_port      = int(request.form.get("smtp_port", 587))
        sender_email   = request.form.get("sender_email", "").strip()
        sender_password= request.form.get("sender_password", "").strip()
        sender_name    = request.form.get("sender_name", "CivicPulse Portal").strip()
        # Keep old password if blank submitted
        if not sender_password and cfg:
            sender_password = cfg["sender_password"]
        db.execute("""UPDATE email_config SET
            smtp_host=?, smtp_port=?, sender_email=?, sender_password=?,
            sender_name=?, is_configured=1 WHERE id=1""",
            (smtp_host, smtp_port, sender_email, sender_password, sender_name))
        db.commit()
        flash("Email settings saved successfully! ✅", "success")
        return redirect(url_for("admin_email_settings"))
    return render_template("admin_email_settings.html", cfg=cfg)


@app.route("/admin/email-settings/test", methods=["POST"])
@admin_required
def admin_email_test():
    """Send a test email to verify SMTP config works."""
    test_to = request.form.get("test_email", "").strip()
    if not test_to:
        flash("Enter a recipient email for the test.", "danger")
        return redirect(url_for("admin_email_settings"))
    otp = "123456"
    ok, err = send_otp_email(test_to, otp, "Test User")
    if ok:
        flash(f"✅ Test email sent to {test_to}! Check your inbox.", "success")
    else:
        flash(f"❌ Email failed: {err}", "danger")
    return redirect(url_for("admin_email_settings"))


if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
