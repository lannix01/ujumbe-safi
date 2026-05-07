import pickle
from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_mysqldb import MySQL
from werkzeug.security import generate_password_hash, check_password_hash
import MySQLdb.cursors
from werkzeug.utils import secure_filename
import os
from datetime import datetime
from googletrans import Translator
import re
import json
from urllib.parse import quote
from urllib.request import Request, urlopen

app = Flask(__name__)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_tfidf = None
_nb_model = None
TOXIC_TERMS = {
    'matako', 'malaya', 'kuma', 'nigga', 'mjinga', 'mshenzi',
    'chupa nyeusi', 'panya', 'mkundu', 'asshole', 'gay', 'shoga',
    'mdangaji', 'tomba', 'kutombwa', 'msenge', 'kumamako', 'umbwa',
    'nyapu', 'ikus', 'punyeto'
}

# Configure MySQL
# Set upload folder and allowed extensions for image uploads
app.config['UPLOAD_FOLDER'] = os.path.join(BASE_DIR, 'static', 'uploads')
app.config['ALLOWED_EXTENSIONS'] = {'png', 'jpg', 'jpeg', 'gif'}
app.config['MYSQL_HOST'] = 'localhost'
app.config['MYSQL_USER'] = 'crud'
app.config['MYSQL_PASSWORD'] = ''
app.config['MYSQL_DB'] = 'twitter'
mysql = MySQL(app)
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Set a secret key for session management
app.secret_key = 'your_secret_key'


def validate_password(password):
    if len(password) < 6:
        return 'Password must be at least 6 characters long.'
    if not re.match(r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d).+$", password):
        return 'Password must contain at least one lowercase letter, one uppercase letter, and one digit.'
    return ''


def contains_toxic_term(text):
    normalized_text = re.sub(r'\s+', ' ', text.lower()).strip()
    for term in TOXIC_TERMS:
        normalized_term = re.escape(term.lower())
        if re.search(r'(?<!\w)' + normalized_term + r'(?!\w)', normalized_text):
            return True
    return False


def normalize_label(label):
    return 'Toxic' if label == 'Toxic' else 'Non-Toxic'


def label_matches_text(text, term):
    normalized_text = re.sub(r'\s+', ' ', text.lower()).strip()
    normalized_term = re.sub(r'\s+', ' ', term.lower()).strip()
    if not normalized_term:
        return False
    return re.search(r'(?<!\w)' + re.escape(normalized_term) + r'(?!\w)', normalized_text) is not None


def ensure_training_table():
    try:
        cursor = mysql.connection.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS moderation_terms (
                id INT PRIMARY KEY AUTO_INCREMENT,
                term VARCHAR(255) NOT NULL UNIQUE,
                translation VARCHAR(255),
                meaning TEXT,
                label ENUM('Toxic', 'Non-Toxic') NOT NULL,
                source VARCHAR(50) DEFAULT 'manual',
                created_by INT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            )
        """)
        mysql.connection.commit()
        cursor.close()
    except Exception:
        pass


def ensure_posts_moderation_columns():
    try:
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        cursor.execute(
            """
            SELECT COLUMN_NAME
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'posts'
            """,
            (app.config['MYSQL_DB'],)
        )
        existing_columns = {row['COLUMN_NAME'] for row in cursor.fetchall()}
        column_updates = {
            'toxicity_label': "ALTER TABLE posts ADD COLUMN toxicity_label ENUM('Toxic', 'Non-Toxic') DEFAULT 'Non-Toxic'",
            'moderation_status': "ALTER TABLE posts ADD COLUMN moderation_status ENUM('Approved', 'Rejected') DEFAULT 'Approved'",
            'moderation_reason': "ALTER TABLE posts ADD COLUMN moderation_reason VARCHAR(255)",
            'audience': "ALTER TABLE posts ADD COLUMN audience ENUM('Public', 'Friends', 'Only Me') DEFAULT 'Public'",
            'comments_enabled': "ALTER TABLE posts ADD COLUMN comments_enabled TINYINT(1) DEFAULT 1"
        }
        for column, statement in column_updates.items():
            if column not in existing_columns:
                cursor.execute(statement)
        mysql.connection.commit()
        cursor.close()
    except Exception:
        pass


def ensure_social_schema():
    try:
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        cursor.execute(
            """
            SELECT COLUMN_NAME
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'accounts'
            """,
            (app.config['MYSQL_DB'],)
        )
        account_columns = {row['COLUMN_NAME'] for row in cursor.fetchall()}
        account_updates = {
            'is_admin': "ALTER TABLE accounts ADD COLUMN is_admin TINYINT(1) DEFAULT 0",
            'account_status': "ALTER TABLE accounts ADD COLUMN account_status ENUM('Active', 'Disabled', 'Black Book') DEFAULT 'Active'",
            'can_post': "ALTER TABLE accounts ADD COLUMN can_post TINYINT(1) DEFAULT 1",
            'black_label_count': "ALTER TABLE accounts ADD COLUMN black_label_count INT DEFAULT 0",
            'bio': "ALTER TABLE accounts ADD COLUMN bio VARCHAR(280)"
        }
        for column, statement in account_updates.items():
            if column not in account_columns:
                cursor.execute(statement)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS connections (
                id INT PRIMARY KEY AUTO_INCREMENT,
                requester_id INT NOT NULL,
                receiver_id INT NOT NULL,
                status ENUM('Pending', 'Accepted', 'Rejected') DEFAULT 'Pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                UNIQUE KEY unique_connection (requester_id, receiver_id)
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INT PRIMARY KEY AUTO_INCREMENT,
                sender_id INT NOT NULL,
                receiver_id INT NOT NULL,
                message TEXT NOT NULL,
                toxicity_label ENUM('Toxic', 'Non-Toxic') DEFAULT 'Non-Toxic',
                moderation_status ENUM('Delivered', 'Rejected') DEFAULT 'Delivered',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute(
            """
            SELECT COLUMN_NAME
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'messages'
            """,
            (app.config['MYSQL_DB'],)
        )
        message_columns = {row['COLUMN_NAME'] for row in cursor.fetchall()}
        message_updates = {
            'toxicity_label': "ALTER TABLE messages ADD COLUMN toxicity_label ENUM('Toxic', 'Non-Toxic') DEFAULT 'Non-Toxic'",
            'moderation_status': "ALTER TABLE messages ADD COLUMN moderation_status ENUM('Delivered', 'Rejected') DEFAULT 'Delivered'"
        }
        for column, statement in message_updates.items():
            if column not in message_columns:
                cursor.execute(statement)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS comments (
                id INT PRIMARY KEY AUTO_INCREMENT,
                post_id INT NOT NULL,
                user_id INT NOT NULL,
                comment TEXT NOT NULL,
                toxicity_label ENUM('Toxic', 'Non-Toxic') DEFAULT 'Non-Toxic',
                moderation_status ENUM('Approved', 'Rejected') DEFAULT 'Approved',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS reposts (
                id INT PRIMARY KEY AUTO_INCREMENT,
                post_id INT NOT NULL,
                user_id INT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE KEY unique_repost (post_id, user_id)
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS likes (
                id INT PRIMARY KEY AUTO_INCREMENT,
                post_id INT NOT NULL,
                user_id INT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE KEY unique_like (post_id, user_id)
            )
        """)
        mysql.connection.commit()
        cursor.close()
    except Exception:
        pass


def current_user_is_admin():
    return bool(session.get('is_admin'))


def login_required():
    return 'loggedin' in session


def admin_required():
    return login_required() and current_user_is_admin()


def account_is_admin(account):
    return bool(account.get('is_admin')) or account.get('id') == 1 or account.get('username') == 'admin'


def get_learned_terms():
    ensure_training_table()
    try:
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        cursor.execute("SELECT * FROM moderation_terms ORDER BY updated_at DESC")
        terms = cursor.fetchall()
        cursor.close()
        return terms
    except Exception:
        return []


def learned_label_for_text(text):
    for term in get_learned_terms():
        candidates = [term.get('term', ''), term.get('translation', '')]
        for candidate in candidates:
            if candidate and label_matches_text(text, candidate):
                return term['label']
    return ''


def fetch_internet_meaning(term):
    lookup = quote(term.strip())
    if not lookup:
        return ''

    try:
        request = Request(
            f"https://api.dictionaryapi.dev/api/v2/entries/en/{lookup}",
            headers={"User-Agent": "Ujumbe-Safi/1.0"}
        )
        with urlopen(request, timeout=4) as response:
            data = json.loads(response.read().decode("utf-8"))
        meanings = data[0].get('meanings', [])
        definitions = meanings[0].get('definitions', []) if meanings else []
        return definitions[0].get('definition', '') if definitions else ''
    except Exception:
        return ''


def suggest_term_context(term):
    translated = swahili_to_english(term)
    meaning = fetch_internet_meaning(translated if translated else term)
    return translated, meaning

@app.route('/', methods=['GET', 'POST'])
def login():
    msg = ''
    if request.method == 'POST' and 'username' in request.form and 'password' in request.form:
        ensure_social_schema()
        username = request.form['username']
        password = request.form['password']
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        cursor.execute('SELECT * FROM accounts WHERE username = %s', (username,))
        account = cursor.fetchone()
        if account and check_password_hash(account['password'], password):
            if account.get('account_status') in ('Disabled', 'Black Book'):
                msg = 'This account is not active. Contact the administrator.'
                return render_template('login.html', msg=msg)
            session['loggedin'] = True
            session['id'] = account['id']
            session['username'] = account['username']
            session['pic'] = account['profile_pic']
            session['fullname'] = account['fullname']
            session['is_admin'] = account_is_admin(account)
            return redirect(url_for('home' if session['is_admin'] else 'user_home'))
        else:
            msg = 'Incorrect username/password!'
    return render_template('login.html', msg=msg)


"""
Adds a route to register users to the system
"""
@app.route('/register/', methods=['GET', 'POST'])
def register():
    msg = ''
    if request.method == 'POST':
        ensure_social_schema()
        fullname = request.form['fullname']
        username = request.form['username']
        password = request.form['password']
        email = request.form['email']
        profile_pic = request.files['profile_pic']  # Get the uploaded file
        
        # Validate email format
        if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
            msg = 'Invalid email address. Please enter a valid email.'
            return render_template('register.html', msg=msg)
        
        msg = validate_password(password)
        if msg:
            return render_template('register.html', msg=msg)
        
        # Further validation logic for username, email uniqueness, etc.
        
        if profile_pic and allowed_file(profile_pic.filename):
            filename = secure_filename(profile_pic.filename)
            profile_pic.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))  # Save the file to the server
            # Hashing the password using Werkzeug
            hashed_password = generate_password_hash(password, method='pbkdf2:sha256')
            # Pushing user data into the database
            cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
            cursor.execute(
                "INSERT INTO accounts (fullname, username, password, email, profile_pic, is_admin) VALUES (%s, %s, %s, %s, %s, %s)",
                (fullname, username, hashed_password, email, filename, 0)
            )
            mysql.connection.commit()
            msg = 'You have successfully registered!'
            return render_template('login.html', msg=msg)
        else:
            msg = 'Invalid file format. Please upload a valid image.'
    return render_template('register.html', msg=msg)


@app.route('/reset-password/', methods=['GET', 'POST'])
def reset_password():
    msg = ''
    success = ''
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')

        if not username or not email or not password:
            msg = 'Fill in your username, email, and new password.'
        elif not re.match(r"[^@]+@[^@]+\.[^@]+", email):
            msg = 'Invalid email address. Please enter a valid email.'
        else:
            msg = validate_password(password)

        if not msg:
            cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
            cursor.execute(
                'SELECT id FROM accounts WHERE username = %s AND email = %s',
                (username, email)
            )
            account = cursor.fetchone()
            if account:
                hashed_password = generate_password_hash(password, method='pbkdf2:sha256')
                cursor.execute(
                    'UPDATE accounts SET password = %s WHERE id = %s',
                    (hashed_password, account['id'])
                )
                mysql.connection.commit()
                success = 'Password reset successfully. You can now login.'
            else:
                msg = 'No account matched that username and email.'
            cursor.close()

    return render_template('reset_password.html', msg=msg, success=success)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']
'''
Getting all posts
'''
def get_all_tweets():
    with app.app_context():
        ensure_social_schema()
        ensure_posts_moderation_columns()
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        cursor.execute("""
            SELECT p.*,
                   COUNT(DISTINCT l.id) AS like_count,
                   COUNT(DISTINCT c.id) AS comment_count,
                   COUNT(DISTINCT r.id) AS repost_count,
                   CASE
                     WHEN p.user_id = %s THEN 3
                     WHEN EXISTS (
                       SELECT 1 FROM connections cn2
                       WHERE cn2.status = 'Accepted'
                         AND ((cn2.requester_id = %s AND cn2.receiver_id = p.user_id)
                          OR (cn2.receiver_id = %s AND cn2.requester_id = p.user_id))
                     ) THEN 2
                     WHEN EXISTS (
                       SELECT 1 FROM likes l2
                       JOIN posts p2 ON p2.id = l2.post_id
                       WHERE l2.user_id = %s AND p2.user_id = p.user_id
                     ) THEN 1
                     ELSE 0
                   END AS feed_weight
            FROM posts p
            LEFT JOIN likes l ON l.post_id = p.id
            LEFT JOIN comments c ON c.post_id = p.id
            LEFT JOIN reposts r ON r.post_id = p.id
            GROUP BY p.id
            ORDER BY p.timestamp DESC
        """)
        posts = cursor.fetchall()
        cursor.close()
    
    return posts


def get_approved_posts():
    with app.app_context():
        ensure_social_schema()
        ensure_posts_moderation_columns()
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        current_user = session.get('id', 0)
        cursor.execute("""
            SELECT p.*,
                   COUNT(DISTINCT l.id) AS like_count,
                   COUNT(DISTINCT c.id) AS comment_count,
                   COUNT(DISTINCT r.id) AS repost_count,
                   CASE
                     WHEN p.user_id = %s THEN 3
                     WHEN EXISTS (
                       SELECT 1 FROM connections cn2
                       WHERE cn2.status = 'Accepted'
                         AND ((cn2.requester_id = %s AND cn2.receiver_id = p.user_id)
                          OR (cn2.receiver_id = %s AND cn2.requester_id = p.user_id))
                     ) THEN 2
                     WHEN EXISTS (
                       SELECT 1 FROM likes l2
                       JOIN posts p2 ON p2.id = l2.post_id
                       WHERE l2.user_id = %s AND p2.user_id = p.user_id
                     ) THEN 1
                     ELSE 0
                   END AS feed_weight
            FROM posts p
            LEFT JOIN likes l ON l.post_id = p.id
            LEFT JOIN comments c ON c.post_id = p.id AND c.moderation_status = 'Approved'
            LEFT JOIN reposts r ON r.post_id = p.id
            WHERE p.moderation_status = 'Approved'
              AND (
                COALESCE(p.audience, 'Public') = 'Public'
                OR p.user_id = %s
                OR (
                  COALESCE(p.audience, 'Public') = 'Friends'
                  AND EXISTS (
                    SELECT 1 FROM connections cn
                    WHERE cn.status = 'Accepted'
                      AND ((cn.requester_id = %s AND cn.receiver_id = p.user_id)
                       OR (cn.receiver_id = %s AND cn.requester_id = p.user_id))
                  )
                )
              )
            GROUP BY p.id
            ORDER BY feed_weight DESC, RAND(), p.timestamp DESC
        """, (current_user, current_user, current_user, current_user, current_user, current_user, current_user))
        posts = cursor.fetchall()
        cursor.close()
    return posts


def get_recommended_users():
    ensure_social_schema()
    try:
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        cursor.execute(
            """
            SELECT a.id, a.fullname, a.username, a.profile_pic,
                   c.status AS connection_status
            FROM accounts a
            LEFT JOIN connections c
              ON ((c.requester_id = %s AND c.receiver_id = a.id)
               OR (c.receiver_id = %s AND c.requester_id = a.id))
            WHERE a.id <> %s
              AND COALESCE(a.account_status, 'Active') = 'Active'
              AND COALESCE(a.is_admin, 0) = 0
            ORDER BY a.created_at DESC
            LIMIT 20
            """,
            (session['id'], session['id'], session['id'])
        )
        users = cursor.fetchall()
        cursor.close()
        return users
    except Exception:
        return []


def get_connection_requests():
    ensure_social_schema()
    try:
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        cursor.execute(
            """
            SELECT c.*, a.fullname, a.username, a.profile_pic
            FROM connections c
            JOIN accounts a ON a.id = c.requester_id
            WHERE c.receiver_id = %s AND c.status = 'Pending'
            ORDER BY c.created_at DESC
            """,
            (session['id'],)
        )
        requests = cursor.fetchall()
        cursor.close()
        return requests
    except Exception:
        return []


def get_connected_users():
    ensure_social_schema()
    try:
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        cursor.execute(
            """
            SELECT a.id, a.fullname, a.username, a.profile_pic
            FROM connections c
            JOIN accounts a
              ON a.id = CASE WHEN c.requester_id = %s THEN c.receiver_id ELSE c.requester_id END
            WHERE (c.requester_id = %s OR c.receiver_id = %s)
              AND c.status = 'Accepted'
            ORDER BY a.fullname
            """,
            (session['id'], session['id'], session['id'])
        )
        users = cursor.fetchall()
        cursor.close()
        return users
    except Exception:
        return []


def get_sent_connection_requests():
    ensure_social_schema()
    try:
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        cursor.execute(
            """
            SELECT c.*, a.fullname, a.username, a.profile_pic
            FROM connections c
            JOIN accounts a ON a.id = c.receiver_id
            WHERE c.requester_id = %s AND c.status = 'Pending'
            ORDER BY c.created_at DESC
            """,
            (session['id'],)
        )
        requests = cursor.fetchall()
        cursor.close()
        return requests
    except Exception:
        return []


def search_users(query):
    ensure_social_schema()
    if not query:
        return []
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    like_query = '%' + query + '%'
    cursor.execute(
        """
        SELECT id, fullname, username, profile_pic
        FROM accounts
        WHERE id <> %s
          AND COALESCE(account_status, 'Active') = 'Active'
          AND (username LIKE %s OR fullname LIKE %s)
        ORDER BY username
        LIMIT 20
        """,
        (session['id'], like_query, like_query)
    )
    users = cursor.fetchall()
    cursor.close()
    return users


def profile_stats(user_id):
    ensure_social_schema()
    ensure_posts_moderation_columns()
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute(
        """
        SELECT
          (SELECT COUNT(*) FROM posts WHERE user_id = %s AND moderation_status = 'Approved') AS post_count,
          (SELECT COUNT(*) FROM connections WHERE status = 'Accepted' AND (requester_id = %s OR receiver_id = %s)) AS connection_count,
          (SELECT COUNT(*) FROM connections WHERE status = 'Pending' AND receiver_id = %s) AS request_count,
          (SELECT COUNT(*) FROM likes l JOIN posts p ON p.id = l.post_id WHERE p.user_id = %s) AS like_count,
          (SELECT COUNT(*) FROM comments c JOIN posts p ON p.id = c.post_id WHERE p.user_id = %s) AS comment_count,
          (SELECT COUNT(*) FROM reposts r JOIN posts p ON p.id = r.post_id WHERE p.user_id = %s) AS repost_count
        """,
        (user_id, user_id, user_id, user_id, user_id, user_id, user_id)
    )
    stats = cursor.fetchone()
    cursor.close()
    return stats or {}


def get_post_detail(post_id, include_rejected=False):
    ensure_social_schema()
    ensure_posts_moderation_columns()
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    status_filter = "" if include_rejected else "AND p.moderation_status = 'Approved'"
    cursor.execute(
        f"""
        SELECT p.*,
               COUNT(DISTINCT l.id) AS like_count,
               COUNT(DISTINCT c.id) AS comment_count,
               COUNT(DISTINCT r.id) AS repost_count
        FROM posts p
        LEFT JOIN likes l ON l.post_id = p.id
        LEFT JOIN comments c ON c.post_id = p.id {' ' if include_rejected else "AND c.moderation_status = 'Approved'"}
        LEFT JOIN reposts r ON r.post_id = p.id
        WHERE p.id = %s {status_filter}
        GROUP BY p.id
        """,
        (post_id,)
    )
    post = cursor.fetchone()
    if not post:
        cursor.close()
        return None, []

    comment_filter = "" if include_rejected else "AND c.moderation_status = 'Approved'"
    cursor.execute(
        f"""
        SELECT c.*, a.fullname, a.username, a.profile_pic
        FROM comments c
        JOIN accounts a ON a.id = c.user_id
        WHERE c.post_id = %s {comment_filter}
        ORDER BY c.created_at ASC
        """,
        (post_id,)
    )
    comments = cursor.fetchall()
    cursor.close()
    return post, comments
    
@app.route('/posts')
def posts():
    if admin_required():
        return redirect(url_for('admin_posts'))
    if login_required():
        return redirect(url_for('user_home'))
    return redirect(url_for('login'))

@app.route('/redirect_to_posts')
def redirect_to_posts():
    return redirect('/posts')

"""
home redirection
"""
@app.route('/home/')
def home():
    if admin_required():
        return render_template('index.html', posts=get_approved_posts(), username=session['username'], pic=session['pic'])
    if login_required():
        return redirect(url_for('user_home'))
    return redirect(url_for('login'))


@app.route('/user/')
def user_home():
    if not login_required():
        return redirect(url_for('login'))
    ensure_social_schema()
    return render_template(
        'user_home.html',
        posts=get_approved_posts(),
        username=session['username'],
        pic=session['pic'],
        recommended_users=get_recommended_users(),
        connection_requests=get_connection_requests(),
        connected_users=get_connected_users()
    )


@app.route('/compose')
def compose():
    if not login_required():
        return redirect(url_for('login'))
    return render_template('compose.html', pic=session.get('pic'))


def load_tfidf():
    global _tfidf
    if _tfidf is None:
        with open(os.path.join(BASE_DIR, "tf_idf.pkt"), "rb") as model_file:
            _tfidf = pickle.load(model_file)
    return _tfidf

def load_model():
    global _nb_model
    if _nb_model is None:
        with open(os.path.join(BASE_DIR, "toxicity_model.pkt"), "rb") as model_file:
            _nb_model = pickle.load(model_file)
    return _nb_model

def toxicity_prediction(text):
    learned_label = learned_label_for_text(text)
    if learned_label:
        return learned_label

    if contains_toxic_term(text):
        return "Toxic"

    tfidf = load_tfidf()
    text_tfidf = tfidf.transform([text]).toarray()
    nb_model = load_model()
    prediction = nb_model.predict(text_tfidf)
    class_name = "Toxic" if int(prediction[0]) == 1 else "Non-Toxic"
    return class_name


def model_terms(limit=20):
    try:
        tfidf = load_tfidf()
        model = load_model()
        features = tfidf.get_feature_names_out()
        toxic_index = 1 if len(model.classes_) > 1 else 0
        safe_index = 0
        toxic_scores = model.feature_log_prob_[toxic_index]
        safe_scores = model.feature_log_prob_[safe_index]

        top_toxic = sorted(
            zip(features, toxic_scores),
            key=lambda item: item[1],
            reverse=True
        )[:limit]
        top_safe = sorted(
            zip(features, safe_scores),
            key=lambda item: item[1],
            reverse=True
        )[:limit]
        return {
            'vocabulary_size': len(features),
            'top_toxic': top_toxic,
            'top_safe': top_safe
        }
    except Exception as exc:
        return {
            'vocabulary_size': 0,
            'top_toxic': [],
            'top_safe': [],
            'error': str(exc)
        }

def swahili_to_english(tweet):
    try:
        translator = Translator()
        translation = translator.translate(tweet, dest='en')
        return translation.text
    except Exception:
        return tweet

@app.route('/create_post', methods=['POST'])
def create_post():
    if request.method == 'POST':
        if 'loggedin' in session:
            ensure_social_schema()
            ensure_posts_moderation_columns()
            current_user = session['id']
            fullname = session['fullname']
            username = session['username']
            tweet = request.form['tweet']
            audience = request.form.get('audience', 'Public')
            if audience not in ('Public', 'Friends', 'Only Me'):
                audience = 'Public'
            pic = request.files.get('post_pic')
            cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
            cursor.execute('SELECT can_post, account_status FROM accounts WHERE id = %s', (current_user,))
            account = cursor.fetchone()
            cursor.close()
            if account and (not account.get('can_post') or account.get('account_status') in ('Disabled', 'Black Book')):
                flash("Your posting access is currently disabled.")
                return redirect(url_for('user_home'))

            # Validate tweet length
            if len(tweet) > 280:
                flash("Tweet is too long. Please keep it under 280 characters.")
                return redirect(url_for('home'))
            res = swahili_to_english(tweet)
            toxicity = "Toxic" if contains_toxic_term(tweet) else toxicity_prediction(res)
            moderation_status = "Rejected" if toxicity == "Toxic" else "Approved"
            moderation_reason = "Flagged as toxic content." if toxicity == "Toxic" else "Passed moderation."

            timestamp = datetime.now()

            try:
                # Retrieve profile pic from session
                profile_pic = session.get('pic', '')

                if pic and allowed_file(pic.filename):
                    filename = secure_filename(pic.filename)
                    # Store only the file name
                    post_pic = filename
                    # Save the post picture to the upload folder
                    pic.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                else:
                    post_pic = None

                cursor = mysql.connection.cursor()

                # Insert the new post into the 'posts' table
                cursor.execute(
                    """
                    INSERT INTO posts
                    (user_id, fullname, username, tweet, post_pic, profile_pic, timestamp, toxicity_label, moderation_status, moderation_reason, audience)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        current_user,
                        fullname,
                        username,
                        tweet,
                        post_pic,
                        profile_pic,
                        timestamp,
                        toxicity,
                        moderation_status,
                        moderation_reason,
                        audience
                    )
                )

                # Commit the transaction and close the cursor
                mysql.connection.commit()
                cursor.close()

                if moderation_status == "Rejected":
                    cursor = mysql.connection.cursor()
                    cursor.execute(
                        """
                        UPDATE accounts
                        SET black_label_count = COALESCE(black_label_count, 0) + 1,
                            account_status = CASE
                                WHEN COALESCE(black_label_count, 0) + 1 >= 10 THEN 'Black Book'
                                ELSE account_status
                            END,
                            can_post = CASE
                                WHEN COALESCE(black_label_count, 0) + 1 >= 10 THEN 0
                                ELSE can_post
                            END
                        WHERE id = %s
                        """,
                        (current_user,)
                    )
                    mysql.connection.commit()
                    cursor.close()
                    flash("Post saved as rejected because it contains toxic content.")
                else:
                    flash("Tweet posted successfully!")
                return redirect(url_for('home' if current_user_is_admin() else 'user_home'))

            except Exception as e:
                # Rollback the transaction in case of error
                mysql.connection.rollback()
                flash("An error occurred while creating the post: " + str(e))
                return redirect(url_for('home' if current_user_is_admin() else 'user_home'))

    return redirect(url_for('login'))
@app.route('/manual', methods=['GET', 'POST'])
def manual_test():
    result = None
    original_text = ''
    translated_text = ''
    error = ''

    if request.method == 'POST':
        original_text = request.form.get('text_input', '').strip()
        if not original_text:
            error = 'Enter a word, phrase, or post before running the check.'
        else:
            try:
                translated_text = swahili_to_english(original_text)
                result = "Toxic" if contains_toxic_term(original_text) else toxicity_prediction(translated_text)
            except Exception as exc:
                error = 'The detector could not complete the analysis: ' + str(exc)

    return render_template(
        'testpage.html',
        result=result,
        original_text=original_text,
        translated_text=translated_text,
        error=error
    )


@app.route('/connect/<int:user_id>', methods=['POST'])
def connect_user(user_id):
    if not login_required() or user_id == session['id']:
        return redirect(url_for('login'))
    ensure_social_schema()
    cursor = mysql.connection.cursor()
    cursor.execute(
        """
        INSERT IGNORE INTO connections (requester_id, receiver_id, status)
        VALUES (%s, %s, 'Pending')
        """,
        (session['id'], user_id)
    )
    mysql.connection.commit()
    cursor.close()
    flash("Connection request sent.")
    return redirect(request.referrer or url_for('requests_page'))


@app.route('/connections/<int:connection_id>/<action>', methods=['POST'])
def manage_connection(connection_id, action):
    if not login_required():
        return redirect(url_for('login'))
    status = 'Accepted' if action == 'accept' else 'Rejected'
    ensure_social_schema()
    cursor = mysql.connection.cursor()
    cursor.execute(
        """
        UPDATE connections
        SET status = %s
        WHERE id = %s AND receiver_id = %s
        """,
        (status, connection_id, session['id'])
    )
    mysql.connection.commit()
    cursor.close()
    flash("Connection request updated.")
    return redirect(request.referrer or url_for('requests_page'))


@app.route('/connections/disconnect/<int:user_id>', methods=['POST'])
def disconnect_user(user_id):
    if not login_required():
        return redirect(url_for('login'))
    ensure_social_schema()
    cursor = mysql.connection.cursor()
    cursor.execute(
        """
        DELETE FROM connections
        WHERE status = 'Accepted'
          AND ((requester_id = %s AND receiver_id = %s)
           OR (requester_id = %s AND receiver_id = %s))
        """,
        (session['id'], user_id, user_id, session['id'])
    )
    mysql.connection.commit()
    cursor.close()
    flash("Connection removed.")
    return redirect(request.referrer or url_for('requests_page', tab='friends'))


@app.route('/requests')
def requests_page():
    if not login_required():
        return redirect(url_for('login'))
    query = request.args.get('q', '').strip()
    return render_template(
        'requests.html',
        connection_requests=get_connection_requests(),
        sent_requests=get_sent_connection_requests(),
        connected_users=get_connected_users(),
        search_results=search_users(query),
        query=query,
        searched=bool(query),
        tab=request.args.get('tab', 'requests')
    )


@app.route('/messages')
def messages_home():
    if not login_required():
        return redirect(url_for('login'))
    query = request.args.get('q', '').strip()
    return render_template(
        'messages_home.html',
        connected_users=get_connected_users(),
        search_results=search_users(query),
        query=query,
        searched=bool(query)
    )


@app.route('/messages/<int:user_id>', methods=['GET', 'POST'])
def messages(user_id):
    if not login_required():
        return redirect(url_for('login'))
    ensure_social_schema()
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

    if request.method == 'POST':
        message = request.form.get('message', '').strip()
        if message:
            translated = swahili_to_english(message)
            label = "Toxic" if contains_toxic_term(message) else toxicity_prediction(translated)
            status = "Rejected" if label == "Toxic" else "Delivered"
            cursor.execute(
                """
                INSERT INTO messages (sender_id, receiver_id, message, toxicity_label, moderation_status)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (session['id'], user_id, message, label, status)
            )
            mysql.connection.commit()
            if status == "Rejected":
                flash("Message rejected because it contains toxic content.")

    cursor.execute('SELECT id, fullname, username, profile_pic FROM accounts WHERE id = %s', (user_id,))
    other_user = cursor.fetchone()
    cursor.execute(
        """
        SELECT m.*, sender.username AS sender_username
        FROM messages m
        JOIN accounts sender ON sender.id = m.sender_id
        WHERE ((m.sender_id = %s AND m.receiver_id = %s)
           OR (m.sender_id = %s AND m.receiver_id = %s))
          AND m.moderation_status = 'Delivered'
        ORDER BY m.created_at ASC
        """,
        (session['id'], user_id, user_id, session['id'])
    )
    thread = cursor.fetchall()
    cursor.close()
    return render_template('messages.html', other_user=other_user, thread=thread)


@app.route('/admin/posts')
def admin_posts():
    if not admin_required():
        return redirect(url_for('login'))
    return render_template('admin_posts.html', posts=get_all_tweets())


@app.route('/admin/users')
def admin_users():
    if not admin_required():
        return redirect(url_for('login'))
    ensure_social_schema()
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute("""
        SELECT id, fullname, username, email, profile_pic, created_at,
               COALESCE(is_admin, 0) AS is_admin,
               COALESCE(account_status, 'Active') AS account_status,
               COALESCE(can_post, 1) AS can_post,
               COALESCE(black_label_count, 0) AS black_label_count
        FROM accounts
        ORDER BY created_at DESC
    """)
    users = cursor.fetchall()
    cursor.close()
    return render_template('admin_users.html', users=users)


@app.route('/admin/users/<int:user_id>/<action>', methods=['POST'])
def admin_user_action(user_id, action):
    if not admin_required():
        return redirect(url_for('login'))
    ensure_social_schema()
    if user_id == session.get('id') and action == 'delete':
        flash("You cannot delete the account you are currently using.")
        return redirect(url_for('admin_users'))

    if action == 'delete':
        cursor = mysql.connection.cursor()
        cursor.execute('DELETE FROM messages WHERE sender_id = %s OR receiver_id = %s', (user_id, user_id))
        cursor.execute('DELETE FROM connections WHERE requester_id = %s OR receiver_id = %s', (user_id, user_id))
        cursor.execute('DELETE FROM comments WHERE user_id = %s', (user_id,))
        cursor.execute('DELETE FROM reposts WHERE user_id = %s', (user_id,))
        cursor.execute('DELETE FROM posts WHERE user_id = %s', (user_id,))
        cursor.execute('DELETE FROM accounts WHERE id = %s', (user_id,))
        mysql.connection.commit()
        cursor.close()
        flash("Account deleted.")
        return redirect(url_for('admin_users'))

    actions = {
        'disable': ("account_status = 'Disabled'", "Account disabled."),
        'enable': ("account_status = 'Active'", "Account enabled."),
        'revoke-posting': ("can_post = 0", "Posting revoked."),
        'allow-posting': ("can_post = 1", "Posting enabled."),
        'black-book': ("account_status = 'Black Book', can_post = 0", "User moved to Black Book."),
        'clear-labels': ("black_label_count = 0, account_status = 'Active', can_post = 1", "Black labels cleared.")
    }
    if action in actions:
        update_sql, message = actions[action]
        cursor = mysql.connection.cursor()
        cursor.execute(f"UPDATE accounts SET {update_sql} WHERE id = %s", (user_id,))
        mysql.connection.commit()
        cursor.close()
        flash(message)
    return redirect(url_for('admin_users'))


@app.route('/admin/posts/<int:post_id>/<action>', methods=['POST'])
def admin_post_action(post_id, action):
    if not admin_required():
        return redirect(url_for('login'))
    ensure_social_schema()
    ensure_posts_moderation_columns()
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute('SELECT id, user_id FROM posts WHERE id = %s', (post_id,))
    post = cursor.fetchone()
    if not post:
        cursor.close()
        return redirect(url_for('admin_posts'))

    if action == 'approve':
        cursor.execute(
            """
            UPDATE posts
            SET toxicity_label = 'Non-Toxic',
                moderation_status = 'Approved',
                moderation_reason = 'Approved by admin.'
            WHERE id = %s
            """,
            (post_id,)
        )
        flash("Post approved.")
    elif action == 'reject':
        cursor.execute(
            """
            UPDATE posts
            SET toxicity_label = 'Toxic',
                moderation_status = 'Rejected',
                moderation_reason = 'Rejected by admin.'
            WHERE id = %s
            """,
            (post_id,)
        )
        flash("Post rejected.")
    elif action == 'black-label':
        cursor.execute(
            """
            UPDATE accounts
            SET black_label_count = COALESCE(black_label_count, 0) + 1,
                account_status = CASE
                    WHEN COALESCE(black_label_count, 0) + 1 >= 10 THEN 'Black Book'
                    ELSE account_status
                END,
                can_post = CASE
                    WHEN COALESCE(black_label_count, 0) + 1 >= 10 THEN 0
                    ELSE can_post
                END
            WHERE id = %s
            """,
            (post['user_id'],)
        )
        flash("User received a black label.")
    elif action == 'delete':
        cursor.execute('DELETE FROM comments WHERE post_id = %s', (post_id,))
        cursor.execute('DELETE FROM reposts WHERE post_id = %s', (post_id,))
        cursor.execute('DELETE FROM posts WHERE id = %s', (post_id,))
        flash("Post deleted.")

    mysql.connection.commit()
    cursor.close()
    return redirect(url_for('admin_posts'))


@app.route('/posts/<int:post_id>/comment', methods=['POST'])
def comment_post(post_id):
    if not login_required():
        return redirect(url_for('login'))
    ensure_social_schema()
    ensure_posts_moderation_columns()
    comment = request.form.get('comment', '').strip()
    if comment:
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        cursor.execute('SELECT comments_enabled FROM posts WHERE id = %s', (post_id,))
        post = cursor.fetchone()
        cursor.close()
        if post and not post.get('comments_enabled'):
            flash("Comments are closed for this post.")
            return redirect(request.referrer or url_for('focused_post', post_id=post_id))

        translated = swahili_to_english(comment)
        label = "Toxic" if contains_toxic_term(comment) else toxicity_prediction(translated)
        status = "Rejected" if label == "Toxic" else "Approved"
        cursor = mysql.connection.cursor()
        cursor.execute(
            """
            INSERT INTO comments (post_id, user_id, comment, toxicity_label, moderation_status)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (post_id, session['id'], comment, label, status)
        )
        mysql.connection.commit()
        cursor.close()
        flash("Comment added." if status == "Approved" else "Comment saved as rejected.")
    return redirect(request.referrer or url_for('user_home'))


@app.route('/posts/<int:post_id>/repost', methods=['POST'])
def repost(post_id):
    if not login_required():
        return redirect(url_for('login'))
    ensure_social_schema()
    cursor = mysql.connection.cursor()
    cursor.execute(
        "INSERT IGNORE INTO reposts (post_id, user_id) VALUES (%s, %s)",
        (post_id, session['id'])
    )
    mysql.connection.commit()
    cursor.close()
    flash("Post reshared.")
    return redirect(request.referrer or url_for('user_home'))


@app.route('/posts/<int:post_id>/manage', methods=['POST'])
def manage_own_post(post_id):
    if not login_required():
        return redirect(url_for('login'))
    ensure_posts_moderation_columns()
    action = request.form.get('action')
    audience = request.form.get('audience')
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute('SELECT user_id FROM posts WHERE id = %s', (post_id,))
    post = cursor.fetchone()
    if not post or (post['user_id'] != session['id'] and not current_user_is_admin()):
        cursor.close()
        return redirect(request.referrer or url_for('user_home'))

    if action == 'delete':
        cursor.execute('DELETE FROM comments WHERE post_id = %s', (post_id,))
        cursor.execute('DELETE FROM reposts WHERE post_id = %s', (post_id,))
        cursor.execute('DELETE FROM likes WHERE post_id = %s', (post_id,))
        cursor.execute('DELETE FROM posts WHERE id = %s', (post_id,))
    elif action == 'close-comments':
        cursor.execute('UPDATE posts SET comments_enabled = 0 WHERE id = %s', (post_id,))
    elif action == 'open-comments':
        cursor.execute('UPDATE posts SET comments_enabled = 1 WHERE id = %s', (post_id,))
    elif action == 'visibility' and audience in ('Public', 'Friends', 'Only Me'):
        cursor.execute('UPDATE posts SET audience = %s WHERE id = %s', (audience, post_id))

    mysql.connection.commit()
    cursor.close()
    return redirect(request.referrer or url_for('profile', user_id=session['id']))


@app.route('/posts/<int:post_id>/like', methods=['POST'])
def like_post(post_id):
    if not login_required():
        return redirect(url_for('login'))
    ensure_social_schema()
    cursor = mysql.connection.cursor()
    cursor.execute(
        "INSERT IGNORE INTO likes (post_id, user_id) VALUES (%s, %s)",
        (post_id, session['id'])
    )
    mysql.connection.commit()
    cursor.close()
    return redirect(request.referrer or url_for('user_home'))


@app.route('/post/<int:post_id>')
def focused_post(post_id):
    if not login_required():
        return redirect(url_for('login'))
    post, comments = get_post_detail(post_id, include_rejected=current_user_is_admin())
    return render_template(
        'post_detail.html',
        post=post,
        comments=comments,
        show_moderation=current_user_is_admin()
    )


@app.route('/profile/<int:user_id>')
def profile(user_id):
    if not login_required():
        return redirect(url_for('login'))
    ensure_social_schema()
    ensure_posts_moderation_columns()
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute('SELECT * FROM accounts WHERE id = %s', (user_id,))
    user = cursor.fetchone()
    if current_user_is_admin():
        cursor.execute('SELECT * FROM posts WHERE user_id = %s ORDER BY timestamp DESC', (user_id,))
        show_moderation = True
    else:
        cursor.execute(
            """
            SELECT * FROM posts
            WHERE user_id = %s AND moderation_status = 'Approved'
            ORDER BY timestamp DESC
            """,
            (user_id,)
        )
        show_moderation = False
    posts = cursor.fetchall()
    cursor.close()
    return render_template(
        'profile.html',
        user=user,
        posts=posts,
        show_moderation=show_moderation,
        stats=profile_stats(user_id),
        is_own_profile=(user_id == session.get('id'))
    )


@app.route('/profile')
def my_profile():
    if not login_required():
        return redirect(url_for('login'))
    return redirect(url_for('profile', user_id=session['id']))


@app.route('/profile/edit', methods=['GET', 'POST'])
def edit_profile():
    if not login_required():
        return redirect(url_for('login'))
    ensure_social_schema()
    msg = ''
    if request.method == 'POST':
        fullname = request.form.get('fullname', '').strip()
        bio = request.form.get('bio', '').strip()[:280]
        profile_pic = request.files.get('profile_pic')
        filename = None

        if profile_pic and allowed_file(profile_pic.filename):
            filename = secure_filename(profile_pic.filename)
            profile_pic.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))

        cursor = mysql.connection.cursor()
        if filename:
            cursor.execute(
                "UPDATE accounts SET fullname = %s, bio = %s, profile_pic = %s WHERE id = %s",
                (fullname, bio, filename, session['id'])
            )
            session['pic'] = filename
        else:
            cursor.execute(
                "UPDATE accounts SET fullname = %s, bio = %s WHERE id = %s",
                (fullname, bio, session['id'])
            )
        mysql.connection.commit()
        cursor.close()
        session['fullname'] = fullname
        return redirect(url_for('profile', user_id=session['id']))

    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute('SELECT * FROM accounts WHERE id = %s', (session['id'],))
    user = cursor.fetchone()
    cursor.close()
    return render_template('edit_profile.html', user=user, msg=msg)


@app.route('/posts/<int:post_id>/delete', methods=['POST'])
def delete_own_post(post_id):
    if not login_required():
        return redirect(url_for('login'))
    ensure_social_schema()
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute('SELECT user_id FROM posts WHERE id = %s', (post_id,))
    post = cursor.fetchone()
    if post and (post['user_id'] == session['id'] or current_user_is_admin()):
        cursor.execute('DELETE FROM comments WHERE post_id = %s', (post_id,))
        cursor.execute('DELETE FROM reposts WHERE post_id = %s', (post_id,))
        cursor.execute('DELETE FROM likes WHERE post_id = %s', (post_id,))
        cursor.execute('DELETE FROM posts WHERE id = %s', (post_id,))
        mysql.connection.commit()
    cursor.close()
    return redirect(request.referrer or url_for('profile', user_id=session['id']))


@app.route('/model-data')
def model_data():
    if not admin_required():
        return redirect(url_for('login'))
    return render_template(
        'model_data.html',
        model_data=model_terms(),
        learned_terms=get_learned_terms()
    )


@app.route('/training', methods=['GET', 'POST'])
def training():
    if not admin_required():
        return redirect(url_for('login'))

    msg = ''
    success = ''
    suggested_term = ''
    suggested_translation = ''
    suggested_meaning = ''

    if request.method == 'POST':
        action = request.form.get('action', 'save')
        term = request.form.get('term', '').strip()
        label = normalize_label(request.form.get('label', 'Non-Toxic'))
        translation = request.form.get('translation', '').strip()
        meaning = request.form.get('meaning', '').strip()

        if not term:
            msg = 'Enter a word or phrase first.'
        elif action == 'lookup':
            suggested_term = term
            suggested_translation, suggested_meaning = suggest_term_context(term)
            success = 'Review the suggested meaning, choose the correct label, then save it.'
        else:
            if not translation:
                translation = swahili_to_english(term)
            if not meaning:
                meaning = fetch_internet_meaning(translation if translation else term)

            ensure_training_table()
            try:
                cursor = mysql.connection.cursor()
                cursor.execute(
                    """
                    INSERT INTO moderation_terms (term, translation, meaning, label, source, created_by)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        translation = VALUES(translation),
                        meaning = VALUES(meaning),
                        label = VALUES(label),
                        source = VALUES(source),
                        created_by = VALUES(created_by)
                    """,
                    (term, translation, meaning, label, 'user-confirmed', session.get('id'))
                )
                mysql.connection.commit()
                cursor.close()
                success = 'Training term saved. Future checks will use it immediately.'
            except Exception as exc:
                msg = 'Could not save training term: ' + str(exc)

    return render_template(
        'training.html',
        msg=msg,
        success=success,
        suggested_term=suggested_term,
        suggested_translation=suggested_translation,
        suggested_meaning=suggested_meaning,
        learned_terms=get_learned_terms()
    )

if __name__ == '__main__':
    app.run(host='0.0.0.0',port=5000, debug=True)
