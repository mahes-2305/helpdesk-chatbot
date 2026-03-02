from flask import Flask, request, redirect, url_for, session, jsonify, render_template, render_template_string
import sqlite3
import os
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np
from flask import g

# Load embedding model once
model = SentenceTransformer("all-MiniLM-L6-v2")


# Global cache
faq_questions = []
faq_answers = []
faq_embeddings = None

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
            answer TEXT,
            intent TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_input TEXT,
            bot_response TEXT,
            confidence REAL,
            is_low_confidence INTEGER DEFAULT 0,
            helpful_count INTEGER DEFAULT 0,
            not_helpful_count INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)


    cursor.execute("""
    CREATE TABLE IF NOT EXISTS unanswered (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        question TEXT,
        reviewed INTEGER DEFAULT 0
    )
""")
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS students (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        password TEXT
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

    try:
        cursor.execute("ALTER TABLE logs ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
    except:
        pass

    try:
        cursor.execute("ALTER TABLE logs ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
    except:
        pass

    try:
        cursor.execute("ALTER TABLE logs ADD COLUMN intent TEXT")
    except:
        pass

    conn.commit()
    conn.close()

def reload_faq_cache():
    global faq_questions, faq_answers, faq_embeddings

    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT question, answer FROM faqs")
    data = cursor.fetchall()
    conn.close()

    faq_questions = [row[0] for row in data]
    faq_answers = [row[1] for row in data]

    if faq_questions:
        faq_embeddings = model.encode(faq_questions)
    else:
        faq_embeddings = None

migrate_logs_table()


reload_faq_cache()



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
    

## ================= STUDENT LOGIN =================

@app.route("/student-login", methods=["GET", "POST"])
def student_login():

    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        conn = sqlite3.connect("database.db")
        cursor = conn.cursor()

        cursor.execute(
            "SELECT * FROM students WHERE username=? AND password=?",
            (username, password)
        )

        student = cursor.fetchone()
        conn.close()

        if student:
            session["student"] = username
            return redirect(url_for("home"))
        else:
            return "Invalid credentials"

    return render_template_string("""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Student Login</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
    </head>
    <body class="bg-dark d-flex justify-content-center align-items-center vh-100">

        <div class="card p-4" style="width:350px;">
            <h4 class="text-center mb-3"> Student Login</h4>

            <form method="POST">
                <input name="username" class="form-control mb-2" placeholder="Username" required>
                <input type="password" name="password" class="form-control mb-2" placeholder="Password" required>
                <button class="btn btn-primary w-100">Login</button>
            </form>
        </div>

    </body>
    </html>
    """)    



# ================= STUDENT LOGOUT =================

@app.route("/student_logout")
def student_logout():
    session.pop("student", None)
    session.pop("chat_history", None)
    return redirect(url_for("student_login"))
    




# ================= HOME =================

@app.route("/")
def home():
    if not session.get("student"):
        return redirect(url_for("student_login"))

    return render_template("index.html")


def detect_intent(text):
    text = text.lower()

    intent_map = {
        "Exams": ["exam", "internal", "mark", "result"],
        "Fees": ["fee", "payment", "tuition"],
        "Hostel": ["hostel", "room", "mess"],
        "Transport": ["bus", "transport", "route"],
        "OD": ["od", "on duty", "leave"],
        "Complaint": ["complaint", "issue", "problem"]
    }

    for intent, keywords in intent_map.items():
        if any(word in text for word in keywords):
            return intent

    return "General"



# ================= CHAT =================

@app.route("/chat", methods=["POST"])
def chat():
    try:
        user_input = request.json.get("message")

        if not user_input:
            return jsonify({
                "response": "Please enter a message.",
                "confidence": 0
            })

        # 🔐 Student Protection
        if not session.get("student"):
            return jsonify({
                "response": "Please login first.",
                "confidence": 0
            })

        # -------- SESSION MEMORY --------
        if "chat_history" not in session:
            session["chat_history"] = []

        context = " ".join(session["chat_history"][-2:])
        combined_input = context + " " + user_input

        intent = detect_intent(user_input)

        conn = sqlite3.connect("database.db")
        cursor = conn.cursor()

        # ✅ HYBRID: Filter by intent first
        cursor.execute("""
    SELECT question, answer 
    FROM faqs
    WHERE intent=? OR intent IS NULL
""", (intent,))
        data = cursor.fetchall()

        # If no FAQ under that intent
        if not data:
            response = "I don't have information about this topic yet."
            confidence = 0
            is_low = 1

            cursor.execute("""
                INSERT INTO unanswered (question, reviewed)
                VALUES (?, 0)
            """, (user_input,))

        else:
            questions = [row[0] for row in data]
            answers = [row[1] for row in data]

            faq_embeddings = model.encode(questions)
            user_embedding = model.encode([combined_input])

            similarity = cosine_similarity(user_embedding, faq_embeddings)

            score = float(similarity[0].max())
            index = int(similarity[0].argmax())

            confidence = round(score * 100, 2)

            # 🎯 Strict threshold logic
            if len(user_input.split()) <= 2:
                threshold = 0.50
            else:
                threshold = 0.70

            if score >= threshold:
                response = answers[index]
                is_low = 0

            elif 0.55 <= score < threshold:
                response = answers[index] + "\n\n(This answer may not be exact.)"
                is_low = 0

            else:
                response = "I'm not confident about this answer. It has been sent for admin review."
                is_low = 1

                cursor.execute("""
                    INSERT INTO unanswered (question, reviewed)
                    VALUES (?, 0)
                """, (user_input,))

        # -------- LOGGING --------
        cursor.execute("""
            INSERT INTO logs (user_input, bot_response, confidence, is_low_confidence)
            VALUES (?, ?, ?, ?)
        """, (user_input, response, confidence, is_low))

        log_id = cursor.lastrowid

        conn.commit()
        conn.close()

        # -------- SAVE MEMORY --------
        session["chat_history"].append(user_input)

        if len(session["chat_history"]) > 5:
            session["chat_history"] = session["chat_history"][-5:]

        return jsonify({
            "response": response,
            "confidence": confidence,
            "log_id": log_id
        })

    except Exception as e:
        print("ERROR:", e)
        return jsonify({
            "response": "Something went wrong.",
            "confidence": 0
        })


## ================= FEEDBACK =================

@app.route("/feedback", methods=["POST"])
def feedback():
    data = request.get_json()
    log_id = data.get("log_id")
    feedback_type = data.get("type")

    if not log_id:
        return jsonify({"status": "error"})

    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()

    if feedback_type == "helpful":
        cursor.execute("""
            UPDATE logs
            SET helpful_count = helpful_count + 1
            WHERE id = ?
        """, (log_id,))
    else:
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
        <h3 class="text-center mb-3"> Admin Login</h3>
        
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

    selected_date = request.args.get("date")

    # ===== BASIC STATS =====
    cursor.execute("SELECT COUNT(*) FROM logs")
    total_queries = cursor.fetchone()[0]

    cursor.execute("SELECT * FROM logs WHERE confidence < 40")
    low_confidence_logs = cursor.fetchall()

    cursor.execute("""
        SELECT SUM(helpful_count), SUM(not_helpful_count)
        FROM logs
    """)
    feedback = cursor.fetchone()

    total_helpful = feedback[0] if feedback[0] else 0
    total_not_helpful = feedback[1] if feedback[1] else 0
    total_feedback = total_helpful + total_not_helpful

    helpful_percentage = round((total_helpful / total_feedback) * 100, 2) if total_feedback > 0 else 0

    # ===== TODAY QUERIES =====
    cursor.execute("""
        SELECT COUNT(*) FROM logs
        WHERE DATE(created_at) = DATE('now')
    """)
    today_queries = cursor.fetchone()[0]

    # ===== DATE FILTER =====
    if selected_date:
        cursor.execute("""
            SELECT id, user_input, confidence, helpful_count, not_helpful_count
            FROM logs
            WHERE DATE(created_at) = ?
            ORDER BY id DESC
        """, (selected_date,))
    else:
        cursor.execute("""
            SELECT id, user_input, confidence, helpful_count, not_helpful_count
            FROM logs
            ORDER BY id DESC
        """)

    all_logs = cursor.fetchall()

    # ===== DAILY STATS =====
    cursor.execute("""
        SELECT DATE(created_at), COUNT(*)
        FROM logs
        GROUP BY DATE(created_at)
        ORDER BY DATE(created_at)
    """)
    daily_stats = cursor.fetchall()

    feedback_stats = [total_helpful, total_not_helpful]

    # ===== FAQ =====
    cursor.execute("SELECT * FROM faqs")
    faqs = cursor.fetchall()

    # ===== UNANSWERED =====
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS unanswered (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question TEXT,
            reviewed INTEGER DEFAULT 0
        )
    """)

    cursor.execute("SELECT * FROM unanswered WHERE reviewed = 0")
    unanswered_list = cursor.fetchall()

    conn.close()

    return render_template(
        "admin.html",
        total_queries=total_queries,
        low_confidence_logs=low_confidence_logs,
        helpful_percentage=helpful_percentage,
        today_queries=today_queries,
        all_logs=all_logs,
        daily_stats=daily_stats,
        feedback_stats=feedback_stats,
        faqs=faqs,
        selected_date=selected_date,
        unanswered_list=unanswered_list,
    )
# ================= ADD FAQ =================

@app.route("/add", methods=["POST"])
def add():
    if not session.get("admin"):
        return redirect(url_for("login"))

    question = request.form.get("question")
    answer = request.form.get("answer")

    if not question or not answer:
        return "Missing data", 400

    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()

    intent = detect_intent(question)

    cursor.execute(
    "INSERT INTO faqs (question, answer, intent) VALUES (?, ?, ?)",
    (question, answer, intent)
)

    conn.commit()
    conn.close()

    reload_faq_cache()

    return redirect(url_for("admin"))


@app.route("/convert/<int:id>", methods=["POST"])
def convert_to_faq(id):
    if not session.get("admin"):
        return redirect(url_for("login"))

    answer = request.form["answer"]

    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()

    # Get question
    cursor.execute("SELECT question FROM unanswered WHERE id=?", (id,))
    result = cursor.fetchone()

    if result:
        question = result[0]

        # Insert into FAQ
        cursor.execute("INSERT INTO faqs (question, answer) VALUES (?,?)",
                       (question, answer))

        # Mark as reviewed
        cursor.execute("UPDATE unanswered SET reviewed=1 WHERE id=?", (id,))

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


# ================= DELETE UNANSWERED =================

@app.route("/delete-unanswered/<int:id>")
def delete_unanswered(id):
    if not session.get("admin"):
        return redirect(url_for("login"))

    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM unanswered WHERE id=?", (id,))
    conn.commit()
    conn.close()

    return redirect(url_for("admin"))


# ================= LOGOUT =================

@app.route("/logout")
def logout():
    session.pop("admin",None)
    return redirect(url_for("home"))



