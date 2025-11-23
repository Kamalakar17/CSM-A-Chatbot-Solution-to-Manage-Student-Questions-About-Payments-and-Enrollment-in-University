from flask import Flask, render_template, request, jsonify, session, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
import os, random, smtplib, traceback
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from flask_mail import Mail
from flask_bcrypt import Bcrypt
from flask_migrate import Migrate
import difflib

# ---------------------- Flask Setup ---------------------- #
app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "secretkey")

# Database
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///chatbot_booking.db'
app.config['SQLALCHEMY_BINDS'] = {'booking_db': 'sqlite:///booking_database.db'}
app.config['UPLOAD_FOLDER'] = 'uploads'

# Mail Config (Gmail App Password)
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.environ.get("MAIL_USER", "kamalakarreddy202@gmail.com")
app.config['MAIL_PASSWORD'] = os.environ.get("MAIL_PASS", "uzusahgxuvonjeth")
app.config['MAIL_DEFAULT_SENDER'] = app.config['MAIL_USERNAME']

db = SQLAlchemy(app)
bcrypt = Bcrypt(app)
mail = Mail(app)
migrate = Migrate(app, db)

if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

# ---------------------- Database Models ---------------------- #
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(150), unique=True, nullable=True)
    otp_verified = db.Column(db.Boolean, default=False)
    subscribed = db.Column(db.Boolean, default=True)
    current_topic = db.Column(db.String(50), default=None)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class ChatHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    message = db.Column(db.String(500))
    response = db.Column(db.String(500))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

class Document(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    doc_name = db.Column(db.String(150))
    doc_path = db.Column(db.String(200))
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)

class Course(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    course_name = db.Column(db.String(150))
    payment_details = db.Column(db.String(150))

with app.app_context():
    db.create_all()

# ---------------------- Helper Functions ---------------------- #
user_state = {}  # user_id -> state
otp_store = {}   # user_id -> otp

def generate_otp():
    return str(random.randint(100000, 999999))

def send_mail(to, subject, body):
    """Send email using Gmail SMTP with App Password."""
    try:
        msg = MIMEMultipart()
        msg['From'] = app.config['MAIL_USERNAME']
        msg['To'] = to
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))

        server = smtplib.SMTP(app.config['MAIL_SERVER'], app.config['MAIL_PORT'])
        server.starttls()
        server.login(app.config['MAIL_USERNAME'], app.config['MAIL_PASSWORD'])
        server.sendmail(app.config['MAIL_USERNAME'], to, msg.as_string())
        server.quit()
        print(f"✅ Email sent to {to}")
        return True
    except Exception as e:
        print(f"❌ Email Error: {e}")
        traceback.print_exc()
        return False

def log_to_file(user, message, response):
    """Save chat logs per user in text files."""
    log_dir = "user_logs"
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
    filename = os.path.join(log_dir, f"{user.email or 'guest'}_log.txt")
    with open(filename, "a", encoding="utf-8") as f:
        f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] User: {message}\n")
        f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Bot: {response}\n\n")

def load_intents():
    """Load Q/A from txt files for each topic."""
    intents = {}
    topics = ["enrollment", "payment", "placement", "documents"]
    for topic in topics:
        qa_list = []
        path = os.path.join("intents", f"{topic}.txt")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    if "|" in line:
                        q, a = line.strip().split("|")
                        qa_list.append((q.strip().lower(), a.strip()))
        intents[topic] = qa_list
    return intents

intents = load_intents()

def get_response(message, topic):
    """Return best-matching answer from selected topic using fuzzy matching."""
    if not topic:
        return "Please select a topic: Enrollment, Documents, Payments, Placements."
    
    msg = message.lower().strip()
    qa_list = intents.get(topic, [])

    if not qa_list:
        return f"No FAQs found for {topic}."

    # Use difflib to find the closest question
    questions = [q for q, a in qa_list]
    match = difflib.get_close_matches(msg, questions, n=1, cutoff=0.4)  # adjust cutoff
    if match:
        for q, a in qa_list:
            if q == match[0]:
                return a

    return "Sorry, I don't understand. Please ask another question about your selected topic."

# ---------------------- Routes ---------------------- #
@app.route('/')
def home():
    return render_template('home.html')

@app.route('/chatbot')
def chatbot_page():
    return render_template('chatbot.html')

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        if username == 'admin' and password == 'admin123':
            session['admin_logged_in'] = True
            return redirect(url_for('admin_logs'))
        else:
            flash('Invalid credentials', 'danger')
    return render_template('admin_login.html')

@app.route('/chatbot/send_message', methods=['POST'])
def chatbot_send_message():
    message = request.form.get('message', '').strip()
    user_id = request.form.get('user_id')

    if user_id:
        try:
            user_id = int(user_id)
        except ValueError:
            user_id = None

    # Step 0: New user creation
    if not user_id:
        user = User(email=None)
        db.session.add(user)
        db.session.commit()
        user_id = user.id
        user_state[user_id] = 'awaiting_email'
        return jsonify({"response": "Welcome! Please enter your email to register:", "user_id": user_id})

    user = db.session.get(User, user_id)

    # Step 1: Awaiting email
    if user_state.get(user_id) == 'awaiting_email':
        if "@" not in message or "." not in message:
            return jsonify({"response": "Please enter a valid email address.", "user_id": user_id})

        existing_user = User.query.filter_by(email=message).first()
        if existing_user:
            user = existing_user
            user_state[user.id] = 'verified'
            return jsonify({
                "response": "✅ Welcome back! How can I help you?",
                "options": ["Documents", "Placements", "Enrollment", "Payments", "Unsubscribe"],
                "user_id": user.id
            })

        user.email = message
        db.session.commit()

        otp = generate_otp()
        otp_store[user_id] = otp
        sent = send_mail(user.email, "Chatbot OTP", f"Your OTP is {otp}")

        if sent:
            user_state[user_id] = 'awaiting_otp'
            log_to_file(user, message, "OTP sent to email.")
            return jsonify({"response": "OTP sent to your email. Please enter the OTP to verify.", "user_id": user_id})
        else:
            return jsonify({"response": "Failed to send OTP. Please try again later.", "user_id": user_id})

    # Step 2: Awaiting OTP
    if user_state.get(user_id) == 'awaiting_otp':
        if message == otp_store.get(user_id):
            user.otp_verified = True
            db.session.commit()
            user_state[user_id] = 'verified'
            return jsonify({
                "response": "✅ Registration completed! How can I help you? Select a topic.",
                "options": ["Documents", "Placements", "Enrollment", "Payments", "Unsubscribe"],
                "user_id": user_id
            })
        else:
            return jsonify({"response": "Invalid OTP. Please try again.", "user_id": user_id})

    # Step 3: Verified users → Topic selection & queries
    topics = ["documents", "placement", "enrollment", "payment", "unsubscribe"]

    if message.lower() == "unsubscribe":
        user.subscribed = False
        db.session.commit()
        return jsonify({"response": "You have unsubscribed successfully.", "user_id": user_id})

    if message.lower() in topics:
        user.current_topic = message.lower()
        db.session.commit()
        user_state[user_id] = "topic_selected"
        return jsonify({
            "response": f"You selected '{message.title()}'. You can now ask your questions about {message.title()}.",
            "user_id": user_id
        })

    if user_state.get(user_id) in ["verified", "topic_selected"] and user.current_topic:
        response = get_response(message, user.current_topic)
        log_to_file(user, message, response)
        return jsonify({"response": response, "user_id": user_id})

    return jsonify({
        "response": "Please select a topic first: Documents, Placement, Enrollment, Payment.",
        "user_id": user_id
    })

# ---------------------- Admin Logs ---------------------- #
@app.route('/admin/logs')
def admin_logs():
    if not session.get("admin_logged_in"):
        return redirect(url_for("admin_login"))

    users = User.query.all()
    log_dir = "user_logs"
    user_data = []

    for user in users:
        email = user.email or "Guest"
        otp_status = "Verified" if user.otp_verified else "Pending"

        # Check if chat log exists
        log_filename = f"{email}_log.txt"
        log_path = os.path.join(log_dir, log_filename)
        if os.path.exists(log_path):
            download_link = url_for('download_log', filename=log_filename)
        else:
            download_link = None

        user_data.append({
            "email": email,
            "otp_status": otp_status,
            "log_link": download_link
        })

    return render_template("admin_logs.html", users=user_data)

from flask import Flask, render_template, request, jsonify, session, redirect, url_for, flash, send_from_directory


@app.route('/admin/download/<filename>')
def download_log(filename):
    if not session.get("admin_logged_in"):
        return redirect(url_for("admin_login"))
    return send_from_directory('user_logs', filename, as_attachment=True)


@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_logged_in', None)  # or your session key
    flash("Logged out successfully.", "success")
    return redirect(url_for('home'))


# ---------------------- Run ---------------------- #
if __name__ == '__main__':
    app.run(debug=True)
