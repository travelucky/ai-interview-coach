import json
import random

from app.models import InterviewSession, Position, Question
from app.models.question import QuestionType
from app.services.question_quality_service import is_question_interview_ready


QUESTION_TYPE_ORDER = (
    QuestionType.TECHNICAL,
    QuestionType.PROJECT,
    QuestionType.SCENARIO,
    QuestionType.BEHAVIORAL,
)


def _recent_question_ids(user_id, position_code, session_limit=3):
    sessions = (
        InterviewSession.query.filter_by(
            user_id=user_id,
            position_code=position_code,
        )
        .order_by(InterviewSession.started_at.desc())
        .limit(session_limit)
        .all()
    )
    result = set()
    for session in sessions:
        try:
            values = json.loads(session.question_ids)
        except (TypeError, ValueError):
            continue
        if isinstance(values, list):
            result.update(value for value in values if isinstance(value, int))
    return result


def _type_quotas(limit):
    if limit <= 0:
        return {}
    quotas = {question_type: 0 for question_type in QUESTION_TYPE_ORDER}
    if limit >= len(QUESTION_TYPE_ORDER):
        for question_type in QUESTION_TYPE_ORDER:
            quotas[question_type] = 1
        quotas[QuestionType.TECHNICAL] += limit - len(QUESTION_TYPE_ORDER)
    else:
        for question_type in QUESTION_TYPE_ORDER[:limit]:
            quotas[question_type] = 1
    return quotas


def select_questions(position_code, limit, user_id=None):
    position = Position.get_by_code(position_code)
    if position is None or limit <= 0:
        return []

    active_questions = Question.query.filter_by(
        position_id=position.id,
        is_active=True,
    ).all()
    all_questions = [
        question for question in active_questions
        if is_question_interview_ready(question)
    ]
    if not all_questions:
        return []

    recent_ids = _recent_question_ids(user_id, position_code) if user_id else set()
    selected = []
    selected_ids = set()

    def choose(candidates, count):
        preferred = [q for q in candidates if q.id not in recent_ids and q.id not in selected_ids]
        fallback = [q for q in candidates if q.id not in selected_ids]
        pool = preferred if len(preferred) >= count else fallback
        if not pool or count <= 0:
            return []
        # Core questions are preferred, but every fallback row has already
        # passed the same review and structural quality gate above.
        trusted = [
            q for q in pool
            if q.is_core
        ]
        primary = trusted if len(trusted) >= count else pool
        chosen = []
        # Prefer a spread of difficulty levels before filling randomly.
        for difficulty in (2, 3, 4, 1, 5):
            level = [q for q in primary if q.difficulty == difficulty and q not in chosen]
            if level and len(chosen) < count:
                # Randomness only varies questions; it is not a security decision.
                chosen.append(random.choice(level))  # nosec B311
        remaining = [q for q in primary if q not in chosen]
        if len(chosen) < count and remaining:
            chosen.extend(random.sample(remaining, min(count - len(chosen), len(remaining))))  # nosec B311
        return chosen[:count]

    quotas = _type_quotas(limit)
    for question_type in QUESTION_TYPE_ORDER:
        candidates = [q for q in all_questions if q.type == question_type]
        for question in choose(candidates, quotas.get(question_type, 0)):
            selected.append(question)
            selected_ids.add(question.id)

    if len(selected) < limit:
        for question in choose(all_questions, limit - len(selected)):
            selected.append(question)
            selected_ids.add(question.id)

    return selected[:limit]


def select_targeted_questions(position_code, primary_question, limit=3):
    """Select a deterministic short set around one verified practice question."""
    position = Position.get_by_code(position_code)
    if position is None or primary_question is None or limit <= 0:
        return []
    if primary_question.position_id != position.id:
        return []

    selected = [primary_question]
    if limit == 1:
        return selected

    primary_tags = {
        item.strip().lower()
        for item in (primary_question.tags or '').replace('，', ',').split(',')
        if item.strip()
    }

    def relevance(question):
        score = 0
        if primary_question.topic and question.topic == primary_question.topic:
            score += 60
        if question.type == primary_question.type:
            score += 30
        question_tags = {
            item.strip().lower()
            for item in (question.tags or '').replace('，', ',').split(',')
            if item.strip()
        }
        score += len(primary_tags & question_tags) * 10
        return score

    candidates = Question.query.filter(
        Question.position_id == position.id,
        Question.id != primary_question.id,
        Question.is_active.is_(True),
    ).all()
    candidates = [
        question for question in candidates
        if is_question_interview_ready(question)
    ]
    candidates.sort(key=lambda question: (-relevance(question), question.id))
    selected.extend(candidates[:max(0, limit - 1)])
    return selected[:limit]
