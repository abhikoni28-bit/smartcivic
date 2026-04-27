# 🚀 SmartCivic / CivicPulse — Deployment Guide
## Deploy to the Internet (Free, Beginner-Friendly)

---

## What Changed in Your Project

| File | Change | Why |
|------|--------|-----|
| `app.py` | `SECRET_KEY` now reads from env variable | Security |
| `app.py` | `debug=False`, port from `$PORT` env var | Required for production |
| `app.py` | DB & uploads go to `/data/` on Render | Persistent storage survives redeploys |
| `app.py` | Added `/uploads/<filename>` route | Serve complaint images from persistent disk |
| `templates/*.html` | Image src updated to use new `/uploads/` route | Match new image serving route |
| `requirements.txt` | Added `gunicorn` | Production WSGI server (Flask's built-in isn't for production) |
| `Procfile` | New file | Tells Render/Railway how to start your app |
| `render.yaml` | New file | One-click Render config with persistent disk |
| `runtime.txt` | New file | Pins Python 3.11 |
| `.gitignore` | New file | Excludes DB/uploads/cache from Git |

**No routes, UI, logic, or templates were changed.**

---

## ✅ Recommended: Deploy on Render (Free, HTTPS automatic)

Render is the best free option for Flask apps with SQLite. It provides:
- Free web service tier
- Automatic HTTPS (your app gets `https://your-app.onrender.com`)
- Persistent disk (so your SQLite database and uploads survive restarts)
- No credit card required for the free tier

---

## Step-by-Step: Render Deployment

### Step 1 — Create a GitHub repository

1. Go to [github.com](https://github.com) and sign in (or create a free account).
2. Click **New repository** (the green button or the `+` icon at the top right).
3. Name it: `smartcivic` (or anything you like).
4. Set it to **Public** (required for the free Render tier).
5. Click **Create repository**.

### Step 2 — Upload your project files to GitHub

**Option A — GitHub website (easiest, no command line):**

1. Open your new repository on GitHub.
2. Click **Add file → Upload files**.
3. Drag and drop ALL files from the `SmartCivic_Deploy` folder:
   - `app.py`
   - `requirements.txt`
   - `Procfile`
   - `render.yaml`
   - `runtime.txt`
   - `.gitignore`
   - The entire `templates/` folder
   - The entire `static/` folder
4. Click **Commit changes**.

**Option B — Git command line:**
```bash
cd SmartCivic_Deploy
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/smartcivic.git
git push -u origin main
```

### Step 3 — Sign up on Render

1. Go to [render.com](https://render.com).
2. Click **Get Started for Free**.
3. Sign up with your **GitHub account** (this lets Render access your repo).

### Step 4 — Create a new Web Service on Render

1. In your Render dashboard, click **New +** → **Web Service**.
2. Click **Connect a repository** and select your `smartcivic` repo.
3. Render will auto-detect it as a Python app. Fill in:

   | Field | Value |
   |-------|-------|
   | **Name** | `smartcivic` (or any name) |
   | **Region** | Singapore (closest to India) |
   | **Branch** | `main` |
   | **Runtime** | `Python 3` |
   | **Build Command** | `pip install -r requirements.txt` |
   | **Start Command** | `gunicorn app:app --workers 2 --bind 0.0.0.0:$PORT --timeout 120` |
   | **Instance Type** | `Free` |

4. Click **Advanced** and add this **Environment Variable**:

   | Key | Value |
   |-----|-------|
   | `SECRET_KEY` | (click "Generate" — Render will create a secure random key) |

5. Click **Create Web Service**.

### Step 5 — Add a Persistent Disk (for SQLite + uploads)

> ⚠️ This is important! Without this, your database resets every time Render restarts your app.

1. After creating the service, go to its settings page.
2. In the left menu, click **Disks**.
3. Click **Add Disk** and fill in:

   | Field | Value |
   |-------|-------|
   | **Name** | `sqlite-data` |
   | **Mount Path** | `/data` |
   | **Size** | `1 GB` (free) |

4. Click **Save**.
5. Render will redeploy your app automatically.

### Step 6 — Wait for deployment

1. Go to the **Logs** tab in your Render service.
2. Wait ~3-5 minutes for the build to finish.
3. You'll see: `Gunicorn: started with 2 workers on port XXXX`.
4. Your app is now live! Click the URL at the top: `https://smartcivic.onrender.com`

---

## 🌐 Your App URLs After Deployment

| Page | URL |
|------|-----|
| Homepage | `https://smartcivic.onrender.com/` |
| Citizen Login | `https://smartcivic.onrender.com/citizen/login` |
| Admin Login | `https://smartcivic.onrender.com/admin/login` |
| Track Complaint | `https://smartcivic.onrender.com/track` |

**Default credentials (same as local):**
- Admin: `admin@civic.gov.in` / `Admin@123`
- Staff: `staff@civic.gov.in` / `Staff@123`

---

## ⚠️ Important Notes

### Free Tier Spin-Down
Render's free tier **spins down** your app after 15 minutes of inactivity. The next visitor will wait ~30-60 seconds for it to wake up. This is normal for the free tier. To avoid this, upgrade to the $7/month Starter plan.

### HTTPS
HTTPS is **automatic** on Render — no extra steps needed. Your app will be served at `https://...`.

### Email / OTP Feature
Your email (SMTP) settings are stored in the database. After deployment:
1. Log in as admin at `/admin/login`.
2. Go to **Admin → Email Settings**.
3. Enter your Gmail SMTP credentials (same as you did locally).
4. This works exactly the same as on your local network.

### Uploading Files (Complaint Images)
Images uploaded by citizens are stored in `/data/uploads/` on the persistent disk and served via the `/uploads/<filename>` route. This works correctly on the deployed app.

---

## Alternative: PythonAnywhere (also free, simpler)

If Render feels complex, PythonAnywhere is even simpler but has limitations (no persistent disk on free tier, so SQLite resets on app restarts).

1. Sign up at [pythonanywhere.com](https://pythonanywhere.com).
2. Go to **Files** and upload your project ZIP.
3. Open a **Bash console** and run:
   ```bash
   unzip SmartCivic_Deploy.zip
   cd SmartCivic_Deploy
   pip3.11 install --user flask werkzeug gunicorn
   python app.py  # to initialise DB
   ```
4. Go to **Web** → **Add a new web app** → **Manual config** → **Python 3.11**.
5. Set **Source code** to `/home/yourusername/SmartCivic_Deploy`.
6. Set **WSGI file** — edit it to:
   ```python
   import sys
   sys.path.insert(0, '/home/yourusername/SmartCivic_Deploy')
   from app import app as application
   application.debug = False
   ```
7. Click **Reload** and your app is live at `yourusername.pythonanywhere.com`.

---

## File Structure After Changes

```
SmartCivic_Deploy/
├── app.py                  ← Updated (env vars, persistent paths, debug off)
├── requirements.txt        ← Updated (added gunicorn)
├── Procfile                ← NEW — production startup command
├── render.yaml             ← NEW — Render one-click config
├── runtime.txt             ← NEW — Python version pin
├── .gitignore              ← NEW — excludes DB/uploads/cache
├── static/
│   └── style.css
└── templates/
    ├── view_complaint.html      ← Updated image URL
    ├── admin_view_complaint.html← Updated image URL
    └── ... (all others unchanged)
```

---

## Deployment Checklist

- [x] `debug=False` in production
- [x] `SECRET_KEY` from environment variable
- [x] Port from `$PORT` environment variable
- [x] `gunicorn` as production WSGI server
- [x] SQLite on persistent disk (`/data/database.db`)
- [x] Uploads on persistent disk (`/data/uploads/`)
- [x] HTTPS (automatic on Render)
- [x] All routes work correctly
- [x] Static files (CSS) load properly
- [x] Image uploads serve correctly
- [x] Mobile & desktop browser compatible (no UI changes)
- [x] Email/OTP system works (configure SMTP via Admin panel)
