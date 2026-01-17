from collections import defaultdict

from flask import Blueprint, jsonify, request, g

from ..auth import auth_required
from ..extensions import db
from ..models import Category, Feedback, FeedbackStatusHistory, SummaryJobQueue, Teacher
from ..services.ai.moderation import run_toxicity_check
from ..services.audit import record_feedback_status

bp = Blueprint("student_api", __name__)


@bp.route("/api/teachers", methods=["GET"])
def get_teachers():
    year_level = request.args.get("year_level")
    query = Teacher.query.filter(Teacher.is_active.is_(True))
    if year_level == "Year 6":
        query = query.filter(Teacher.year_6.is_(True))
    elif year_level == "Year 7":
        query = query.filter(Teacher.year_7.is_(True))
    elif year_level == "Year 8":
        query = query.filter(Teacher.year_8.is_(True))
    teachers_list = [
        {"id": t.id, "name": t.name, "email": t.email} for t in query.all()
    ]
    return jsonify(teachers_list)


@bp.route("/api/submit_feedback", methods=["POST"])
@auth_required(role="student")
def submit_feedback():
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "Invalid or missing JSON body."}), 400

    feedback_text = data.get("feedback_text")
    category = (data.get("category") or "").strip().lower()
    teacher_id = data.get("teacher_id")
    year_level = data.get("year_level")
    willing_to_share_name = data.get("willing_to_share_name", False)
    context_detail = data.get("context_detail")

    if not feedback_text or not category:
        return jsonify({"error": "Missing required fields."}), 400
    category_record = Category.query.filter_by(slug=category, is_active=True).first()
    if not category_record:
        return jsonify({"error": "Invalid or inactive category."}), 400
    if len(feedback_text) > 2000:
        return jsonify({"error": "Feedback text exceeds 2000 characters."}), 400
    if context_detail and len(context_detail) > 255:
        return jsonify({"error": "Context detail exceeds 255 characters."}), 400

    teacher_id_int = None
    if category_record.requires_teacher:
        if not teacher_id:
            return jsonify({"error": "Teacher feedback requires a teacher_id."}), 400
        try:
            teacher_id_int = int(teacher_id)
        except ValueError:
            return jsonify({"error": "Invalid teacher ID format."}), 400
        teacher_profile = db.session.get(Teacher, teacher_id_int)
        if not teacher_profile or not teacher_profile.is_active:
            return jsonify({"error": "Teacher not found."}), 400

    try:
        screening = run_toxicity_check(feedback_text)
        is_inappropriate = screening["is_inappropriate"]

        new_feedback = Feedback(
            submitted_by_user_id=g.user.id,
            feedback_text=feedback_text,
            category=category_record.slug,
            teacher_id=teacher_id_int,
            year_level_submitted=year_level,
            context_detail=context_detail,
            willing_to_share_name=willing_to_share_name,
            toxicity_score=screening["toxicity_score"],
            is_inappropriate=is_inappropriate,
            status="New",
            is_summary_approved=False,
            rating_clarity=data.get("rating_clarity"),
            rating_pacing=data.get("rating_pacing"),
            rating_resources=data.get("rating_resources"),
            rating_support=data.get("rating_support"),
        )

        if is_inappropriate:
            new_feedback.status = "Screened - Escalation"
        else:
            new_feedback.status = "Approved"
            new_feedback.is_summary_approved = True

        db.session.add(new_feedback)
        db.session.flush()
        record_feedback_status(new_feedback.id, None, new_feedback.status, g.user.id)

        if not is_inappropriate:
            job_type = "teacher" if category_record.requires_teacher else "category"
            target_id = str(teacher_id_int) if job_type == "teacher" else category_record.slug

            print(f"API: Adding '{job_type}' summary job for target '{target_id}'.")
            job = SummaryJobQueue(
                job_type=job_type, target_id=target_id, feedback_id=new_feedback.id
            )
            db.session.add(job)
        db.session.commit()

        return (
            jsonify(
                {
                    "message": f"Feedback submitted successfully. Status: {new_feedback.status}",
                    "id": new_feedback.id,
                    "status": new_feedback.status,
                }
            ),
            201,
        )

    except Exception as exc:
        db.session.rollback()
        print(f"Error submitting feedback: {exc}")
        return jsonify({"error": "Internal server error during submission."}), 500


@bp.route("/api/student/feedback", methods=["GET"])
@auth_required(role="student")
def get_student_feedback():
    status_filter = request.args.get("status")
    query = Feedback.query.filter_by(submitted_by_user_id=g.user.id)
    if status_filter:
        query = query.filter(Feedback.status == status_filter)

    feedback_items = query.order_by(Feedback.id.desc()).all()
    feedback_ids = [item.id for item in feedback_items]
    history_map = defaultdict(list)
    if feedback_ids:
        history_entries = (
            FeedbackStatusHistory.query.filter(
                FeedbackStatusHistory.feedback_id.in_(feedback_ids)
            )
            .order_by(FeedbackStatusHistory.changed_at.asc())
            .all()
        )
        for entry in history_entries:
            history_map[entry.feedback_id].append(
                {
                    "old_status": entry.old_status,
                    "new_status": entry.new_status,
                    "changed_at": entry.changed_at.isoformat(),
                    "note": entry.note,
                }
            )
    results = []
    for item in feedback_items:
        teacher_name = None
        if item.teacher_id:
            teacher = db.session.get(Teacher, item.teacher_id)
            teacher_name = teacher.name if teacher else None
        results.append(
            {
                "id": item.id,
                "category": item.category,
                "status": item.status,
                "teacher_name": teacher_name,
                "context_detail": item.context_detail,
                "year_level": item.year_level_submitted,
                "created_at": item.created_at.isoformat() if item.created_at else None,
                "status_history": history_map.get(item.id, []),
            }
        )
    return jsonify(results)
