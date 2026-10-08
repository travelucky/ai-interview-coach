import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SEED_DIR = ROOT / 'seed'
TARGET_POSITIONS = {'python_algorithm', 'web_sec'}
TYPE_TOPICS = {
    'technical': '技术基础',
    'project': '项目实践',
    'scenario': '场景设计',
    'behavioral': '行为能力',
}
TYPE_DEPTH_POINTS = {
    'project': ('说明个人职责、实施过程和可验证结果', ['负责', '实施', '结果', '指标', '提升', '降低']),
    'scenario': ('说明方案取舍、异常处理和风险边界', ['取舍', '异常', '风险', '降级', '应急', '边界']),
    'behavioral': ('结合真实案例说明行动、结果和复盘', ['案例', '行动', '结果', '复盘', '改进']),
}


def _read(name):
    return json.loads((SEED_DIR / name).read_text(encoding='utf-8'))


def _write(name, data):
    (SEED_DIR / name).write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + '\n',
        encoding='utf-8',
    )


def _tag_list(value):
    return [part.strip() for part in re.split(r'[,，;；]', value or '') if part.strip()]


def _keywords(question, text=None):
    combined = text or f"{question.get('content') or ''} {question.get('reference_answer') or ''}"
    values = [
        tag for tag in _tag_list(question.get('tags'))
        if tag.lower() in combined.lower()
    ]
    values.extend(re.findall(r'[A-Za-z][A-Za-z0-9+#./-]{1,30}', combined))
    result = []
    seen = set()
    for value in values:
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result[:12]


def _scoring_points(question):
    reference = (question.get('reference_answer') or '').strip()
    clauses = [
        clause.strip(' ：:。；;，,')
        for clause in re.split(r'[。；;\n]', reference)
        if clause.strip(' ：:。；;，,')
    ]
    if not clauses and reference:
        clauses = [reference]
    if len(clauses) == 1 and len(clauses[0]) > 80:
        clauses = [
            clause.strip()
            for clause in re.split(r'[，,、]', clauses[0])
            if clause.strip()
        ]
    if len(clauses) == 1:
        space_parts = [part.strip() for part in clauses[0].split() if part.strip()]
        if 1 < len(space_parts) <= 8:
            clauses = space_parts
    clauses = clauses[:6]
    if not clauses:
        clauses = _tag_list(question.get('tags'))[:4]
    if not clauses:
        clauses = ['回答覆盖题目要求并给出合理说明']

    points = [
        {
            'name': clause[:80],
            'keywords': _keywords(question, clause),
        }
        for clause in clauses
    ]
    depth = TYPE_DEPTH_POINTS.get(question.get('type'))
    if depth:
        points.append({'name': depth[0], 'keywords': depth[1]})
    base_weight = 100 // len(points)
    remainder = 100 - base_weight * len(points)
    for index, point in enumerate(points):
        point['weight'] = base_weight + (1 if index < remainder else 0)
    return points


def enrich():
    questions = _read('questions.json')
    knowledge = _read('knowledge.json')
    existing = {
        (item.get('position_code'), item.get('title')): item
        for item in knowledge
    }
    enriched_count = 0
    generated_knowledge_count = 0

    for question in questions:
        if question.get('position_code') not in TARGET_POSITIONS:
            continue
        tags = _tag_list(question.get('tags'))
        question['topic'] = tags[0] if tags else TYPE_TOPICS.get(
            question.get('type'),
            '岗位能力',
        )
        question['scoring_points'] = _scoring_points(question)
        enriched_count += 1

        reference = (question.get('reference_answer') or '').strip()
        if not reference:
            continue
        title = (question.get('content') or question['topic'])[:240]
        identity = (question['position_code'], title)
        knowledge_values = {
            'position_code': question['position_code'],
            'title': title,
            'content': reference,
            'tags': question.get('tags'),
            'topic': question['topic'],
            'keywords': ','.join(_keywords(question)),
            'difficulty': question.get('difficulty') or 1,
            'source': 'question_reference',
        }
        if identity in existing:
            existing[identity].update(knowledge_values)
            continue
        knowledge.append(knowledge_values)
        existing[identity] = knowledge_values
        generated_knowledge_count += 1

    _write('questions.json', questions)
    _write('knowledge.json', knowledge)
    print(
        f'Enriched {enriched_count} additional questions and generated '
        f'{generated_knowledge_count} knowledge chunks.'
    )


if __name__ == '__main__':
    enrich()
