from flask import Flask, request, redirect, url_for, session, jsonify, render_template_string
import sqlite3
import os
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "devkey")

# Admin credentials from environment
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "1234")

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

# ================= NLP TRAINING =================

def train_model():
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT question FROM faqs")
    data = cursor.fetchall()
    conn.close()

    questions = [row[0] for row in data]

    if questions:
        vectorizer = TfidfVectorizer()
        X = vectorizer.fit_transform(questions)
        return vectorizer, X, questions
    return None, None, []

# ================= HOME =================

@app.route("/")
def home():
    return render_template_string("""
<!DOCTYPE html>
<html>
<head>
<title>CiperBot AI</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
<style>
body {
    background: linear-gradient(135deg,#141e30,#243b55);
    height: 100vh;
    display:flex;
    justify-content:center;
    align-items:center;
    font-family: Arial;
}
.chat-container {
    width: 500px;
    height: 600px;
    background: #1f2937;
    border-radius: 15px;
    display:flex;
    flex-direction:column;
    box-shadow: 0 15px 40px rgba(0,0,0,0.4);
}
.chat-header {
    padding:15px;
    background:#111827;
    color:white;
    text-align:center;
    border-top-left-radius:15px;
    border-top-right-radius:15px;
}
.chat-body {
    flex:1;
    padding:15px;
    overflow-y:auto;
}
.message {
    margin-bottom:15px;
    padding:10px 15px;
    border-radius:20px;
    max-width:75%;
}
.user {
    background:#3b82f6;
    color:white;
    margin-left:auto;
}
.bot {
    background:#374151;
    color:white;
}
.chat-footer {
    padding:10px;
    display:flex;
    background:#111827;
}
.chat-footer input {
    flex:1;
    border-radius:20px;
    border:none;
    padding:10px;
}
.chat-footer button {
    margin-left:10px;
    border-radius:20px;
}
.typing {
    font-size:12px;
    color:#9ca3af;
}
</style>
</head>

<body>

<div class="chat-container">

    <div class="chat-header d-flex justify-content-between align-items-center">
    <div>
        🤖 <strong>CiperBot AI</strong><br>
        <small>College Helpdesk Assistant</small>
    </div>
    <a href="/login" class="btn btn-outline-light btn-sm">Admin login</a>
</div>

    <div id="chatBody" class="chat-body"></div>

    <div class="chat-footer">
        <input id="msg" placeholder="Ask me anything...">
        <button class="btn btn-primary" onclick="send()">Send</button>
    </div>

</div>

<script>
function send(){
    let msg = document.getElementById("msg").value;
    if(!msg) return;

    let chatBody = document.getElementById("chatBody");

    chatBody.innerHTML += `<div class="message user">${msg}</div>`;
    chatBody.innerHTML += `<div class="typing">CiperBot is typing...</div>`;
    chatBody.scrollTop = chatBody.scrollHeight;

    fetch("/chat",{
        method:"POST",
        headers:{"Content-Type":"application/json"},
        body:JSON.stringify({message:msg})
    })
    .then(res=>res.json())
    .then(data=>{
        document.querySelector(".typing").remove();
        chatBody.innerHTML += `
            <div class="message bot">
                ${data.response}
                <br><small>Confidence: ${data.confidence}%</small>
            </div>`;
        chatBody.scrollTop = chatBody.scrollHeight;
    });

    document.getElementById("msg").value="";
}
</script>

</body>
</html>
""")

# ================= CHAT =================

@app.route("/chat", methods=["POST"])
def chat():
    user_input = request.json["message"]

    vectorizer, X, questions = train_model()

    if not questions:
        return jsonify({"response": "No FAQs available.", "confidence": 0})

    user_vector = vectorizer.transform([user_input])
    similarity = cosine_similarity(user_vector, X)

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

    confidence = round(score * 100, 2)

    # Log query
    cursor.execute(
        "INSERT INTO logs (user_input, bot_response, confidence) VALUES (?, ?, ?)",
        (user_input, response, confidence)
    )

    conn.commit()
    conn.close()

    return jsonify({"response": response, "confidence": confidence})

# ================= LOGIN =================

import os

def get_admin_credentials():
    admins = []

    for i in range(1, 5):  # Supports 4 admins
        username = os.environ.get(f"ADMIN_{i}_USER")
        password = os.environ.get(f"ADMIN_{i}_PASS")

        if username and password:
            admins.append((username, password))

    return admins


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        entered_user = request.form["username"]
        entered_pass = request.form["password"]

        admins = get_admin_credentials()

        for user, pwd in admins:
            if entered_user == user and entered_pass == pwd:
                session["admin"] = True
                session["admin_name"] = user
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
.card { border-radius:15px; }
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

    cursor.execute("SELECT * FROM faqs")
    faqs = cursor.fetchall()

    cursor.execute("SELECT COUNT(*) FROM logs")
    total_queries = cursor.fetchone()[0]

    cursor.execute("SELECT * FROM logs WHERE confidence < 40")
    low_confidence_logs = cursor.fetchall()

    conn.close()

    return render_template_string("""
<!DOCTYPE html>
<html>
<head>
<title>Admin Dashboard</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
<style>
body.dark { background-color:#121212; color:white; }
.dark .card { background:#1e1e1e; color:white; }
</style>
</head>

<body class="bg-light" id="body">

<nav class="navbar navbar-dark bg-dark px-4">
    <span class="navbar-brand">Admin Dashboard</span>
    <div>
        <button class="btn btn-secondary btn-sm me-2" onclick="toggle()">🌙</button>
        <a href="/logout" class="btn btn-danger btn-sm">Logout</a>
    </div>
</nav>

<div class="container mt-4">

    <div class="card shadow p-3 mb-4">
        <h5>📊 Statistics</h5>
        <p><strong>Total Queries:</strong> {{total_queries}}</p>
        <p><strong>Low Confidence (&lt;40%):</strong> {{low_confidence_logs|length}}</p>
    </div>

    <div class="row">
        <div class="col-md-6">
            <div class="card shadow p-3">
                <h5>Add FAQ</h5>
                <form method="POST" action="/add">
                    <input name="question" class="form-control mb-2" placeholder="Question" required>
                    <textarea name="answer" class="form-control mb-2" placeholder="Answer" required></textarea>
                    <button class="btn btn-primary">Add FAQ</button>
                </form>
            </div>
        </div>

        <div class="col-md-6">
            <div class="card shadow p-3">
                <h5>Existing FAQs</h5>
                {% for faq in faqs %}
                    <div class="border rounded p-2 mb-2">
                        <strong>{{faq[1]}}</strong>
                        <p>{{faq[2]}}</p>
                        <a href="/delete/{{faq[0]}}" class="btn btn-sm btn-danger">Delete</a>
                    </div>
                {% endfor %}
            </div>
        </div>
    </div>

    <div class="card shadow p-3 mt-4">
        <h5>⚠ Low Confidence Queries</h5>
        {% if low_confidence_logs %}
            {% for log in low_confidence_logs %}
                <div class="border rounded p-2 mb-2">
                    <strong>User:</strong> {{log[1]}} <br>
                    <strong>Confidence:</strong> {{log[3]}}%
                </div>
            {% endfor %}
        {% else %}
            <p>No low confidence queries.</p>
        {% endif %}
    </div>

</div>

<script>
function toggle(){
    document.getElementById("body").classList.toggle("dark");
}
</script>

</body>
</html>
""", faqs=faqs, total_queries=total_queries, low_confidence_logs=low_confidence_logs)

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