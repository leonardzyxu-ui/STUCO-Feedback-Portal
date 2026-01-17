from datetime import date

from flask import Blueprint, jsonify, g

from ..auth import auth_required
from ..models import MonthlyDigest
from ..services.ai.summaries import (
    get_month_date_range,
    is_last_day_of_month,
    month_key_for_date,
    run_monthly_digest,
)

bp = Blueprint("digest_api", __name__)


@bp.route("/api/monthly_digest", methods=["GET"])
@auth_required()
def get_monthly_digest():
    if g.user.role not in {"teacher", "stuco_admin"}:
        return jsonify({"error": "Access is limited to teachers and STUCO admins."}), 403

    today = date.today()
    current_key = month_key_for_date(today)
    start_date, end_date = get_month_date_range(today)
    is_last_day = is_last_day_of_month(today)

    digest = MonthlyDigest.query.filter_by(month_key=current_key).first()
    status_message = ""
    note = ""

    if is_last_day and not digest:
        digest = run_monthly_digest(today)
        status_message = "New digest generated for month end."

    if not digest:
        digest = MonthlyDigest.query.order_by(MonthlyDigest.month_key.desc()).first()
        if not digest:
            return jsonify(
                {
                    "title": f"Monthly digest: {current_key}",
                    "coverage": f"{start_date.isoformat()} to {end_date.isoformat()}",
                    "generated_at": None,
                    "feedback_count": 0,
                    "positive_bullets": [],
                    "actionable_bullets": [],
                    "status_message": "Monthly digest will generate on the last day of the month.",
                    "next_run": end_date.isoformat(),
                    "note": "No digest is available yet.",
                }
            ), 200
        status_message = "Showing the most recent digest on file."
        note = "The next digest will be generated on the last day of the current month."
    else:
        if digest.month_key != current_key:
            status_message = "Showing the most recent digest on file."
        elif not is_last_day:
            status_message = "Digest generated at the last month end."

    generated_at = digest.generated_at.isoformat() if digest.generated_at else None
    coverage = f"{digest.start_date.isoformat()} to {digest.end_date.isoformat()}"

    return jsonify(
        {
            "title": f"Monthly digest: {digest.month_key}",
            "coverage": coverage,
            "generated_at": generated_at,
            "feedback_count": digest.feedback_count or 0,
            "positive_bullets": digest.positive_bullets or [],
            "actionable_bullets": digest.actionable_bullets or [],
            "status_message": status_message,
            "next_run": end_date.isoformat(),
            "note": note,
        }
    ), 200
