import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(dotenv_path=BASE_DIR / ".env")


def _env_bool(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no"}


@dataclass(frozen=True)
class AppConfig:
    base_dir: Path
    database_file: str
    database_url: Optional[str]
    secret_key: str
    deepseek_api_key: Optional[str]
    deepseek_model: str
    deepseek_api_url: str
    openai_api_key: Optional[str]
    openai_model: str
    openai_api_url: str
    gemini_api_key: Optional[str]
    gemini_model: str
    gemini_api_url: str
    ai_provider: str
    ai_timeout: int
    ai_max_tokens: int
    deepthink_or_not: bool
    worker_sleep_interval: int
    browser_host: str
    host: str
    port: int
    auto_open_browser: bool
    enable_worker: bool
    student_signup_enabled: bool
    teacher_invite_code: Optional[str]
    admin_invite_code: Optional[str]
    allow_mock_auth: bool
    mcp_api_key: Optional[str]
    mcp_host: str
    mcp_port: int
    mcp_require_auth: bool
    session_cookie_secure: bool
    session_cookie_samesite: str
    session_cookie_httponly: bool

    @classmethod
    def from_env(cls):
        return cls(
            base_dir=BASE_DIR,
            database_file=os.getenv("DATABASE_FILE", "feedback.db"),
            database_url=os.getenv("DATABASE_URL"),
            secret_key=os.getenv("SECRET_KEY", "default-development-key"),
            deepseek_api_key=os.getenv("DEEPSEEK_API_KEY"),
            deepseek_model=os.getenv("DEEPSEEK_MODEL", "deepseek-v3.2"),
            deepseek_api_url=os.getenv(
                "DEEPSEEK_API_URL", "https://api.deepseek.com/chat/completions"
            ),
            openai_api_key=os.getenv("OPENAI_API_KEY"),
            openai_model=os.getenv("OPENAI_MODEL", "gpt-5.2"),
            openai_api_url=os.getenv(
                "OPENAI_API_URL", "https://api.openai.com/v1/chat/completions"
            ),
            gemini_api_key=os.getenv("GEMINI_API_KEY"),
            gemini_model=os.getenv("GEMINI_MODEL", "gemini-3-pro-preview"),
            gemini_api_url=os.getenv(
                "GEMINI_API_URL", "https://generativelanguage.googleapis.com/v1beta/models"
            ),
            ai_provider=(os.getenv("AI_PROVIDER", "deepseek") or "deepseek").lower(),
            ai_timeout=int(os.getenv("AI_TIMEOUT", "60")),
            ai_max_tokens=int(os.getenv("AI_MAX_TOKENS", "800")),
            deepthink_or_not=_env_bool("DEEPTHINK_OR_NOT", False),
            worker_sleep_interval=int(os.getenv("WORKER_SLEEP_INTERVAL", "10")),
            browser_host=os.getenv("BROWSER_HOST", "127.0.0.1"),
            host=os.getenv("HOST", "0.0.0.0"),
            port=int(os.getenv("PORT", "5001")),
            auto_open_browser=_env_bool("AUTO_OPEN_BROWSER", True),
            enable_worker=_env_bool("ENABLE_WORKER", True),
            student_signup_enabled=_env_bool("STUDENT_SIGNUP_ENABLED", True),
            teacher_invite_code=os.getenv("TEACHER_INVITE_CODE"),
            admin_invite_code=os.getenv("ADMIN_INVITE_CODE"),
            allow_mock_auth=_env_bool("ALLOW_MOCK_AUTH", True),
            mcp_api_key=os.getenv("MCP_API_KEY"),
            mcp_host=os.getenv("MCP_HOST", "127.0.0.1"),
            mcp_port=int(os.getenv("MCP_PORT", "5002")),
            mcp_require_auth=_env_bool("MCP_REQUIRE_AUTH", True),
            session_cookie_secure=_env_bool("SESSION_COOKIE_SECURE", False),
            session_cookie_samesite=os.getenv("SESSION_COOKIE_SAMESITE", "Lax"),
            session_cookie_httponly=_env_bool("SESSION_COOKIE_HTTPONLY", True),
        )

    def to_flask_config(self):
        return {
            "SECRET_KEY": self.secret_key,
            "SQLALCHEMY_DATABASE_URI": self.database_url
            or f"sqlite:///{self.database_file}",
            "SQLALCHEMY_TRACK_MODIFICATIONS": False,
            "SQLALCHEMY_ENGINE_OPTIONS": {"pool_pre_ping": True},
            "DEEPSEEK_API_KEY": self.deepseek_api_key,
            "DEEPSEEK_MODEL": self.deepseek_model,
            "DEEPSEEK_API_URL": self.deepseek_api_url,
            "OPENAI_API_KEY": self.openai_api_key,
            "OPENAI_MODEL": self.openai_model,
            "OPENAI_API_URL": self.openai_api_url,
            "GEMINI_API_KEY": self.gemini_api_key,
            "GEMINI_MODEL": self.gemini_model,
            "GEMINI_API_URL": self.gemini_api_url,
            "AI_PROVIDER": self.ai_provider,
            "AI_TIMEOUT": self.ai_timeout,
            "AI_MAX_TOKENS": self.ai_max_tokens,
            "DEEPTHINK_OR_NOT": self.deepthink_or_not,
            "WORKER_SLEEP_INTERVAL": self.worker_sleep_interval,
            "BROWSER_HOST": self.browser_host,
            "HOST": self.host,
            "PORT": self.port,
            "AUTO_OPEN_BROWSER": self.auto_open_browser,
            "ENABLE_WORKER": self.enable_worker,
            "STUDENT_SIGNUP_ENABLED": self.student_signup_enabled,
            "TEACHER_INVITE_CODE": self.teacher_invite_code,
            "ADMIN_INVITE_CODE": self.admin_invite_code,
            "ALLOW_MOCK_AUTH": self.allow_mock_auth,
            "MCP_API_KEY": self.mcp_api_key,
            "MCP_HOST": self.mcp_host,
            "MCP_PORT": self.mcp_port,
            "MCP_REQUIRE_AUTH": self.mcp_require_auth,
            "SESSION_COOKIE_SECURE": self.session_cookie_secure,
            "SESSION_COOKIE_SAMESITE": self.session_cookie_samesite,
            "SESSION_COOKIE_HTTPONLY": self.session_cookie_httponly,
        }
