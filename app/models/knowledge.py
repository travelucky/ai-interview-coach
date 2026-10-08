                       
from datetime import datetime
from app import db


class Knowledge(db.Model):
    __tablename__ = 'knowledge'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    position_code = db.Column(db.String(64), nullable=False, index=True)
    title = db.Column(db.String(256), nullable=False)
    content = db.Column(db.Text, nullable=False)
    tags = db.Column(db.String(512))
    topic = db.Column(db.String(128))
    keywords = db.Column(db.Text)
    difficulty = db.Column(db.Integer, default=1)
    source = db.Column(db.String(128))
    document_name = db.Column(db.String(256))
    chunk_index = db.Column(db.Integer)
    source_hash = db.Column(db.String(64), index=True)
    content_hash = db.Column(db.String(64), index=True)
    embedding_model = db.Column(db.String(128))
    embedding_vector = db.Column(db.Text)
    embedding_updated_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'position_code': self.position_code,
            'title': self.title,
            'content': self.content,
            'tags': self.tags,
            'topic': self.topic,
            'keywords': self.keywords,
            'difficulty': self.difficulty,
            'source': self.source,
            'document_name': self.document_name,
            'chunk_index': self.chunk_index,
            'source_hash': self.source_hash,
            'embedding_status': (
                'ready' if self.embedding_vector and self.embedding_model else 'missing'
            ),
            'embedding_model': self.embedding_model,
            'embedding_updated_at': (
                self.embedding_updated_at.isoformat()
                if self.embedding_updated_at else None
            ),
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self):
        return f'<Knowledge {self.id} {(self.title or "")[:20]}>'

                                
    @classmethod
    def create(cls, position_code, title, content, tags=None, topic=None,
               keywords=None, difficulty=1, source=None):
        obj = cls(
            position_code=position_code,
            title=title,
            content=content,
            tags=tags,
            topic=topic,
            keywords=keywords,
            difficulty=difficulty,
            source=source,
        )
        db.session.add(obj)
        db.session.commit()
        return obj

    @classmethod
    def get_by_id(cls, knowledge_id):
        return cls.query.get(knowledge_id)

    @classmethod
    def update_by_id(cls, knowledge_id, **kwargs):
        obj = cls.query.get(knowledge_id)
        if not obj:
            return None
        for k, v in kwargs.items():
            if hasattr(obj, k):
                setattr(obj, k, v)
        if set(kwargs) & {
            'position_code', 'title', 'content', 'tags', 'topic', 'keywords',
        }:
            obj.content_hash = None
            obj.embedding_model = None
            obj.embedding_vector = None
            obj.embedding_updated_at = None
        db.session.commit()
        return obj

    @classmethod
    def delete_by_id(cls, knowledge_id):
        obj = cls.query.get(knowledge_id)
        if not obj:
            return False
        db.session.delete(obj)
        db.session.commit()
        return True

    @classmethod
    def list_by_position(cls, position_code):
        return cls.query.filter_by(position_code=position_code).order_by(cls.id.asc()).all()

    @classmethod
    def list_page(cls, position_code=None, keyword=None, page=1, per_page=20):
        q = cls.query
        if position_code:
            q = q.filter_by(position_code=position_code)
        if keyword and keyword.strip():
            pattern = f'%{keyword.strip()}%'
            q = q.filter(db.or_(
                cls.title.like(pattern),
                cls.content.like(pattern),
                cls.tags.like(pattern),
                cls.topic.like(pattern),
                cls.keywords.like(pattern),
            ))
        return q.order_by(cls.id.desc()).paginate(page=page, per_page=per_page)

    @classmethod
    def search_by_position_and_keywords(cls, position_code, keywords):
        q = cls.query.filter_by(position_code=position_code)
        if keywords:
            if isinstance(keywords, str):
                keywords = [keywords]
            for kw in keywords:
                if not kw or not kw.strip():
                    continue
                pattern = f'%{kw.strip()}%'
                q = q.filter(
                    db.or_(
                        cls.title.like(pattern),
                        cls.content.like(pattern),
                        cls.tags.like(pattern),
                    )
                )
        return q.order_by(cls.id.asc()).limit(50).all()
