from flask import Flask, request, redirect, url_for, session, jsonify, render_template_string
import sqlite3
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

app = Flask(__name__)
app.secret_key = "supersecretkey"

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
    else:
        return None, None, []

# ================= HOME =================

@app.route("/")
def home():
    return render_template_string("""
    <!DOCTYPE html>
    <html>
    <head>
    <title>College Helpdesk</title>
    <style>
    body { font-family: Arial; background: linear-gradient(135deg,#2b5876,#4e4376); display:flex; justify-content:center; align-items:center; height:100vh; }
    .chat { background:white; padding:20px; border-radius:15px; width:400px; box-shadow:0 10px 30px rgba(0,0,0,0.3); }
    #messages { min-height:200px; margin-bottom:10px; }
    input { width:75%; padding:8px; }
    button { padding:8px; }
    </style>
    </head>
    <body>
    <div class="chat">
        <h2>🎓 College Helpdesk Chatbot</h2>
        <div id="messages"></div>
        <input id="msg" placeholder="Type your question...">
        <button onclick="send()">Send</button>
        <br><br>
        <a href="/login">Admin Login</a>
    </div>

    <script>
    function send(){
        let msg = document.getElementById("msg").value;
        fetch("/chat",{
            method:"POST",
            headers:{"Content-Type":"application/json"},
            body:JSON.stringify({message:msg})
        })
        .then(res=>res.json())
        .then(data=>{
            document.getElementById("messages").innerHTML += 
            "<p><b>You:</b> "+msg+"</p>"+
            "<p><b>Bot:</b> "+data.response+
            "<br><small>Confidence: "+data.confidence+"%</small></p>";
        });
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
        return jsonify({"response":"No FAQs available.","confidence":0})

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
        response = cursor.fetchone()[0]

    confidence = round(score*100,2)

    cursor.execute("INSERT INTO logs (user_input, bot_response, confidence) VALUES (?,?,?)",
                   (user_input,response,confidence))
    conn.commit()
    conn.close()

    return jsonify({"response":response,"confidence":confidence})

# ================= LOGIN =================

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method=="POST":
        if request.form["username"]=="admin" and request.form["password"]=="1234":
            session["admin"]=True
            return redirect(url_for("admin"))
        else:
            return "Invalid credentials"

    return """
    <form method="POST">
    <h2>Admin Login</h2>
    Username:<br><input name="username"><br>
    Password:<br><input name="password" type="password"><br><br>
    <button>Login</button>
    </form>
    """

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

    cursor.execute("SELECT COUNT(*) FROM logs WHERE confidence < 40")
    low_confidence = cursor.fetchone()[0]

    conn.close()

    return render_template_string("""
<!DOCTYPE html>
<html>
<head>
<title>Admin Dashboard</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
<style>
body.dark {
    background-color:#121212;
    color:white;
}
.dark .card {
    background:#1e1e1e;
    color:white;
}
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

    <div class="row">
        <div class="col-md-6">
            <div class="card shadow p-3">
                <h5>📊 Statistics</h5>
                <p><strong>Total Queries:</strong> {{total_queries}}</p>
                <p><strong>Low Confidence (&lt;40%):</strong> {{low_confidence}}</p>
            </div>
        </div>

        <div class="col-md-6">
            <div class="card shadow p-3">
                <h5>Add FAQ</h5>
                <form method="POST" action="/add">
                    <div class="mb-2">
                        <input name="question" class="form-control" placeholder="Question">
                    </div>
                    <div class="mb-2">
                        <textarea name="answer" class="form-control" placeholder="Answer"></textarea>
                    </div>
                    <button class="btn btn-primary">Add FAQ</button>
                </form>
            </div>
        </div>
    </div>

    <div class="card shadow p-3 mt-4">
        <h5>Existing FAQs</h5>
        {% for faq in faqs %}
            <div class="border rounded p-3 mb-3">
                <h6>{{faq[1]}}</h6>
                <p>{{faq[2]}}</p>
                <a href="/delete/{{faq[0]}}" class="btn btn-sm btn-danger">Delete</a>
            </div>
        {% endfor %}
    </div>

</div>

<script>
function toggle(){
    document.getElementById("body").classList.toggle("dark");
}
</script>

</body>
</html>
""", faqs=faqs, total_queries=total_queries, low_confidence=low_confidence)

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
    app.run(debug=True)