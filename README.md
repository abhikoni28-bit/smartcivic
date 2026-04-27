# CivicPulse — Smart Civic Complaint Management System
### BCA Major Project 2026

## 🚀 Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Run the app
python app.py

# 3. Open browser
http://127.0.0.1:5000
```

---

## 👤 Default Login Credentials

| Role       | Email                    | Password   |
|------------|--------------------------|------------|
| Super Admin| admin@civic.gov.in       | Admin@123  |
| Staff      | staff@civic.gov.in       | Staff@123  |
| Citizen    | Register a new account   | —          |

---

## 📦 Modules Included

### 🏠 Public Portal
- Landing page with live statistics
- Complaint tracker (no login required)
- Notice board

### 👤 Citizen Portal
- Register & Login
- File a Complaint (with photo upload, priority, ward)
- My Complaints dashboard
- View complaint detail with timeline
- Submit feedback & rating

### 🛡️ Admin / Staff Panel
- Admin Dashboard with charts (Chart.js)
- Complaint Management (filter, search, manage)
- Assign complaints to staff, add remarks
- User Management (add/suspend/delete)
- Notice Management
- Reports & Analytics (charts + ward breakdown)

---

## 🛠️ Tech Stack
- Python 3 + Flask
- SQLite3 (auto-created on first run)
- HTML5 / CSS3 (custom design system)
- Chart.js (analytics)
- Font Awesome 6 (icons)
- Google Fonts — Inter

---

## 📂 Project Structure
```
SmartCivicMajor/
├── app.py                  # Main Flask application
├── requirements.txt
├── database.db             # Auto-created on first run
├── static/
│   ├── style.css
│   └── uploads/            # Uploaded complaint images
└── templates/
    ├── base.html           # Public base layout
    ├── admin_base.html     # Admin sidebar layout
    ├── index.html          # Home page
    ├── track.html          # Public complaint tracker
    ├── about.html
    ├── citizen_login.html
    ├── citizen_register.html
    ├── citizen_dashboard.html
    ├── file_complaint.html
    ├── my_complaints.html
    ├── view_complaint.html
    ├── citizen_profile.html
    ├── admin_login.html
    ├── admin_dashboard.html
    ├── admin_complaints.html
    ├── admin_view_complaint.html
    ├── admin_users.html
    ├── admin_notices.html
    └── admin_reports.html
```
