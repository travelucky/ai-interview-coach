import os
import secrets
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / '.env')


def _default_database_uri():
    instance_dir = BASE_DIR / 'instance'
    return 'sqlite:///' + str(instance_dir / 'interview.db')


def _env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in ('1', 'true', 'yes', 'on')


class Config:
    SECRET_KEY = os.environ.get('FLASK_SECRET_KEY') or secrets.token_hex(32)
    SECRET_KEY_IS_EPHEMERAL = not bool(os.environ.get('FLASK_SECRET_KEY'))

    SQLALCHEMY_DATABASE_URI = (
        os.environ.get('DATABASE_URL')
        or os.environ.get('DATABASE_URI')  # Backward-compatible alias.
        or _default_database_uri()
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ECHO = False

    DEFAULT_PAGE_SIZE = 20
    MAX_PAGE_SIZE = 100
    QUESTIONS_PER_SESSION = max(1, int(os.environ.get('QUESTIONS_PER_SESSION', '5')))
    MIN_INTERVIEW_COMPLETION_RATIO = min(
        1.0,
        max(0.1, float(os.environ.get('MIN_INTERVIEW_COMPLETION_RATIO', '0.6'))),
    )

    LLM_API_KEY = os.environ.get('LLM_API_KEY', '').strip()
    LLM_API_BASE = os.environ.get('LLM_API_BASE', 'https://api.openai.com/v1').strip()
    LLM_MODEL = os.environ.get('LLM_MODEL', 'gpt-4o-mini').strip()
    LLM_TIMEOUT_SECONDS = max(1, int(os.environ.get('LLM_TIMEOUT_SECONDS', '30')))

    EMBEDDING_API_KEY = os.environ.get('EMBEDDING_API_KEY', '').strip()
    EMBEDDING_BASE_URL = os.environ.get('EMBEDDING_BASE_URL', '').strip()
    EMBEDDING_MODEL = os.environ.get('EMBEDDING_MODEL', '').strip()
    EMBEDDING_TIMEOUT_SECONDS = max(
        1, int(os.environ.get('EMBEDDING_TIMEOUT_SECONDS', '30'))
    )
    EMBEDDING_BATCH_SIZE = max(
        1, min(64, int(os.environ.get('EMBEDDING_BATCH_SIZE', '32')))
    )
    RAG_MIN_RELEVANCE = min(
        1.0, max(0.0, float(os.environ.get('RAG_MIN_RELEVANCE', '0.25')))
    )
    RAG_MIN_SEMANTIC_SIMILARITY = min(
        1.0,
        max(0.0, float(os.environ.get('RAG_MIN_SEMANTIC_SIMILARITY', '0.52'))),
    )

    XFYUN_APP_ID = os.environ.get('XFYUN_APP_ID', '').strip()
    XFYUN_API_KEY = os.environ.get('XFYUN_API_KEY', '').strip()
    XFYUN_API_SECRET = os.environ.get('XFYUN_API_SECRET', '').strip()
    ASR_TIMEOUT_SECONDS = max(10, int(os.environ.get('ASR_TIMEOUT_SECONDS', '20')))
    ASR_MAX_AUDIO_BYTES = max(100000, int(os.environ.get('ASR_MAX_AUDIO_BYTES', '4000000')))
    ASR_MAX_DURATION_SECONDS = min(
        60,
        max(5, int(os.environ.get('ASR_MAX_DURATION_SECONDS', '60'))),
    )
    ASR_RECEIPT_MAX_AGE_SECONDS = max(
        60, int(os.environ.get('ASR_RECEIPT_MAX_AGE_SECONDS', '900'))
    )

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    SESSION_COOKIE_SECURE = False
    PERMANENT_SESSION_LIFETIME = timedelta(hours=12)
    MAX_CONTENT_LENGTH = 6 * 1024 * 1024
    TRUSTED_ORIGINS = tuple(
        value.strip().rstrip('/')
        for value in os.environ.get('TRUSTED_ORIGINS', '').split(',')
        if value.strip()
    )
    LOGIN_MAX_FAILURES = max(3, int(os.environ.get('LOGIN_MAX_FAILURES', '5')))
    LOGIN_FAILURE_WINDOW_SECONDS = max(
        60, int(os.environ.get('LOGIN_FAILURE_WINDOW_SECONDS', '300'))
    )


class DevelopmentConfig(Config):
    DEBUG = _env_bool('FLASK_DEBUG', False)


class ProductionConfig(Config):
    DEBUG = False
    SESSION_COOKIE_SECURE = True


class TestingConfig(Config):
    TESTING = True
    DEBUG = False
    WTF_CSRF_ENABLED = False


config_by_name = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig,
}
