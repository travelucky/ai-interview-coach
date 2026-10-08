import json
import re


APPROVED_REVIEW_STATUSES = {'reviewed', 'ai_reviewed'}
QUESTION_TYPES = {'technical', 'project', 'scenario', 'behavioral'}
TERMINAL_PUNCTUATION = ('？', '?', '。', '！', '!')


def parse_scoring_points(value):
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value or '[]')
        except (TypeError, ValueError):
            return []
        return parsed if isinstance(parsed, list) else []
    return []


def question_quality_errors(content, reference_answer, scoring_points,
                            question_type=None):
    """Return deterministic errors for a question allowed into interviews.

    This gate intentionally checks reviewable data quality rather than trying to
    prove subject-matter correctness. Human/expert review remains separately
    represented by ``review_status == 'reviewed'``.
    """
    errors = []
    content = (content or '').strip()
    reference_answer = (reference_answer or '').strip()
    points = parse_scoring_points(scoring_points)

    if question_type and question_type not in QUESTION_TYPES:
        errors.append('题型无效')
    # Short definition questions such as “什么是 GC？” are complete despite
    # their length; title fragments are rejected separately by punctuation.
    if len(content) < 5:
        errors.append('题目内容过短')
    if re.search(r'[“"]\s*[^”"]{0,2}\W?\s*[”"]', content):
        errors.append('题目主题疑似残缺')
    if content and not content.endswith(TERMINAL_PUNCTUATION):
        errors.append('题目必须是以问号或句号结尾的完整表述')
    if len(reference_answer) < 20:
        errors.append('参考答案至少需要 20 个字符')
    if len(points) < 2:
        errors.append('至少需要两个独立评分点')

    total_weight = 0.0
    for index, point in enumerate(points, start=1):
        if not isinstance(point, dict):
            errors.append(f'第 {index} 个评分点格式无效')
            continue
        # Acronyms such as AES, RSA and ECC are valid independent criteria.
        if len((point.get('name') or '').strip()) < 2:
            errors.append(f'第 {index} 个评分点说明过短')
        keywords = point.get('keywords')
        if not isinstance(keywords, list) or not any(
            str(keyword).strip() for keyword in keywords
        ):
            errors.append(f'第 {index} 个评分点缺少关键词')
        try:
            weight = float(point.get('weight') or 0)
        except (TypeError, ValueError):
            weight = 0
        if weight <= 0:
            errors.append(f'第 {index} 个评分点权重必须大于 0')
        total_weight += weight
    if points and abs(total_weight - 100) > 0.01:
        errors.append('评分点权重合计必须为 100')
    return errors


def is_question_interview_ready(question):
    if not question or not question.is_active:
        return False
    if question.review_status not in APPROVED_REVIEW_STATUSES:
        return False
    return not question_quality_errors(
        question.content,
        question.reference_answer,
        question.scoring_points,
        question.type,
    )
