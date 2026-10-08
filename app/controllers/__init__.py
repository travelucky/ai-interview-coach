                       
from app.controllers.auth_controller import bp as auth_bp
from app.controllers.user_controller import bp as user_bp
from app.controllers.admin_controller import bp as admin_bp
from app.controllers.interview_controller import bp as interview_bp
from app.controllers.dashboard_controller import bp as dashboard_bp
from app.controllers.health_controller import bp as health_bp


def register_blueprints(app):
    app.register_blueprint(auth_bp)
    app.register_blueprint(user_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(interview_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(health_bp)
