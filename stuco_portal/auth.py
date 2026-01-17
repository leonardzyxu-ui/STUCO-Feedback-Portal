import re
from functools import wraps

from flask import current_app, g, jsonify, request, session

from .extensions import db
from .models import Teacher, User

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
        "role": user.role,
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
            allow_mock = current_app.config.get("ALLOW_MOCK_AUTH", False)
            if not user and allow_mock:
                mock_user_id = request.args.get("mock_user_id") or request.headers.get(
                    "X-Mock-User-Id"
                )
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
                return (
                    jsonify({"error": f"Access denied. Required role: {role}"}),
                    403,
                )

            g.user = user
            g.teacher_profile = None
            if user.role in ["teacher", "stuco_admin"]:
                g.teacher_profile = Teacher.query.filter_by(user_id=user.id).first()
                if not g.teacher_profile and user.role == "teacher":
                    return jsonify({"error": "Teacher profile not found."}), 403

            return f(*args, **kwargs)

        return decorated_function

    return wrapper
