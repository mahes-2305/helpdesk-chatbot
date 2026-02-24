from flask import Flask, request, redirect, url_for, session, jsonify, render_template, render_template_string
import sqlite3
import os
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np

# Load embedding model once
model = SentenceTransformer("all-MiniLM-L6-v2")

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "devkey")

# Admin credentials from environment
def get_admin_credentials():
    admins = []
    for i in range(1, 5):
        username = os.environ.get(f"ADMIN_{i}_USER", "")
        password = os.environ.get(f"ADMIN_{i}_PASS", "")
        if username.strip() and password.strip():
            admins.append((username.strip(), password.strip()))
    return admins
# ================= DATABASE SETUP =================

def init_db():
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS faqs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question TEXT,
            answer TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_input TEXT,
            bot_response TEXT,
            confidence REAL
        )
    """)

    conn.commit()
    conn.close()

init_db()

def migrate_logs_table():
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()

    try:
        cursor.execute("ALTER TABLE logs ADD COLUMN is_low_confidence INTEGER DEFAULT 0")
    except:
        pass

    try:
        cursor.execute("ALTER TABLE logs ADD COLUMN helpful_count INTEGER DEFAULT 0")
    except:
        pass

    try:
        cursor.execute("ALTER TABLE logs ADD COLUMN not_helpful_count INTEGER DEFAULT 0")
    except:
        pass

    conn.commit()
    conn.close()

migrate_logs_table()

# ================= NLP TRAINING =================

def load_faq_embeddings():
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT question FROM faqs")
    data = cursor.fetchall()
    conn.close()

    questions = [row[0] for row in data]

    if questions:
        embeddings = model.encode(questions)
        return questions, embeddings
    else:
        return [], None

# ================= HOME =================

@app.route("/")
def home():
    return render_template("index.html")

# ================= CHAT =================

@app.route("/chat", methods=["POST"])
def chat():
    user_input = request.json["message"]

    questions, faq_embeddings = load_faq_embeddings()

    if not questions:
        return jsonify({"response": "No FAQs available.", "confidence": 0})

    user_embedding = model.encode([user_input])

    similarity = cosine_similarity(user_embedding, faq_embeddings)

    score = similarity.max()
    index = similarity.argmax()

    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()

    if score < 0.4:
        response = "I am not sure about that. Forwarded to admin."
    else:
        cursor.execute("SELECT answer FROM faqs WHERE question=?", (questions[index],))
        result = cursor.fetchone()
        response = result[0] if result else "Answer not found."

    confidence = round(float(score) * 100, 2)

    is_low = 1 if confidence < 50 else 0

    # Log query
    cursor.execute("""
        INSERT INTO logs (user_input, bot_response, confidence, is_low_confidence)
        VALUES (?, ?, ?, ?)
    """, (user_input, response, confidence, is_low))

    log_id = cursor.lastrowid
    
    conn.commit()
    conn.close()

    return jsonify({
    "response": response,
    "confidence": confidence,
    "log_id": log_id
})


## ================= FEEDBACK =================

@app.route("/feedback", methods=["POST"])
def feedback():
    data = request.json
    log_id = data.get("log_id")
    feedback_type = data.get("type")  # "helpful" or "not_helpful"

    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()

    if feedback_type == "helpful":
        cursor.execute("""
            UPDATE logs
            SET helpful_count = helpful_count + 1
            WHERE id = ?
        """, (log_id,))
    elif feedback_type == "not_helpful":
        cursor.execute("""
            UPDATE logs
            SET not_helpful_count = not_helpful_count + 1
            WHERE id = ?
        """, (log_id,))

    conn.commit()
    conn.close()

    return jsonify({"status": "success"})

## ================= LOGIN =================

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        admins = get_admin_credentials()

        # If no environment variables set → fallback default admin
        if not admins:
            admins = [("admin", "1234")]

        # Check against all admins
        for admin_user, admin_pass in admins:
            if username == admin_user and password == admin_pass:
                session["admin"] = True
                return redirect(url_for("admin"))

        return "Invalid credentials"

    return render_template_string("""
    <!DOCTYPE html>
    <html>
    <head>
    <title>Admin Login</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
    body {
        background: linear-gradient(135deg,#2b5876,#4e4376);
        display:flex;
        justify-content:center;
        align-items:center;
        height:100vh;
    }
    .card {
        border-radius:15px;
    }
    </style>
    </head>

    <body>

    <div class="card shadow p-4" style="width:350px;">
        <h3 class="text-center mb-3">🔐 Admin Login</h3>
        
        <form method="POST">
            <div class="mb-3">
                <input name="username" class="form-control" placeholder="Username" required>
            </div>
            <div class="mb-3">
                <input name="password" type="password" class="form-control" placeholder="Password" required>
            </div>
            <button class="btn btn-dark w-100">Login</button>
        </form>

        <div class="text-center mt-3">
            <a href="/" class="text-decoration-none">← Back to Chat</a>
        </div>
    </div>

    </body>
    </html>
    """)

# ================= ADMIN =================

@app.route("/admin")
def admin():
    if not session.get("admin"):
        return redirect(url_for("login"))

    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()

    from datetime import datetime, timedelta

# Today's date
    today = datetime.now().date()

    cursor.execute("""
        SELECT COUNT(*) FROM logs
        WHERE DATE(rowid, 'unixepoch') = DATE('now')
""")
    today_queries = cursor.fetchone()[0]

# Helpful percentage
    cursor.execute("SELECT SUM(helpful_count), SUM(not_helpful_count) FROM logs")
    result = cursor.fetchone()

    total_helpful = result[0] if result[0] else 0
    total_not_helpful = result[1] if result[1] else 0

    total_feedback = total_helpful + total_not_helpful

    if total_feedback > 0:
       helpful_percentage = round((total_helpful / total_feedback) * 100, 2)
    else:
        helpful_percentage = 0

    cursor.execute("SELECT * FROM faqs")
    faqs = cursor.fetchall()

    cursor.execute("SELECT COUNT(*) FROM logs")
    total_queries = cursor.fetchone()[0]

    cursor.execute("SELECT * FROM logs WHERE confidence < 40")
    low_confidence_logs = cursor.fetchall()

    cursor.execute("""
        SELECT id, user_input, confidence, helpful_count, not_helpful_count
        FROM logs
        ORDER BY id DESC
""")
    all_logs = cursor.fetchall()

    conn.close()

    from flask import render_template

    return render_template(
    "admin.html",
    faqs=faqs,
    total_queries=total_queries,
    low_confidence_logs=low_confidence_logs,
    all_logs=all_logs,
    today_queries=today_queries,
    helpful_percentage=helpful_percentage
)
# ================= ADD FAQ =================

@app.route("/add", methods=["POST"])
def add():
    if not session.get("admin"):
        return redirect(url_for("login"))

    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute("INSERT INTO faqs (question,answer) VALUES (?,?)",
                   (request.form["question"],request.form["answer"]))
    conn.commit()
    conn.close()
    return redirect(url_for("admin"))

# ================= DELETE =================

@app.route("/delete/<int:id>")
def delete(id):
    if not session.get("admin"):
        return redirect(url_for("login"))

    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM faqs WHERE id=?", (id,))
    conn.commit()
    conn.close()
    return redirect(url_for("admin"))

# ================= LOGOUT =================

@app.route("/logout")
def logout():
    session.pop("admin",None)
    return redirect(url_for("home"))

if __name__=="__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)