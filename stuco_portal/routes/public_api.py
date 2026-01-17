from flask import Blueprint, jsonify, request

from ..models import Announcement, Category

bp = Blueprint("public_api", __name__)


@bp.route("/api/categories", methods=["GET"])
def get_categories():
    include_inactive = request.args.get("include_inactive", "0").lower() in {
        "1",
        "true",
        "yes",
    }
    query = Category.query
    if not include_inactive:
        query = query.filter(Category.is_active.is_(True))
    categories = query.order_by(Category.sort_order, Category.title).all()
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


@bp.route("/api/announcements", methods=["GET"])
def get_announcements():
    audience = (request.args.get("audience") or "all").strip().lower()
    limit = request.args.get("limit")
    query = Announcement.query.filter(Announcement.is_active.is_(True))
    if audience in {"student", "teacher"}:
        query = query.filter(Announcement.audience.in_(["all", audience]))
    elif audience != "all":
        query = query.filter(Announcement.audience == "all")
    query = query.order_by(Announcement.created_at.desc())
    if limit:
        try:
            limit_val = max(1, min(int(limit), 20))
        except ValueError:
            limit_val = 5
        query = query.limit(limit_val)
    announcements = query.all()
    return jsonify(
        [
            {
                "id": a.id,
                "title": a.title,
                "body": a.body,
                "audience": a.audience,
                "created_at": a.created_at.isoformat(),
                "updated_at": a.updated_at.isoformat(),
            }
            for a in announcements
        ]
    )
