"""Normalize the versioned question bank without touching user records.

The original Python/algorithm import contained task labels such as
``反转字符串`` rather than complete interview prompts.  This script performs a
deterministic, reviewable migration of seed questions and their generated
knowledge entries.  Database rows are updated later by ``init_db.py --seed``
through the persisted ``legacy_content`` / ``legacy_title`` identities.
"""

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
QUESTION_PATH = ROOT / 'seed' / 'questions.json'
KNOWLEDGE_PATH = ROOT / 'seed' / 'knowledge.json'
REVIEWER = 'Codex-assisted question-bank audit'
REVIEWED_AT = '2026-09-23T15:30:00'
ENDINGS = ('？', '?', '。', '！', '!')


GENERIC_WORDS = {
    '使用', '实现', '说明', '回答', '问题', '方法', '进行', '相关', '核心',
    '需要', '可以', '以及', '或者', '一个', '一种', '主要', '关键',
}

LEGACY_PROMPT_FIXES = {
    'n)': '计算 x 的 n 次幂',
}

REFERENCE_GUIDANCE = (
    '回答还应说明所用数据结构或算法的执行步骤，分析时间复杂度和空间复杂度，'
    '并覆盖空输入、重复值、越界或极端规模等与本题相关的边界情况。',
    '回答还应说明关键原理、适用场景以及必要的限制或边界。',
    '还应明确个人职责、关键取舍、量化结果和后续复盘。',
    '还应说明排查顺序、方案取舍、风险控制和验证方法。',
    '建议用 STAR 结构说明个人行动、最终结果和复盘改进。',
)


def _read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def _write(path, value):
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + '\n',
        encoding='utf-8',
    )


def _keywords(*values):
    result = []
    for value in values:
        if isinstance(value, list):
            candidates = value
        else:
            candidates = re.findall(
                r'[A-Za-z][A-Za-z0-9+.#/_-]{1,20}|[\u4e00-\u9fff]{2,8}',
                str(value or ''),
            )
        for candidate in candidates:
            candidate = str(candidate).strip(' ,，。；;：:（）()')
            if (
                len(candidate) >= 2
                and candidate not in GENERIC_WORDS
                and candidate not in result
            ):
                result.append(candidate)
    return result[:8] or ['核心原理']


def _complete_prompt(item):
    content = (item.get('content') or '').strip()
    legacy_content = (item.get('legacy_content') or '').strip()
    if legacy_content in LEGACY_PROMPT_FIXES:
        content = LEGACY_PROMPT_FIXES[legacy_content]
    elif content.startswith('请使用 Python 解决“'):
        return content
    else:
        content = LEGACY_PROMPT_FIXES.get(content, content)
    if item.get('position_code') == 'python_algorithm' and not content.endswith(ENDINGS):
        return (
            f'请使用 Python 解决“{content}”问题，说明核心思路和关键步骤，'
            '分析时间与空间复杂度，并指出需要处理的边界情况。'
        )
    if content.endswith(ENDINGS):
        return content
    if item.get('type') == 'project':
        return content + '，请重点说明你的职责、方案取舍、结果和复盘。'
    return content + '？'


def _complete_reference(item, original_reference):
    if item.get('position_code') == 'python_algorithm':
        if original_reference.startswith('一种可行的核心方案是：'):
            return original_reference
        return (
            f'一种可行的核心方案是：{original_reference.rstrip("。；;")}。'
            '回答还应说明所用数据结构或算法的执行步骤，分析时间复杂度和'
            '空间复杂度，并覆盖空输入、重复值、越界或极端规模等与本题相关的边界情况。'
        )
    suffixes = {
        'technical': '回答还应说明关键原理、适用场景以及必要的限制或边界。',
        'project': '还应明确个人职责、关键取舍、量化结果和后续复盘。',
        'scenario': '还应说明排查顺序、方案取舍、风险控制和验证方法。',
        'behavioral': '建议用 STAR 结构说明个人行动、最终结果和复盘改进。',
    }
    reference = original_reference
    if reference and not reference.endswith(('。', '！', '？', '.', '!', '?')):
        reference += '。'
    suffix = suffixes.get(item.get('type'), suffixes['technical'])
    if len(reference) < 45:
        reference += suffix
    return reference


def _knowledge_title(item, question):
    legacy_title = (item.get('legacy_title') or '').strip()
    if legacy_title:
        return legacy_title
    prompt = (question.get('content') or '').strip()
    quoted = re.search(r'请使用 Python 解决[“"]([^”"]+)[”"]问题', prompt)
    return quoted.group(1).strip() if quoted else prompt


def _knowledge_content(reference):
    content = (reference or '').strip()
    for guidance in REFERENCE_GUIDANCE:
        while guidance in content:
            content = content.replace(guidance, '')
    content = re.sub(r'^(一种可行的核心方案是：)+', '', content).strip()
    content = re.sub(r'。{2,}', '。', content).strip()
    return content or (reference or '').strip()


def _supplemental_points(question_type):
    return {
        'technical': [
            ('说明关键原理或执行步骤', ['原理', '步骤', '实现']),
            ('分析适用场景、复杂度或边界', ['场景', '复杂度', '边界']),
        ],
        'project': [
            ('说明个人职责和方案取舍', ['职责', '取舍', '方案']),
            ('提供结果证据并完成复盘', ['结果', '指标', '复盘']),
        ],
        'scenario': [
            ('给出有顺序的定位和处理方案', ['定位', '排查', '方案']),
            ('说明风险控制与验证闭环', ['风险', '验证', '监控']),
        ],
        'behavioral': [
            ('说明个人行动与协作过程', ['行动', '协作', '负责']),
            ('说明结果、反思和改进', ['结果', '复盘', '改进']),
        ],
    }.get(question_type, [
        ('说明关键原理和步骤', ['原理', '步骤']),
        ('说明边界和验证方法', ['边界', '验证']),
    ])


def _complete_points(item, original_reference, reference):
    points = item.get('scoring_points')
    points = [dict(point) for point in points if isinstance(point, dict)] \
        if isinstance(points, list) else []
    tags = [part.strip() for part in str(item.get('tags') or '').replace('，', ',').split(',') if part.strip()]
    for point in points:
        point['name'] = (point.get('name') or '').strip() or '说明核心知识与可执行方案'
        point['keywords'] = _keywords(
            point.get('keywords') or [], point['name'], tags, original_reference,
        )

    additions = _supplemental_points(item.get('type'))
    addition_index = 0
    while len(points) < 3:
        name, keywords = additions[min(addition_index, len(additions) - 1)]
        if not any(point.get('name') == name for point in points):
            points.append({'name': name, 'keywords': keywords, 'weight': 0})
        else:
            points.append({
                'name': '结合证据说明方案限制和验证结果',
                'keywords': ['证据', '限制', '验证'],
                'weight': 0,
            })
        addition_index += 1

    # Preserve at most three independently reviewable criteria and use stable
    # weights so every report has comparable scoring-point semantics.
    points = points[:3]
    weights = (50, 30, 20)
    for point, weight in zip(points, weights):
        point['weight'] = weight
        if not point.get('keywords'):
            point['keywords'] = _keywords(point.get('name'), reference, tags)
    return points


def repair():
    questions = _read(QUESTION_PATH)
    mapping = {}
    changed = 0
    for item in questions:
        original_content = (item.get('content') or '').strip()
        original_reference = (item.get('reference_answer') or '').strip()
        original_points = item.get('scoring_points')
        original_tags = item.get('tags')
        original_topic = item.get('topic')
        original_status = item.get('review_status')
        original_version = max(1, int(item.get('content_version') or 1))
        content = _complete_prompt(item)
        reference = _complete_reference(item, original_reference)
        points = _complete_points(item, original_reference, reference)

        if content != original_content:
            existing_legacy = (item.get('legacy_content') or '').strip()
            item['legacy_content'] = existing_legacy or original_content
            aliases = list(item.get('legacy_contents') or [])
            if original_content != item['legacy_content'] and original_content not in aliases:
                aliases.append(original_content)
            if aliases:
                item['legacy_contents'] = aliases
        item['content'] = content
        item['reference_answer'] = reference
        item['scoring_points'] = points
        item['tags'] = item.get('tags') or (
            'Python,算法,数据结构'
            if item.get('position_code') == 'python_algorithm'
            else item.get('topic') or '岗位知识'
        )
        if item.get('position_code') == 'python_algorithm' and item.get('topic') == '技术基础':
            item['topic'] = '算法与数据结构'
        item['source'] = item.get('source') or 'legacy_seed'
        item['review_status'] = 'ai_reviewed'
        item['reviewer'] = REVIEWER
        item['reviewed_at'] = REVIEWED_AT
        content_changed = any((
            content != original_content,
            reference != original_reference,
            points != original_points,
            item.get('tags') != original_tags,
            item.get('topic') != original_topic,
            original_status != 'ai_reviewed',
        ))
        item['content_version'] = (
            max(2, original_version + 1) if content_changed else original_version
        )
        identities = [original_content, item.get('legacy_content')]
        identities.extend(item.get('legacy_contents') or [])
        for identity in identities:
            identity = (identity or '').strip()
            if identity:
                mapping[(item.get('position_code'), identity)] = item
        if content_changed:
            changed += 1

    knowledge = _read(KNOWLEDGE_PATH)
    knowledge_changed = 0
    for item in knowledge:
        key = (item.get('position_code'), (item.get('title') or '').strip())
        question = mapping.get(key)
        if not question:
            continue
        original_title = (item.get('title') or '').strip()
        title = _knowledge_title(item, question)
        content = _knowledge_content(question['reference_answer'])
        if title != original_title:
            existing_legacy = (item.get('legacy_title') or '').strip()
            item['legacy_title'] = existing_legacy or original_title
            aliases = list(item.get('legacy_titles') or [])
            if original_title != item['legacy_title'] and original_title not in aliases:
                aliases.append(original_title)
            if aliases:
                item['legacy_titles'] = aliases
        item['title'] = title
        item['content'] = content
        item['tags'] = question.get('tags')
        item['topic'] = question.get('topic')
        item['keywords'] = ','.join(_keywords(
            question.get('tags'), title, content,
        ))
        item['difficulty'] = question.get('difficulty') or 1
        knowledge_changed += 1

    _write(QUESTION_PATH, questions)
    _write(KNOWLEDGE_PATH, knowledge)
    print(
        f'Repaired {changed} questions and synchronized '
        f'{knowledge_changed} generated knowledge entries.'
    )


if __name__ == '__main__':
    repair()
