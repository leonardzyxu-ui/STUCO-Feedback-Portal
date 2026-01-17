from flask import Blueprint, jsonify, request, g
from sqlalchemy import func

from ..auth import auth_required
from ..extensions import db
from ..models import ClarificationRequest, Feedback, TeacherSummary
from ..services.ai.summaries import get_summary_bullets, render_bullets_html

bp = Blueprint("teacher_api", __name__)


@bp.route("/api/teacher/stats", methods=["GET"])
@auth_required(role="teacher")
def get_teacher_stats():
    teacher_id = g.teacher_profile.id

    total_feedback = Feedback.query.filter(Feedback.teacher_id == teacher_id).count()
    approved_count = Feedback.query.filter(
        Feedback.teacher_id == teacher_id, Feedback.is_summary_approved.is_(True)
    ).count()

    trend_query = (
        db.session.query(
            func.coalesce(func.avg(Feedback.rating_pacing), 0),
            func.coalesce(func.avg(Feedback.rating_clarity), 0),
            func.coalesce(func.avg(Feedback.rating_resources), 0),
            func.coalesce(func.avg(Feedback.rating_support), 0),
        )
        .filter(
            Feedback.teacher_id == teacher_id,
            Feedback.is_inappropriate.is_(False),
            Feedback.is_summary_approved.is_(True),
        )
        .one()
    )

    trend_data_list = [
        round(trend_query[0], 1),
        round(trend_query[1], 1),
        round(trend_query[2], 1),
        round(trend_query[3], 1),
    ]

    trend_data = {"labels": ["Pacing", "Clarity", "Resources", "Support"], "data": trend_data_list}

    return jsonify(
        {
            "stats": {
                "total_feedback": total_feedback,
                "approved_summaries_count": approved_count,
                "last_check_in": "Today",
            },
            "trends": trend_data,
        }
    )


@bp.route("/api/teacher/holistic_summary", methods=["GET"])
@auth_required(role="teacher")
def get_teacher_holistic_summary():
    teacher_id = g.teacher_profile.id
    summary = db.session.get(TeacherSummary, teacher_id)
    if not summary:
        positive_bullets = ["No summaries have been generated yet."]
        actionable_bullets = ["Please check back after new feedback is submitted."]
        return jsonify(
            {
                "teacher_name": g.teacher_profile.name,
                "positive_bullets": positive_bullets,
                "actionable_bullets": actionable_bullets,
                "positive_summary": render_bullets_html(positive_bullets),
                "actionable_summary": render_bullets_html(actionable_bullets),
            }
        )
    positive_bullets = get_summary_bullets(summary, True)
    actionable_bullets = get_summary_bullets(summary, False)
    if not positive_bullets:
        positive_bullets = ["No summaries have been generated yet."]
    if not actionable_bullets:
        actionable_bullets = ["Please check back after new feedback is submitted."]
    return jsonify(
        {
            "teacher_name": g.teacher_profile.name,
            "positive_bullets": positive_bullets,
            "actionable_bullets": actionable_bullets,
            "positive_summary": render_bullets_html(positive_bullets),
            "actionable_summary": render_bullets_html(actionable_bullets),
            "last_updated": summary.last_updated.isoformat(),
        }
    )


@bp.route("/api/clarification_request", methods=["POST"])
@auth_required(role="teacher")
def create_clarification_request():
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "Invalid or missing JSON body."}), 400
    question_text = data.get("question_text")
    if not question_text:
        return jsonify({"error": "Clarification question text is required."}), 400
    new_request = ClarificationRequest(
        teacher_id=g.teacher_profile.id, question_text=question_text, status="pending"
    )
    db.session.add(new_request)
    db.session.commit()
    return jsonify({"message": "Clarification request submitted to STUCO."}), 201


@bp.route("/api/teacher/clarifications", methods=["GET"])
@auth_required(role="teacher")
def get_teacher_clarifications():
    status_filter = request.args.get("status", "pending")

    try:
        query = (
            ClarificationRequest.query.filter_by(
                teacher_id=g.teacher_profile.id, status=status_filter
            )
            .order_by(ClarificationRequest.requested_on.desc())
        )

        requests_list = []
        for req in query.all():
            requests_list.append(
                {
                    "id": req.id,
                    "question_text": req.question_text,
                    "status": req.status,
                    "admin_reply": req.admin_reply,
                    "requested_on": req.requested_on.isoformat(),
                }
            )
        return jsonify(requests_list)
    except Exception as exc:
        print(f"ERROR fetching teacher clarifications: {exc}")
        return jsonify({"error": "Could not fetch clarification history."}), 500
