from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from datetime import date, timedelta
from functools import wraps
import os
import sqlite3

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:
    psycopg = None
    dict_row = None

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "athenaeum-demo-secret-key-change-me")
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
SQLITE_DB = os.path.join(os.path.dirname(__file__), "athenaeum.db")

# PostgreSQL is used when DATABASE_URL is present (Render production).
# SQLite remains available for simple local development when DATABASE_URL is absent.
USE_POSTGRES = bool(DATABASE_URL)


def normalize_database_url(url):
    if url.startswith("postgres://"):
        return "postgresql://" + url[len("postgres://"):]
    return url


def get_db():
    if USE_POSTGRES:
        if psycopg is None:
            raise RuntimeError("psycopg is required when DATABASE_URL is configured.")
        return psycopg.connect(normalize_database_url(DATABASE_URL), row_factory=dict_row)
    conn = sqlite3.connect(SQLITE_DB)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_db()
    if USE_POSTGRES:
        schema = """
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            name TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('admin','librarian','member'))
        );
        CREATE TABLE IF NOT EXISTS books (
            id SERIAL PRIMARY KEY,
            title TEXT NOT NULL,
            author TEXT NOT NULL,
            category TEXT NOT NULL,
            isbn TEXT,
            copies INTEGER NOT NULL DEFAULT 1,
            available INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS loans (
            id SERIAL PRIMARY KEY,
            book_id INTEGER NOT NULL REFERENCES books(id),
            member_id INTEGER NOT NULL REFERENCES users(id),
            borrow_date TEXT NOT NULL,
            due_date TEXT NOT NULL,
            return_date TEXT
        );
        CREATE TABLE IF NOT EXISTS reservations (
            id SERIAL PRIMARY KEY,
            book_id INTEGER NOT NULL REFERENCES books(id),
            member_id INTEGER NOT NULL REFERENCES users(id),
            reserved_date TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Active'
        );
        CREATE TABLE IF NOT EXISTS fines (
            id SERIAL PRIMARY KEY,
            loan_id INTEGER NOT NULL REFERENCES loans(id),
            member_id INTEGER NOT NULL REFERENCES users(id),
            amount DOUBLE PRECISION NOT NULL,
            reason TEXT NOT NULL,
            paid INTEGER NOT NULL DEFAULT 0
        );
        """
        conn.execute(schema)
    else:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            name TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('admin','librarian','member'))
        );
        CREATE TABLE IF NOT EXISTS books (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            author TEXT NOT NULL,
            category TEXT NOT NULL,
            isbn TEXT,
            copies INTEGER NOT NULL DEFAULT 1,
            available INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS loans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            book_id INTEGER NOT NULL,
            member_id INTEGER NOT NULL,
            borrow_date TEXT NOT NULL,
            due_date TEXT NOT NULL,
            return_date TEXT,
            FOREIGN KEY(book_id) REFERENCES books(id),
            FOREIGN KEY(member_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS reservations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            book_id INTEGER NOT NULL,
            member_id INTEGER NOT NULL,
            reserved_date TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Active',
            FOREIGN KEY(book_id) REFERENCES books(id),
            FOREIGN KEY(member_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS fines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            loan_id INTEGER NOT NULL,
            member_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            reason TEXT NOT NULL,
            paid INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY(loan_id) REFERENCES loans(id),
            FOREIGN KEY(member_id) REFERENCES users(id)
        );
        """)

    if conn.execute("SELECT COUNT(*) AS count FROM users").fetchone()["count"] == 0:
        users = [
            ("admin", "admin123", "System Admin", "admin"),
            ("librarian", "lib123", "Main Librarian", "librarian"),
            ("member", "member123", "Demo Member", "member"),
        ]
        for u in users:
            conn.execute("INSERT INTO users(username,password,name,role) VALUES(?,?,?,?)", u) if not USE_POSTGRES else conn.execute("INSERT INTO users(username,password,name,role) VALUES(%s,%s,%s,%s)", u)

    if conn.execute("SELECT COUNT(*) AS count FROM books").fetchone()["count"] == 0:
        books = [
            ("Clean Code", "Robert C. Martin", "Programming", "9780132350884", 3, 3),
            ("Artificial Intelligence: A Modern Approach", "Stuart Russell", "AI", "9780134610993", 2, 2),
            ("Python Crash Course", "Eric Matthes", "Programming", "9781593279288", 4, 4),
            ("The Design of Everyday Things", "Don Norman", "Design", "9780465050659", 2, 2),
            ("Data Science from Scratch", "Joel Grus", "Data Science", "9781492041139", 2, 2),
            ("Atomic Habits", "James Clear", "Self Help", "9780735211292", 3, 3),
        ]
        sql = "INSERT INTO books(title,author,category,isbn,copies,available) VALUES(?,?,?,?,?,?)"
        if USE_POSTGRES:
            sql = sql.replace("?", "%s")
        for b in books:
            conn.execute(sql, b)
    conn.commit()
    conn.close()


def execute(conn, sql, params=()):
    """Execute portable SQL. Existing app queries use ? placeholders."""
    if USE_POSTGRES:
        sql = sql.replace("?", "%s")
    return conn.execute(sql, params)


def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper


def roles(*allowed):
    def deco(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if "user_id" not in session:
                return redirect(url_for("login"))
            if session.get("role") not in allowed:
                flash("You do not have permission for that action.", "danger")
                return redirect(url_for("dashboard"))
            return f(*args, **kwargs)
        return wrapper
    return deco


def fine_for(due, returned=None):
    end = date.fromisoformat(returned) if returned else date.today()
    days = (end - date.fromisoformat(due)).days
    return max(0, days) * 5.0


@app.context_processor
def inject_user():
    return {"current_user": session}


@app.route("/")
def home():
    return redirect(url_for("dashboard")) if "user_id" in session else redirect(url_for("login"))


@app.route("/health")
def health():
    try:
        conn = get_db()
        execute(conn, "SELECT 1").fetchone()
        conn.close()
        return jsonify({"status": "ok", "database": "postgresql" if USE_POSTGRES else "sqlite"})
    except Exception as exc:
        return jsonify({"status": "error", "message": str(exc)}), 500


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username, password = request.form["username"], request.form["password"]
        conn = get_db()
        user = execute(conn, "SELECT * FROM users WHERE username=? AND password=?", (username, password)).fetchone()
        conn.close()
        if user:
            session.update(user_id=user["id"], username=user["username"], name=user["name"], role=user["role"])
            return redirect(url_for("dashboard"))
        flash("Invalid username or password.", "danger")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/dashboard")
@login_required
def dashboard():
    conn = get_db()
    stats = {
        "books": execute(conn, "SELECT COUNT(*) AS count FROM books").fetchone()["count"],
        "copies": execute(conn, "SELECT COALESCE(SUM(copies),0) AS value FROM books").fetchone()["value"],
        "available": execute(conn, "SELECT COALESCE(SUM(available),0) AS value FROM books").fetchone()["value"],
        "loans": execute(conn, "SELECT COUNT(*) AS count FROM loans WHERE return_date IS NULL").fetchone()["count"],
        "reservations": execute(conn, "SELECT COUNT(*) AS count FROM reservations WHERE status='Active'").fetchone()["count"],
        "unpaid": execute(conn, "SELECT COALESCE(SUM(amount),0) AS value FROM fines WHERE paid=0").fetchone()["value"],
    }
    conn.close()
    return render_template("dashboard.html", stats=stats)


@app.route("/books")
@login_required
def books():
    q = request.args.get("q", "").strip()
    conn = get_db()
    if q:
        rows = execute(conn, """SELECT * FROM books
            WHERE title LIKE ? OR author LIKE ? OR category LIKE ? OR isbn LIKE ?
            ORDER BY title""", tuple([f"%{q}%"] * 4)).fetchall()
    else:
        rows = execute(conn, "SELECT * FROM books ORDER BY title").fetchall()
    conn.close()
    return render_template("books.html", books=rows, q=q)


@app.route("/books/add", methods=["POST"])
@roles("admin", "librarian")
def add_book():
    data = request.form
    copies = max(1, int(data["copies"]))
    conn = get_db()
    execute(conn, """INSERT INTO books(title,author,category,isbn,copies,available)
                    VALUES(?,?,?,?,?,?)""",
            (data["title"], data["author"], data["category"], data.get("isbn", ""), copies, copies))
    conn.commit(); conn.close()
    flash("Book added successfully.", "success")
    return redirect(url_for("books"))


@app.route("/books/<int:book_id>/edit", methods=["POST"])
@roles("admin", "librarian")
def edit_book(book_id):
    data = request.form
    new_copies = max(1, int(data["copies"]))
    conn = get_db()
    old = execute(conn, "SELECT copies,available FROM books WHERE id=?", (book_id,)).fetchone()
    borrowed = old["copies"] - old["available"]
    available = max(0, new_copies - borrowed)
    execute(conn, """UPDATE books SET title=?,author=?,category=?,isbn=?,copies=?,available=? WHERE id=?""",
            (data["title"], data["author"], data["category"], data.get("isbn", ""), new_copies, available, book_id))
    conn.commit(); conn.close()
    flash("Book updated.", "success")
    return redirect(url_for("books"))


@app.route("/loans")
@login_required
def loans():
    conn = get_db()
    if USE_POSTGRES:
        overdue_expr = "CASE WHEN loans.return_date IS NULL AND loans.due_date < CURRENT_DATE::text THEN 1 ELSE 0 END"
    else:
        overdue_expr = "CASE WHEN loans.return_date IS NULL AND date(loans.due_date)<date('now') THEN 1 ELSE 0 END"
    rows = execute(conn, f"""SELECT loans.*, books.title, users.name AS member_name,
                           {overdue_expr} AS overdue
                           FROM loans JOIN books ON books.id=loans.book_id
                           JOIN users ON users.id=loans.member_id
                           ORDER BY loans.id DESC""").fetchall()
    members = execute(conn, "SELECT id,name FROM users WHERE role='member' ORDER BY name").fetchall()
    available_books = execute(conn, "SELECT id,title,available FROM books WHERE available>0 ORDER BY title").fetchall()
    conn.close()
    return render_template("loans.html", loans=rows, members=members, books=available_books)


@app.route("/loans/borrow", methods=["POST"])
@roles("admin", "librarian")
def borrow():
    book_id, member_id = int(request.form["book_id"]), int(request.form["member_id"])
    conn = get_db()
    book = execute(conn, "SELECT * FROM books WHERE id=?", (book_id,)).fetchone()
    if not book or book["available"] <= 0:
        flash("No available copy for this book.", "danger")
        conn.close(); return redirect(url_for("loans"))
    borrow_date = date.today()
    due_date = borrow_date + timedelta(days=14)
    execute(conn, "INSERT INTO loans(book_id,member_id,borrow_date,due_date) VALUES(?,?,?,?)",
            (book_id, member_id, borrow_date.isoformat(), due_date.isoformat()))
    execute(conn, "UPDATE books SET available=available-1 WHERE id=?", (book_id,))
    conn.commit(); conn.close()
    flash(f"Book borrowed. Due date: {due_date.isoformat()}", "success")
    return redirect(url_for("loans"))


@app.route("/loans/<int:loan_id>/return", methods=["POST"])
@roles("admin", "librarian")
def return_book(loan_id):
    conn = get_db()
    loan = execute(conn, "SELECT * FROM loans WHERE id=? AND return_date IS NULL", (loan_id,)).fetchone()
    if not loan:
        flash("Loan not found or already returned.", "danger")
        conn.close(); return redirect(url_for("loans"))
    today = date.today().isoformat()
    amount = fine_for(loan["due_date"], today)
    execute(conn, "UPDATE loans SET return_date=? WHERE id=?", (today, loan_id))
    execute(conn, "UPDATE books SET available=available+1 WHERE id=?", (loan["book_id"],))
    if amount > 0:
        execute(conn, "INSERT INTO fines(loan_id,member_id,amount,reason) VALUES(?,?,?,?)",
                (loan_id, loan["member_id"], amount, f"Overdue return ({int(amount/5)} day(s))"))
    execute(conn, """UPDATE reservations SET status='Ready'
                    WHERE id=(SELECT id FROM reservations
                              WHERE book_id=? AND status='Active'
                              ORDER BY reserved_date,id LIMIT 1)""", (loan["book_id"],))
    conn.commit(); conn.close()
    flash("Book returned" + (f". Fine generated: ₹{amount:.2f}" if amount else "."), "success")
    return redirect(url_for("loans"))


@app.route("/reservations")
@login_required
def reservations():
    conn = get_db()
    rows = execute(conn, """SELECT reservations.*, books.title, users.name AS member_name
                           FROM reservations JOIN books ON books.id=reservations.book_id
                           JOIN users ON users.id=reservations.member_id
                           ORDER BY reservations.id DESC""").fetchall()
    available_books = execute(conn, "SELECT id,title FROM books ORDER BY title").fetchall()
    members = execute(conn, "SELECT id,name FROM users WHERE role='member' ORDER BY name").fetchall()
    conn.close()
    return render_template("reservations.html", reservations=rows, books=available_books, members=members)


@app.route("/reservations/add", methods=["POST"])
@roles("admin", "librarian", "member")
def add_reservation():
    book_id = int(request.form["book_id"])
    member_id = int(request.form.get("member_id") or session["user_id"])
    conn = get_db()
    exists = execute(conn, """SELECT 1 FROM reservations
                             WHERE book_id=? AND member_id=? AND status IN ('Active','Ready')""",
                     (book_id, member_id)).fetchone()
    if exists:
        flash("This member already has an active reservation.", "danger")
    else:
        execute(conn, "INSERT INTO reservations(book_id,member_id,reserved_date) VALUES(?,?,?)",
                (book_id, member_id, date.today().isoformat()))
        conn.commit(); flash("Reservation placed.", "success")
    conn.close()
    return redirect(url_for("reservations"))


@app.route("/reservations/<int:rid>/complete", methods=["POST"])
@roles("admin", "librarian")
def complete_reservation(rid):
    conn = get_db()
    execute(conn, "UPDATE reservations SET status='Completed' WHERE id=?", (rid,))
    conn.commit(); conn.close()
    flash("Reservation marked completed.", "success")
    return redirect(url_for("reservations"))


@app.route("/fines")
@login_required
def fines():
    conn = get_db()
    rows = execute(conn, """SELECT fines.*, users.name AS member_name, books.title
                           FROM fines JOIN users ON users.id=fines.member_id
                           JOIN loans ON loans.id=fines.loan_id
                           JOIN books ON books.id=loans.book_id
                           ORDER BY fines.id DESC""").fetchall()
    conn.close()
    return render_template("fines.html", fines=rows)


@app.route("/fines/<int:fine_id>/pay", methods=["POST"])
@roles("admin", "librarian")
def pay_fine(fine_id):
    conn = get_db()
    execute(conn, "UPDATE fines SET paid=1 WHERE id=?", (fine_id,))
    conn.commit(); conn.close()
    flash("Fine marked as paid.", "success")
    return redirect(url_for("fines"))


@app.route("/reports")
@roles("admin", "librarian")
def reports():
    conn = get_db()
    if USE_POSTGRES:
        overdue_sql = "SELECT COUNT(*) AS count FROM loans WHERE return_date IS NULL AND due_date < CURRENT_DATE::text"
    else:
        overdue_sql = "SELECT COUNT(*) AS count FROM loans WHERE return_date IS NULL AND date(due_date)<date('now')"
    data = {
        "books": execute(conn, "SELECT COUNT(*) AS count FROM books").fetchone()["count"],
        "copies": execute(conn, "SELECT COALESCE(SUM(copies),0) AS value FROM books").fetchone()["value"],
        "available": execute(conn, "SELECT COALESCE(SUM(available),0) AS value FROM books").fetchone()["value"],
        "borrowed": execute(conn, "SELECT COALESCE(SUM(copies-available),0) AS value FROM books").fetchone()["value"],
        "active_loans": execute(conn, "SELECT COUNT(*) AS count FROM loans WHERE return_date IS NULL").fetchone()["count"],
        "overdue": execute(conn, overdue_sql).fetchone()["count"],
        "reservations": execute(conn, "SELECT COUNT(*) AS count FROM reservations WHERE status IN ('Active','Ready')").fetchone()["count"],
        "fines": execute(conn, "SELECT COALESCE(SUM(amount),0) AS value FROM fines").fetchone()["value"],
        "unpaid": execute(conn, "SELECT COALESCE(SUM(amount),0) AS value FROM fines WHERE paid=0").fetchone()["value"],
    }
    category = execute(conn, """SELECT category, SUM(copies) AS copies, SUM(available) AS available
                               FROM books GROUP BY category ORDER BY category""").fetchall()
    conn.close()
    return render_template("reports.html", data=data, category=category)


@app.route("/members")
@roles("admin", "librarian")
def members():
    conn = get_db()
    rows = execute(conn, "SELECT id,name,username,role FROM users WHERE role='member' ORDER BY name").fetchall()
    conn.close()
    return render_template("members.html", members=rows)


@app.route("/members/add", methods=["POST"])
@roles("admin", "librarian")
def add_member():
    conn = get_db()
    try:
        execute(conn, "INSERT INTO users(username,password,name,role) VALUES(?,?,?,'member')",
                (request.form["username"], request.form["password"], request.form["name"]))
        conn.commit(); flash("Member created.", "success")
    except Exception as exc:
        conn.rollback()
        if "unique" in str(exc).lower() or "duplicate" in str(exc).lower():
            flash("Username already exists.", "danger")
        else:
            raise
    finally:
        conn.close()
    return redirect(url_for("members"))


@app.route("/api/stats")
@login_required
def api_stats():
    conn = get_db()
    data = {
        "books": execute(conn, "SELECT COUNT(*) AS count FROM books").fetchone()["count"],
        "available": execute(conn, "SELECT COALESCE(SUM(available),0) AS value FROM books").fetchone()["value"],
        "active_loans": execute(conn, "SELECT COUNT(*) AS count FROM loans WHERE return_date IS NULL").fetchone()["count"],
        "unpaid_fines": execute(conn, "SELECT COALESCE(SUM(amount),0) AS value FROM fines WHERE paid=0").fetchone()["value"]
    }
    conn.close()
    return jsonify(data)


# Initialize the database on process start. On Render, DATABASE_URL points to PostgreSQL.
init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(debug=os.environ.get("FLASK_DEBUG", "0") == "1", host="0.0.0.0", port=port)
