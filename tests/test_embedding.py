import pytest

from app.models import Knowledge
from app.services.embedding_service import (
    EmbeddingServiceError,
    embed_texts,
    refresh_knowledge_embeddings,
)


class _FakeEmbeddingResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def _configure(app):
    app.config.update(
        EMBEDDING_API_KEY='test-only-key',
        EMBEDDING_BASE_URL='https://example.invalid/v1',
        EMBEDDING_MODEL='test-embedding',
        EMBEDDING_BATCH_SIZE=32,
    )


def test_refresh_embeddings_persists_model_hash_and_vector(app, monkeypatch):
    captured = {}

    def fake_post(url, **kwargs):
        captured['url'] = url
        captured['authorization'] = kwargs['headers']['Authorization']
        inputs = kwargs['json']['input']
        return _FakeEmbeddingResponse({
            'data': [
                {'index': index, 'embedding': [float(index + 1), 0.5]}
                for index, _value in enumerate(inputs)
            ],
        })

    monkeypatch.setattr('requests.post', fake_post)
    with app.app_context():
        _configure(app)
        result = refresh_knowledge_embeddings(force=True)
        item = Knowledge.query.one()

        assert result['updated'] == 1
        assert result['dimension'] == 2
        assert item.embedding_model == 'test-embedding'
        assert item.content_hash
        assert item.embedding_vector == '[1.0,0.5]'
        assert captured['url'] == 'https://example.invalid/v1/embeddings'
        assert captured['authorization'] == 'Bearer test-only-key'


def test_embedding_response_shape_is_validated(app, monkeypatch):
    monkeypatch.setattr(
        'requests.post',
        lambda *_args, **_kwargs: _FakeEmbeddingResponse({
            'data': [{'index': 0, 'embedding': ['not-a-number']}],
        }),
    )
    with app.app_context():
        _configure(app)
        with pytest.raises(EmbeddingServiceError, match='非数值'):
            embed_texts(['测试文本'])
