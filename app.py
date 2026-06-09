import os
import secrets
import sqlite3
from datetime import datetime

from flask import Flask, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("FLASK_SECRET_KEY", "dev-secret-change-me")
app.config["DATABASE"] = os.path.join(app.root_path, "auth.db")


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = sqlite3.connect(app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
    return g.db


def init_db() -> None:
    db = get_db()
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            reset_token TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    db.commit()


def get_current_user() -> sqlite3.Row | None:
    user_id = session.get("user_id")
    if not user_id:
        return None
    db = get_db()
    return db.execute("SELECT id, email, created_at FROM users WHERE id = ?", (user_id,)).fetchone()


@app.before_request
def ensure_db_initialized() -> None:
    init_db()


@app.teardown_appcontext
def close_db(_: BaseException | None) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


@app.context_processor
def inject_user():
    return {"current_user": get_current_user()}


@app.get("/")
def index():
    if get_current_user():
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if get_current_user():
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not email or not password:
            flash("Please enter both email and password.", "error")
        elif len(password) < 8:
            flash("Password must be at least 8 characters.", "error")
        else:
            db = get_db()
            existing = db.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
            if existing:
                flash("An account with that email already exists.", "error")
            else:
                db.execute(
                    "INSERT INTO users (email, password_hash, created_at) VALUES (?, ?, ?)",
                    (email, generate_password_hash(password), datetime.utcnow().isoformat()),
                )
                db.commit()
                flash("Account created. You can now sign in.", "success")
                return redirect(url_for("login"))

    return render_template("signup.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if get_current_user():
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not email or not password:
            flash("Please enter both email and password.", "error")
        else:
            db = get_db()
            user = db.execute("SELECT id, password_hash FROM users WHERE email = ?", (email,)).fetchone()
            if not user or not check_password_hash(user["password_hash"], password):
                flash("Invalid email or password.", "error")
            else:
                session["user_id"] = user["id"]
                flash("Signed in successfully.", "success")
                return redirect(url_for("dashboard"))

    return render_template("login.html")


@app.post("/logout")
def logout():
    session.clear()
    flash("You have been signed out.", "success")
    return redirect(url_for("login"))


@app.get("/dashboard")
def dashboard():
    user = get_current_user()
    if not user:
        flash("Please sign in to continue.", "error")
        return redirect(url_for("login"))
    return render_template("dashboard.html")


@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        if not email:
            flash("Please enter your email.", "error")
        else:
            db = get_db()
            user = db.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
            if user:
                token = secrets.token_urlsafe(24)
                db.execute("UPDATE users SET reset_token = ? WHERE id = ?", (token, user["id"]))
                db.commit()
                reset_link = url_for("reset_password", token=token, _external=True)
                # In production, send this via email provider.
                print("Password reset link:", reset_link)
            flash("If the account exists, a reset link has been generated.", "success")

    return render_template("forgot_password.html")


@app.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token: str):
    db = get_db()
    user = db.execute("SELECT id FROM users WHERE reset_token = ?", (token,)).fetchone()
    if not user:
        flash("Reset link is invalid or expired.", "error")
        return redirect(url_for("forgot_password"))

    if request.method == "POST":
        password = request.form.get("password", "")
        if len(password) < 8:
            flash("Password must be at least 8 characters.", "error")
        else:
            db.execute(
                "UPDATE users SET password_hash = ?, reset_token = NULL WHERE id = ?",
                (generate_password_hash(password), user["id"]),
            )
            db.commit()
            flash("Password updated. Please sign in.", "success")
            return redirect(url_for("login"))

    return render_template("reset_password.html")


if __name__ == "__main__":
    app.run(debug=True)
