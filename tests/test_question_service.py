from app.models import Question
from app.services.question_service import _type_quotas, select_questions


def test_default_five_question_mix_covers_all_four_types(app):
    assert _type_quotas(5) == {
        'technical': 2,
        'project': 1,
        'scenario': 1,
        'behavioral': 1,
    }
    with app.app_context():
        selected = select_questions('java_backend', 5)

    assert len(selected) == 5
    assert [item.type for item in selected].count('technical') == 2
    assert {item.type for item in selected} == {
        'technical', 'project', 'scenario', 'behavioral'
    }


def test_question_selection_returns_no_duplicates(app):
    with app.app_context():
        selected = select_questions('java_backend', 5)

    assert len({item.id for item in selected}) == len(selected)
    assert all(isinstance(item, Question) for item in selected)
