# 📧 OTP Authentication – Setup Guide

## What Was Added

### Backend (`app.py`)
| Addition | Purpose |
|---|---|
| `import random, smtplib` + MIME imports | Email sending via standard library |
| `EMAIL_CONFIG` dict | Central SMTP configuration |
| `otp_tokens` DB table | Stores OTP, email, expiry, used-flag |
| `generate_otp()` | Secure 6-digit OTP generator |
| `send_otp_email()` | Sends styled HTML email via SMTP |
| `store_otp()` | Saves OTP to DB, invalidates old ones |
| `verify_otp_token()` | Checks OTP validity + expiry, marks used |
| `POST /otp/send` | API: generate & email OTP |
| `POST /otp/verify` | API: verify OTP → create session |
| `GET /citizen/login/otp` | New OTP login page route |

### Frontend
| File | Change |
|---|---|
| `templates/otp_login.html` | Full OTP login UI (new file) |
| `templates/citizen_login.html` | Added "Login with OTP" button |

---

## ⚙️ Configuration (Required)

Open `app.py` and update the `EMAIL_CONFIG` block near the top:

```python
EMAIL_CONFIG = {
    "SMTP_HOST":        "smtp.gmail.com",
    "SMTP_PORT":        587,
    "SENDER_EMAIL":     "your_email@gmail.com",      # ← your Gmail
    "SENDER_PASSWORD":  "your_app_password_here",    # ← Gmail App Password (not your login password)
    "SENDER_NAME":      "CivicPulse Portal",
}
```

### Getting a Gmail App Password
1. Go to your Google Account → **Security**
2. Enable **2-Step Verification** (required)
3. Search "App passwords" → Create one for "Mail"
4. Paste the 16-character code into `SENDER_PASSWORD`

### Using Other SMTP Providers
| Provider | SMTP_HOST | SMTP_PORT |
|---|---|---|
| Gmail | smtp.gmail.com | 587 |
| Outlook/Hotmail | smtp-mail.outlook.com | 587 |
| Yahoo | smtp.mail.yahoo.com | 587 |
| Custom domain | your-mail-server.com | 587 |

---

## 🛠️ Development / Testing (No Email Setup)

If email is not configured, the app **still works**. The OTP is:
1. Logged to the server console: `[DEV] OTP for user@email.com: 123456`
2. Displayed in a yellow badge on the OTP screen itself

This lets you test the full flow without any email credentials.

---

## 🔐 Security Features

- **5-minute expiry** – OTP auto-expires via DB timestamp check
- **Single use** – OTP marked `is_used=1` immediately after successful verify
- **Old OTPs invalidated** – Resend always creates a fresh token, old ones disabled
- **Email enumeration prevention** – `/otp/send` returns "OTP sent" even for unknown emails
- **60-second resend cooldown** – Client-side timer prevents spam
- **Auto-wipe on login** – Session is set only after valid OTP verification

---

## 🚀 Running the App

```bash
pip install Flask Werkzeug
python app.py
```

Visit: http://localhost:5000

- **OTP Login page**: http://localhost:5000/citizen/login/otp
- **Password Login**: http://localhost:5000/citizen/login (OTP button added here too)

---

## 📁 Changed Files Summary

```
SmartCivic_OTP_Auth/
├── app.py                          ← Updated (OTP routes + helpers added)
├── requirements.txt                ← No new packages needed
├── templates/
│   ├── otp_login.html              ← NEW — full OTP login page
│   ├── citizen_login.html          ← Updated — "Login with OTP" button added
│   └── ... (all other templates unchanged)
└── static/
    └── ... (unchanged)
```
