import re
from collections import Counter
from difflib import SequenceMatcher

from app.models import Question
from app.models.question import QuestionType
from app.services.retrieval_service import retrieve_knowledge


CATEGORY_META = {
    'technical_knowledge': ('技术知识', '补齐关键概念、原理和适用边界'),
    'project_practice': ('项目实践', '用个人职责、实施过程和量化结果证明实践能力'),
    'scenario_analysis': ('场景分析', '补充约束、方案取舍、异常处理和风险边界'),
    'answer_structure': ('回答结构', '使用清晰框架组织案例、行动、结果和复盘'),
    'expression': ('表达训练', '调整语速并减少填充词和重复表达'),
    'consolidation': ('巩固训练', '复盘现有回答并补充证据、边界和项目案例'),
}

ANSWER_FRAMEWORKS = {
    QuestionType.TECHNICAL: ['先给出定义或结论', '解释核心原理', '说明边界或常见误区', '结合项目案例'],
    QuestionType.PROJECT: ['说明项目背景', '明确个人职责', '描述关键行动和取舍', '给出量化结果', '总结复盘'],
    QuestionType.SCENARIO: ['澄清目标和约束', '提出候选方案', '比较取舍', '补充异常与风险', '说明验证方式'],
    QuestionType.BEHAVIORAL: ['描述情境', '说明任务', '突出个人行动', '给出结果', '总结反思与改进'],
}

GENERIC_CONSOLIDATION = (
    ('结构化复述', '使用“结论—原理—证据—边界”重新组织回答。'),
    ('项目案例量化', '为回答补充个人职责、关键动作和可验证结果。'),
    ('场景取舍复盘', '补充约束条件、替代方案、风险和降级措施。'),
)


def _normalize_weakness(value):
    normalized = re.sub(r'[^\u4e00-\u9fffA-Za-z0-9+#.]', '', str(value or '').lower())
    for prefix in ('需要加强', '需要补充', '进一步说明', '说明', '解释', '掌握', '理解', '补充'):
        if normalized.startswith(prefix) and len(normalized) > len(prefix) + 2:
            normalized = normalized[len(prefix):]
            break
    return normalized[:120]


def _is_similar(left, right):
    if not left or not right:
        return False
    if left == right:
        return True
    if min(len(left), len(right)) >= 4 and (left in right or right in left):
        return True
    return SequenceMatcher(None, left, right).ratio() >= 0.78


def _category_for(question_type, label=''):
    normalized = _normalize_weakness(label)
    if any(word in normalized for word in ('项目', '案例', '职责', '指标', '量化', '落地', '实践')):
        return 'project_practice'
    if any(word in normalized for word in ('取舍', '异常', '风险', '降级', '边界', '场景', '应急')):
        return 'scenario_analysis'
    if any(word in normalized for word in ('结构', 'star', '行动', '复盘', '表达完整')):
        return 'answer_structure'
    return {
        QuestionType.TECHNICAL: 'technical_knowledge',
        QuestionType.PROJECT: 'project_practice',
        QuestionType.SCENARIO: 'scenario_analysis',
        QuestionType.BEHAVIORAL: 'answer_structure',
    }.get(question_type, 'technical_knowledge')


def aggregate_weaknesses(question_results):
    clusters = []
    for result in question_results or []:
        for point in result.get('missing_points') or []:
            label = str(point or '').strip()
            normalized = _normalize_weakness(label)
            if not normalized:
                continue
            cluster = next(
                (item for item in clusters if _is_similar(item['normalized'], normalized)),
                None,
            )
            if cluster is None:
                cluster = {
                    'label': label[:120],
                    'normalized': normalized,
                    'occurrence_count': 0,
                    'question_ids': [],
                    'question_types': [],
                    'lowest_score': 100.0,
                    'primary_result': result,
                }
                clusters.append(cluster)
            cluster['occurrence_count'] += 1
            question_id = result.get('question_id')
            if question_id and question_id not in cluster['question_ids']:
                cluster['question_ids'].append(question_id)
            question_type = result.get('question_type')
            if question_type:
                cluster['question_types'].append(question_type)
            score = float(result.get('final_score') or 0)
            if score < cluster['lowest_score']:
                cluster['lowest_score'] = score
                cluster['primary_result'] = result

    for cluster in clusters:
        cluster['category'] = _category_for(
            Counter(cluster['question_types']).most_common(1)[0][0]
            if cluster['question_types'] else None,
            cluster['label'],
        )
        cluster['priority'] = round(
            cluster['occurrence_count'] * 100 + (100 - cluster['lowest_score']),
            1,
        )
    return sorted(clusters, key=lambda item: (-item['priority'], item['label']))


def _material_for(position_code, result, weakness, cache=None):
    cache_key = (
        position_code,
        result.get('question_id') or result.get('question_content') or weakness,
    )
    if cache is not None and cache_key in cache:
        return cache[cache_key]
    knowledge = retrieve_knowledge(
        position_code,
        result.get('question_content') or weakness,
        weakness,
        '',
        limit=1,
        retrieval_context={
            'session_id': result.get('session_id'),
            'question_id': result.get('question_id'),
            'use_case': 'training',
        },
    )
    material = None
    if knowledge and knowledge[0].get('score', 0) > 0:
        item = knowledge[0]
        material = {
            'knowledge_id': item.get('id'),
            'title': item.get('title') or '岗位知识材料',
            'summary': (item.get('content') or '')[:260],
            'source': item.get('source'),
        }
    if cache is not None:
        cache[cache_key] = material
    return material


def _task_from_weakness(position_code, weakness, index, material_cache=None):
    result = weakness['primary_result']
    question_type = result.get('question_type')
    category = weakness['category']
    category_label, objective_prefix = CATEGORY_META[category]
    material = _material_for(
        position_code,
        result,
        weakness['label'],
        cache=material_cache,
    )
    return {
        'id': f'weakness-{index}',
        'category': category,
        'category_label': category_label,
        'title': weakness['label'],
        'objective': f"{objective_prefix}：{weakness['label']}",
        'reason': (
            f"该要点在 {weakness['occurrence_count']} 道题中缺失，"
            f"相关题最低得分为 {weakness['lowest_score']:.1f}。"
        ),
        'occurrence_count': weakness['occurrence_count'],
        'knowledge': material,
        'practice_question': {
            'question_id': result.get('question_id'),
            'content': result.get('question_content') or '请围绕该知识点重新组织一次回答。',
            'type': question_type,
        },
        'answer_framework': ANSWER_FRAMEWORKS.get(
            {
                'project_practice': QuestionType.PROJECT,
                'scenario_analysis': QuestionType.SCENARIO,
                'answer_structure': QuestionType.BEHAVIORAL,
            }.get(category, question_type),
            ANSWER_FRAMEWORKS[QuestionType.TECHNICAL],
        ),
        'suggested_days': 2 if weakness['occurrence_count'] >= 2 else 3,
        'status': 'todo',
    }


def _expression_task(expression_analysis, index):
    pace = float(expression_analysis.get('characters_per_minute') or 0)
    fillers = float(expression_analysis.get('filler_rate_percent') or 0)
    repetitions = float(expression_analysis.get('repetition_rate_percent') or 0)
    issues = []
    if pace and pace < 140:
        issues.append('语速偏慢')
    elif pace > 300:
        issues.append('语速偏快')
    if fillers > 1:
        issues.append(f'填充词占比 {fillers}%')
    if repetitions > 1:
        issues.append(f'重复表达占比 {repetitions}%')
    if not issues:
        return None
    category_label, objective = CATEGORY_META['expression']
    return {
        'id': f'expression-{index}',
        'category': 'expression',
        'category_label': category_label,
        'title': '口头表达节奏与简洁度',
        'objective': objective,
        'reason': '；'.join(issues) + '。',
        'occurrence_count': 1,
        'knowledge': None,
        'practice_question': None,
        'answer_framework': ['先写出三个回答要点', '每个要点只说一个结论', '录音 60～90 秒', '回听并删减填充词'],
        'suggested_days': 2,
        'status': 'todo',
    }


def _consolidation_task(position_code, result, index, title=None, instruction=None,
                        material_cache=None):
    question = Question.get_by_id(result.get('question_id')) if result.get('question_id') else None
    topic = (question.topic if question else None) or (title or '岗位核心能力')
    category_label, objective_prefix = CATEGORY_META['consolidation']
    material = _material_for(
        position_code,
        result,
        topic,
        cache=material_cache,
    )
    return {
        'id': f'consolidation-{index}',
        'category': 'consolidation',
        'category_label': category_label,
        'title': title or f'巩固：{topic}',
        'objective': instruction or f'{objective_prefix}：{topic}',
        'reason': f"本题得分为 {float(result.get('final_score') or 0):.1f}，建议复述并补充可验证案例。",
        'occurrence_count': 1,
        'knowledge': material,
        'practice_question': {
            'question_id': result.get('question_id'),
            'content': result.get('question_content') or '请重新组织一次更完整的回答。',
            'type': result.get('question_type'),
        },
        'answer_framework': ANSWER_FRAMEWORKS.get(
            result.get('question_type'),
            ANSWER_FRAMEWORKS[QuestionType.TECHNICAL],
        ),
        'suggested_days': 3,
        'status': 'todo',
    }


def build_training_tasks(session, question_results, expression_analysis=None, limit=5):
    limit = max(3, min(5, int(limit or 5)))
    material_cache = {}
    # Select the final weaknesses before retrieving materials.  The old list
    # comprehension retrieved every candidate and only then sliced the list,
    # which produced many unused API calls and duplicate audit events.
    selected_weaknesses = aggregate_weaknesses(question_results)[:limit]
    tasks = [
        _task_from_weakness(
            session.position_code,
            weakness,
            index + 1,
            material_cache=material_cache,
        )
        for index, weakness in enumerate(selected_weaknesses)
    ]

    if expression_analysis and expression_analysis.get('status') == 'measured' and len(tasks) < limit:
        expression_task = _expression_task(expression_analysis, len(tasks) + 1)
        if expression_task:
            tasks.append(expression_task)

    used_question_ids = {
        task.get('practice_question', {}).get('question_id')
        for task in tasks if task.get('practice_question')
    }
    ranked_results = sorted(
        question_results or [],
        key=lambda item: (float(item.get('final_score') or 0), item.get('question_id') or 0),
    )
    for result in ranked_results:
        if len(tasks) >= min(3, limit):
            break
        if result.get('question_id') in used_question_ids:
            continue
        tasks.append(_consolidation_task(
            session.position_code,
            result,
            len(tasks) + 1,
            material_cache=material_cache,
        ))
        used_question_ids.add(result.get('question_id'))

    if ranked_results:
        primary = ranked_results[0]
        for title, instruction in GENERIC_CONSOLIDATION:
            if len(tasks) >= min(3, limit):
                break
            tasks.append(
                _consolidation_task(
                    session.position_code,
                    primary,
                    len(tasks) + 1,
                    title=title,
                    instruction=instruction,
                    material_cache=material_cache,
                )
            )

    return tasks[:limit]
