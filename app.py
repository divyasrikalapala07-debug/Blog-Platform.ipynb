
import os
import sqlite3
from functools import wraps
from flask import (
    Flask, render_template, request, redirect,
    url_for, session, flash, g
)
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get(
    "SECRET_KEY", "change-this-key-before-deployment"
)

DATABASE = os.path.join(os.path.dirname(__file__), "blog.db")


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(error=None):
    db = g.pop("db", None)
    if db:
        db.close()


def init_db():
    db = get_db()
    db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(post_id) REFERENCES posts(id)
                ON DELETE CASCADE,
            FOREIGN KEY(user_id) REFERENCES users(id)
        );
    """)
    db.commit()


@app.before_request
def setup():
    init_db()


def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            flash("Please login first.", "error")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapper


@app.route("/")
def index():
    posts = get_db().execute("""
        SELECT posts.*, users.username,
        (SELECT COUNT(*) FROM comments
         WHERE comments.post_id = posts.id) AS comment_count
        FROM posts
        JOIN users ON users.id = posts.user_id
        ORDER BY posts.created_at DESC
    """).fetchall()
    return render_template("index.html", posts=posts)


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"]

        if len(username) < 3 or len(password) < 6:
            flash("Username needs 3 characters and password 6.", "error")
        else:
            try:
                db = get_db()
                db.execute(
                    "INSERT INTO users(username,password_hash) VALUES (?,?)",
                    (username, generate_password_hash(password))
                )
                db.commit()
                flash("Registration successful! Please login.", "success")
                return redirect(url_for("login"))
            except sqlite3.IntegrityError:
                flash("Username already exists.", "error")

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"]
        user = get_db().execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()

        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            return redirect(url_for("index"))

        flash("Invalid username or password.", "error")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


@app.route("/create", methods=["POST"])
@login_required
def create_post():
    title = request.form["title"].strip()
    content = request.form["content"].strip()

    if title and content:
        db = get_db()
        db.execute(
            "INSERT INTO posts(user_id,title,content) VALUES (?,?,?)",
            (session["user_id"], title, content)
        )
        db.commit()
        flash("Post published successfully!", "success")
    else:
        flash("Enter title and content.", "error")

    return redirect(url_for("index"))


@app.route("/post/<int:post_id>")
def post_detail(post_id):
    db = get_db()
    post = db.execute("""
        SELECT posts.*, users.username
        FROM posts JOIN users ON users.id = posts.user_id
        WHERE posts.id = ?
    """, (post_id,)).fetchone()

    if post is None:
        flash("Post not found.", "error")
        return redirect(url_for("index"))

    comments = db.execute("""
        SELECT comments.*, users.username
        FROM comments JOIN users ON users.id = comments.user_id
        WHERE comments.post_id = ?
        ORDER BY comments.created_at
    """, (post_id,)).fetchall()

    return render_template(
        "post.html", post=post, comments=comments
    )


@app.route("/post/<int:post_id>/edit", methods=["GET", "POST"])
@login_required
def edit_post(post_id):
    db = get_db()
    post = db.execute(
        "SELECT * FROM posts WHERE id = ?", (post_id,)
    ).fetchone()

    if post is None:
        flash("Post not found.", "error")
        return redirect(url_for("index"))

    if post["user_id"] != session["user_id"]:
        flash("You can edit only your own posts.", "error")
        return redirect(url_for("index"))

    if request.method == "POST":
        title = request.form["title"].strip()
        content = request.form["content"].strip()

        if title and content:
            db.execute(
                "UPDATE posts SET title=?, content=? WHERE id=?",
                (title, content, post_id)
            )
            db.commit()
            return redirect(url_for("post_detail", post_id=post_id))

        flash("Title and content are required.", "error")

    return render_template("edit.html", post=post)


@app.route("/post/<int:post_id>/delete", methods=["POST"])
@login_required
def delete_post(post_id):
    db = get_db()
    post = db.execute(
        "SELECT * FROM posts WHERE id = ?", (post_id,)
    ).fetchone()

    if post and post["user_id"] == session["user_id"]:
        db.execute("DELETE FROM comments WHERE post_id=?", (post_id,))
        db.execute("DELETE FROM posts WHERE id=?", (post_id,))
        db.commit()
        flash("Post deleted.", "success")
    else:
        flash("You can delete only your own posts.", "error")

    return redirect(url_for("index"))


@app.route("/post/<int:post_id>/comment", methods=["POST"])
@login_required
def add_comment(post_id):
    content = request.form["content"].strip()
    db = get_db()

    post = db.execute(
        "SELECT id FROM posts WHERE id=?", (post_id,)
    ).fetchone()

    if post and content:
        db.execute(
            "INSERT INTO comments(post_id,user_id,content) VALUES (?,?,?)",
            (post_id, session["user_id"], content)
        )
        db.commit()
    else:
        flash("Please enter a comment.", "error")

    return redirect(url_for("post_detail", post_id=post_id))


if __name__ == "__main__":
    app.run(debug=True)
