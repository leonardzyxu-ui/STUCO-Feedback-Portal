from typing import Any

from .extensions import db


class BaseModel(db.Model):
    __abstract__ = True

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)


class User(BaseModel):
    __tablename__ = "users"
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
    __tablename__ = "teachers"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), unique=True, nullable=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    year_6 = db.Column(db.Boolean, default=False)
    year_7 = db.Column(db.Boolean, default=False)
    year_8 = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=True)


class Feedback(BaseModel):
    __tablename__ = "feedback"
    id = db.Column(db.Integer, primary_key=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey("teachers.id"), nullable=True)
    category = db.Column(db.String(50), nullable=False)
    feedback_text = db.Column(db.Text, nullable=False)
    context_detail = db.Column(db.String(255), nullable=True)
    year_level_submitted = db.Column(db.String(10), nullable=True)
    willing_to_share_name = db.Column(db.Boolean, default=False)
    submitted_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=db.func.now())
    toxicity_score = db.Column(db.Float, default=0.0)
    is_inappropriate = db.Column(db.Boolean, default=False)
    status = db.Column(db.String(50), default="New")
    is_summary_approved = db.Column(db.Boolean, default=False)
    rating_clarity = db.Column(db.Integer, nullable=True)
    rating_pacing = db.Column(db.Integer, nullable=True)
    rating_resources = db.Column(db.Integer, nullable=True)
    rating_support = db.Column(db.Integer, nullable=True)


class TeacherSummary(BaseModel):
    __tablename__ = "teacher_summary"
    teacher_id = db.Column(db.Integer, db.ForeignKey("teachers.id"), primary_key=True)
    latest_positive_summary = db.Column(db.Text, nullable=True)
    latest_actionable_summary = db.Column(db.Text, nullable=True)
    last_updated = db.Column(db.DateTime, default=db.func.now(), onupdate=db.func.now())
    raw_positive_bullets = db.Column(db.JSON, nullable=True)
    raw_actionable_bullets = db.Column(db.JSON, nullable=True)


class ClarificationRequest(BaseModel):
    __tablename__ = "clarification_requests"
    id = db.Column(db.Integer, primary_key=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey("teachers.id"), nullable=False)
    question_text = db.Column(db.Text, nullable=False)
    requested_on = db.Column(db.DateTime, default=db.func.now())
    status = db.Column(db.String(50), default="pending")
    admin_reply = db.Column(db.Text, nullable=True)


class SummaryJobQueue(BaseModel):
    __tablename__ = "summary_job_queue"
    job_id = db.Column(db.Integer, primary_key=True)
    job_type = db.Column(db.String(50), nullable=False)
    target_id = db.Column(db.String(50), nullable=False)
    feedback_id = db.Column(db.Integer, db.ForeignKey("feedback.id"), nullable=True)
    status = db.Column(db.String(50), default="pending")
    created_at = db.Column(db.DateTime, default=db.func.now())
    updated_at = db.Column(db.DateTime, default=db.func.now(), onupdate=db.func.now())


class CategorySummary(BaseModel):
    __tablename__ = "category_summary"
    category_name = db.Column(db.String(50), primary_key=True)
    latest_positive_summary = db.Column(db.Text, nullable=True)
    latest_actionable_summary = db.Column(db.Text, nullable=True)
    last_updated = db.Column(db.DateTime, default=db.func.now(), onupdate=db.func.now())
    raw_positive_bullets = db.Column(db.JSON, nullable=True)
    raw_actionable_bullets = db.Column(db.JSON, nullable=True)


class MonthlyDigest(BaseModel):
    __tablename__ = "monthly_digests"
    month_key = db.Column(db.String(7), primary_key=True)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    generated_at = db.Column(db.DateTime, default=db.func.now())
    positive_bullets = db.Column(db.JSON, nullable=True)
    actionable_bullets = db.Column(db.JSON, nullable=True)
    feedback_count = db.Column(db.Integer, default=0)


class Category(BaseModel):
    __tablename__ = "categories"
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
    __tablename__ = "announcements"
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(140), nullable=False)
    body = db.Column(db.Text, nullable=False)
    audience = db.Column(db.String(30), default="all")
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=db.func.now())
    updated_at = db.Column(db.DateTime, default=db.func.now(), onupdate=db.func.now())
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)


class FeedbackStatusHistory(BaseModel):
    __tablename__ = "feedback_status_history"
    id = db.Column(db.Integer, primary_key=True)
    feedback_id = db.Column(
        db.Integer, db.ForeignKey("feedback.id", ondelete="CASCADE"), nullable=False
    )
    old_status = db.Column(db.String(50), nullable=True)
    new_status = db.Column(db.String(50), nullable=False)
    changed_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    changed_at = db.Column(db.DateTime, default=db.func.now())
    note = db.Column(db.String(255), nullable=True)


class AuditLog(BaseModel):
    __tablename__ = "audit_logs"
    id = db.Column(db.Integer, primary_key=True)
    actor_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    action = db.Column(db.String(80), nullable=False)
    target_type = db.Column(db.String(80), nullable=True)
    target_id = db.Column(db.String(80), nullable=True)
    details = db.Column(db.JSON, nullable=True)
    created_at = db.Column(db.DateTime, default=db.func.now())
