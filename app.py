# app.py (V2.0 FINAL - Immaculate & Hardened)

import os
from pathlib import Path
from dotenv import load_dotenv
from functools import wraps
import html as html_lib
import json
import re
import threading
import random
import atexit
import webbrowser
from collections import defaultdict
from typing import Any
from uuid import uuid4

import requests
from flask import Flask, jsonify, request, g, render_template, session
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func, inspect, text
from werkzeug.security import generate_password_hash, check_password_hash

# --- Config ---
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(dotenv_path=BASE_DIR / '.env')


# ======================================================================
# --- CONFIGURATION BLOCK ---
# ======================================================================
DATABASE_FILE = 'feedback.db' 
DATABASE_URL = os.getenv('DATABASE_URL')
DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY') 
DEEPSEEK_MODEL = "deepseek-chat"
DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"
# Set to True for real AI summaries, False for fast, generic placeholders
DEEPTHINK_OR_NOT = False 
# Worker thread sleep interval (seconds). 10s for demo, 60s for production.
WORKER_SLEEP_INTERVAL = 10 
BROWSER_HOST = os.getenv('BROWSER_HOST', '127.0.0.1')
HOST = os.getenv('HOST', '0.0.0.0')
PORT = int(os.getenv('PORT', '5001'))
AUTO_OPEN_BROWSER = os.getenv('AUTO_OPEN_BROWSER', '1').lower() not in {'0', 'false', 'no'}
ENABLE_WORKER = os.getenv('ENABLE_WORKER', '1').lower() not in {'0', 'false', 'no'}
# Auth configuration
STUDENT_SIGNUP_ENABLED = os.getenv('STUDENT_SIGNUP_ENABLED', '1').lower() not in {'0', 'false', 'no'}
TEACHER_INVITE_CODE = os.getenv('TEACHER_INVITE_CODE')
ADMIN_INVITE_CODE = os.getenv('ADMIN_INVITE_CODE')
ALLOW_MOCK_AUTH = os.getenv('ALLOW_MOCK_AUTH', '1').lower() not in {'0', 'false', 'no'}
# ======================================================================

USE_REAL_DEEPSEEK = bool(DEEPSEEK_API_KEY)
USE_REAL_SUMMARIES = DEEPTHINK_OR_NOT and USE_REAL_DEEPSEEK

if DEEPTHINK_OR_NOT and not USE_REAL_DEEPSEEK:
    raise SystemExit("FATAL ERROR: 'DEEPSEEK_API_KEY' is required when DEEPTHINK_OR_NOT=True.")
if not USE_REAL_DEEPSEEK:
    print("WARNING: 'DEEPSEEK_API_KEY' missing. Using mock toxicity checks and summaries.")

# --- App Configuration ---
app = Flask(__name__, static_folder=BASE_DIR, static_url_path='/static', template_folder=BASE_DIR)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'default-development-key')
app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL or f'sqlite:///{DATABASE_FILE}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {"pool_pre_ping": True}
db = SQLAlchemy(app)
CORS(app) 

# ======================================================================
# --- Database Models (V2.0 FINAL) ---
# ======================================================================

class BaseModel(db.Model):
    __abstract__ = True

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)


class User(BaseModel):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    azure_oid = db.Column(db.String(128), unique=True, nullable=False) 
    email = db.Column(db.String(120), unique=True, nullable=False)
    name = db.Column(db.String(120), nullable=True) 
    role = db.Column(db.String(50), nullable=False)
    password_hash = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=db.func.now())
    last_login_at = db.Column(db.DateTime, nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    
class Teacher(BaseModel):
    __tablename__ = 'teachers'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), unique=True, nullable=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    year_6 = db.Column(db.Boolean, default=False)
    year_7 = db.Column(db.Boolean, default=False)
    year_8 = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=True)

class Feedback(BaseModel):
    __tablename__ = 'feedback'
    id = db.Column(db.Integer, primary_key=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey('teachers.id'), nullable=True) 
    category = db.Column(db.String(50), nullable=False) 
    feedback_text = db.Column(db.Text, nullable=False)
    context_detail = db.Column(db.String(255), nullable=True)
    year_level_submitted = db.Column(db.String(10), nullable=True) 
    willing_to_share_name = db.Column(db.Boolean, default=False)
    submitted_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=db.func.now())
    toxicity_score = db.Column(db.Float, default=0.0)
    is_inappropriate = db.Column(db.Boolean, default=False)
    status = db.Column(db.String(50), default='New') 
    is_summary_approved = db.Column(db.Boolean, default=False) 
    
    # V2.0: Real Teacher Trends
    rating_clarity = db.Column(db.Integer, nullable=True)
    rating_pacing = db.Column(db.Integer, nullable=True)
    rating_resources = db.Column(db.Integer, nullable=True)
    rating_support = db.Column(db.Integer, nullable=True)

class TeacherSummary(BaseModel):
    __tablename__ = 'teacher_summary'
    teacher_id = db.Column(db.Integer, db.ForeignKey('teachers.id'), primary_key=True)
    latest_positive_summary = db.Column(db.Text, nullable=True)
    latest_actionable_summary = db.Column(db.Text, nullable=True)
    last_updated = db.Column(db.DateTime, default=db.func.now(), onupdate=db.func.now())
    raw_positive_bullets = db.Column(db.JSON, nullable=True)
    raw_actionable_bullets = db.Column(db.JSON, nullable=True)

class ClarificationRequest(BaseModel):
    __tablename__ = 'clarification_requests'
    id = db.Column(db.Integer, primary_key=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey('teachers.id'), nullable=False)
    question_text = db.Column(db.Text, nullable=False)
    requested_on = db.Column(db.DateTime, default=db.func.now())
    # V2.0: 'is_resolved' (bool) is replaced by 'status' (string)
    status = db.Column(db.String(50), default='pending') # 'pending', 'resolved'
    admin_reply = db.Column(db.Text, nullable=True)

class SummaryJobQueue(BaseModel):
    __tablename__ = 'summary_job_queue'
    job_id = db.Column(db.Integer, primary_key=True)
    job_type = db.Column(db.String(50), nullable=False) # 'teacher' or 'category'
    target_id = db.Column(db.String(50), nullable=False) # '1' (teacher_id) or 'food' (category_name)
    # V2.0 (Bug Fix): Must be nullable for delete-triggered jobs
    feedback_id = db.Column(db.Integer, db.ForeignKey('feedback.id'), nullable=True)
    status = db.Column(db.String(50), default='pending') # 'pending', 'processing', 'complete', 'failed'
    created_at = db.Column(db.DateTime, default=db.func.now())
    updated_at = db.Column(db.DateTime, default=db.func.now(), onupdate=db.func.now())

class CategorySummary(BaseModel):
    __tablename__ = 'category_summary'
    category_name = db.Column(db.String(50), primary_key=True) # 'food', 'policy', etc.
    latest_positive_summary = db.Column(db.Text, nullable=True)
    latest_actionable_summary = db.Column(db.Text, nullable=True)
    last_updated = db.Column(db.DateTime, default=db.func.now(), onupdate=db.func.now())
    raw_positive_bullets = db.Column(db.JSON, nullable=True)
    raw_actionable_bullets = db.Column(db.JSON, nullable=True)

class Category(BaseModel):
    __tablename__ = 'categories'
    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(50), unique=True, nullable=False)
    title = db.Column(db.String(120), nullable=False)
    description = db.Column(db.String(255), nullable=True)
    icon = db.Column(db.String(50), nullable=True)
    context_label = db.Column(db.String(120), nullable=True)
    requires_teacher = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=True)
    sort_order = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=db.func.now())

class Announcement(BaseModel):
    __tablename__ = 'announcements'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(140), nullable=False)
    body = db.Column(db.Text, nullable=False)
    audience = db.Column(db.String(30), default='all') # 'all', 'student', 'teacher'
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=db.func.now())
    updated_at = db.Column(db.DateTime, default=db.func.now(), onupdate=db.func.now())
    created_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

class FeedbackStatusHistory(BaseModel):
    __tablename__ = 'feedback_status_history'
    id = db.Column(db.Integer, primary_key=True)
    feedback_id = db.Column(db.Integer, db.ForeignKey('feedback.id', ondelete='CASCADE'), nullable=False)
    old_status = db.Column(db.String(50), nullable=True)
    new_status = db.Column(db.String(50), nullable=False)
    changed_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    changed_at = db.Column(db.DateTime, default=db.func.now())
    note = db.Column(db.String(255), nullable=True)

class AuditLog(BaseModel):
    __tablename__ = 'audit_logs'
    id = db.Column(db.Integer, primary_key=True)
    actor_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    action = db.Column(db.String(80), nullable=False)
    target_type = db.Column(db.String(80), nullable=True)
    target_id = db.Column(db.String(80), nullable=True)
    details = db.Column(db.JSON, nullable=True)
    created_at = db.Column(db.DateTime, default=db.func.now())

# ======================================================================
# --- Utility Functions & Auth ---
# ======================================================================
EMAIL_RE = re.compile(r"^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$")


def normalize_email(email):
    return email.strip().lower()


def is_valid_email(email):
    return bool(EMAIL_RE.match(email or ""))


def build_user_payload(user, teacher_profile=None):
    payload = {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "role": user.role
    }
    if teacher_profile:
        payload["teacher_id"] = teacher_profile.id
    return payload


def resolve_session_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    user = db.session.get(User, user_id)
    if not user or user.is_active is False:
        session.pop("user_id", None)
        return None
    return user


def auth_required(role=None):
    def wrapper(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            user = resolve_session_user()
            if not user and ALLOW_MOCK_AUTH:
                mock_user_id = request.args.get('mock_user_id') or request.headers.get('X-Mock-User-Id')
                if mock_user_id is not None:
                    try:
                        mock_user_id = int(mock_user_id)
                    except (TypeError, ValueError):
                        return jsonify({"error": "Invalid mock_user_id."}), 400
                    user = db.session.get(User, mock_user_id)

            if not user:
                return jsonify({"error": "Authentication required."}), 401
            if user.is_active is False:
                return jsonify({"error": "Account disabled. Contact an administrator."}), 403
            if role and user.role != role:
                return jsonify({"error": f"Access denied. Required role: {role}"}), 403

            g.user = user
            g.teacher_profile = None
            if user.role in ['teacher', 'stuco_admin']:
                g.teacher_profile = Teacher.query.filter_by(user_id=user.id).first()
                if not g.teacher_profile and user.role == 'teacher':
                    return jsonify({"error": "Teacher profile not found."}), 403

            return f(*args, **kwargs)
        return decorated_function
    return wrapper


def ensure_schema_updates():
    inspector = inspect(db.engine)
    table_names = set(inspector.get_table_names())
    schema_updates = {
        "users": [
            ("password_hash", "VARCHAR(255)"),
            ("created_at", "DATETIME"),
            ("last_login_at", "DATETIME"),
            ("is_active", "BOOLEAN")
        ],
        "feedback": [
            ("created_at", "DATETIME")
        ],
        "teachers": [
            ("is_active", "BOOLEAN")
        ]
    }
    with db.engine.begin() as connection:
        for table, columns in schema_updates.items():
            if table not in table_names:
                continue
            existing_columns = {col["name"] for col in inspector.get_columns(table)}
            for column_name, column_type in columns:
                if column_name in existing_columns:
                    continue
                try:
                    connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {column_name} {column_type}"))
                    print(f"INFO: Added column '{column_name}' to '{table}'.")
                except Exception as exc:
                    print(f"WARNING: Could not add column '{column_name}' to '{table}': {exc}")


def normalize_slug(value):
    value = (value or "").strip().lower()
    value = re.sub(r"[^a-z0-9\\s-]", "", value)
    value = re.sub(r"\\s+", "-", value)
    return value[:50]


def log_audit(action, target_type=None, target_id=None, details=None, actor_id=None):
    try:
        if actor_id is None and hasattr(g, "user") and g.user:
            actor_id = g.user.id
        entry = AuditLog(
            actor_user_id=actor_id,
            action=action,
            target_type=target_type,
            target_id=str(target_id) if target_id is not None else None,
            details=details
        )
        db.session.add(entry)
    except Exception as exc:
        print(f"WARNING: Failed to write audit log: {exc}")


def record_feedback_status(feedback_id, old_status, new_status, actor_id=None, note=None):
    entry = FeedbackStatusHistory(
        feedback_id=feedback_id,
        old_status=old_status,
        new_status=new_status,
        changed_by_user_id=actor_id,
        note=note
    )
    db.session.add(entry)

# ======================================================================
# --- AI Functions (Toxicity & Summarization) ---
# ======================================================================

def run_real_deepseek_toxicity_check(text_input):
    """
    Runs a REAL, lightweight DeepSeek API call to check for toxicity.
    This prompt is now extremely strict and tells the AI to ignore context.
    """
    print(f"REAL TOXICITY CHECK: Sending to DeepSeek for moderation: '{text_input[:30]}...'")
    if not DEEPSEEK_API_KEY:
        print("ERROR: DEEPSEEK_API_KEY missing. Cannot run real toxicity check.")
        return {'toxicity_score': 1.0, 'is_inappropriate': True} # Fail safe

    system_prompt = (
        "You are an extremely strict content moderation expert for a school feedback system. "
        "Your job is to protect teachers from ANY personal insults, profanity, or abusive language. "
        "Your response MUST be in a single, valid JSON object format with two keys: 'is_inappropriate' (boolean) and 'toxicity_score' (float 0.0-1.0). "
        "**CRITICAL:** Set 'is_inappropriate' to **true** if the text contains *any* of the following: "
        "1. **Any Profanity (REGARDLESS OF CONTEXT):** Flag *any* use of words like 'fuck', 'shit', 'bitch', 'ass', 'damn', etc. "
        "   Even if used as an adjective (e.g., 'hard ass homework'), it MUST be flagged as inappropriate. "
        "2. **Personal Insults:** Flag *any* direct insults to the teacher or others (e.g., 'idiot', 'stupid', 'terrible teacher', 'horrible person', 'worst teacher'). "
        "3. **Bullying or Threats:** Flag any bullying or threatening language. "
        "Be extremely sensitive and err on the side of caution. Do not analyze intent; filter based on the words themselves."
    )
    
    headers = {'Authorization': f'Bearer {DEEPSEEK_API_KEY}','Content-Type': 'application/json'}
    payload = {
        'model': DEEPSEEK_MODEL,
        'messages': [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': text_input}
        ],
        'response_format': {'type': 'json_object'},
        'max_tokens': 100,
        'temperature': 0.0
    }
    
    try:
        response = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=10)
        response.raise_for_status() 
        data = response.json()
        ai_content_str = data['choices'][0]['message']['content']
        result = json.loads(ai_content_str)
        is_inappropriate = result.get('is_inappropriate', False)
        toxicity_score = result.get('toxicity_score', 0.0)
        
        if is_inappropriate and toxicity_score < 0.8:
            toxicity_score = 0.95
            
        print(f"REAL TOXICITY CHECK Success: inappropriate={is_inappropriate}, score={toxicity_score}")
        return {'toxicity_score': toxicity_score, 'is_inappropriate': is_inappropriate}

    except Exception as e:
        print(f"CRITICAL TOXICITY CHECK ERROR: {e}. Defaulting to 'inappropriate'.")
        return {'toxicity_score': 1.0, 'is_inappropriate': True}

MOCK_TOXICITY_REGEXES = [
    re.compile(pattern)
    for pattern in [
        r"\bfuck\b",
        r"\bshit\b",
        r"\bbitch\b",
        r"\bass\b",
        r"\bdamn\b",
        r"\bidiot\b",
        r"\bstupid\b",
        r"\bterrible teacher\b",
        r"\bhorrible person\b",
        r"\bworst teacher\b",
        r"\bbully\b",
        r"\bbullying\b",
        r"\bthreat\b",
        r"\bkill\b",
    ]
]

def run_mock_toxicity_check(text_input):
    """
    Lightweight local moderation fallback for demo mode (no API key).
    """
    text_lower = text_input.lower()
    is_inappropriate = any(regex.search(text_lower) for regex in MOCK_TOXICITY_REGEXES)
    toxicity_score = 0.95 if is_inappropriate else 0.0
    return {'toxicity_score': toxicity_score, 'is_inappropriate': is_inappropriate}

def run_toxicity_check(text_input):
    if USE_REAL_DEEPSEEK:
        return run_real_deepseek_toxicity_check(text_input)
    return run_mock_toxicity_check(text_input)

BULLET_REGEX = re.compile(r"<li>(.*?)</li>", re.IGNORECASE | re.DOTALL)

def extract_bullets_from_html(summary_html):
    if not summary_html:
        return []
    matches = BULLET_REGEX.findall(summary_html)
    if matches:
        bullets = []
        for match in matches:
            text = re.sub(r"<[^>]+>", "", match)
            text = html_lib.unescape(text).strip()
            if text:
                bullets.append(text)
        return bullets
    text = re.sub(r"<[^>]+>", " ", summary_html)
    text = html_lib.unescape(text)
    lines = [line.strip(" -\t") for line in text.splitlines()]
    return [line for line in lines if line]

def get_summary_bullets(summary_entry, is_positive):
    if not summary_entry:
        return []
    bullets = summary_entry.raw_positive_bullets if is_positive else summary_entry.raw_actionable_bullets
    if bullets:
        return bullets
    summary_html = summary_entry.latest_positive_summary if is_positive else summary_entry.latest_actionable_summary
    return extract_bullets_from_html(summary_html)

def render_bullets_html(bullets):
    safe_items = [html_lib.escape(item) for item in bullets]
    return "<ul>" + "".join(f"<li>{item}</li>" for item in safe_items) + "</ul>"

def generate_mock_summary(target_id, summary_type='teacher'):
    """
    This is the privacy-safe 'Fast Demo Mode' summary generator.
    """
    print(f"MOCK SUMMARY: Generating FAST, SAFE summary for {summary_type} ID: {target_id}.")
    MOCK_POSITIVES = [
        "Students find the class activities engaging and fun.",
        "The teacher's enthusiasm for the subject is appreciated.",
        "Clear explanations help students understand complex topics.",
        "Students feel supported and comfortable asking questions."
    ]
    MOCK_ACTIONABLES = [
        "Consider reviewing the pacing of homework assignments.",
        "Some students would appreciate more in-class practice time.",
        "Ensure test content directly aligns with in-class material.",
        "Posting slides or resources in advance would be helpful."
    ]
    
    if summary_type == 'teacher':
        summary_entry = db.session.get(TeacherSummary, int(target_id))
    else:
        summary_entry = db.session.get(CategorySummary, target_id)

    if summary_entry:
        positive_bullets = list(summary_entry.raw_positive_bullets or [])
        actionable_bullets = list(summary_entry.raw_actionable_bullets or [])
    else:
        positive_bullets = []
        actionable_bullets = []

    if not positive_bullets:
        positive_bullets = [random.choice(MOCK_POSITIVES)]
    if not actionable_bullets:
        actionable_bullets = [random.choice(MOCK_ACTIONABLES)]

    if random.choice([True, False]):
        new_pos = random.choice(MOCK_POSITIVES)
        if new_pos not in positive_bullets:
            positive_bullets.append(new_pos)
    else:
        new_act = random.choice(MOCK_ACTIONABLES)
        if new_act not in actionable_bullets:
            actionable_bullets.append(new_act)
    
    positive_summary_html = "<ul>" + "".join(f"<li>{item}</li>" for item in positive_bullets) + "</ul>"
    actionable_summary_html = "<ul>" + "".join(f"<li>{item}</li>" for item in actionable_bullets) + "</ul>"

    if summary_type == 'teacher':
        new_summary_entry = TeacherSummary(
            teacher_id=int(target_id),
            latest_positive_summary=positive_summary_html,
            latest_actionable_summary=actionable_summary_html,
            raw_positive_bullets=positive_bullets,
            raw_actionable_bullets=actionable_bullets
        )
    else:
        new_summary_entry = CategorySummary(
            category_name=target_id,
            latest_positive_summary=positive_summary_html,
            latest_actionable_summary=actionable_summary_html,
            raw_positive_bullets=positive_bullets,
            raw_actionable_bullets=actionable_bullets
        )

    db.session.merge(new_summary_entry)
    db.session.commit()
    print(f"MOCK SUMMARY: Fast, SAFE summary updated for {summary_type} ID: {target_id}.")


def run_deepseek_summary(target_id):
    """
    This is the REAL, SLOW, SMART AI summary engine for TEACHERS.
    """
    teacher_id = int(target_id)
    if not USE_REAL_SUMMARIES:
        print("INFO: Real summaries disabled. Running MOCK teacher summary.")
        generate_mock_summary(teacher_id, 'teacher')
        return 
    
    print(f"REAL AI SUMMARY (DEEPTHINK=True): Generating holistic report for teacher_id {teacher_id}...")
    
    past_feedback = Feedback.query.filter(
        Feedback.teacher_id == teacher_id,
        Feedback.is_inappropriate.is_(False),
        Feedback.is_summary_approved.is_(True)
    ).all()
    
    feedback_entries = [f.feedback_text for f in past_feedback]
    
    if not feedback_entries:
        print("INFO: No feedback to summarize for teacher. Clearing summary.")
        summary_entry = TeacherSummary(
            teacher_id=teacher_id,
            latest_positive_summary="<ul><li>No feedback available.</li></ul>",
            latest_actionable_summary="<ul><li>No feedback available.</li></ul>",
            raw_positive_bullets=[],
            raw_actionable_bullets=[]
        )
        db.session.merge(summary_entry)
        db.session.commit()
        return

    combined_text = "\n---\n".join(feedback_entries)
    
    system_prompt = (
        "You are an expert educational analyst. Your task is to synthesize a list of raw, "
        "anonymous student feedback into a **holistic and cumulative** report for the teacher. "
        "Your response MUST be in a single, valid JSON object format. "
        "The JSON object must have exactly two keys: 'positive_highlights' and 'actionable_growth'. "
        "Each key must contain a list (an array) of bullet-point strings. "
        "**CRITICAL RULES:** "
        "1. **BE COMPREHENSIVE:** Include ALL distinct themes. "
        "2. **DO NOT FORGET:** Do not let new feedback overshadow older points. This is a cumulative report. "
        "3. **CONSOLIDATE:** Consolidate similar points into a single bullet point. "
        "4. **BE ACTIONABLE:** Growth points must be constructive. "
        "5. **FORMAT:** Do not use markdown."
    )
    user_prompt = f"Here is the collected feedback:\n\n{combined_text}"
    
    headers = {'Authorization': f'Bearer {DEEPSEEK_API_KEY}','Content-Type': 'application/json'}
    payload = {
        'model': DEEPSEEK_MODEL,
        'messages': [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': user_prompt}
        ],
        'response_format': {'type': 'json_object'}
    }
    
    try:
        response = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=60)
        response.raise_for_status() 
        data = response.json()
        ai_content_str = data['choices'][0]['message']['content']
        summary_json = json.loads(ai_content_str)
        positive_bullets = summary_json.get('positive_highlights', [])
        actionable_bullets = summary_json.get('actionable_growth', [])
        print(f"REAL AI SUCCESS: Generated {len(positive_bullets)} positive and {len(actionable_bullets)} actionable points for teacher {teacher_id}.")
        positive_summary_html = "<ul>" + "".join(f"<li>{item}</li>" for item in positive_bullets) + "</ul>"
        actionable_summary_html = "<ul>" + "".join(f"<li>{item}</li>" for item in actionable_bullets) + "</ul>"
        summary_entry = TeacherSummary(
            teacher_id=teacher_id,
            latest_positive_summary=positive_summary_html,
            latest_actionable_summary=actionable_summary_html,
            raw_positive_bullets=positive_bullets,
            raw_actionable_bullets=actionable_bullets
        )
        db.session.merge(summary_entry)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"CRITICAL AI ERROR (Teacher Summary): {e}")
        raise 

def run_deepseek_category_summary(target_id):
    """
    This is the REAL, SLOW, SMART AI summary engine for CATEGORIES (e.g., 'food').
    """
    category_name = target_id
    if not USE_REAL_SUMMARIES:
        print(f"INFO: Real summaries disabled. Running MOCK category summary for '{category_name}'.")
        generate_mock_summary(category_name, 'category')
        return 
    
    print(f"REAL AI SUMMARY (DEEPTHINK=True): Generating holistic report for category '{category_name}'...")
    
    past_feedback = Feedback.query.filter(
        Feedback.category == category_name,
        Feedback.is_inappropriate.is_(False),
        Feedback.is_summary_approved.is_(True)
    ).all()
    
    feedback_entries = [f.feedback_text for f in past_feedback]
    
    if not feedback_entries:
        print(f"INFO: No feedback to summarize for category '{category_name}'. Clearing summary.")
        summary_entry = CategorySummary(
            category_name=category_name,
            latest_positive_summary="<ul><li>No feedback available.</li></ul>",
            latest_actionable_summary="<ul><li>No feedback available.</li></ul>",
            raw_positive_bullets=[],
            raw_actionable_bullets=[]
        )
        db.session.merge(summary_entry)
        db.session.commit()
        return

    combined_text = "\n---\n".join(feedback_entries)
    
    system_prompt = (
        "You are an expert operational analyst for a school's Student Council (STUCO). "
        "Your task is to synthesize raw, anonymous student feedback about a specific school category "
        f"into a **holistic and cumulative** report for STUCO admins. The category is: **{category_name.upper()}**. "
        "Your response MUST be in a single, valid JSON object format. "
        "The JSON object must have exactly two keys: 'positive_highlights' and 'actionable_growth'. "
        "Each key must contain a list (an array) of bullet-point strings. "
        "**CRITICAL RULES:** "
        "1. **BE COMPREHENSIVE:** Include ALL distinct themes. "
        "2. **DO NOT FORGET:** This is a cumulative report. Do not let new feedback overshadow older points. "
        "3. **CONSOLIDATE:** Consolidate similar points into a single bullet point. "
        "4. **BE ACTIONABLE:** Growth points must be constructive suggestions for STUCO or school operations. "
        "5. **FORMAT:** Do not use markdown."
    )
    user_prompt = f"Here is the collected feedback for {category_name}:\n\n{combined_text}"
    
    headers = {'Authorization': f'Bearer {DEEPSEEK_API_KEY}','Content-Type': 'application/json'}
    payload = {
        'model': DEEPSEEK_MODEL,
        'messages': [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': user_prompt}
        ],
        'response_format': {'type': 'json_object'}
    }
    
    try:
        response = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=60)
        response.raise_for_status() 
        data = response.json()
        ai_content_str = data['choices'][0]['message']['content']
        summary_json = json.loads(ai_content_str)
        positive_bullets = summary_json.get('positive_highlights', [])
        actionable_bullets = summary_json.get('actionable_growth', [])
        print(f"REAL AI SUCCESS: Generated {len(positive_bullets)} positive and {len(actionable_bullets)} actionable points for category '{category_name}'.")
        positive_summary_html = "<ul>" + "".join(f"<li>{item}</li>" for item in positive_bullets) + "</ul>"
        actionable_summary_html = "<ul>" + "".join(f"<li>{item}</li>" for item in actionable_bullets) + "</ul>"
        summary_entry = CategorySummary(
            category_name=category_name,
            latest_positive_summary=positive_summary_html,
            latest_actionable_summary=actionable_summary_html,
            raw_positive_bullets=positive_bullets,
            raw_actionable_bullets=actionable_bullets
        )
        db.session.merge(summary_entry)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"CRITICAL AI ERROR (Category Summary): {e}")
        raise 

# ======================================================================
# --- V2.0 Background Worker Thread ---
# ======================================================================

worker_thread = None
worker_started = False
stop_worker_event = threading.Event()

def summary_worker_thread(flask_app):
    """
    This is the persistent background worker. It runs in its own thread
    and processes jobs from the SummaryJobQueue.
    """
    print("WORKER: Background summary worker thread started.")
    
    while not stop_worker_event.is_set():
        try:
            with flask_app.app_context():
                pending_jobs = SummaryJobQueue.query.filter_by(status='pending').order_by(SummaryJobQueue.created_at).all()
                
                if not pending_jobs:
                    stop_worker_event.wait(WORKER_SLEEP_INTERVAL)
                    continue

                print(f"WORKER: Found {len(pending_jobs)} pending jobs. Batching...")
                
                jobs_to_run = defaultdict(list)
                for job in pending_jobs:
                    jobs_to_run[(job.job_type, job.target_id)].append(job)

                for (job_type, target_id), job_list in jobs_to_run.items():
                    print(f"WORKER: Processing batch for {job_type} ID {target_id} ({len(job_list)} jobs)...")
                    
                    try:
                        for job in job_list:
                            job.status = 'processing'
                        db.session.commit()
                        
                        if job_type == 'teacher':
                            run_deepseek_summary(target_id)
                        elif job_type == 'category':
                            run_deepseek_category_summary(target_id)
                        
                        for job in job_list:
                            job.status = 'complete'
                        db.session.commit()
                        print(f"WORKER: Batch for {job_type} ID {target_id} complete.")

                    except Exception as e:
                        print(f"WORKER: CRITICAL ERROR processing batch for {job_type} ID {target_id}. Error: {e}")
                        db.session.rollback()
                        for job in job_list:
                            job.status = 'failed'
                        db.session.commit()

            stop_worker_event.wait(WORKER_SLEEP_INTERVAL)
            
        except Exception as e:
            print(f"WORKER: CATASTROPHIC FAILURE. {e}. Restarting loop in 60s.")
            stop_worker_event.wait(60) 

    print("WORKER: Background worker thread shutting down.")

def is_thread_alive(thread):
    return thread is not None and thread.is_alive()

def start_worker_thread():
    global worker_thread
    global worker_started
    if is_thread_alive(worker_thread):
        return False
    stop_worker_event.clear()
    worker_thread = threading.Thread(target=summary_worker_thread, args=(app,))
    worker_thread.daemon = True
    worker_thread.start()
    worker_started = True
    return True

def open_browser():
    url = f"http://{BROWSER_HOST}:{PORT}/"
    try:
        webbrowser.open(url)
    except Exception as exc:
        print(f"WARNING: Could not open browser automatically: {exc}")

# ======================================================================
# --- V2.0 Seeding (Now includes Ratings & Clarifications) ---
# ======================================================================
def seed_data():
    """Populates the database *only if it is empty*."""
    seeded_users = False
    if db.session.query(User).first() is None:
        print("INFO: Database is empty. Seeding initial data...")
        demo_student_password = os.getenv('DEMO_STUDENT_PASSWORD', 'student123')
        demo_teacher_password = os.getenv('DEMO_TEACHER_PASSWORD', 'teacher123')
        demo_admin_password = os.getenv('DEMO_ADMIN_PASSWORD', 'admin123')
        db.session.add_all([
            User(id=1, azure_oid='student_1', email='student@test.com', name='Student A', role='student', password_hash=generate_password_hash(demo_student_password)),
            User(id=2, azure_oid='teacher_1', email='harper@test.com', name='Mr. Harper', role='teacher', password_hash=generate_password_hash(demo_teacher_password)),
            User(id=3, azure_oid='admin_1', email='chen@test.com', name='Ms. Chen', role='stuco_admin', password_hash=generate_password_hash(demo_admin_password))
        ])
        db.session.commit()
        db.session.add_all([
            Teacher(id=1, user_id=2, name='Mr. Harper', email='harper@test.com', year_6=True, year_7=True, year_8=False, is_active=True),
            Teacher(id=2, user_id=None, name='Ms. Williams', email='williams@test.com', year_6=True, year_7=False, year_8=True, is_active=True),
            Teacher(id=3, user_id=None, name='Ms. Chen (Admin)', email='chen@test.com', year_6=True, year_7=True, year_8=True, is_active=True)
        ])
        db.session.commit()
        seeded_users = True

        f1 = Feedback(id=1, teacher_id=1, year_level_submitted='Year 7', feedback_text='Mr. Harper is a great teacher! His explanations are very clear.', willing_to_share_name=True, submitted_by_user_id=1, category='teacher', rating_clarity=5, rating_pacing=4, rating_resources=5, rating_support=5)
        f2 = Feedback(id=2, teacher_id=None, year_level_submitted='N/A', feedback_text='The cafeteria food, especially the pasta, has been excellent this week.', context_detail='Upper School Hot Lunch', willing_to_share_name=False, submitted_by_user_id=1, category='food')
        f3 = Feedback(id=3, teacher_id=None, year_level_submitted='N/A', feedback_text='This teacher is a horrible bully and should be fired! I hate their lessons.', context_detail='Advisory', willing_to_share_name=False, submitted_by_user_id=1, category='other')
        f4 = Feedback(id=4, teacher_id=None, year_level_submitted='N/A', feedback_text='The new uniform policy is unclear. We need more examples of what is allowed.', context_detail='Uniform Policy', willing_to_share_name=False, submitted_by_user_id=1, category='policy')
        f5 = Feedback(id=5, teacher_id=1, year_level_submitted='Year 7', feedback_text='This class is a bit too fast and the homework is hard.', willing_to_share_name=False, submitted_by_user_id=1, category='teacher', rating_clarity=3, rating_pacing=2, rating_resources=3, rating_support=4)

        db.session.add_all([f1, f2, f3, f4, f5])
        db.session.commit()

        for feedback_item in db.session.query(Feedback).filter(Feedback.status == 'New').all():
            screening = run_toxicity_check(feedback_item.feedback_text)
            feedback_item.toxicity_score = screening['toxicity_score']
            feedback_item.is_inappropriate = screening['is_inappropriate']

            if feedback_item.is_inappropriate:
                feedback_item.status = 'Screened - Escalation'
            else:
                feedback_item.status = 'Approved'
                feedback_item.is_summary_approved = True

                if feedback_item.category == 'teacher':
                    job = SummaryJobQueue(job_type='teacher', target_id=str(feedback_item.teacher_id), feedback_id=feedback_item.id, status='pending')
                    db.session.add(job)
                else:
                    job = SummaryJobQueue(job_type='category', target_id=feedback_item.category, feedback_id=feedback_item.id, status='pending')
                    db.session.add(job)
            record_feedback_status(feedback_item.id, None, feedback_item.status, None, note='Seeded data')

        db.session.commit()

        cr1 = ClarificationRequest(teacher_id=1, question_text="A summary mentioned 'pacing' was a problem. Could I know if this refers to the homework pacing or the in-class lecture pacing?", status='pending')
        db.session.add(cr1)
        db.session.commit()

        f3_toxic = db.session.get(Feedback, 3)
        if f3_toxic and f3_toxic.is_inappropriate:
            print("INFO: Seeded safeguarding item (ID 3) correctly flagged for escalation.")

    if Category.query.first() is None:
        category_seed = [
            Category(slug='teacher', title='Teacher Suggestions', description='Share classroom feedback and ratings.', icon='teacher', context_label='Class or subject detail', requires_teacher=True, sort_order=1, is_active=True),
            Category(slug='food', title='Food', description='Menus, service, and dining flow.', icon='food', context_label='Dining hall area or specific item', requires_teacher=False, sort_order=2, is_active=True),
            Category(slug='policy', title='Policy', description='Rules, expectations, and clarity.', icon='policy', context_label='Related policy or department', requires_teacher=False, sort_order=3, is_active=True),
            Category(slug='equipment', title='General services', description='Equipment, facilities, support.', icon='equipment', context_label='Equipment or location', requires_teacher=False, sort_order=4, is_active=True),
            Category(slug='school-buses', title='School buses', description='Routes, timing, and safety.', icon='school-buses', context_label='Route, bus number, or time', requires_teacher=False, sort_order=5, is_active=True),
            Category(slug='other', title='Other', description='Anything else on your mind.', icon='other', context_label='Relevant detail (optional)', requires_teacher=False, sort_order=6, is_active=True),
            Category(slug='help', title='Help', description='Reach out for support and care.', icon='help', context_label='Who should know? (optional)', requires_teacher=False, sort_order=7, is_active=True)
        ]
        db.session.add_all(category_seed)
        db.session.commit()

    if Announcement.query.first() is None:
        welcome = Announcement(
            title='Welcome to the STUCO Feedback Portal',
            body='This is the new home for student voice. Submit feedback, track updates, and expect clearer follow-through.',
            audience='all',
            is_active=True,
            created_by_user_id=3 if seeded_users else None
        )
        db.session.add(welcome)
        db.session.commit()

    print("INFO: Seed data finished.")


# ======================================================================
# --- Page Routes ---
# ======================================================================
@app.route('/', methods=['GET'])
def index():
    return render_template('home.html')

@app.route('/auth.html', methods=['GET'])
def auth_page():
    return render_template('auth.html')

@app.route('/feedback', methods=['GET'])
def feedback_portal():
    return render_template('stu_frontend.html')

@app.route('/student_dashboard', methods=['GET'])
def student_dashboard():
    return render_template('student_dashboard.html')

@app.route('/teach_frontend.html', methods=['GET'])
def teacher_dashboard():
    return render_template('teach_frontend.html')

@app.route('/stuco_admin_dashboard.html', methods=['GET'])
def stuco_admin_dashboard():
    return render_template('stuco_admin_dashboard.html')

# ======================================================================
# --- Public API Routes ---
# ======================================================================
@app.route('/api/categories', methods=['GET'])
def get_categories():
    include_inactive = request.args.get('include_inactive', '0').lower() in {'1', 'true', 'yes'}
    query = Category.query
    if not include_inactive:
        query = query.filter(Category.is_active.is_(True))
    categories = query.order_by(Category.sort_order, Category.title).all()
    return jsonify([
        {
            'id': c.id,
            'slug': c.slug,
            'title': c.title,
            'description': c.description,
            'icon': c.icon,
            'context_label': c.context_label,
            'requires_teacher': c.requires_teacher,
            'is_active': c.is_active,
            'sort_order': c.sort_order
        }
        for c in categories
    ])


@app.route('/api/announcements', methods=['GET'])
def get_announcements():
    audience = (request.args.get('audience') or 'all').strip().lower()
    limit = request.args.get('limit')
    query = Announcement.query.filter(Announcement.is_active.is_(True))
    if audience in {'student', 'teacher'}:
        query = query.filter(Announcement.audience.in_(['all', audience]))
    elif audience != 'all':
        query = query.filter(Announcement.audience == 'all')
    query = query.order_by(Announcement.created_at.desc())
    if limit:
        try:
            limit_val = max(1, min(int(limit), 20))
        except ValueError:
            limit_val = 5
        query = query.limit(limit_val)
    announcements = query.all()
    return jsonify([
        {
            'id': a.id,
            'title': a.title,
            'body': a.body,
            'audience': a.audience,
            'created_at': a.created_at.isoformat(),
            'updated_at': a.updated_at.isoformat()
        }
        for a in announcements
    ])

# ======================================================================
# --- Auth API Routes ---
# ======================================================================
@app.route('/api/auth/register', methods=['POST'])
def register_user():
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({'error': 'Invalid or missing JSON body.'}), 400

    name = (data.get('name') or '').strip()
    email = normalize_email(data.get('email') or '')
    password = data.get('password') or ''
    requested_role = (data.get('role') or 'student').strip().lower()
    invite_code = (data.get('invite_code') or '').strip()
    year_levels = data.get('year_levels') or []

    if not name or not email or not password:
        return jsonify({'error': 'Name, email, and password are required.'}), 400
    if not is_valid_email(email):
        return jsonify({'error': 'Please enter a valid email address.'}), 400
    if len(password) < 8:
        return jsonify({'error': 'Password must be at least 8 characters.'}), 400

    if User.query.filter_by(email=email).first():
        return jsonify({'error': 'An account with this email already exists.'}), 409

    role = 'student'
    if invite_code:
        if ADMIN_INVITE_CODE and invite_code == ADMIN_INVITE_CODE:
            role = 'stuco_admin'
        elif TEACHER_INVITE_CODE and invite_code == TEACHER_INVITE_CODE:
            role = 'teacher'
        else:
            return jsonify({'error': 'Invalid invite code.'}), 403
    elif requested_role in {'teacher', 'stuco_admin'}:
        return jsonify({'error': 'Invite code required for this role.'}), 403
    elif not STUDENT_SIGNUP_ENABLED:
        return jsonify({'error': 'Student signups are currently disabled.'}), 403

    year_level_flags = {'year_6': False, 'year_7': False, 'year_8': False}
    if isinstance(year_levels, str):
        year_levels = [item.strip() for item in year_levels.split(',') if item.strip()]
    if isinstance(year_levels, list):
        for level in year_levels:
            if level == 'Year 6':
                year_level_flags['year_6'] = True
            elif level == 'Year 7':
                year_level_flags['year_7'] = True
            elif level == 'Year 8':
                year_level_flags['year_8'] = True

    if role == 'teacher' and not any(year_level_flags.values()):
        return jsonify({'error': 'Select at least one year level for teacher accounts.'}), 400

    user = User(
        azure_oid=f"local:{uuid4()}",
        email=email,
        name=name,
        role=role,
        password_hash=generate_password_hash(password)
    )
    db.session.add(user)
    db.session.flush()

    teacher_profile = None
    if role == 'teacher':
        teacher_profile = Teacher.query.filter_by(email=email).first()
        if teacher_profile:
            if teacher_profile.user_id:
                db.session.rollback()
                return jsonify({'error': 'Teacher profile already linked to an account.'}), 409
            teacher_profile.user_id = user.id
            teacher_profile.name = name
            teacher_profile.year_6 = year_level_flags['year_6']
            teacher_profile.year_7 = year_level_flags['year_7']
            teacher_profile.year_8 = year_level_flags['year_8']
        else:
            teacher_profile = Teacher(
                user_id=user.id,
                name=name,
                email=email,
                year_6=year_level_flags['year_6'],
                year_7=year_level_flags['year_7'],
                year_8=year_level_flags['year_8']
            )
            db.session.add(teacher_profile)

    db.session.commit()
    session['user_id'] = user.id

    return jsonify({
        'message': 'Account created successfully.',
        'user': build_user_payload(user, teacher_profile)
    }), 201


@app.route('/api/auth/login', methods=['POST'])
def login_user():
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({'error': 'Invalid or missing JSON body.'}), 400

    email = normalize_email(data.get('email') or '')
    password = data.get('password') or ''
    if not email or not password:
        return jsonify({'error': 'Email and password are required.'}), 400

    user = User.query.filter_by(email=email).first()
    if not user or not user.password_hash or not check_password_hash(user.password_hash, password):
        return jsonify({'error': 'Invalid email or password.'}), 401
    if user.is_active is False:
        return jsonify({'error': 'Account disabled. Contact an administrator.'}), 403

    session['user_id'] = user.id
    user.last_login_at = db.func.now()
    db.session.commit()

    teacher_profile = None
    if user.role == 'teacher':
        teacher_profile = Teacher.query.filter_by(user_id=user.id).first()

    return jsonify({
        'message': 'Login successful.',
        'user': build_user_payload(user, teacher_profile)
    }), 200


@app.route('/api/auth/logout', methods=['POST'])
def logout_user():
    session.pop('user_id', None)
    return jsonify({'message': 'Logged out successfully.'}), 200


@app.route('/api/auth/me', methods=['GET'])
def get_current_user():
    user = resolve_session_user()
    if not user:
        return jsonify({'error': 'Authentication required.'}), 401

    teacher_profile = None
    if user.role == 'teacher':
        teacher_profile = Teacher.query.filter_by(user_id=user.id).first()

    return jsonify({
        'user': build_user_payload(user, teacher_profile)
    }), 200

# ======================================================================
# --- Student API Routes ---
# ======================================================================
@app.route('/api/teachers', methods=['GET'])
def get_teachers():
    year_level = request.args.get('year_level') 
    query = Teacher.query.filter(Teacher.is_active.is_(True))
    if year_level == 'Year 6':
        query = query.filter(Teacher.year_6.is_(True))
    elif year_level == 'Year 7':
        query = query.filter(Teacher.year_7.is_(True))
    elif year_level == 'Year 8':
        query = query.filter(Teacher.year_8.is_(True))
    teachers_list = [{'id': t.id, 'name': t.name, 'email': t.email} for t in query.all()]
    return jsonify(teachers_list)

@app.route('/api/submit_feedback', methods=['POST'])
@auth_required(role='student')
def submit_feedback():
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({'error': 'Invalid or missing JSON body.'}), 400

    feedback_text = data.get('feedback_text')
    category = (data.get('category') or '').strip().lower()
    teacher_id = data.get('teacher_id')
    year_level = data.get('year_level')
    willing_to_share_name = data.get('willing_to_share_name', False)
    context_detail = data.get('context_detail')
    
    if not feedback_text or not category:
        return jsonify({'error': 'Missing required fields.'}), 400
    category_record = Category.query.filter_by(slug=category, is_active=True).first()
    if not category_record:
        return jsonify({'error': 'Invalid or inactive category.'}), 400
    if len(feedback_text) > 2000:
        return jsonify({'error': 'Feedback text exceeds 2000 characters.'}), 400
    if context_detail and len(context_detail) > 255:
        return jsonify({'error': 'Context detail exceeds 255 characters.'}), 400
    
    teacher_id_int = None
    if category_record.requires_teacher:
        if not teacher_id:
            return jsonify({'error': 'Teacher feedback requires a teacher_id.'}), 400
        try:
            teacher_id_int = int(teacher_id)
        except ValueError:
            return jsonify({'error': 'Invalid teacher ID format.'}), 400
        teacher_profile = db.session.get(Teacher, teacher_id_int)
        if not teacher_profile or not teacher_profile.is_active:
            return jsonify({'error': 'Teacher not found.'}), 400
    
    try:
        screening = run_toxicity_check(feedback_text)
        is_inappropriate = screening['is_inappropriate']
        
        new_feedback = Feedback(
            submitted_by_user_id=g.user.id,
            feedback_text=feedback_text,
            category=category_record.slug,
            teacher_id=teacher_id_int, 
            year_level_submitted=year_level,
            context_detail=context_detail,
            willing_to_share_name=willing_to_share_name,
            toxicity_score=screening['toxicity_score'],
            is_inappropriate=is_inappropriate,
            status='New',
            is_summary_approved=False,
            # Add ratings if they exist
            rating_clarity = data.get('rating_clarity'),
            rating_pacing = data.get('rating_pacing'),
            rating_resources = data.get('rating_resources'),
            rating_support = data.get('rating_support')
        )

        if is_inappropriate:
            new_feedback.status = 'Screened - Escalation'
        else:
            new_feedback.status = 'Approved'
            new_feedback.is_summary_approved = True
        
        db.session.add(new_feedback)
        db.session.flush()
        record_feedback_status(new_feedback.id, None, new_feedback.status, g.user.id)
        
        if not is_inappropriate:
            job_type = 'teacher' if category_record.requires_teacher else 'category'
            target_id = str(teacher_id_int) if job_type == 'teacher' else category_record.slug
            
            print(f"API: Adding '{job_type}' summary job for target '{target_id}'.")
            job = SummaryJobQueue(job_type=job_type, target_id=target_id, feedback_id=new_feedback.id)
            db.session.add(job)
        db.session.commit()
            
        return jsonify({'message': f'Feedback submitted successfully. Status: {new_feedback.status}', 'id': new_feedback.id, 'status': new_feedback.status}), 201
    
    except Exception as e:
        db.session.rollback()
        print(f"Error submitting feedback: {e}")
        return jsonify({'error': 'Internal server error during submission.'}), 500

# ======================================================================
# --- Student Dashboard API Routes ---
# ======================================================================
@app.route('/api/student/feedback', methods=['GET'])
@auth_required(role='student')
def get_student_feedback():
    status_filter = request.args.get('status')
    query = Feedback.query.filter_by(submitted_by_user_id=g.user.id)
    if status_filter:
        query = query.filter(Feedback.status == status_filter)

    feedback_items = query.order_by(Feedback.id.desc()).all()
    feedback_ids = [item.id for item in feedback_items]
    history_map = defaultdict(list)
    if feedback_ids:
        history_entries = FeedbackStatusHistory.query.filter(
            FeedbackStatusHistory.feedback_id.in_(feedback_ids)
        ).order_by(FeedbackStatusHistory.changed_at.asc()).all()
        for entry in history_entries:
            history_map[entry.feedback_id].append({
                'old_status': entry.old_status,
                'new_status': entry.new_status,
                'changed_at': entry.changed_at.isoformat(),
                'note': entry.note
            })
    results = []
    for item in feedback_items:
        teacher_name = None
        if item.teacher_id:
            teacher = db.session.get(Teacher, item.teacher_id)
            teacher_name = teacher.name if teacher else None
        results.append({
            'id': item.id,
            'category': item.category,
            'status': item.status,
            'teacher_name': teacher_name,
            'context_detail': item.context_detail,
            'year_level': item.year_level_submitted,
            'created_at': item.created_at.isoformat() if item.created_at else None,
            'status_history': history_map.get(item.id, [])
        })
    return jsonify(results)

# ======================================================================
# --- Teacher API Routes ---
# ======================================================================
@app.route('/api/teacher/stats', methods=['GET'])
@auth_required(role='teacher')
def get_teacher_stats():
    teacher_id = g.teacher_profile.id
    
    total_feedback = Feedback.query.filter(Feedback.teacher_id == teacher_id).count()
    approved_count = Feedback.query.filter(
        Feedback.teacher_id == teacher_id, 
        Feedback.is_summary_approved.is_(True)
    ).count()
    
    trend_query = db.session.query(
        func.coalesce(func.avg(Feedback.rating_pacing), 0),
        func.coalesce(func.avg(Feedback.rating_clarity), 0),
        func.coalesce(func.avg(Feedback.rating_resources), 0),
        func.coalesce(func.avg(Feedback.rating_support), 0)
    ).filter(
        Feedback.teacher_id == teacher_id,
        Feedback.is_inappropriate.is_(False),
        Feedback.is_summary_approved.is_(True)
    ).one()

    trend_data_list = [
        round(trend_query[0], 1), # Pacing
        round(trend_query[1], 1), # Clarity
        round(trend_query[2], 1), # Resources
        round(trend_query[3], 1)  # Support
    ]
    
    trend_data = {
        'labels': ['Pacing', 'Clarity', 'Resources', 'Support'],
        'data': trend_data_list, 
    }

    return jsonify({
        'stats': {
            'total_feedback': total_feedback,
            'approved_summaries_count': approved_count, 
            'last_check_in': "Today" 
        },
        'trends': trend_data
    })

@app.route('/api/teacher/holistic_summary', methods=['GET'])
@auth_required(role='teacher')
def get_teacher_holistic_summary():
    teacher_id = g.teacher_profile.id
    summary = db.session.get(TeacherSummary, teacher_id)
    if not summary:
        positive_bullets = ["No summaries have been generated yet."]
        actionable_bullets = ["Please check back after new feedback is submitted."]
        return jsonify({
            'teacher_name': g.teacher_profile.name,
            'positive_bullets': positive_bullets,
            'actionable_bullets': actionable_bullets,
            'positive_summary': render_bullets_html(positive_bullets),
            'actionable_summary': render_bullets_html(actionable_bullets)
        })
    positive_bullets = get_summary_bullets(summary, True)
    actionable_bullets = get_summary_bullets(summary, False)
    if not positive_bullets:
        positive_bullets = ["No summaries have been generated yet."]
    if not actionable_bullets:
        actionable_bullets = ["Please check back after new feedback is submitted."]
    return jsonify({
        'teacher_name': g.teacher_profile.name,
        'positive_bullets': positive_bullets,
        'actionable_bullets': actionable_bullets,
        'positive_summary': render_bullets_html(positive_bullets),
        'actionable_summary': render_bullets_html(actionable_bullets),
        'last_updated': summary.last_updated.isoformat()
    })

@app.route('/api/clarification_request', methods=['POST'])
@auth_required(role='teacher')
def create_clarification_request():
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({'error': 'Invalid or missing JSON body.'}), 400
    question_text = data.get('question_text')
    if not question_text:
        return jsonify({'error': 'Clarification question text is required.'}), 400
    new_request = ClarificationRequest(
        teacher_id=g.teacher_profile.id,
        question_text=question_text,
        status='pending'
    )
    db.session.add(new_request)
    db.session.commit()
    return jsonify({'message': 'Clarification request submitted to STUCO.'}), 201

@app.route('/api/teacher/clarifications', methods=['GET'])
@auth_required(role='teacher')
def get_teacher_clarifications():
    status_filter = request.args.get('status', 'pending')
    
    try:
        query = ClarificationRequest.query.filter_by(
            teacher_id=g.teacher_profile.id,
            status=status_filter
        ).order_by(ClarificationRequest.requested_on.desc())
        
        requests = []
        for r in query.all():
            requests.append({
                'id': r.id,
                'question_text': r.question_text,
                'status': r.status,
                'admin_reply': r.admin_reply,
                'requested_on': r.requested_on.isoformat()
            })
        return jsonify(requests)
    except Exception as e:
        print(f"ERROR fetching teacher clarifications: {e}")
        return jsonify({'error': 'Could not fetch clarification history.'}), 500

# ======================================================================
# --- Admin API Routes ---
# ======================================================================
@app.route('/api/admin/moderation/queue', methods=['GET'])
@auth_required(role='stuco_admin')
def get_admin_feedback_queue():
    status_filter = request.args.get('status', 'Approved') 
    category_filter = request.args.get('category')
    print(f"--- ADMIN API HIT: Fetching status='{status_filter}' and category='{category_filter}' ---")
    query = Feedback.query.filter(Feedback.status == status_filter)
    if category_filter and category_filter != 'all':
        query = query.filter(Feedback.category == category_filter)
    category_lookup = {c.slug: c.title for c in Category.query.all()}
    queue_items = []
    for f in query.order_by(Feedback.id.desc()).all():
        teacher = db.session.get(Teacher, f.teacher_id)
        teacher_name = teacher.name if teacher else 'N/A'
        summary_positive_bullets = []
        summary_actionable_bullets = []
        summary_note = None
        
        if f.category == 'teacher' and f.teacher_id:
            teacher_summary = db.session.get(TeacherSummary, f.teacher_id)
            if teacher_summary:
                summary_positive_bullets = get_summary_bullets(teacher_summary, True)
                summary_actionable_bullets = get_summary_bullets(teacher_summary, False)
            else:
                summary_note = "Summary not yet generated."
        
        elif f.category != 'teacher':
             category_summary = db.session.get(CategorySummary, f.category)
             if category_summary:
                 summary_positive_bullets = get_summary_bullets(category_summary, True)
                 summary_actionable_bullets = get_summary_bullets(category_summary, False)
             else:
                summary_note = "Summary not yet generated."

        queue_items.append({
            'id': f.id,
            'teacher_name': teacher_name,
            'category': f.category,
            'category_title': category_lookup.get(f.category, f.category),
            'feedback_text': f.feedback_text,
            'context_detail': f.context_detail,
            'toxicity_score': f.toxicity_score,
            'status': f.status,
            'summary_positive_bullets': summary_positive_bullets,
            'summary_actionable_bullets': summary_actionable_bullets,
            'summary_note': summary_note,
            'is_inappropriate': f.is_inappropriate,
            'is_summary_approved': f.is_summary_approved
        })
    return jsonify(queue_items)

@app.route('/api/admin/category_summaries', methods=['GET'])
@auth_required(role='stuco_admin')
def get_category_summaries():
    try:
        summaries = CategorySummary.query.all()
        category_lookup = {c.slug: c.title for c in Category.query.all()}
        summary_data = []
        for s in summaries:
            positive_bullets = get_summary_bullets(s, True)
            actionable_bullets = get_summary_bullets(s, False)
            summary_data.append({
                'category_name': s.category_name,
                'category_title': category_lookup.get(s.category_name, s.category_name),
                'positive_bullets': positive_bullets,
                'actionable_bullets': actionable_bullets,
                'positive_summary': render_bullets_html(positive_bullets),
                'actionable_summary': render_bullets_html(actionable_bullets),
                'last_updated': s.last_updated.isoformat()
            })
        return jsonify(summary_data)
    except Exception as e:
        print(f"ERROR fetching category summaries: {e}")
        return jsonify({"error": "Could not fetch category summaries."}), 500

@app.route('/api/admin/categories', methods=['GET', 'POST'])
@auth_required(role='stuco_admin')
def admin_categories():
    if request.method == 'GET':
        categories = Category.query.order_by(Category.sort_order, Category.title).all()
        return jsonify([
            {
                'id': c.id,
                'slug': c.slug,
                'title': c.title,
                'description': c.description,
                'icon': c.icon,
                'context_label': c.context_label,
                'requires_teacher': c.requires_teacher,
                'is_active': c.is_active,
                'sort_order': c.sort_order
            }
            for c in categories
        ])

    data = request.get_json(silent=True)
    if data is None:
        return jsonify({'error': 'Invalid or missing JSON body.'}), 400

    title = (data.get('title') or '').strip()
    slug = normalize_slug(data.get('slug') or title)
    if not title or not slug:
        return jsonify({'error': 'Title and slug are required.'}), 400
    if Category.query.filter_by(slug=slug).first():
        return jsonify({'error': 'Category slug already exists.'}), 409

    try:
        sort_order = int(data.get('sort_order') or 0)
    except (TypeError, ValueError):
        sort_order = 0

    category = Category(
        slug=slug,
        title=title,
        description=(data.get('description') or '').strip(),
        icon=(data.get('icon') or '').strip(),
        context_label=(data.get('context_label') or '').strip(),
        requires_teacher=bool(data.get('requires_teacher')),
        is_active=bool(data.get('is_active', True)),
        sort_order=sort_order
    )
    db.session.add(category)
    db.session.flush()
    log_audit('category_created', 'category', category.id, details={'slug': slug})
    db.session.commit()
    return jsonify({'message': 'Category created.', 'id': category.id}), 201


@app.route('/api/admin/categories/<int:category_id>', methods=['PUT', 'DELETE'])
@auth_required(role='stuco_admin')
def admin_category_detail(category_id):
    category = db.session.get(Category, category_id)
    if not category:
        return jsonify({'error': 'Category not found.'}), 404

    if request.method == 'DELETE':
        if Feedback.query.filter_by(category=category.slug).first():
            return jsonify({'error': 'Category has feedback attached. Deactivate instead.'}), 400
        db.session.delete(category)
        log_audit('category_deleted', 'category', category_id, details={'slug': category.slug})
        db.session.commit()
        return jsonify({'message': 'Category deleted.'}), 200

    data = request.get_json(silent=True)
    if data is None:
        return jsonify({'error': 'Invalid or missing JSON body.'}), 400

    category.title = (data.get('title') or category.title).strip()
    category.description = (data.get('description') or category.description or '').strip()
    category.icon = (data.get('icon') or category.icon or '').strip()
    category.context_label = (data.get('context_label') or category.context_label or '').strip()
    if data.get('requires_teacher') is not None:
        category.requires_teacher = bool(data.get('requires_teacher'))
    if data.get('is_active') is not None:
        category.is_active = bool(data.get('is_active'))
    if data.get('sort_order') is not None:
        try:
            category.sort_order = int(data.get('sort_order') or 0)
        except (TypeError, ValueError):
            category.sort_order = 0

    log_audit('category_updated', 'category', category_id, details={'slug': category.slug})
    db.session.commit()
    return jsonify({'message': 'Category updated.'}), 200


@app.route('/api/admin/teachers', methods=['GET', 'POST'])
@auth_required(role='stuco_admin')
def admin_teachers():
    if request.method == 'GET':
        teachers = Teacher.query.order_by(Teacher.name).all()
        return jsonify([
            {
                'id': t.id,
                'name': t.name,
                'email': t.email,
                'year_6': t.year_6,
                'year_7': t.year_7,
                'year_8': t.year_8,
                'is_active': t.is_active,
                'user_id': t.user_id,
                'user_email': db.session.get(User, t.user_id).email if t.user_id else None
            }
            for t in teachers
        ])

    data = request.get_json(silent=True)
    if data is None:
        return jsonify({'error': 'Invalid or missing JSON body.'}), 400
    name = (data.get('name') or '').strip()
    email = normalize_email(data.get('email') or '')
    if not name or not email:
        return jsonify({'error': 'Name and email are required.'}), 400
    if not is_valid_email(email):
        return jsonify({'error': 'Invalid email address.'}), 400
    existing = Teacher.query.filter_by(email=email).first()
    if existing:
        return jsonify({'error': 'Teacher with this email already exists.'}), 409

    teacher = Teacher(
        name=name,
        email=email,
        year_6=bool(data.get('year_6')),
        year_7=bool(data.get('year_7')),
        year_8=bool(data.get('year_8')),
        is_active=bool(data.get('is_active', True))
    )
    user = User.query.filter_by(email=email).first()
    if user and user.role == 'teacher':
        teacher.user_id = user.id
    db.session.add(teacher)
    db.session.flush()
    log_audit('teacher_created', 'teacher', teacher.id, details={'email': email})
    db.session.commit()
    return jsonify({'message': 'Teacher created.', 'id': teacher.id}), 201


@app.route('/api/admin/teachers/<int:teacher_id>', methods=['PUT'])
@auth_required(role='stuco_admin')
def admin_teacher_detail(teacher_id):
    teacher = db.session.get(Teacher, teacher_id)
    if not teacher:
        return jsonify({'error': 'Teacher not found.'}), 404

    data = request.get_json(silent=True)
    if data is None:
        return jsonify({'error': 'Invalid or missing JSON body.'}), 400

    if data.get('name') is not None:
        teacher.name = (data.get('name') or teacher.name).strip()
    if data.get('email') is not None:
        email = normalize_email(data.get('email') or '')
        if not is_valid_email(email):
            return jsonify({'error': 'Invalid email address.'}), 400
        duplicate = Teacher.query.filter(Teacher.email == email, Teacher.id != teacher_id).first()
        if duplicate:
            return jsonify({'error': 'Another teacher already uses this email.'}), 409
        teacher.email = email
    if data.get('year_6') is not None:
        teacher.year_6 = bool(data.get('year_6'))
    if data.get('year_7') is not None:
        teacher.year_7 = bool(data.get('year_7'))
    if data.get('year_8') is not None:
        teacher.year_8 = bool(data.get('year_8'))
    if data.get('is_active') is not None:
        teacher.is_active = bool(data.get('is_active'))

    if 'user_email' in data:
        user_email = normalize_email(data.get('user_email') or '')
        if not user_email:
            teacher.user_id = None
        else:
            user = User.query.filter_by(email=user_email).first()
            if not user:
                return jsonify({'error': 'User not found for linking.'}), 404
            if user.role != 'teacher':
                return jsonify({'error': 'User is not a teacher role.'}), 400
            linked = Teacher.query.filter(Teacher.user_id == user.id, Teacher.id != teacher_id).first()
            if linked:
                return jsonify({'error': 'User already linked to another teacher profile.'}), 409
            teacher.user_id = user.id

    log_audit('teacher_updated', 'teacher', teacher_id, details={'email': teacher.email})
    db.session.commit()
    return jsonify({'message': 'Teacher updated.'}), 200


@app.route('/api/admin/announcements', methods=['GET', 'POST'])
@auth_required(role='stuco_admin')
def admin_announcements():
    if request.method == 'GET':
        announcements = Announcement.query.order_by(Announcement.created_at.desc()).all()
        return jsonify([
            {
                'id': a.id,
                'title': a.title,
                'body': a.body,
                'audience': a.audience,
                'is_active': a.is_active,
                'created_at': a.created_at.isoformat(),
                'updated_at': a.updated_at.isoformat()
            }
            for a in announcements
        ])

    data = request.get_json(silent=True)
    if data is None:
        return jsonify({'error': 'Invalid or missing JSON body.'}), 400
    title = (data.get('title') or '').strip()
    body = (data.get('body') or '').strip()
    if not title or not body:
        return jsonify({'error': 'Title and body are required.'}), 400
    audience = (data.get('audience') or 'all').strip().lower()
    if audience not in {'all', 'student', 'teacher'}:
        return jsonify({'error': 'Invalid audience.'}), 400

    announcement = Announcement(
        title=title,
        body=body,
        audience=audience,
        is_active=bool(data.get('is_active', True)),
        created_by_user_id=g.user.id
    )
    db.session.add(announcement)
    db.session.flush()
    log_audit('announcement_created', 'announcement', announcement.id, details={'audience': audience})
    db.session.commit()
    return jsonify({'message': 'Announcement created.', 'id': announcement.id}), 201


@app.route('/api/admin/announcements/<int:announcement_id>', methods=['PUT', 'DELETE'])
@auth_required(role='stuco_admin')
def admin_announcement_detail(announcement_id):
    announcement = db.session.get(Announcement, announcement_id)
    if not announcement:
        return jsonify({'error': 'Announcement not found.'}), 404

    if request.method == 'DELETE':
        db.session.delete(announcement)
        log_audit('announcement_deleted', 'announcement', announcement_id)
        db.session.commit()
        return jsonify({'message': 'Announcement deleted.'}), 200

    data = request.get_json(silent=True)
    if data is None:
        return jsonify({'error': 'Invalid or missing JSON body.'}), 400
    if data.get('title') is not None:
        announcement.title = (data.get('title') or announcement.title).strip()
    if data.get('body') is not None:
        announcement.body = (data.get('body') or announcement.body).strip()
    if data.get('audience') is not None:
        audience = (data.get('audience') or announcement.audience).strip().lower()
        if audience not in {'all', 'student', 'teacher'}:
            return jsonify({'error': 'Invalid audience.'}), 400
        announcement.audience = audience
    if data.get('is_active') is not None:
        announcement.is_active = bool(data.get('is_active'))

    log_audit('announcement_updated', 'announcement', announcement_id, details={'audience': announcement.audience})
    db.session.commit()
    return jsonify({'message': 'Announcement updated.'}), 200


@app.route('/api/admin/audit_logs', methods=['GET'])
@auth_required(role='stuco_admin')
def admin_audit_logs():
    limit = request.args.get('limit', '50')
    try:
        limit_val = max(1, min(int(limit), 200))
    except ValueError:
        limit_val = 50
    logs = AuditLog.query.order_by(AuditLog.created_at.desc()).limit(limit_val).all()
    return jsonify([
        {
            'id': log.id,
            'actor_user_id': log.actor_user_id,
            'actor_name': db.session.get(User, log.actor_user_id).name if log.actor_user_id else None,
            'action': log.action,
            'target_type': log.target_type,
            'target_id': log.target_id,
            'details': log.details,
            'created_at': log.created_at.isoformat()
        }
        for log in logs
    ])

@app.route('/api/admin/feedback/<int:feedback_id>/approve', methods=['PUT'])
@auth_required(role='stuco_admin')
def approve_feedback_summary(feedback_id):
    feedback_item = db.session.get(Feedback, feedback_id)
    if not feedback_item:
        return jsonify({'error': 'Feedback not found.'}), 404
    old_status = feedback_item.status
    feedback_item.is_summary_approved = True
    feedback_item.status = 'Approved'
    
    job_type = 'teacher' if feedback_item.category == 'teacher' else 'category'
    target_id = str(feedback_item.teacher_id) if job_type == 'teacher' else feedback_item.category
    
    job = SummaryJobQueue(job_type=job_type, target_id=target_id, feedback_id=feedback_item.id)
    db.session.add(job)
    record_feedback_status(feedback_item.id, old_status, feedback_item.status, g.user.id, note='Admin approved feedback')
    log_audit('feedback_approved', 'feedback', feedback_item.id, details={'previous_status': old_status, 'new_status': feedback_item.status})
    db.session.commit()
    return jsonify({'message': f'Feedback ID {feedback_id} re-approved. Summary regenerating in background.'})

@app.route('/api/admin/feedback/<int:feedback_id>/retract', methods=['PUT'])
@auth_required(role='stuco_admin')
def retract_feedback_summary(feedback_id):
    feedback_item = db.session.get(Feedback, feedback_id)
    if not feedback_item:
        return jsonify({'error': 'Feedback not found.'}), 404
    old_status = feedback_item.status
    feedback_item.is_summary_approved = False
    feedback_item.status = 'Retracted by Admin'

    job_type = 'teacher' if feedback_item.category == 'teacher' else 'category'
    target_id = str(feedback_item.teacher_id) if job_type == 'teacher' else feedback_item.category
    
    job = SummaryJobQueue(job_type=job_type, target_id=target_id, feedback_id=feedback_item.id)
    db.session.add(job)
    record_feedback_status(feedback_item.id, old_status, feedback_item.status, g.user.id, note='Admin retracted feedback')
    log_audit('feedback_retracted', 'feedback', feedback_item.id, details={'previous_status': old_status, 'new_status': feedback_item.status})
    db.session.commit()
    return jsonify({'message': f'Feedback ID {feedback_id} retracted. Summary regenerating in background.'})

@app.route('/api/admin/feedback/<int:feedback_id>/delete', methods=['DELETE'])
@auth_required(role='stuco_admin')
def delete_feedback(feedback_id):
    try:
        feedback_item = db.session.get(Feedback, feedback_id)
        if not feedback_item:
            return jsonify({'error': 'Feedback not found.'}), 404
        old_status = feedback_item.status
        
        # Get target info *before* deleting
        job_type = 'teacher' if feedback_item.category == 'teacher' else 'category'
        target_id = str(feedback_item.teacher_id) if job_type == 'teacher' else feedback_item.category
        
        # --- FIX #2: Delete dependent jobs first to avoid race condition ---
        SummaryJobQueue.query.filter_by(feedback_id=feedback_id).delete()
        
        # Now, delete the item
        record_feedback_status(feedback_item.id, old_status, 'Deleted', g.user.id, note='Admin deleted feedback')
        log_audit('feedback_deleted', 'feedback', feedback_item.id, details={'previous_status': old_status})
        db.session.delete(feedback_item)
        db.session.commit()
        
        # Create the new job *after* deleting, with a null feedback_id
        job = SummaryJobQueue(job_type=job_type, target_id=target_id, feedback_id=None, status='pending')
        db.session.add(job)
        db.session.commit()
        
        return jsonify({'message': f'Feedback ID {feedback_id} permanently deleted.'}), 200
    except Exception as e:
        db.session.rollback()
        print(f"ERROR: Delete feedback failed. {e}")
        return jsonify({'error': f'An error occurred during deletion: {e}'}), 500

@app.route('/api/admin/clarification_requests', methods=['GET'])
@auth_required(role='stuco_admin')
def get_clarification_queue():
    status_filter = request.args.get('status', 'pending')
    query = ClarificationRequest.query.filter_by(status=status_filter)
    
    queue_items = []
    for r in query.order_by(ClarificationRequest.requested_on.desc()).all():
        teacher = db.session.get(Teacher, r.teacher_id)
        teacher_name = teacher.name if teacher else 'Unknown'
        queue_items.append({
            'id': r.id,
            'teacher_name': teacher_name,
            'question_text': r.question_text,
            'status': r.status,
            'admin_reply': r.admin_reply,
            'requested_on': r.requested_on.isoformat()
        })
    return jsonify(queue_items)

@app.route('/api/admin/clarification/<int:request_id>/reply', methods=['POST'])
@auth_required(role='stuco_admin')
def reply_to_clarification(request_id):
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({'error': 'Invalid or missing JSON body.'}), 400
    reply_text = data.get('reply_text')
    
    if not reply_text:
        return jsonify({'error': 'Reply text is required.'}), 400
        
    clarification_req = db.session.get(ClarificationRequest, request_id)
    if not clarification_req:
        return jsonify({'error': 'Clarification request not found.'}), 404
    
    try:
        clarification_req.admin_reply = reply_text
        clarification_req.status = 'resolved'
        log_audit('clarification_replied', 'clarification_request', clarification_req.id, details={'teacher_id': clarification_req.teacher_id})
        db.session.commit()
        return jsonify({'message': 'Reply sent and request resolved.'}), 200
    except Exception as e:
        db.session.rollback()
        print(f"ERROR replying to clarification: {e}")
        return jsonify({'error': 'Internal server error.'}), 500

@app.route('/api/admin/reset_database', methods=['POST'])
@auth_required(role='stuco_admin')
def reset_database():
    try:
        print("INFO: Admin triggered database reset.")
        
        print("WORKER: Sending stop signal...")
        stop_worker_event.set()
        if is_thread_alive(worker_thread):
            worker_thread.join()
        print("WORKER: Worker thread stopped.")

        db.drop_all()
        db.create_all()
        ensure_schema_updates()
        seed_data()
        log_audit('database_reset', 'database', 'all', details={'action': 'reset'})
        db.session.commit()
        
        print("INFO: Database reset and re-seed successful.")
        
    finally:
        # --- FIX #1: Ensure worker *always* restarts ---
        if ENABLE_WORKER and start_worker_thread():
            print("WORKER: Worker thread has been restarted.")
            
    return jsonify({'message': 'Database has been successfully reset.'}), 200

# ======================================================================
# --- Server Startup ---
# ======================================================================
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        ensure_schema_updates()
        seed_data()
    
    if ENABLE_WORKER:
        print("MAIN: Starting background worker thread...")
        start_worker_thread()

    if AUTO_OPEN_BROWSER:
        threading.Timer(1.0, open_browser).start()
    
    def stop_worker():
        print("MAIN: Shutting down worker thread...")
        stop_worker_event.set()
        if is_thread_alive(worker_thread):
            worker_thread.join()
    atexit.register(stop_worker)
        
    print("\n--- SERVER READY ---")
    print(f"Home: http://{BROWSER_HOST}:{PORT}/")
    print(f"Student Feedback: http://{BROWSER_HOST}:{PORT}/feedback")
    print(f"Student Dashboard: http://{BROWSER_HOST}:{PORT}/student_dashboard")
    print(f"Teacher: http://{BROWSER_HOST}:{PORT}/teach_frontend.html")
    print(f"Admin: http://{BROWSER_HOST}:{PORT}/stuco_admin_dashboard.html")
    print("Dev shortcut: append ?mock_user_id=1/2/3 if ALLOW_MOCK_AUTH is enabled.")
    print("--------------------------------------------------")
    app.run(host=HOST, port=PORT, debug=False)
