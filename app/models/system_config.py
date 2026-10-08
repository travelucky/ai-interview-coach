                       
from datetime import datetime
from app import db


class ConfigKey:
    # External credentials are environment-managed. These names remain only so
    # legacy database rows can be recognized and ignored.
    LLM_API_KEY = 'llm_api_key'
    LLM_API_BASE = 'llm_api_base'
    QUESTIONS_PER_SESSION = 'questions_per_session'
    XFYUN_APPID = 'xfyun_appid'
    XFYUN_API_KEY = 'xfyun_api_key'
    # This is a database key name retained for legacy-row detection, not a credential.
    XFYUN_API_SECRET = 'xfyun_api_secret'  # nosec B105


               
DEFAULT_CONFIG_ITEMS = [
    (ConfigKey.QUESTIONS_PER_SESSION, '5', '每次面试抽取题目数量'),
]

SENSITIVE_CONFIG_KEYS = {
    ConfigKey.LLM_API_KEY,
    ConfigKey.XFYUN_APPID,
    ConfigKey.XFYUN_API_KEY,
    ConfigKey.XFYUN_API_SECRET,
}


class SystemConfig(db.Model):
    __tablename__ = 'system_config'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    config_key = db.Column(db.String(64), unique=True, nullable=False)
    config_value = db.Column(db.Text)
    description = db.Column(db.String(256))
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self, mask_sensitive=True):
        val = self.config_value
        if mask_sensitive and self.config_key in SENSITIVE_CONFIG_KEYS:
            val = '***' if (val and len(val) > 0) else ''
        return {
            'id': self.id,
            'config_key': self.config_key,
            'config_value': val,
            'description': self.description,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self):
        return f'<SystemConfig {self.config_key}>'

                                
    @classmethod
    def get_by_key(cls, config_key):
        return cls.query.filter_by(config_key=config_key).first()

    @classmethod
    def get_value(cls, config_key, default=None):
        row = cls.query.filter_by(config_key=config_key).first()
        return row.config_value if row else default

    @classmethod
    def get_int(cls, config_key, default=0):
        val = cls.get_value(config_key, default)
        try:
            return int(val) if val is not None else default
        except (TypeError, ValueError):
            return default

    @classmethod
    def get_bool(cls, config_key, default=False):
        val = cls.get_value(config_key)
        if val is None:
            return default
        return str(val).strip().lower() in ('1', 'true', 'yes', 'on')

    @classmethod
    def set_key_value(cls, config_key, config_value, description=None):
        row = cls.query.filter_by(config_key=config_key).first()
        if row:
            row.config_value = config_value
            if description is not None:
                row.description = description
        else:
            row = cls(config_key=config_key, config_value=config_value, description=description or '')
            db.session.add(row)
        db.session.commit()
        return row

    @classmethod
    def get_all(cls, mask_sensitive=True):
        return cls.query.order_by(cls.id.asc()).all()

    @classmethod
    def set_many(cls, key_value_dict):
        for k, v in key_value_dict.items():
            cls.set_key_value(k, v)
        return True

    @classmethod
    def seed_defaults(cls):
        for key, value, desc in DEFAULT_CONFIG_ITEMS:
            if cls.get_by_key(key) is None:
                cls.set_key_value(key, value, desc)
