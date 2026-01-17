from typing import Optional

from flask import Flask

from .config import AppConfig
from .extensions import init_extensions
from .routes import register_blueprints


def create_base_app(config: Optional[AppConfig] = None) -> Flask:
    config = config or AppConfig.from_env()
    app = Flask(
        __name__,
        static_folder=str(config.base_dir),
        static_url_path="/static",
        template_folder=str(config.base_dir),
    )
    app.config.update(config.to_flask_config())
    app.config["BASE_DIR"] = str(config.base_dir)
    app.extensions["app_config"] = config
    init_extensions(app)
    return app


def create_app(config: Optional[AppConfig] = None) -> Flask:
    app = create_base_app(config)
    register_blueprints(app)
    return app
