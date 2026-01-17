from flask import Blueprint, render_template

bp = Blueprint("pages", __name__)


@bp.route("/", methods=["GET"])
def index():
    return render_template("home.html")


@bp.route("/auth.html", methods=["GET"])
def auth_page():
    return render_template("auth.html")


@bp.route("/feedback", methods=["GET"])
def feedback_portal():
    return render_template("stu_frontend.html")


@bp.route("/student_dashboard", methods=["GET"])
def student_dashboard():
    return render_template("student_dashboard.html")


@bp.route("/teach_frontend.html", methods=["GET"])
def teacher_dashboard():
    return render_template("teach_frontend.html")


@bp.route("/stuco_admin_dashboard.html", methods=["GET"])
def stuco_admin_dashboard():
    return render_template("stuco_admin_dashboard.html")


@bp.route("/documentation.html", methods=["GET"])
def documentation_page():
    return render_template("documentation.html")


@bp.route("/monthly_digest.html", methods=["GET"])
def monthly_digest_page():
    return render_template("monthly_digest.html")
