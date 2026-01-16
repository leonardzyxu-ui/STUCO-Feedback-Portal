# app.py (V2.0 FINAL - Immaculate & Hardened)

import os
from pathlib import Path
from dotenv import load_dotenv
from functools import wraps
import json
import re
import threading
import random
import atexit
from collections import defaultdict
from typing import Any

import requests
from flask import Flask, jsonify, request, g, render_template
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func

# --- Config ---
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(dotenv_path=BASE_DIR / '.env')


# ======================================================================
# --- CONFIGURATION BLOCK ---
# ======================================================================
DATABASE_FILE = 'feedback.db' 
DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY') 
DEEPSEEK_MODEL = "deepseek-chat"
DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"
# Set to True for real AI summaries, False for fast, generic placeholders
DEEPTHINK_OR_NOT = False 
# Worker thread sleep interval (seconds). 10s for demo, 60s for production.
WORKER_SLEEP_INTERVAL = 10 
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
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{DATABASE_FILE}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
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
    
class Teacher(BaseModel):
    __tablename__ = 'teachers'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), unique=True, nullable=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    year_6 = db.Column(db.Boolean, default=False)
    year_7 = db.Column(db.Boolean, default=False)
    year_8 = db.Column(db.Boolean, default=False)

class Feedback(BaseModel):
    __tablename__ = 'feedback'
    id = db.Column(db.Integer, primary_key=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey('teachers.id'), nullable=True) 
    category = db.Column(db.String(50), nullable=False) 
    feedback_text = db.Column(db.Text, nullable=False)
    year_level_submitted = db.Column(db.String(10), nullable=True) 
    willing_to_share_name = db.Column(db.Boolean, default=False)
    submitted_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
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

# ======================================================================
# --- Utility Functions & Auth ---
# ======================================================================
    
def auth_required(role=None):
    def wrapper(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            try:
                mock_user_id = int(request.args.get('mock_user_id', 1))
            except (TypeError, ValueError):
                return jsonify({"error": "Invalid mock_user_id."}), 400
            g.user = db.session.get(User, mock_user_id)
            if not g.user:
                return jsonify({"error": "Authentication required."}), 401
            if role and g.user.role != role:
                return jsonify({"error": f"Access denied. Required role: {role}"}), 403
            if g.user.role in ['teacher', 'stuco_admin']:
                g.teacher_profile = Teacher.query.filter_by(user_id=g.user.id).first()
                if not g.teacher_profile:
                    if g.user.role == 'stuco_admin':
                        g.teacher_profile = None 
                    else:
                        return jsonify({"error": "Teacher profile not found."}), 403
            return f(*args, **kwargs)
        return decorated_function
    return wrapper

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
    if is_thread_alive(worker_thread):
        return False
    stop_worker_event.clear()
    worker_thread = threading.Thread(target=summary_worker_thread, args=(app,))
    worker_thread.daemon = True
    worker_thread.start()
    return True

# ======================================================================
# --- V2.0 Seeding (Now includes Ratings & Clarifications) ---
# ======================================================================
def seed_data():
    """Populates the database *only if it is empty*."""
    if db.session.query(User).first() is not None:
        print("INFO: Database already contains data. Skipping seed.")
        return
    print("INFO: Database is empty. Seeding initial data...")
    db.session.add_all([
        User(id=1, azure_oid='student_1', email='student@test.com', name='Student A', role='student'),
        User(id=2, azure_oid='teacher_1', email='harper@test.com', name='Mr. Harper', role='teacher'),
        User(id=3, azure_oid='admin_1', email='chen@test.com', name='Ms. Chen', role='stuco_admin')
    ])
    db.session.commit()
    db.session.add_all([
        Teacher(id=1, user_id=2, name='Mr. Harper', email='harper@test.com', year_6=True, year_7=True, year_8=False),
        Teacher(id=2, user_id=None, name='Ms. Williams', email='williams@test.com', year_6=True, year_7=False, year_8=True),
        Teacher(id=3, user_id=None, name='Ms. Chen (Admin)', email='chen@test.com', year_6=True, year_7=True, year_8=True)
    ])
    db.session.commit()
    
    f1 = Feedback(id=1, teacher_id=1, year_level_submitted='Year 7', feedback_text='Mr. Harper is a great teacher! His explanations are very clear.', willing_to_share_name=True, submitted_by_user_id=1, category='teacher', rating_clarity=5, rating_pacing=4, rating_resources=5, rating_support=5)
    f2 = Feedback(id=2, teacher_id=None, year_level_submitted='N/A', feedback_text='The cafeteria food, especially the pasta, has been excellent this week.', willing_to_share_name=False, submitted_by_user_id=1, category='food')
    f3 = Feedback(id=3, teacher_id=None, year_level_submitted='N/A', feedback_text='This teacher is a horrible bully and should be fired! I hate their lessons.', willing_to_share_name=False, submitted_by_user_id=1, category='other')
    f4 = Feedback(id=4, teacher_id=None, year_level_submitted='N/A', feedback_text='The new uniform policy is unclear. We need more examples of what is allowed.', willing_to_share_name=False, submitted_by_user_id=1, category='policy')
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

    db.session.commit()
    
    cr1 = ClarificationRequest(teacher_id=1, question_text="A summary mentioned 'pacing' was a problem. Could I know if this refers to the homework pacing or the in-class lecture pacing?", status='pending')
    db.session.add(cr1)
    db.session.commit()
    
    f3_toxic = db.session.get(Feedback, 3)
    if f3_toxic and f3_toxic.is_inappropriate:
        print("INFO: Seeded safeguarding item (ID 3) correctly flagged for escalation.")
    print("INFO: Seed data finished.")


# ======================================================================
# --- Page Routes ---
# ======================================================================
@app.route('/', methods=['GET'])
def index():
    return render_template('stu_frontend.html')
@app.route('/teach_frontend.html', methods=['GET'])
@auth_required(role='teacher')
def teacher_dashboard():
    return render_template('teach_frontend.html')
@app.route('/stuco_admin_dashboard.html', methods=['GET'])
@auth_required(role='stuco_admin')
def stuco_admin_dashboard():
    return render_template('stuco_admin_dashboard.html')

# ======================================================================
# --- Student API Routes ---
# ======================================================================
@app.route('/api/teachers', methods=['GET'])
def get_teachers():
    year_level = request.args.get('year_level') 
    query = Teacher.query
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
    category = data.get('category')
    teacher_id = data.get('teacher_id')
    year_level = data.get('year_level')
    willing_to_share_name = data.get('willing_to_share_name', False)
    
    if not feedback_text or not category:
        return jsonify({'error': 'Missing required fields.'}), 400
    
    teacher_id_int = None
    if category == 'teacher':
        if not teacher_id:
            return jsonify({'error': 'Teacher feedback requires a teacher_id.'}), 400
        try:
            teacher_id_int = int(teacher_id)
        except ValueError:
            return jsonify({'error': 'Invalid teacher ID format.'}), 400
        if not db.session.get(Teacher, teacher_id_int):
            return jsonify({'error': 'Teacher not found.'}), 400
    
    try:
        screening = run_toxicity_check(feedback_text)
        is_inappropriate = screening['is_inappropriate']
        
        new_feedback = Feedback(
            submitted_by_user_id=g.user.id,
            feedback_text=feedback_text,
            category=category,
            teacher_id=teacher_id_int, 
            year_level_submitted=year_level,
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
        db.session.commit() 
        
        if not is_inappropriate:
            job_type = 'teacher' if category == 'teacher' else 'category'
            target_id = str(teacher_id_int) if category == 'teacher' else category
            
            print(f"API: Adding '{job_type}' summary job for target '{target_id}'.")
            job = SummaryJobQueue(job_type=job_type, target_id=target_id, feedback_id=new_feedback.id)
            db.session.add(job)
            db.session.commit()
            
        return jsonify({'message': f'Feedback submitted successfully. Status: {new_feedback.status}', 'id': new_feedback.id}), 201
    
    except Exception as e:
        db.session.rollback()
        print(f"Error submitting feedback: {e}")
        return jsonify({'error': 'Internal server error during submission.'}), 500

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
        return jsonify({
            'teacher_name': g.teacher_profile.name,
            'positive_summary': '<ul><li>No summaries have been generated yet.</li></ul>',
            'actionable_summary': '<ul><li>Please check back after new feedback is submitted.</li></ul>'
        })
    return jsonify({
        'teacher_name': g.teacher_profile.name,
        'positive_summary': summary.latest_positive_summary,
        'actionable_summary': summary.latest_actionable_summary,
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
    queue_items = []
    for f in query.order_by(Feedback.id.desc()).all():
        teacher = db.session.get(Teacher, f.teacher_id)
        teacher_name = teacher.name if teacher else 'N/A'
        summary_positive = "N/A"
        summary_actionable = "N/A"
        
        if f.category == 'teacher' and f.teacher_id:
            teacher_summary = db.session.get(TeacherSummary, f.teacher_id)
            if teacher_summary:
                summary_positive = teacher_summary.latest_positive_summary
                summary_actionable = teacher_summary.latest_actionable_summary
            else:
                summary_positive = "N/A (Summary not yet generated)"
                summary_actionable = "N/A (Summary not yet generated)"
        
        elif f.category != 'teacher':
             category_summary = db.session.get(CategorySummary, f.category)
             if category_summary:
                 summary_positive = category_summary.latest_positive_summary
                 summary_actionable = category_summary.latest_actionable_summary
             else:
                summary_positive = "N/A (Summary not yet generated)"
                summary_actionable = "N/A (Summary not yet generated)"

        queue_items.append({
            'id': f.id,
            'teacher_name': teacher_name,
            'category': f.category,
            'feedback_text': f.feedback_text,
            'toxicity_score': f.toxicity_score,
            'status': f.status,
            'summary_positive': summary_positive,
            'summary_actionable': summary_actionable,
            'is_inappropriate': f.is_inappropriate,
            'is_summary_approved': f.is_summary_approved
        })
    return jsonify(queue_items)

@app.route('/api/admin/category_summaries', methods=['GET'])
@auth_required(role='stuco_admin')
def get_category_summaries():
    try:
        summaries = CategorySummary.query.all()
        summary_data = []
        for s in summaries:
            summary_data.append({
                'category_name': s.category_name,
                'positive_summary': s.latest_positive_summary,
                'actionable_summary': s.latest_actionable_summary,
                'last_updated': s.last_updated.isoformat()
            })
        return jsonify(summary_data)
    except Exception as e:
        print(f"ERROR fetching category summaries: {e}")
        return jsonify({"error": "Could not fetch category summaries."}), 500

@app.route('/api/admin/feedback/<int:feedback_id>/approve', methods=['PUT'])
@auth_required(role='stuco_admin')
def approve_feedback_summary(feedback_id):
    feedback_item = db.session.get(Feedback, feedback_id)
    if not feedback_item:
        return jsonify({'error': 'Feedback not found.'}), 404
    feedback_item.is_summary_approved = True
    feedback_item.status = 'Approved'
    
    job_type = 'teacher' if feedback_item.category == 'teacher' else 'category'
    target_id = str(feedback_item.teacher_id) if job_type == 'teacher' else feedback_item.category
    
    job = SummaryJobQueue(job_type=job_type, target_id=target_id, feedback_id=feedback_item.id)
    db.session.add(job)
    db.session.commit()
    return jsonify({'message': f'Feedback ID {feedback_id} re-approved. Summary regenerating in background.'})

@app.route('/api/admin/feedback/<int:feedback_id>/retract', methods=['PUT'])
@auth_required(role='stuco_admin')
def retract_feedback_summary(feedback_id):
    feedback_item = db.session.get(Feedback, feedback_id)
    if not feedback_item:
        return jsonify({'error': 'Feedback not found.'}), 404
    feedback_item.is_summary_approved = False
    feedback_item.status = 'Retracted by Admin'

    job_type = 'teacher' if feedback_item.category == 'teacher' else 'category'
    target_id = str(feedback_item.teacher_id) if job_type == 'teacher' else feedback_item.category
    
    job = SummaryJobQueue(job_type=job_type, target_id=target_id, feedback_id=feedback_item.id)
    db.session.add(job)
    db.session.commit()
    return jsonify({'message': f'Feedback ID {feedback_id} retracted. Summary regenerating in background.'})

@app.route('/api/admin/feedback/<int:feedback_id>/delete', methods=['DELETE'])
@auth_required(role='stuco_admin')
def delete_feedback(feedback_id):
    try:
        feedback_item = db.session.get(Feedback, feedback_id)
        if not feedback_item:
            return jsonify({'error': 'Feedback not found.'}), 404
        
        # Get target info *before* deleting
        job_type = 'teacher' if feedback_item.category == 'teacher' else 'category'
        target_id = str(feedback_item.teacher_id) if job_type == 'teacher' else feedback_item.category
        
        # --- FIX #2: Delete dependent jobs first to avoid race condition ---
        SummaryJobQueue.query.filter_by(feedback_id=feedback_id).delete()
        
        # Now, delete the item
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
        seed_data()
        
        print("INFO: Database reset and re-seed successful.")
        
    finally:
        # --- FIX #1: Ensure worker *always* restarts ---
        if start_worker_thread():
            print("WORKER: Worker thread has been restarted.")
            
    return jsonify({'message': 'Database has been successfully reset.'}), 200

# ======================================================================
# --- Server Startup ---
# ======================================================================
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        seed_data()
    
    print("MAIN: Starting background worker thread...")
    start_worker_thread()
    
    def stop_worker():
        print("MAIN: Shutting down worker thread...")
        stop_worker_event.set()
        if is_thread_alive(worker_thread):
            worker_thread.join()
    atexit.register(stop_worker)
        
    print("\n--- SERVER READY ---")
    print("Student: http://127.0.0.1:5000/?mock_user_id=1")
    print("Teacher: http://127.0.0.1:5000/teach_frontend.html?mock_user_id=2")
    print("Admin: http://127.0.0.1:5000/stuco_admin_dashboard.html?mock_user_id=3")
    print("--------------------------------------------------")
    app.run(host='0.0.0.0', port=5000, debug=False)
