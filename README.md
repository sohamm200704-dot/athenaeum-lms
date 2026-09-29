# Athenaeum — Library Management System

A working capstone prototype based on the provided LMS presentation.

## Modules
- Catalog Search
- Borrow & Return
- Reservations
- Fine Management
- Role-based Access
- Reporting

## Stack
- Python + Flask
- SQLite
- HTML/CSS/JavaScript

## Demo accounts
- Admin: admin / admin123
- Librarian: librarian / lib123
- Member: member / member123

## Run on macOS
```bash
cd Athenaeum_LMS
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python app.py
```

Then open http://127.0.0.1:5000

The SQLite database `athenaeum.db` is created automatically and seeded with demo data on first run.

## Public deployment

See `README_DEPLOY.md` for PostgreSQL + Render deployment instructions. The project includes a `render.yaml` Blueprint for creating the web service and PostgreSQL database together.
