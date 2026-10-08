                       
import json
import logging
from flask import current_app

logger = logging.getLogger(__name__)

               
MAX_FOLLOW_UPS_PER_QUESTION = 1
DEPTH_FOLLOW_UP_MIN_LENGTH = 120


def _offline_depth_followup(question, user_answer):
    if question is None or len((user_answer or '').strip()) < DEPTH_FOLLOW_UP_MIN_LENGTH:
        return None
    templates = {
        'project': '你的方案描述得比较完整。请再结合一个真实项目说明：你个人负责了什么、如何落地，以及最终结果如何量化？',
        'scenario': '你已经给出了主要方案。请继续说明：如果方案失效或资源受限，你会如何取舍、降级并处理异常？',
        'behavioral': '请再用一个真实案例说明你当时采取的具体行动、最终结果，以及事后有哪些复盘改进。',
    }
    return templates.get(getattr(question, 'type', None))


def _call_llm_for_followup(current_question, user_answer, follow_ups_this_question,
                           next_question_preview, position_code, question_context=None):
    api_key = (current_app.config.get('LLM_API_KEY') or '').strip()
    api_base = (current_app.config.get('LLM_API_BASE') or '').strip() or 'https://api.openai.com/v1'
    model_name = (current_app.config.get('LLM_MODEL') or '').strip() or 'gpt-4o-mini'
    timeout = current_app.config.get('LLM_TIMEOUT_SECONDS', 30)
    if not api_key:
        return None
    import requests
    url = api_base.rstrip("/") + "/chat/completions"

    can_follow_up = follow_ups_this_question < MAX_FOLLOW_UPS_PER_QUESTION
    system = (
        "你是 AI 面试官，正在对候选人进行岗位面试。你需要根据候选人当前回答决定：是否追问以深入考察，还是进入下一题。\n\n"
        "规则：\n"
        "1. 若候选人回答较简略、有可深挖的关键词（如技术点、项目经历、数字等），且本題尚未追问过，可追问一道简短的跟进问题（一两句话），便于更好评估。\n"
        "2. 若回答已较充分、或不宜再追问，则选择进入下一题。\n"
        "3. 追问须紧扣候选人回答中的要点，不要脱离其回答泛泛而问。\n"
        "4. 控制节奏：追问简洁，不要一次问多问。\n\n"
        "请严格只输出一个 JSON 对象，不要其他文字。键为：action（字符串 \"follow_up\" 或 \"next\"）、content（字符串。若 action 为 follow_up 则为追问内容；若为 next 则为空字符串）。"
    )
    next_preview = ("下一题摘要：" + (next_question_preview or "无")[:80]) if next_question_preview else "没有下一题，应选 next。"
    context = question_context or {}
    reference_answer = context.get('reference_answer') or '未提供'
    scoring_points = context.get('scoring_points') or []
    point_names = [str(point.get('name') or '') for point in scoring_points]
    knowledge_text = '\n'.join(
        f"- {item.get('title')}: {item.get('content')}"
        for item in context.get('knowledge') or []
    ) or '未检索到补充知识'
    user_content = (
        "应聘岗位：%s\n\n当前题目：%s\n\n候选人回答：%s\n\n"
        "参考答案：%s\n\n评分点：%s\n\n岗位知识：\n%s\n\n"
        "本题已追问次数：%d。%s\n\n请输出 JSON：action 与 content。"
        % (
            position_code or "通用",
            current_question or "",
            user_answer or "",
            reference_answer,
            '；'.join(point_names) or '未配置',
            knowledge_text,
            follow_ups_this_question,
            next_preview,
        )
    )
    if not can_follow_up:
        user_content += "\n（本题已达追问上限，必须选 next。）"

    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.3,
    }
    try:
        r = requests.post(url, json=payload, headers={"Authorization": "Bearer " + api_key}, timeout=timeout)
        r.raise_for_status()
        data = r.json()
        text = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
        if not text:
            return None
        text = text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(l for l in lines if l.strip() and not l.strip().startswith("```"))
        out = json.loads(text)
        action = (out.get("action") or "").strip().lower()
        content = (out.get("content") or "").strip()
        if action not in ("follow_up", "next"):
            return None
        if action == "follow_up" and not can_follow_up:
            action = "next"
            content = ""
        if action == "follow_up" and not content:
            action = "next"
        return {"action": action, "content": content}
    except Exception as e:
        logger.warning("追问 LLM 请求失败: %s", e)
        return None


def decide_followup_or_next(current_question, user_answer, follow_ups_this_question,
                            next_question_content, position_code, question=None,
                            retrieval_context=None):
    if follow_ups_this_question >= MAX_FOLLOW_UPS_PER_QUESTION:
        return ("next", next_question_content or "")

    from app.services.retrieval_service import (
        find_missing_scoring_points,
        get_effective_scoring_points,
        retrieve_knowledge,
    )
    knowledge = retrieve_knowledge(
        position_code,
        current_question,
        user_answer,
        question.tags if question else '',
        limit=3,
        retrieval_context=retrieval_context,
    )
    question_context = {
        'reference_answer': question.reference_answer if question else None,
        'scoring_points': get_effective_scoring_points(question),
        'knowledge': knowledge,
    }
    result = _call_llm_for_followup(
        current_question,
        user_answer,
        follow_ups_this_question,
        (next_question_content or "")[:100] if next_question_content else None,
        position_code,
        question_context,
    )
    if not result:
        missing_points = find_missing_scoring_points(question, user_answer)
        if missing_points:
            missing_name = str(missing_points[0].get('name') or '').strip()
            if missing_name:
                return (
                    'follow_up',
                    f'你的回答还可以再深入一些。请进一步说明：{missing_name[:80]}',
                )
        depth_followup = _offline_depth_followup(question, user_answer)
        if depth_followup:
            return ('follow_up', depth_followup)
        return ("next", next_question_content or "")

    action = result.get("action") or "next"
    content = (result.get("content") or "").strip()

    if action == "follow_up" and content:
        return ("follow_up", content)
    return ("next", next_question_content or "")
