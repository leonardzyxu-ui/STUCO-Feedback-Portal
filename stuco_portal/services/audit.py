from flask import g

from ..extensions import db
from ..models import AuditLog, FeedbackStatusHistory


def log_audit(action, target_type=None, target_id=None, details=None, actor_id=None):
    try:
        if actor_id is None and hasattr(g, "user") and g.user:
            actor_id = g.user.id
        entry = AuditLog(
            actor_user_id=actor_id,
            action=action,
            target_type=target_type,
            target_id=str(target_id) if target_id is not None else None,
            details=details,
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
        note=note,
    )
    db.session.add(entry)
