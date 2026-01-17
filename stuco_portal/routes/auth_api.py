from uuid import uuid4

from flask import Blueprint, current_app, jsonify, request, session
from werkzeug.security import check_password_hash, generate_password_hash

from ..auth import build_user_payload, is_valid_email, normalize_email, resolve_session_user
from ..extensions import db
from ..models import Teacher, User

bp = Blueprint("auth_api", __name__)


@bp.route("/api/auth/register", methods=["POST"])
def register_user():
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "Invalid or missing JSON body."}), 400

    name = (data.get("name") or "").strip()
    email = normalize_email(data.get("email") or "")
    password = data.get("password") or ""
    requested_role = (data.get("role") or "student").strip().lower()
    invite_code = (data.get("invite_code") or "").strip()
    year_levels = data.get("year_levels") or []

    if not name or not email or not password:
        return jsonify({"error": "Name, email, and password are required."}), 400
    if not is_valid_email(email):
        return jsonify({"error": "Please enter a valid email address."}), 400
    if len(password) < 8:
        return jsonify({"error": "Password must be at least 8 characters."}), 400

    if User.query.filter_by(email=email).first():
        return jsonify({"error": "An account with this email already exists."}), 409

    role = "student"
    teacher_invite = current_app.config.get("TEACHER_INVITE_CODE")
    admin_invite = current_app.config.get("ADMIN_INVITE_CODE")
    student_signup_enabled = current_app.config.get("STUDENT_SIGNUP_ENABLED", True)
    if invite_code:
        if admin_invite and invite_code == admin_invite:
            role = "stuco_admin"
        elif teacher_invite and invite_code == teacher_invite:
            role = "teacher"
        else:
            return jsonify({"error": "Invalid invite code."}), 403
    elif requested_role in {"teacher", "stuco_admin"}:
        return jsonify({"error": "Invite code required for this role."}), 403
    elif not student_signup_enabled:
        return jsonify({"error": "Student signups are currently disabled."}), 403

    year_level_flags = {"year_6": False, "year_7": False, "year_8": False}
    if isinstance(year_levels, str):
        year_levels = [item.strip() for item in year_levels.split(",") if item.strip()]
    if isinstance(year_levels, list):
        for level in year_levels:
            if level == "Year 6":
                year_level_flags["year_6"] = True
            elif level == "Year 7":
                year_level_flags["year_7"] = True
            elif level == "Year 8":
                year_level_flags["year_8"] = True

    if role == "teacher" and not any(year_level_flags.values()):
        return jsonify({"error": "Select at least one year level for teacher accounts."}), 400

    user = User(
        azure_oid=f"local:{uuid4()}",
        email=email,
        name=name,
        role=role,
        password_hash=generate_password_hash(password),
    )
    db.session.add(user)
    db.session.flush()

    teacher_profile = None
    if role == "teacher":
        teacher_profile = Teacher.query.filter_by(email=email).first()
        if teacher_profile:
            if teacher_profile.user_id:
                db.session.rollback()
                return jsonify({"error": "Teacher profile already linked to an account."}), 409
            teacher_profile.user_id = user.id
            teacher_profile.name = name
            teacher_profile.year_6 = year_level_flags["year_6"]
            teacher_profile.year_7 = year_level_flags["year_7"]
            teacher_profile.year_8 = year_level_flags["year_8"]
        else:
            teacher_profile = Teacher(
                user_id=user.id,
                name=name,
                email=email,
                year_6=year_level_flags["year_6"],
                year_7=year_level_flags["year_7"],
                year_8=year_level_flags["year_8"],
            )
            db.session.add(teacher_profile)

    db.session.commit()
    session["user_id"] = user.id

    return (
        jsonify({"message": "Account created successfully.", "user": build_user_payload(user, teacher_profile)}),
        201,
    )


@bp.route("/api/auth/login", methods=["POST"])
def login_user():
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "Invalid or missing JSON body."}), 400

    email = normalize_email(data.get("email") or "")
    password = data.get("password") or ""
    if not email or not password:
        return jsonify({"error": "Email and password are required."}), 400

    user = User.query.filter_by(email=email).first()
    if not user or not user.password_hash or not check_password_hash(user.password_hash, password):
        return jsonify({"error": "Invalid email or password."}), 401
    if user.is_active is False:
        return jsonify({"error": "Account disabled. Contact an administrator."}), 403

    session["user_id"] = user.id
    user.last_login_at = db.func.now()
    db.session.commit()

    teacher_profile = None
    if user.role == "teacher":
        teacher_profile = Teacher.query.filter_by(user_id=user.id).first()

    return (
        jsonify({"message": "Login successful.", "user": build_user_payload(user, teacher_profile)}),
        200,
    )


@bp.route("/api/auth/logout", methods=["POST"])
def logout_user():
    session.pop("user_id", None)
    return jsonify({"message": "Logged out successfully."}), 200


@bp.route("/api/auth/me", methods=["GET"])
def get_current_user():
    user = resolve_session_user()
    if not user:
        return jsonify({"error": "Authentication required."}), 401

    teacher_profile = None
    if user.role == "teacher":
        teacher_profile = Teacher.query.filter_by(user_id=user.id).first()

    return jsonify({"user": build_user_payload(user, teacher_profile)}), 200
