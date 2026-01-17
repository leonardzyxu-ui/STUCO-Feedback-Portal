from datetime import datetime

from flask import Blueprint, current_app, jsonify, request

from .. import create_base_app
from ..extensions import db
from ..models import (
    Announcement,
    AuditLog,
    Category,
    CategorySummary,
    ClarificationRequest,
    Feedback,
    SummaryJobQueue,
    Teacher,
    TeacherSummary,
)
from ..services.ai.summaries import get_summary_bullets
from ..services.audit import log_audit, record_feedback_status
from ..services.db_utils import ensure_schema_updates
from ..services.seed import seed_data

mcp_bp = Blueprint("mcp", __name__)


def _get_mcp_auth_token():
    header = request.headers.get("Authorization", "")
    if header.lower().startswith("bearer "):
        return header.split(" ", 1)[1].strip()
    return request.headers.get("X-MCP-API-KEY")


def require_mcp_auth(fn):
    def wrapper(*args, **kwargs):
        if not current_app.config.get("MCP_REQUIRE_AUTH", True):
            return fn(*args, **kwargs)
        expected = current_app.config.get("MCP_API_KEY")
        if not expected:
            return jsonify({"error": "MCP_API_KEY not configured."}), 500
        token = _get_mcp_auth_token()
        if token != expected:
            return jsonify({"error": "Unauthorized."}), 401
        return fn(*args, **kwargs)

    wrapper.__name__ = fn.__name__
    return wrapper


@mcp_bp.route("/mcp/health", methods=["GET"])
@require_mcp_auth
def mcp_health():
    return jsonify({"status": "ok", "time": datetime.utcnow().isoformat() + "Z"})


@mcp_bp.route("/mcp/manifest", methods=["GET"])
@require_mcp_auth
def mcp_manifest():
    return jsonify(
        {
            "name": "stuco-mcp",
            "version": "0.1",
            "time": datetime.utcnow().isoformat() + "Z",
            "resources": [
                {
                    "name": "teachers",
                    "description": "Teacher profiles with year-level flags.",
                    "params": ["is_active", "year_level"],
                },
                {
                    "name": "feedback",
                    "description": "Feedback entries filtered by status/category/teacher.",
                    "params": ["status", "category", "teacher_id", "limit"],
                },
                {
                    "name": "categories",
                    "description": "Category catalog.",
                    "params": ["include_inactive"],
                },
                {
                    "name": "teacher_summaries",
                    "description": "Teacher summaries with bullet lists.",
                    "params": ["teacher_id"],
                },
                {
                    "name": "category_summaries",
                    "description": "Category summaries with bullet lists.",
                    "params": ["category"],
                },
                {
                    "name": "clarifications",
                    "description": "Teacher clarification requests.",
                    "params": ["status"],
                },
                {
                    "name": "announcements",
                    "description": "Announcements for all audiences.",
                    "params": ["is_active"],
                },
                {
                    "name": "summary_jobs",
                    "description": "Summary job queue entries.",
                    "params": ["status", "limit"],
                },
                {
                    "name": "audit_logs",
                    "description": "Audit log entries.",
                    "params": ["limit"],
                },
            ],
            "tools": [
                {
                    "name": "approve_feedback",
                    "description": "Approve a feedback item and enqueue a summary job.",
                    "input_schema": {"feedback_id": "int"},
                },
                {
                    "name": "retract_feedback",
                    "description": "Retract a feedback item and enqueue a summary job.",
                    "input_schema": {"feedback_id": "int"},
                },
                {
                    "name": "delete_feedback",
                    "description": "Delete a feedback item and enqueue a summary job.",
                    "input_schema": {"feedback_id": "int"},
                },
                {
                    "name": "enqueue_summary",
                    "description": "Insert a summary job for a teacher/category.",
                    "input_schema": {
                        "job_type": "teacher|category",
                        "target_id": "str",
                        "feedback_id": "int(optional)",
                    },
                },
                {
                    "name": "reply_clarification",
                    "description": "Reply to a clarification request and mark resolved.",
                    "input_schema": {"request_id": "int", "reply_text": "str"},
                },
                {
                    "name": "create_announcement",
                    "description": "Create a new announcement.",
                    "input_schema": {"title": "str", "body": "str", "audience": "str"},
                },
                {
                    "name": "reset_database",
                    "description": "Drop and reseed the database.",
                    "input_schema": {},
                },
            ],
        }
    )


@mcp_bp.route("/mcp/resources/<resource_name>", methods=["GET"])
@require_mcp_auth
def mcp_resource(resource_name):
    if resource_name == "teachers":
        is_active = request.args.get("is_active")
        year_level = request.args.get("year_level")
        query = Teacher.query
        if is_active is not None:
            query = query.filter(Teacher.is_active.is_(is_active.lower() in {"1", "true", "yes"}))
        if year_level == "Year 6":
            query = query.filter(Teacher.year_6.is_(True))
        elif year_level == "Year 7":
            query = query.filter(Teacher.year_7.is_(True))
        elif year_level == "Year 8":
            query = query.filter(Teacher.year_8.is_(True))
        return jsonify(
            [
                {
                    "id": t.id,
                    "name": t.name,
                    "email": t.email,
                    "year_6": t.year_6,
                    "year_7": t.year_7,
                    "year_8": t.year_8,
                    "is_active": t.is_active,
                    "user_id": t.user_id,
                }
                for t in query.order_by(Teacher.name).all()
            ]
        )

    if resource_name == "feedback":
        status = request.args.get("status")
        category = request.args.get("category")
        teacher_id = request.args.get("teacher_id")
        limit = request.args.get("limit")
        query = Feedback.query
        if status:
            query = query.filter(Feedback.status == status)
        if category:
            query = query.filter(Feedback.category == category)
        if teacher_id:
            try:
                query = query.filter(Feedback.teacher_id == int(teacher_id))
            except ValueError:
                return jsonify({"error": "teacher_id must be an integer."}), 400
        if limit:
            try:
                limit_val = max(1, min(int(limit), 200))
                query = query.limit(limit_val)
            except ValueError:
                return jsonify({"error": "limit must be an integer."}), 400
        return jsonify(
            [
                {
                    "id": f.id,
                    "teacher_id": f.teacher_id,
                    "category": f.category,
                    "feedback_text": f.feedback_text,
                    "context_detail": f.context_detail,
                    "year_level_submitted": f.year_level_submitted,
                    "willing_to_share_name": f.willing_to_share_name,
                    "submitted_by_user_id": f.submitted_by_user_id,
                    "created_at": f.created_at.isoformat() if f.created_at else None,
                    "toxicity_score": f.toxicity_score,
                    "is_inappropriate": f.is_inappropriate,
                    "status": f.status,
                    "is_summary_approved": f.is_summary_approved,
                }
                for f in query.order_by(Feedback.id.desc()).all()
            ]
        )

    if resource_name == "categories":
        include_inactive = request.args.get("include_inactive", "0").lower() in {
            "1",
            "true",
            "yes",
        }
        query = Category.query
        if not include_inactive:
            query = query.filter(Category.is_active.is_(True))
        return jsonify(
            [
                {
                    "id": c.id,
                    "slug": c.slug,
                    "title": c.title,
                    "description": c.description,
                    "icon": c.icon,
                    "context_label": c.context_label,
                    "requires_teacher": c.requires_teacher,
                    "is_active": c.is_active,
                    "sort_order": c.sort_order,
                }
                for c in query.order_by(Category.sort_order, Category.title).all()
            ]
        )

    if resource_name == "teacher_summaries":
        teacher_id = request.args.get("teacher_id")
        query = TeacherSummary.query
        if teacher_id:
            query = query.filter(TeacherSummary.teacher_id == int(teacher_id))
        return jsonify(
            [
                {
                    "teacher_id": s.teacher_id,
                    "positive_bullets": get_summary_bullets(s, True),
                    "actionable_bullets": get_summary_bullets(s, False),
                    "last_updated": s.last_updated.isoformat() if s.last_updated else None,
                }
                for s in query.all()
            ]
        )

    if resource_name == "category_summaries":
        category = request.args.get("category")
        query = CategorySummary.query
        if category:
            query = query.filter(CategorySummary.category_name == category)
        return jsonify(
            [
                {
                    "category_name": s.category_name,
                    "positive_bullets": get_summary_bullets(s, True),
                    "actionable_bullets": get_summary_bullets(s, False),
                    "last_updated": s.last_updated.isoformat() if s.last_updated else None,
                }
                for s in query.all()
            ]
        )

    if resource_name == "clarifications":
        status = request.args.get("status")
        query = ClarificationRequest.query
        if status:
            query = query.filter(ClarificationRequest.status == status)
        return jsonify(
            [
                {
                    "id": c.id,
                    "teacher_id": c.teacher_id,
                    "question_text": c.question_text,
                    "status": c.status,
                    "admin_reply": c.admin_reply,
                    "requested_on": c.requested_on.isoformat() if c.requested_on else None,
                }
                for c in query.order_by(ClarificationRequest.requested_on.desc()).all()
            ]
        )

    if resource_name == "announcements":
        is_active = request.args.get("is_active")
        query = Announcement.query
        if is_active is not None:
            query = query.filter(
                Announcement.is_active.is_(is_active.lower() in {"1", "true", "yes"})
            )
        return jsonify(
            [
                {
                    "id": a.id,
                    "title": a.title,
                    "body": a.body,
                    "audience": a.audience,
                    "is_active": a.is_active,
                    "created_at": a.created_at.isoformat() if a.created_at else None,
                }
                for a in query.order_by(Announcement.created_at.desc()).all()
            ]
        )

    if resource_name == "summary_jobs":
        status = request.args.get("status")
        limit = request.args.get("limit")
        query = SummaryJobQueue.query
        if status:
            query = query.filter(SummaryJobQueue.status == status)
        if limit:
            try:
                limit_val = max(1, min(int(limit), 200))
                query = query.limit(limit_val)
            except ValueError:
                return jsonify({"error": "limit must be an integer."}), 400
        return jsonify(
            [
                {
                    "job_id": j.job_id,
                    "job_type": j.job_type,
                    "target_id": j.target_id,
                    "feedback_id": j.feedback_id,
                    "status": j.status,
                    "created_at": j.created_at.isoformat() if j.created_at else None,
                    "updated_at": j.updated_at.isoformat() if j.updated_at else None,
                }
                for j in query.order_by(SummaryJobQueue.created_at.desc()).all()
            ]
        )

    if resource_name == "audit_logs":
        limit = request.args.get("limit", "50")
        try:
            limit_val = max(1, min(int(limit), 200))
        except ValueError:
            limit_val = 50
        logs = AuditLog.query.order_by(AuditLog.created_at.desc()).limit(limit_val).all()
        return jsonify(
            [
                {
                    "id": log.id,
                    "actor_user_id": log.actor_user_id,
                    "action": log.action,
                    "target_type": log.target_type,
                    "target_id": log.target_id,
                    "details": log.details,
                    "created_at": log.created_at.isoformat() if log.created_at else None,
                }
                for log in logs
            ]
        )

    return jsonify({"error": "Unknown resource."}), 404


@mcp_bp.route("/mcp/tools/<tool_name>", methods=["POST"])
@require_mcp_auth
def mcp_tool(tool_name):
    payload = request.get_json(silent=True) or {}

    if tool_name == "approve_feedback":
        feedback_id = payload.get("feedback_id")
        feedback_item = db.session.get(Feedback, feedback_id)
        if not feedback_item:
            return jsonify({"error": "Feedback not found."}), 404
        old_status = feedback_item.status
        feedback_item.is_summary_approved = True
        feedback_item.status = "Approved"
        job_type = "teacher" if feedback_item.category == "teacher" else "category"
        target_id = str(feedback_item.teacher_id) if job_type == "teacher" else feedback_item.category
        db.session.add(
            SummaryJobQueue(job_type=job_type, target_id=target_id, feedback_id=feedback_item.id)
        )
        record_feedback_status(feedback_item.id, old_status, feedback_item.status, note="MCP approved")
        log_audit(
            "feedback_approved",
            "feedback",
            feedback_item.id,
            details={"previous_status": old_status, "new_status": feedback_item.status},
        )
        db.session.commit()
        return jsonify({"ok": True, "message": "Feedback approved."})

    if tool_name == "retract_feedback":
        feedback_id = payload.get("feedback_id")
        feedback_item = db.session.get(Feedback, feedback_id)
        if not feedback_item:
            return jsonify({"error": "Feedback not found."}), 404
        old_status = feedback_item.status
        feedback_item.is_summary_approved = False
        feedback_item.status = "Retracted by Admin"
        job_type = "teacher" if feedback_item.category == "teacher" else "category"
        target_id = str(feedback_item.teacher_id) if job_type == "teacher" else feedback_item.category
        db.session.add(
            SummaryJobQueue(job_type=job_type, target_id=target_id, feedback_id=feedback_item.id)
        )
        record_feedback_status(feedback_item.id, old_status, feedback_item.status, note="MCP retracted")
        log_audit(
            "feedback_retracted",
            "feedback",
            feedback_item.id,
            details={"previous_status": old_status, "new_status": feedback_item.status},
        )
        db.session.commit()
        return jsonify({"ok": True, "message": "Feedback retracted."})

    if tool_name == "delete_feedback":
        feedback_id = payload.get("feedback_id")
        feedback_item = db.session.get(Feedback, feedback_id)
        if not feedback_item:
            return jsonify({"error": "Feedback not found."}), 404
        old_status = feedback_item.status
        job_type = "teacher" if feedback_item.category == "teacher" else "category"
        target_id = str(feedback_item.teacher_id) if job_type == "teacher" else feedback_item.category
        SummaryJobQueue.query.filter_by(feedback_id=feedback_id).delete()
        record_feedback_status(feedback_item.id, old_status, "Deleted", note="MCP deleted")
        log_audit("feedback_deleted", "feedback", feedback_item.id, details={"previous_status": old_status})
        db.session.delete(feedback_item)
        db.session.commit()
        db.session.add(SummaryJobQueue(job_type=job_type, target_id=target_id, feedback_id=None))
        db.session.commit()
        return jsonify({"ok": True, "message": "Feedback deleted."})

    if tool_name == "enqueue_summary":
        job_type = payload.get("job_type")
        target_id = payload.get("target_id")
        if job_type not in {"teacher", "category"} or not target_id:
            return jsonify({"error": "job_type and target_id are required."}), 400
        job = SummaryJobQueue(
            job_type=job_type,
            target_id=str(target_id),
            feedback_id=payload.get("feedback_id"),
            status="pending",
        )
        db.session.add(job)
        db.session.commit()
        return jsonify({"ok": True, "job_id": job.job_id})

    if tool_name == "reply_clarification":
        request_id = payload.get("request_id")
        reply_text = payload.get("reply_text")
        clarification_req = db.session.get(ClarificationRequest, request_id)
        if not clarification_req:
            return jsonify({"error": "Clarification request not found."}), 404
        if not reply_text:
            return jsonify({"error": "reply_text is required."}), 400
        clarification_req.admin_reply = reply_text
        clarification_req.status = "resolved"
        log_audit(
            "clarification_replied",
            "clarification_request",
            clarification_req.id,
            details={"teacher_id": clarification_req.teacher_id},
        )
        db.session.commit()
        return jsonify({"ok": True, "message": "Clarification replied."})

    if tool_name == "create_announcement":
        title = (payload.get("title") or "").strip()
        body = (payload.get("body") or "").strip()
        audience = (payload.get("audience") or "all").strip().lower()
        if not title or not body:
            return jsonify({"error": "title and body are required."}), 400
        if audience not in {"all", "student", "teacher"}:
            return jsonify({"error": "Invalid audience."}), 400
        announcement = Announcement(
            title=title,
            body=body,
            audience=audience,
            is_active=bool(payload.get("is_active", True)),
        )
        db.session.add(announcement)
        db.session.commit()
        return jsonify({"ok": True, "announcement_id": announcement.id})

    if tool_name == "reset_database":
        db.drop_all()
        db.create_all()
        ensure_schema_updates()
        seed_data()
        db.session.commit()
        return jsonify({"ok": True, "message": "Database reset."})

    return jsonify({"error": "Unknown tool."}), 404


def create_mcp_app(config=None):
    app = create_base_app(config)
    app.register_blueprint(mcp_bp)
    return app
