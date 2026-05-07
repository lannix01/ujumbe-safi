# Ujumbe Safi

Ujumbe Safi is a social media and content moderation system built with Flask, MySQL, and a trained toxicity detection model. It combines posting, profiles, connections, messages, comments, reactions, admin moderation, and toxicity checks for posts, comments, and chats.

The project uses a saved TF-IDF vectorizer and toxicity classifier from the training notebooks, then adds a live moderation layer where admins can teach new toxic or non-toxic words/phrases.

## Repository

```bash
git clone https://github.com/lannix01/ujumbe-safi.git
cd ujumbe-safi
```

## Main Features

- User registration and login
- Password reset by username and email
- User feed with mixed public, connected-friends, and interacted-with posts
- Create posts with audience controls:
  - Public
  - Connected friends
  - Me only
- Toxicity screening for posts, comments, direct messages, and manual phrase checks
- Likes, comments, reposts/reshares, and focused post pages
- User profiles with bio, profile image, stats, and post management
- Connections/friends system with requests and disconnect controls
- Direct messages with toxicity filtering before delivery
- Admin dashboard for full moderation audit
- Admin account management:
  - disable/enable accounts
  - revoke/allow posting
  - black-label users
  - move users to Black Book
  - delete accounts
- Admin model tools:
  - view model vocabulary/signals
  - teach new words or phrases

## Project Structure

```text
backend/
  app.py                 Flask application
  api.py                 FastAPI prediction endpoint
  database.sql           MySQL schema
  requirements.txt       Python dependencies
  tf_idf.pkt             Saved TF-IDF vectorizer
  toxicity_model.pkt     Saved toxicity model
  templates/             Flask/Jinja pages
  static/                CSS, JS, images, uploads

datasets/                Training datasets
notebooks/               Data cleaning and model training notebooks
frontend/                Older/static frontend experiments
```

The active integrated app is in `backend/`.

## Requirements

- Python 3.10+
- MySQL or MariaDB
- Git

Python packages are listed in:

```text
backend/requirements.txt
```

## Setup

### 1. Clone the repository

```bash
git clone https://github.com/lannix01/ujumbe-safi.git
cd ujumbe-safi
```

### 2. Create a virtual environment

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Linux/macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install dependencies

```bash
cd backend
pip install -r requirements.txt
```

### 4. Create the database

Log into MySQL and run the schema:

```bash
mysql -u root -p < database.sql
```

The app expects:

```text
Database: twitter
User: crud
Password: empty
Host: localhost
```

These settings are currently configured in `backend/app.py`.

### 5. Run the Flask app

From inside the `backend/` folder:

```bash
python app.py
```

Open:

```text
http://localhost:5000
```

## Admin Access

The app treats an account as admin if:

- `is_admin = 1`, or
- the account id is `1`, or
- the username is `admin`

After creating your first account, you can promote it in MySQL:

```sql
UPDATE accounts SET is_admin = 1 WHERE username = 'your_username';
```

Admins are sent to:

```text
/home/
```

Normal users are sent to:

```text
/user/
```

## Important Routes

```text
/                       Login
/register/              Register
/reset-password/        Reset password
/user/                  Normal user feed
/compose                Create post
/profile                Own profile
/profile/<id>           User profile
/post/<id>              Focused post and comments
/requests               Connections and requests
/messages               Messages hub
/messages/<id>          Chat thread
/manual                 Manual toxicity checker
/home/                  Admin dashboard
/admin/posts            All attempted posts audit
/admin/users            Account management
/model-data             Model signals and learned terms
/training               Teach new moderation terms
```

## Toxicity Detection

Ujumbe Safi checks content using:

- saved trained model: `toxicity_model.pkt`
- saved TF-IDF vectorizer: `tf_idf.pkt`
- built-in toxic term fallback list
- admin-taught moderation terms stored in MySQL

Content is checked before being accepted into:

- posts
- comments
- messages
- manual phrase checks

Flagged posts are saved for admin audit instead of disappearing.

## Notes

- `frontend/` contains older static prototypes. The working application is integrated under `backend/`.
- Uploaded images are stored under `backend/static/uploads/`.
- `.venv/`, `__pycache__/`, and `.pyc` files should not be committed.
- The saved model may warn if loaded with a newer scikit-learn version than the one used during training. For best consistency, use the same scikit-learn version used when the model was created.

## Development

Useful commands:

```bash
python -m py_compile app.py api.py
python app.py
```

Commit and push:

```bash
git status
git add .
git commit -m "Describe your change"
git push
```
