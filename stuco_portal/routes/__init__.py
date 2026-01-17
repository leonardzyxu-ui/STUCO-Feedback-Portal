from .admin_api import bp as admin_api_bp
from .ai_api import bp as ai_api_bp
from .auth_api import bp as auth_api_bp
from .pages import bp as pages_bp
from .public_api import bp as public_api_bp
from .student_api import bp as student_api_bp
from .teacher_api import bp as teacher_api_bp


def register_blueprints(app):
    app.register_blueprint(pages_bp)
    app.register_blueprint(public_api_bp)
    app.register_blueprint(auth_api_bp)
    app.register_blueprint(student_api_bp)
    app.register_blueprint(teacher_api_bp)
    app.register_blueprint(admin_api_bp)
    app.register_blueprint(ai_api_bp)
