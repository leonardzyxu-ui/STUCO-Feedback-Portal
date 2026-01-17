from flask import Blueprint, current_app, jsonify, request, g

from ..auth import auth_required, is_valid_email, normalize_email
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
    User,
)
from ..services.ai.summaries import get_summary_bullets, render_bullets_html
from ..services.audit import log_audit, record_feedback_status
from ..services.db_utils import ensure_schema_updates, normalize_slug
from ..services.seed import seed_data
from ..services.worker import start_worker_thread, stop_worker_thread

bp = Blueprint("admin_api", __name__)


@bp.route("/api/admin/moderation/queue", methods=["GET"])
@auth_required(role="stuco_admin")
def get_admin_feedback_queue():
    status_filter = request.args.get("status", "Approved")
    category_filter = request.args.get("category")
    print(
        f"--- ADMIN API HIT: Fetching status='{status_filter}' and category='{category_filter}' ---"
    )
    query = Feedback.query.filter(Feedback.status == status_filter)
    if category_filter and category_filter != "all":
        query = query.filter(Feedback.category == category_filter)
    category_lookup = {c.slug: c.title for c in Category.query.all()}
    queue_items = []
    for feedback in query.order_by(Feedback.id.desc()).all():
        teacher = db.session.get(Teacher, feedback.teacher_id)
        teacher_name = teacher.name if teacher else "N/A"
        summary_positive_bullets = []
        summary_actionable_bullets = []
        summary_note = None

        if feedback.category == "teacher" and feedback.teacher_id:
            teacher_summary = db.session.get(TeacherSummary, feedback.teacher_id)
            if teacher_summary:
                summary_positive_bullets = get_summary_bullets(teacher_summary, True)
                summary_actionable_bullets = get_summary_bullets(teacher_summary, False)
            else:
                summary_note = "Summary not yet generated."

        elif feedback.category != "teacher":
            category_summary = db.session.get(CategorySummary, feedback.category)
            if category_summary:
                summary_positive_bullets = get_summary_bullets(category_summary, True)
                summary_actionable_bullets = get_summary_bullets(category_summary, False)
            else:
                summary_note = "Summary not yet generated."

        queue_items.append(
            {
                "id": feedback.id,
                "teacher_name": teacher_name,
                "category": feedback.category,
                "category_title": category_lookup.get(feedback.category, feedback.category),
                "feedback_text": feedback.feedback_text,
                "context_detail": feedback.context_detail,
                "toxicity_score": feedback.toxicity_score,
                "status": feedback.status,
                "summary_positive_bullets": summary_positive_bullets,
                "summary_actionable_bullets": summary_actionable_bullets,
                "summary_note": summary_note,
                "is_inappropriate": feedback.is_inappropriate,
                "is_summary_approved": feedback.is_summary_approved,
            }
        )
    return jsonify(queue_items)


@bp.route("/api/admin/category_summaries", methods=["GET"])
@auth_required(role="stuco_admin")
def get_category_summaries():
    try:
        summaries = CategorySummary.query.all()
        category_lookup = {c.slug: c.title for c in Category.query.all()}
        summary_data = []
        for summary in summaries:
            positive_bullets = get_summary_bullets(summary, True)
            actionable_bullets = get_summary_bullets(summary, False)
            summary_data.append(
                {
                    "category_name": summary.category_name,
                    "category_title": category_lookup.get(
                        summary.category_name, summary.category_name
                    ),
                    "positive_bullets": positive_bullets,
                    "actionable_bullets": actionable_bullets,
                    "positive_summary": render_bullets_html(positive_bullets),
                    "actionable_summary": render_bullets_html(actionable_bullets),
                    "last_updated": summary.last_updated.isoformat(),
                }
            )
        return jsonify(summary_data)
    except Exception as exc:
        print(f"ERROR fetching category summaries: {exc}")
        return jsonify({"error": "Could not fetch category summaries."}), 500


@bp.route("/api/admin/categories", methods=["GET", "POST"])
@auth_required(role="stuco_admin")
def admin_categories():
    if request.method == "GET":
        categories = Category.query.order_by(Category.sort_order, Category.title).all()
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
                for c in categories
            ]
        )

    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "Invalid or missing JSON body."}), 400

    title = (data.get("title") or "").strip()
    slug = normalize_slug(data.get("slug") or title)
    if not title or not slug:
        return jsonify({"error": "Title and slug are required."}), 400
    if Category.query.filter_by(slug=slug).first():
        return jsonify({"error": "Category slug already exists."}), 409

    try:
        sort_order = int(data.get("sort_order") or 0)
    except (TypeError, ValueError):
        sort_order = 0

    category = Category(
        slug=slug,
        title=title,
        description=(data.get("description") or "").strip(),
        icon=(data.get("icon") or "").strip(),
        context_label=(data.get("context_label") or "").strip(),
        requires_teacher=bool(data.get("requires_teacher")),
        is_active=bool(data.get("is_active", True)),
        sort_order=sort_order,
    )
    db.session.add(category)
    db.session.flush()
    log_audit("category_created", "category", category.id, details={"slug": slug})
    db.session.commit()
    return jsonify({"message": "Category created.", "id": category.id}), 201


@bp.route("/api/admin/categories/<int:category_id>", methods=["PUT", "DELETE"])
@auth_required(role="stuco_admin")
def admin_category_detail(category_id):
    category = db.session.get(Category, category_id)
    if not category:
        return jsonify({"error": "Category not found."}), 404

    if request.method == "DELETE":
        if Feedback.query.filter_by(category=category.slug).first():
            return jsonify({"error": "Category has feedback attached. Deactivate instead."}), 400
        db.session.delete(category)
        log_audit("category_deleted", "category", category_id, details={"slug": category.slug})
        db.session.commit()
        return jsonify({"message": "Category deleted."}), 200

    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "Invalid or missing JSON body."}), 400

    category.title = (data.get("title") or category.title).strip()
    category.description = (data.get("description") or category.description or "").strip()
    category.icon = (data.get("icon") or category.icon or "").strip()
    category.context_label = (data.get("context_label") or category.context_label or "").strip()
    if data.get("requires_teacher") is not None:
        category.requires_teacher = bool(data.get("requires_teacher"))
    if data.get("is_active") is not None:
        category.is_active = bool(data.get("is_active"))
    if data.get("sort_order") is not None:
        try:
            category.sort_order = int(data.get("sort_order") or 0)
        except (TypeError, ValueError):
            category.sort_order = 0

    log_audit("category_updated", "category", category_id, details={"slug": category.slug})
    db.session.commit()
    return jsonify({"message": "Category updated."}), 200


@bp.route("/api/admin/teachers", methods=["GET", "POST"])
@auth_required(role="stuco_admin")
def admin_teachers():
    if request.method == "GET":
        teachers = Teacher.query.order_by(Teacher.name).all()
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
                    "user_email": db.session.get(User, t.user_id).email if t.user_id else None,
                }
                for t in teachers
            ]
        )

    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "Invalid or missing JSON body."}), 400
    name = (data.get("name") or "").strip()
    email = normalize_email(data.get("email") or "")
    if not name or not email:
        return jsonify({"error": "Name and email are required."}), 400
    if not is_valid_email(email):
        return jsonify({"error": "Invalid email address."}), 400
    existing = Teacher.query.filter_by(email=email).first()
    if existing:
        return jsonify({"error": "Teacher with this email already exists."}), 409

    teacher = Teacher(
        name=name,
        email=email,
        year_6=bool(data.get("year_6")),
        year_7=bool(data.get("year_7")),
        year_8=bool(data.get("year_8")),
        is_active=bool(data.get("is_active", True)),
    )
    user = User.query.filter_by(email=email).first()
    if user and user.role == "teacher":
        teacher.user_id = user.id
    db.session.add(teacher)
    db.session.flush()
    log_audit("teacher_created", "teacher", teacher.id, details={"email": email})
    db.session.commit()
    return jsonify({"message": "Teacher created.", "id": teacher.id}), 201


@bp.route("/api/admin/teachers/<int:teacher_id>", methods=["PUT"])
@auth_required(role="stuco_admin")
def admin_teacher_detail(teacher_id):
    teacher = db.session.get(Teacher, teacher_id)
    if not teacher:
        return jsonify({"error": "Teacher not found."}), 404

    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "Invalid or missing JSON body."}), 400

    if data.get("name") is not None:
        teacher.name = (data.get("name") or teacher.name).strip()
    if data.get("email") is not None:
        email = normalize_email(data.get("email") or "")
        if not is_valid_email(email):
            return jsonify({"error": "Invalid email address."}), 400
        duplicate = Teacher.query.filter(Teacher.email == email, Teacher.id != teacher_id).first()
        if duplicate:
            return jsonify({"error": "Another teacher already uses this email."}), 409
        teacher.email = email
    if data.get("year_6") is not None:
        teacher.year_6 = bool(data.get("year_6"))
    if data.get("year_7") is not None:
        teacher.year_7 = bool(data.get("year_7"))
    if data.get("year_8") is not None:
        teacher.year_8 = bool(data.get("year_8"))
    if data.get("is_active") is not None:
        teacher.is_active = bool(data.get("is_active"))

    if "user_email" in data:
        user_email = normalize_email(data.get("user_email") or "")
        if not user_email:
            teacher.user_id = None
        else:
            user = User.query.filter_by(email=user_email).first()
            if not user:
                return jsonify({"error": "User not found for linking."}), 404
            if user.role != "teacher":
                return jsonify({"error": "User is not a teacher role."}), 400
            linked = Teacher.query.filter(
                Teacher.user_id == user.id, Teacher.id != teacher_id
            ).first()
            if linked:
                return jsonify({"error": "User already linked to another teacher profile."}), 409
            teacher.user_id = user.id

    log_audit("teacher_updated", "teacher", teacher_id, details={"email": teacher.email})
    db.session.commit()
    return jsonify({"message": "Teacher updated."}), 200


@bp.route("/api/admin/announcements", methods=["GET", "POST"])
@auth_required(role="stuco_admin")
def admin_announcements():
    if request.method == "GET":
        announcements = Announcement.query.order_by(Announcement.created_at.desc()).all()
        return jsonify(
            [
                {
                    "id": a.id,
                    "title": a.title,
                    "body": a.body,
                    "audience": a.audience,
                    "is_active": a.is_active,
                    "created_at": a.created_at.isoformat(),
                    "updated_at": a.updated_at.isoformat(),
                }
                for a in announcements
            ]
        )

    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "Invalid or missing JSON body."}), 400
    title = (data.get("title") or "").strip()
    body = (data.get("body") or "").strip()
    if not title or not body:
        return jsonify({"error": "Title and body are required."}), 400
    audience = (data.get("audience") or "all").strip().lower()
    if audience not in {"all", "student", "teacher"}:
        return jsonify({"error": "Invalid audience."}), 400

    announcement = Announcement(
        title=title,
        body=body,
        audience=audience,
        is_active=bool(data.get("is_active", True)),
        created_by_user_id=g.user.id,
    )
    db.session.add(announcement)
    db.session.flush()
    log_audit(
        "announcement_created", "announcement", announcement.id, details={"audience": audience}
    )
    db.session.commit()
    return jsonify({"message": "Announcement created.", "id": announcement.id}), 201


@bp.route("/api/admin/announcements/<int:announcement_id>", methods=["PUT", "DELETE"])
@auth_required(role="stuco_admin")
def admin_announcement_detail(announcement_id):
    announcement = db.session.get(Announcement, announcement_id)
    if not announcement:
        return jsonify({"error": "Announcement not found."}), 404

    if request.method == "DELETE":
        db.session.delete(announcement)
        log_audit("announcement_deleted", "announcement", announcement_id)
        db.session.commit()
        return jsonify({"message": "Announcement deleted."}), 200

    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "Invalid or missing JSON body."}), 400
    if data.get("title") is not None:
        announcement.title = (data.get("title") or announcement.title).strip()
    if data.get("body") is not None:
        announcement.body = (data.get("body") or announcement.body).strip()
    if data.get("audience") is not None:
        audience = (data.get("audience") or announcement.audience).strip().lower()
        if audience not in {"all", "student", "teacher"}:
            return jsonify({"error": "Invalid audience."}), 400
        announcement.audience = audience
    if data.get("is_active") is not None:
        announcement.is_active = bool(data.get("is_active"))

    log_audit(
        "announcement_updated", "announcement", announcement_id, details={"audience": announcement.audience}
    )
    db.session.commit()
    return jsonify({"message": "Announcement updated."}), 200


@bp.route("/api/admin/audit_logs", methods=["GET"])
@auth_required(role="stuco_admin")
def admin_audit_logs():
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
                "actor_name": db.session.get(User, log.actor_user_id).name
                if log.actor_user_id
                else None,
                "action": log.action,
                "target_type": log.target_type,
                "target_id": log.target_id,
                "details": log.details,
                "created_at": log.created_at.isoformat(),
            }
            for log in logs
        ]
    )


@bp.route("/api/admin/feedback/<int:feedback_id>/approve", methods=["PUT"])
@auth_required(role="stuco_admin")
def approve_feedback_summary(feedback_id):
    feedback_item = db.session.get(Feedback, feedback_id)
    if not feedback_item:
        return jsonify({"error": "Feedback not found."}), 404
    old_status = feedback_item.status
    feedback_item.is_summary_approved = True
    feedback_item.status = "Approved"

    job_type = "teacher" if feedback_item.category == "teacher" else "category"
    target_id = str(feedback_item.teacher_id) if job_type == "teacher" else feedback_item.category

    job = SummaryJobQueue(job_type=job_type, target_id=target_id, feedback_id=feedback_item.id)
    db.session.add(job)
    record_feedback_status(
        feedback_item.id,
        old_status,
        feedback_item.status,
        g.user.id,
        note="Admin approved feedback",
    )
    log_audit(
        "feedback_approved",
        "feedback",
        feedback_item.id,
        details={"previous_status": old_status, "new_status": feedback_item.status},
    )
    db.session.commit()
    return jsonify(
        {
            "message": f"Feedback ID {feedback_id} re-approved. Summary regenerating in background."
        }
    )


@bp.route("/api/admin/feedback/<int:feedback_id>/retract", methods=["PUT"])
@auth_required(role="stuco_admin")
def retract_feedback_summary(feedback_id):
    feedback_item = db.session.get(Feedback, feedback_id)
    if not feedback_item:
        return jsonify({"error": "Feedback not found."}), 404
    old_status = feedback_item.status
    feedback_item.is_summary_approved = False
    feedback_item.status = "Retracted by Admin"

    job_type = "teacher" if feedback_item.category == "teacher" else "category"
    target_id = str(feedback_item.teacher_id) if job_type == "teacher" else feedback_item.category

    job = SummaryJobQueue(job_type=job_type, target_id=target_id, feedback_id=feedback_item.id)
    db.session.add(job)
    record_feedback_status(
        feedback_item.id,
        old_status,
        feedback_item.status,
        g.user.id,
        note="Admin retracted feedback",
    )
    log_audit(
        "feedback_retracted",
        "feedback",
        feedback_item.id,
        details={"previous_status": old_status, "new_status": feedback_item.status},
    )
    db.session.commit()
    return jsonify(
        {
            "message": f"Feedback ID {feedback_id} retracted. Summary regenerating in background."
        }
    )


@bp.route("/api/admin/feedback/<int:feedback_id>/delete", methods=["DELETE"])
@auth_required(role="stuco_admin")
def delete_feedback(feedback_id):
    try:
        feedback_item = db.session.get(Feedback, feedback_id)
        if not feedback_item:
            return jsonify({"error": "Feedback not found."}), 404
        old_status = feedback_item.status

        job_type = "teacher" if feedback_item.category == "teacher" else "category"
        target_id = str(feedback_item.teacher_id) if job_type == "teacher" else feedback_item.category

        SummaryJobQueue.query.filter_by(feedback_id=feedback_id).delete()

        record_feedback_status(
            feedback_item.id,
            old_status,
            "Deleted",
            g.user.id,
            note="Admin deleted feedback",
        )
        log_audit("feedback_deleted", "feedback", feedback_item.id, details={"previous_status": old_status})
        db.session.delete(feedback_item)
        db.session.commit()

        job = SummaryJobQueue(job_type=job_type, target_id=target_id, feedback_id=None, status="pending")
        db.session.add(job)
        db.session.commit()

        return jsonify({"message": f"Feedback ID {feedback_id} permanently deleted."}), 200
    except Exception as exc:
        db.session.rollback()
        print(f"ERROR: Delete feedback failed. {exc}")
        return jsonify({"error": f"An error occurred during deletion: {exc}"}), 500


@bp.route("/api/admin/clarification_requests", methods=["GET"])
@auth_required(role="stuco_admin")
def get_clarification_queue():
    status_filter = request.args.get("status", "pending")
    query = ClarificationRequest.query.filter_by(status=status_filter)

    queue_items = []
    for req in query.order_by(ClarificationRequest.requested_on.desc()).all():
        teacher = db.session.get(Teacher, req.teacher_id)
        teacher_name = teacher.name if teacher else "Unknown"
        queue_items.append(
            {
                "id": req.id,
                "teacher_name": teacher_name,
                "question_text": req.question_text,
                "status": req.status,
                "admin_reply": req.admin_reply,
                "requested_on": req.requested_on.isoformat(),
            }
        )
    return jsonify(queue_items)


@bp.route("/api/admin/clarification/<int:request_id>/reply", methods=["POST"])
@auth_required(role="stuco_admin")
def reply_to_clarification(request_id):
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "Invalid or missing JSON body."}), 400
    reply_text = data.get("reply_text")

    if not reply_text:
        return jsonify({"error": "Reply text is required."}), 400

    clarification_req = db.session.get(ClarificationRequest, request_id)
    if not clarification_req:
        return jsonify({"error": "Clarification request not found."}), 404

    try:
        clarification_req.admin_reply = reply_text
        clarification_req.status = "resolved"
        log_audit(
            "clarification_replied",
            "clarification_request",
            clarification_req.id,
            details={"teacher_id": clarification_req.teacher_id},
        )
        db.session.commit()
        return jsonify({"message": "Reply sent and request resolved."}), 200
    except Exception as exc:
        db.session.rollback()
        print(f"ERROR replying to clarification: {exc}")
        return jsonify({"error": "Internal server error."}), 500


@bp.route("/api/admin/reset_database", methods=["POST"])
@auth_required(role="stuco_admin")
def reset_database():
    try:
        print("INFO: Admin triggered database reset.")

        print("WORKER: Sending stop signal...")
        stop_worker_thread()
        print("WORKER: Worker thread stopped.")

        db.drop_all()
        db.create_all()
        ensure_schema_updates()
        seed_data()
        log_audit("database_reset", "database", "all", details={"action": "reset"})
        db.session.commit()

        print("INFO: Database reset and re-seed successful.")

    finally:
        if current_app.config.get("ENABLE_WORKER") and start_worker_thread(
            current_app._get_current_object()
        ):
            print("WORKER: Worker thread has been restarted.")

    return jsonify({"message": "Database has been successfully reset."}), 200
