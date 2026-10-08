                       
import json
import threading
import weakref
from datetime import datetime
from flask import Blueprint, current_app, g, request
from sqlalchemy.exc import IntegrityError
from app import db
from app.models import (
    Question, InterviewSession, InterviewMessage, InterviewReport,
    QuestionScore, SystemConfig, Position, ExpressionMetric, RetrievalEvent,
    TrainingTask,
)
from app.models.interview_message import MessageKind, MessageRole
from app.models.interview_session import SessionStatus
from app.controllers.decorators import login_required
from app.controllers.utils import json_ok, json_fail, get_json

bp = Blueprint('interview', __name__, url_prefix='/api/interview')

_SESSION_LOCKS = weakref.WeakValueDictionary()
_SESSION_LOCKS_GUARD = threading.Lock()


def _session_lock(session_id):
    """Serialize state-changing work for one session in this application process."""
    with _SESSION_LOCKS_GUARD:
        return _SESSION_LOCKS.setdefault(session_id, threading.Lock())


def _summarize_retrieval_trace(events):
    summaries = {}
    order = []
    for event in events:
        use_case = event.get('use_case') or 'unknown'
        if use_case not in summaries:
            summaries[use_case] = {
                'use_case': use_case,
                'event_count': 0,
                'hit_count': 0,
                'rejected_count': 0,
                'methods': [],
                'versions': [],
                'knowledge_titles': [],
                'unique_knowledge_count': 0,
            }
            order.append(use_case)
        summary = summaries[use_case]
        summary['event_count'] += 1
        results = event.get('results') or []
        if results:
            summary['hit_count'] += 1
        else:
            summary['rejected_count'] += 1
        method = event.get('retrieval_method') or 'none'
        version = event.get('retrieval_version') or '-'
        if method not in summary['methods']:
            summary['methods'].append(method)
        if version not in summary['versions']:
            summary['versions'].append(version)
        for result in results:
            title = str(result.get('title') or '').strip()
            if title and title not in summary['knowledge_titles']:
                summary['knowledge_titles'].append(title)

    for summary in summaries.values():
        summary['unique_knowledge_count'] = len(summary['knowledge_titles'])
        summary['knowledge_titles'] = summary['knowledge_titles'][:5]
    return [summaries[use_case] for use_case in order]


def _session_available_actions(sess, report=None):
    report = report or InterviewReport.get_by_session_id(sess.id)
    state = sess.get_interview_state()
    current_index = int(
        state.get('current_question_index', sess.current_question_index or 0)
    )
    total = len(sess.get_question_ids())
    can_finish = (
        report is None
        and sess.status in (
            SessionStatus.INTERVIEWING,
            SessionStatus.SCORING,
            SessionStatus.FAILED,
        )
        and sess.can_generate_report(
            current_app.config.get('MIN_INTERVIEW_COMPLETION_RATIO', 0.6)
        )
    )
    return {
        'can_reply': (
            sess.status == SessionStatus.INTERVIEWING
            and current_index < total
        ),
        'can_finish': can_finish,
        'can_abandon': sess.status in (
            SessionStatus.INTERVIEWING,
            SessionStatus.FAILED,
        ),
        'can_view_report': report is not None,
    }


def _editable_user_message_id(sess, messages=None):
    if sess.status != SessionStatus.INTERVIEWING:
        return None
    messages = messages if messages is not None else InterviewMessage.list_by_session(sess.id)
    if len(messages) < 2:
        return None
    user_message, assistant_message = messages[-2], messages[-1]
    if (
        user_message.role != MessageRole.USER
        or assistant_message.role != MessageRole.ASSISTANT
        or assistant_message.message_kind != MessageKind.FOLLOW_UP
    ):
        return None
    question_ids = sess.get_question_ids()
    state = sess.get_interview_state()
    current_index = int(
        state.get('current_question_index', sess.current_question_index or 0)
    )
    if current_index >= len(question_ids):
        return None
    if user_message.question_id != question_ids[current_index]:
        return None
    return user_message.id


def _session_snapshot(sess):
    question_ids = sess.get_question_ids()
    total = len(question_ids)
    state = sess.get_interview_state()
    current_index = int(
        state.get('current_question_index', sess.current_question_index or 0)
    )
    messages = InterviewMessage.list_by_session(sess.id)
    latest_assistant = next(
        (message for message in reversed(messages)
         if message.role == MessageRole.ASSISTANT),
        None,
    )
    current_question = None
    if latest_assistant is not None:
        current_question = {
            'message_id': latest_assistant.id,
            'question_id': latest_assistant.question_id,
            'content': latest_assistant.content,
            'message_kind': latest_assistant.message_kind,
        }
    report = InterviewReport.get_by_session_id(sess.id)
    position = Position.get_by_code(sess.position_code)
    editable_message_id = _editable_user_message_id(sess, messages=messages)
    message_payloads = []
    for message in messages:
        payload = message.to_dict()
        payload['editable'] = message.id == editable_message_id
        message_payloads.append(payload)
    return {
        'session_id': sess.id,
        'session': sess.to_dict(),
        'position_name': position.name if position else sess.position_code,
        'question_ids': question_ids,
        'messages': message_payloads,
        'current_question': current_question,
        'progress': {
            'current': min(current_index + 1, total) if total else 0,
            'answered': sess.answered_question_count,
            'total': total,
        },
        'available_actions': _session_available_actions(sess, report=report),
    }


def _assistant_after(user_message):
    return (
        InterviewMessage.query.filter(
            InterviewMessage.session_id == user_message.session_id,
            InterviewMessage.role == MessageRole.ASSISTANT,
            InterviewMessage.sequence > user_message.sequence,
        )
        .order_by(InterviewMessage.sequence.asc())
        .first()
    )


def _reply_payload(sess, user_message, assistant_message, total,
                   expression_metric=None, duplicate=False, recovered=False):
    state = sess.get_interview_state()
    current_index = int(state.get('current_question_index', sess.current_question_index or 0))
    actions = _session_available_actions(sess)
    return {
        'role': 'assistant',
        'content': assistant_message.content,
        'user_content': user_message.content,
        'user_message_id': user_message.id,
        'tts_url': None,
        'is_next_question': assistant_message.message_kind == MessageKind.QUESTION,
        'duplicate': duplicate,
        'recovered': recovered,
        'user_message_editable': (
            sess.status == SessionStatus.INTERVIEWING
            and assistant_message.message_kind == MessageKind.FOLLOW_UP
        ),
        'status': sess.status,
        'available_actions': actions,
        'auto_finish': sess.status == SessionStatus.SCORING and actions['can_finish'],
        'expression_metric': expression_metric.to_dict() if expression_metric else None,
        'progress': {
            'current': min(current_index + 1, total),
            'answered': sess.answered_question_count,
            'total': total,
        },
    }


def _reply_decision(sess, question_ids, current_question_index,
                    follow_ups_this_question, content):
    total = len(question_ids)
    current_question = Question.get_by_id(question_ids[current_question_index])
    if current_question is None:
        raise ValueError('当前题目不存在，无法继续面试')
    next_question_index = current_question_index + 1
    if next_question_index < total:
        next_question = Question.get_by_id(question_ids[next_question_index])
        next_question_content = (
            (next_question.content or '') if next_question else '请继续下一题。'
        )
    else:
        next_question_content = '本场题目已全部作答完毕，可点击结束面试生成报告。'

    from app.services.followup_service import decide_followup_or_next
    action, assistant_content = decide_followup_or_next(
        current_question.content or '',
        content,
        follow_ups_this_question,
        next_question_content,
        sess.position_code or 'general',
        question=current_question,
        retrieval_context={
            'session_id': sess.id,
            'question_id': current_question.id,
            'use_case': 'followup',
        },
    )
    if action == 'follow_up':
        new_state = {
            'current_question_index': current_question_index,
            'follow_ups_this_question': follow_ups_this_question + 1,
        }
        answered_count = sess.answered_question_count
        progress_current = current_question_index + 1
        is_next_question = False
        assistant_question_id = current_question.id
        assistant_kind = MessageKind.FOLLOW_UP
    else:
        answered_count = max(sess.answered_question_count, current_question_index + 1)
        new_state = {
            'current_question_index': next_question_index,
            'follow_ups_this_question': 0,
        }
        progress_current = min(next_question_index + 1, total)
        is_next_question = next_question_index < total
        assistant_question_id = (
            question_ids[next_question_index] if is_next_question else None
        )
        assistant_kind = MessageKind.QUESTION if is_next_question else MessageKind.SYSTEM
    return {
        'current_question': current_question,
        'assistant_content': assistant_content,
        'new_state': new_state,
        'answered_count': answered_count,
        'progress_current': progress_current,
        'is_next_question': is_next_question,
        'assistant_question_id': assistant_question_id,
        'assistant_kind': assistant_kind,
    }


def _start_session(user_id, position_code, questions, mode='standard',
                   source_session_id=None, training_task_id=None):
    question_ids = [question.id for question in questions]
    session = InterviewSession.create(
        user_id,
        position_code,
        question_ids,
        mode=mode,
        source_session_id=source_session_id,
        training_task_id=training_task_id,
    )
    first_question = questions[0]
    sequence = InterviewMessage.get_next_sequence(session.id)
    InterviewMessage.create(
        session.id,
        MessageRole.ASSISTANT,
        first_question.content or '',
        sequence,
        question_id=first_question.id,
        message_kind=MessageKind.QUESTION,
    )
    session.record_progress(
        current_question_index=0,
        answered_question_count=0,
        state={'current_question_index': 0, 'follow_ups_this_question': 0},
    )
    return {
        'session_id': session.id,
        'position_code': session.position_code,
        'mode': session.mode,
        'source_session_id': session.source_session_id,
        'training_task_id': session.training_task_id,
        'question_ids': question_ids,
        'progress': {'current': 1, 'answered': 0, 'total': len(question_ids)},
        'first_question': {
            'question_id': first_question.id,
            'content': first_question.content or '',
            'tts_url': None,
        },
    }


@bp.route('/start', methods=['POST'])
@login_required
def start():
    data = get_json()
    if not data or not (data.get('position_code') or '').strip():
        return json_fail('缺少 position_code', 400)
    position_code = (data.get('position_code') or '').strip()
    limit = SystemConfig.get_int(
        'questions_per_session',
        current_app.config.get('QUESTIONS_PER_SESSION', 5),
    )
    from app.services.question_service import select_questions
    questions = select_questions(position_code, limit, user_id=g.current_user.id)
    if not questions:
        return json_fail('该岗位下暂无题目，请先配置知识库', 400)
    return json_ok(_start_session(g.current_user.id, position_code, questions))


@bp.route('/training/start', methods=['POST'])
@login_required
def start_training():
    data = get_json() or {}
    source_session_id = data.get('source_session_id')
    task_id = str(data.get('task_id') or '').strip()
    try:
        source_session_id = int(source_session_id)
    except (TypeError, ValueError):
        return json_fail('缺少有效的 source_session_id', 400)
    if not task_id or len(task_id) > 64:
        return json_fail('缺少有效的训练任务标识', 400)

    source_session = InterviewSession.get_by_id_and_user(
        source_session_id,
        g.current_user.id,
    )
    if source_session is None:
        return json_fail('来源面试不存在或无权访问', 404)
    report = InterviewReport.get_by_session_id(source_session.id)
    if report is None:
        return json_fail('来源面试尚未生成报告', 409)
    try:
        training_tasks = json.loads(report.training_tasks or '[]')
    except (TypeError, ValueError):
        training_tasks = []
    task_rows = TrainingTask.list_by_source(source_session.id)
    if not task_rows and training_tasks:
        task_rows = TrainingTask.create_many(
            source_session.user_id,
            source_session.id,
            training_tasks,
        )
    task_row = next((row for row in task_rows if row.task_id == task_id), None)
    if task_row is None or task_row.user_id != g.current_user.id:
        return json_fail('训练任务不存在或已失效', 404)
    task = task_row.snapshot()
    if task_row.status == 'in_progress' and task_row.training_session_id:
        existing = InterviewSession.get_by_id_and_user(
            task_row.training_session_id,
            g.current_user.id,
        )
        if existing and existing.status != SessionStatus.ABANDONED:
            return json_fail(
                f'该训练任务已在场次 {existing.id} 中进行，请从未完成面试继续',
                409,
            )
    if task_row.status == 'completed':
        return json_fail('该训练任务已完成，可从报告查看复测对比', 409)

    practice = task.get('practice_question') if isinstance(task.get('practice_question'), dict) else {}
    primary_question_id = practice.get('question_id')
    if not primary_question_id:
        source_question_ids = source_session.get_question_ids()
        primary_question_id = source_question_ids[0] if source_question_ids else None
    try:
        primary_question_id = int(primary_question_id)
    except (TypeError, ValueError):
        return json_fail('训练任务未关联有效练习题', 409)

    primary_question = Question.get_by_id(primary_question_id)
    if (
        primary_question is None
        or primary_question.position is None
        or primary_question.position.code != source_session.position_code
    ):
        return json_fail('训练题与来源岗位不匹配', 409)

    from app.services.question_service import select_targeted_questions
    questions = select_targeted_questions(
        source_session.position_code,
        primary_question,
        limit=3,
    )
    if not questions:
        return json_fail('暂时无法生成该专项训练，请稍后重试', 409)
    payload = _start_session(
        g.current_user.id,
        source_session.position_code,
        questions,
        mode='training',
        source_session_id=source_session.id,
        training_task_id=task_id,
    )
    task_row.mark_started(payload['session_id'])
    payload['training_task'] = {
        'id': task_id,
        'title': task.get('title') or '专项训练',
        'category_label': task.get('category_label') or '专项训练',
        'objective': task.get('objective') or '',
    }
    return json_ok(payload)


@bp.route('/transcribe', methods=['POST'])
@login_required
def transcribe_audio():
    audio_file = request.files.get('audio') if request.files else None
    if audio_file is None:
        return json_fail('请上传语音文件 audio', 400)
    from app.services.asr_service import (
        AudioValidationError,
        analyze_wav_acoustics,
        create_transcription_receipt,
        recognize_wav_bytes,
        validate_wav_bytes,
    )
    max_size = current_app.config.get('ASR_MAX_AUDIO_BYTES', 4_000_000)
    wav_bytes = audio_file.stream.read(max_size + 1)
    try:
        metadata = validate_wav_bytes(
            wav_bytes,
            max_size_bytes=max_size,
            max_duration_ms=current_app.config.get('ASR_MAX_DURATION_SECONDS', 60) * 1000,
        )
        acoustic_metrics = analyze_wav_acoustics(wav_bytes)
    except AudioValidationError as error:
        return json_fail(str(error) + '；你仍可改用文字输入', 400)
    try:
        transcript = (recognize_wav_bytes(wav_bytes) or '').strip()
    except Exception as error:
        current_app.logger.warning(
            'transcribe: ASR service failed: %s', type(error).__name__
        )
        return json_fail(
            '语音服务暂时不可用，请稍后重试或改用文字输入', 503
        )
    if not transcript:
        return json_fail('语音识别无结果，请回放检查、重新录制或改用文字输入', 400)
    return json_ok({
        'transcript': transcript,
        'transcription_receipt': create_transcription_receipt(wav_bytes, transcript),
        'audio': metadata,
        'acoustic_metrics': acoustic_metrics,
        'notice': '转写尚未提交，请确认或修改后再正式发送',
    })


@bp.route('/<int:session_id>/reply', methods=['POST'])
@login_required
def reply(session_id):
    with _session_lock(session_id):
        return _reply_locked(session_id)


def _reply_locked(session_id):
    sess = InterviewSession.get_by_id_and_user(session_id, g.current_user.id)
    if not sess:
        current_app.logger.warning('reply: session %s not found or not owned by user', session_id)
        return json_fail('场次不存在或无权访问', 404)
    audio_file = request.files.get('audio') if request.files else None
    data = get_json() or {}
    request_id = (
        request.form.get('request_id') if audio_file else data.get('request_id')
    )
    request_id = (request_id or '').strip() or None
    if request_id and len(request_id) > 64:
        return json_fail('request_id 长度不能超过 64 个字符', 400)
    existing_user_message = InterviewMessage.get_by_client_request_id(
        session_id,
        request_id,
    )
    if existing_user_message:
        assistant_message = _assistant_after(existing_user_message)
        existing_metric = ExpressionMetric.query.filter_by(
            message_id=existing_user_message.id,
        ).first()
        if assistant_message is not None:
            return json_ok(_reply_payload(
                sess,
                existing_user_message,
                assistant_message,
                len(sess.get_question_ids()),
                expression_metric=existing_metric,
                duplicate=True,
            ))
    if sess.status != SessionStatus.INTERVIEWING:
        current_app.logger.warning('reply: session %s status=%s, not interviewing', session_id, sess.status)
        return json_fail('当前场次不在作答状态，无法继续提交回答', 409)

    question_ids = sess.get_question_ids()
    total = len(question_ids)
    state = sess.get_interview_state()
    current_question_index = int(state.get('current_question_index', sess.current_question_index or 0))
    follow_ups_this_question = int(state.get('follow_ups_this_question', 0))
    if current_question_index >= total:
        return json_fail('本场正式题目已全部作答，请结束面试生成报告', 409)

    if existing_user_message:
        # Compatibility and crash recovery for an answer committed by an older
        # application version before its assistant response was persisted.
        try:
            recovery_index = question_ids.index(existing_user_message.question_id)
        except (ValueError, TypeError):
            recovery_index = current_question_index
        previous_assistant = (
            InterviewMessage.query.filter(
                InterviewMessage.session_id == session_id,
                InterviewMessage.role == MessageRole.ASSISTANT,
                InterviewMessage.sequence < existing_user_message.sequence,
            )
            .order_by(InterviewMessage.sequence.desc())
            .first()
        )
        recovery_followups = (
            1 if previous_assistant
            and previous_assistant.message_kind == MessageKind.FOLLOW_UP else 0
        )
        try:
            decision = _reply_decision(
                sess,
                question_ids,
                recovery_index,
                recovery_followups,
                existing_user_message.content,
            )
            sess.record_progress(
                current_question_index=decision['new_state']['current_question_index'],
                answered_question_count=decision['answered_count'],
                state=decision['new_state'],
                commit=False,
            )
            if (
                decision['new_state']['current_question_index'] >= total
                and decision['answered_count'] >= total
            ):
                sess.transition_to(SessionStatus.SCORING, commit=False)
            assistant_message = InterviewMessage.create(
                session_id,
                MessageRole.ASSISTANT,
                decision['assistant_content'],
                InterviewMessage.get_next_sequence(session_id),
                question_id=decision['assistant_question_id'],
                message_kind=decision['assistant_kind'],
                commit=False,
            )
            db.session.commit()
        except Exception as error:
            db.session.rollback()
            current_app.logger.warning(
                'reply: failed to recover partial answer for session %s: %s',
                session_id,
                error,
                exc_info=True,
            )
            return json_fail('回答已保留，但追问生成失败，请稍后使用同一请求重试', 503)
        return json_ok(_reply_payload(
            sess,
            existing_user_message,
            assistant_message,
            total,
            expression_metric=existing_metric,
            duplicate=True,
            recovered=True,
        ))

    content = None
    raw_transcript = None
    audio_metadata = None
    acoustic_metrics = None
    if audio_file:
        from app.services.asr_service import (
            AudioValidationError,
            analyze_wav_acoustics,
            read_transcription_receipt,
            recognize_wav_bytes,
            validate_wav_bytes,
        )
        max_size = current_app.config.get('ASR_MAX_AUDIO_BYTES', 4_000_000)
        wav_bytes = audio_file.stream.read(max_size + 1)
        try:
            audio_metadata = validate_wav_bytes(
                wav_bytes,
                max_size_bytes=max_size,
                max_duration_ms=current_app.config.get('ASR_MAX_DURATION_SECONDS', 60) * 1000,
            )
        except AudioValidationError as error:
            current_app.logger.warning('reply: invalid audio for session %s: %s', session_id, error)
            return json_fail(str(error) + '；你仍可改用文字输入', 400)
        raw_transcript = read_transcription_receipt(
            wav_bytes,
            request.form.get('transcription_receipt'),
        )
        if not raw_transcript:
            try:
                raw_transcript = (recognize_wav_bytes(wav_bytes) or '').strip()
            except Exception as error:
                current_app.logger.warning(
                    'reply: ASR service failed for session %s: %s',
                    session_id,
                    type(error).__name__,
                )
                return json_fail(
                    '语音服务暂时不可用，本题进度未改变；请改用文字输入或稍后重试',
                    503,
                )
        if not raw_transcript:
            current_app.logger.warning('reply: ASR returned empty for session %s', session_id)
            return json_fail('语音识别无结果（可能太短或环境嘈杂），请重试或改用文字输入', 400)
        acoustic_metrics = analyze_wav_acoustics(wav_bytes)
        content = (request.form.get('confirmed_content') or '').strip() or raw_transcript
    if content is None:
        content = (data.get('content') or '').strip()
    if not content:
        current_app.logger.warning('reply: no content and no valid audio for session %s', session_id)
        return json_fail('请提供回答内容（content）或上传语音（audio）', 400)
    try:
        decision = _reply_decision(
            sess,
            question_ids,
            current_question_index,
            follow_ups_this_question,
            content,
        )
    except Exception as error:
        db.session.rollback()
        current_app.logger.warning(
            'reply: response generation failed for session %s: %s',
            session_id,
            error,
            exc_info=True,
        )
        return json_fail('追问生成失败，回答尚未提交，请保留内容后重试', 503)

    expression_metric = None
    try:
        user_msg = InterviewMessage.create(
            session_id,
            MessageRole.USER,
            content,
            InterviewMessage.get_next_sequence(session_id),
            client_request_id=request_id,
            question_id=decision['current_question'].id,
            message_kind=MessageKind.ANSWER,
            answer_source='voice' if audio_file else 'text',
            raw_transcript=raw_transcript,
            commit=False,
        )
        if audio_metadata:
            from app.services.expression_service import save_expression_metric
            expression_metric = save_expression_metric(
                user_msg.id,
                content,
                audio_metadata['duration_ms'],
                acoustic_metrics=acoustic_metrics,
                commit=False,
            )
        sess.record_progress(
            current_question_index=decision['new_state']['current_question_index'],
            answered_question_count=decision['answered_count'],
            state=decision['new_state'],
            commit=False,
        )
        if (
            decision['new_state']['current_question_index'] >= total
            and decision['answered_count'] >= total
        ):
            sess.transition_to(SessionStatus.SCORING, commit=False)
        assistant_message = InterviewMessage.create(
            session_id,
            MessageRole.ASSISTANT,
            decision['assistant_content'],
            InterviewMessage.get_next_sequence(session_id),
            question_id=decision['assistant_question_id'],
            message_kind=decision['assistant_kind'],
            commit=False,
        )
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        existing_user_message = InterviewMessage.get_by_client_request_id(
            session_id,
            request_id,
        )
        assistant_message = (
            _assistant_after(existing_user_message) if existing_user_message else None
        )
        if existing_user_message and assistant_message:
            existing_metric = ExpressionMetric.query.filter_by(
                message_id=existing_user_message.id,
            ).first()
            return json_ok(_reply_payload(
                sess,
                existing_user_message,
                assistant_message,
                total,
                expression_metric=existing_metric,
                duplicate=True,
            ))
        return json_fail('该回答正在由另一个请求处理，请稍后重试', 409)
    except Exception as error:
        db.session.rollback()
        current_app.logger.warning(
            'reply: atomic persistence failed for session %s: %s',
            session_id,
            error,
            exc_info=True,
        )
        return json_fail('回答保存失败，未写入不完整数据，请保留内容后重试', 503)
    return json_ok(_reply_payload(
        sess,
        user_msg,
        assistant_message,
        total,
        expression_metric=expression_metric,
    ))


@bp.route('/<int:session_id>/messages/<int:message_id>', methods=['PATCH'])
@login_required
def update_message(session_id, message_id):
    with _session_lock(session_id):
        return _update_message_locked(session_id, message_id)


def _update_message_locked(session_id, message_id):
    sess = InterviewSession.get_by_id_and_user(session_id, g.current_user.id)
    if not sess:
        return json_fail('场次不存在或无权访问', 404)
    if sess.status != SessionStatus.INTERVIEWING:
        return json_fail('该场次已离开作答状态，无法修改回答', 409)
    msg = InterviewMessage.query.filter_by(
        id=message_id,
        session_id=session_id,
        role=MessageRole.USER,
    ).first()
    if not msg:
        return json_fail('消息不存在或不可编辑', 404)
    messages = InterviewMessage.list_by_session(session_id)
    if _editable_user_message_id(sess, messages=messages) != msg.id:
        return json_fail('只有仍在当前题追问阶段的最新回答可以编辑', 409)
    data = get_json() or {}
    content = (data.get('content') or '').strip()
    if not content:
        return json_fail('请提供 content', 400)
    if content == msg.content:
        assistant_message = messages[-1]
        return json_ok({
            'message': '内容未变化',
            'content': msg.content,
            'assistant_content': assistant_message.content,
            'assistant_message_kind': assistant_message.message_kind,
            'editable': True,
            'status': sess.status,
            'progress': {
                'current': min(
                    sess.current_question_index + 1,
                    sess.total_question_count,
                ),
                'answered': sess.answered_question_count,
                'total': sess.total_question_count,
            },
            'available_actions': _session_available_actions(sess),
        })

    question_ids = sess.get_question_ids()
    state = sess.get_interview_state()
    current_index = int(
        state.get('current_question_index', sess.current_question_index or 0)
    )
    try:
        decision = _reply_decision(
            sess,
            question_ids,
            current_index,
            0,
            content,
        )
    except Exception as error:
        db.session.rollback()
        current_app.logger.warning(
            'update_message: follow-up regeneration failed for session %s: %s',
            session_id,
            error,
            exc_info=True,
        )
        return json_fail('追问重新生成失败，原回答未修改，请稍后重试', 503)

    assistant_message = messages[-1]
    expression_metric = ExpressionMetric.query.filter_by(message_id=msg.id).first()
    try:
        msg.content = content
        msg.edited_at = datetime.utcnow()
        assistant_message.content = decision['assistant_content']
        assistant_message.question_id = decision['assistant_question_id']
        assistant_message.message_kind = decision['assistant_kind']
        sess.record_progress(
            current_question_index=decision['new_state']['current_question_index'],
            answered_question_count=decision['answered_count'],
            state=decision['new_state'],
            commit=False,
        )
        if expression_metric is not None:
            from app.services.expression_service import analyze_expression
            values = analyze_expression(content, expression_metric.duration_ms)
            ExpressionMetric.create_for_message(msg.id, values, commit=False)
        if (
            decision['new_state']['current_question_index'] >= len(question_ids)
            and decision['answered_count'] >= len(question_ids)
        ):
            sess.transition_to(SessionStatus.SCORING, commit=False)
        db.session.commit()
    except Exception as error:
        db.session.rollback()
        current_app.logger.warning(
            'update_message: atomic update failed for session %s: %s',
            session_id,
            error,
            exc_info=True,
        )
        return json_fail('回答修改失败，原内容已保留，请稍后重试', 503)

    actions = _session_available_actions(sess)
    return json_ok({
        'message': '已更新',
        'content': msg.content,
        'raw_transcript': msg.raw_transcript,
        'assistant_content': assistant_message.content,
        'assistant_message_kind': assistant_message.message_kind,
        'editable': _editable_user_message_id(sess) == msg.id,
        'status': sess.status,
        'auto_finish': sess.status == SessionStatus.SCORING and actions['can_finish'],
        'expression_metric': expression_metric.to_dict() if expression_metric else None,
        'progress': {
            'current': min(
                sess.current_question_index + 1,
                sess.total_question_count,
            ),
            'answered': sess.answered_question_count,
            'total': sess.total_question_count,
        },
        'available_actions': actions,
    })


@bp.route('/<int:session_id>/finish', methods=['POST'])
@login_required
def finish(session_id):
    with _session_lock(session_id):
        return _finish_locked(session_id)


def _finish_locked(session_id):
    sess = InterviewSession.get_by_id_and_user(session_id, g.current_user.id)
    if not sess:
        return json_fail('场次不存在或无权访问', 404)

    # A report is the durable proof that scoring finished. Older versions could
    # commit it before the session status; reconcile that legacy split state.
    report = InterviewReport.get_by_session_id(session_id)
    if report:
        if sess.status != SessionStatus.COMPLETED:
            try:
                if sess.status in (SessionStatus.INTERVIEWING, SessionStatus.FAILED):
                    sess.transition_to(SessionStatus.SCORING, commit=False)
                if sess.status == SessionStatus.SCORING:
                    sess.transition_to(SessionStatus.COMPLETED, commit=False)
                db.session.commit()
            except Exception as error:
                db.session.rollback()
                current_app.logger.warning(
                    'finish: failed to reconcile report state for session %s: %s',
                    session_id,
                    error,
                    exc_info=True,
                )
                return json_fail('报告已存在，但场次状态恢复失败，请稍后重试', 503)
        return json_ok({
            'session_id': session_id,
            'report_id': report.id,
            'message': '报告已生成',
        })

    if sess.status == SessionStatus.COMPLETED:
        return json_fail('该场次已完成，但报告记录缺失', 409)
    if sess.status == SessionStatus.ABANDONED:
        return json_fail('该场次已放弃，无法生成报告', 409)

    minimum_ratio = current_app.config.get('MIN_INTERVIEW_COMPLETION_RATIO', 0.6)
    minimum_answers = sess.minimum_required_answers(minimum_ratio)
    if not sess.can_generate_report(minimum_ratio):
        return json_fail(
            f'至少完成 {minimum_answers} 道正式题后才能生成报告，当前已完成 {sess.answered_question_count} 道',
            409,
        )

    if sess.status != SessionStatus.SCORING:
        try:
            sess.transition_to(SessionStatus.SCORING)
        except ValueError as error:
            return json_fail(str(error), 409)

    from app.services.scoring_service import score_interview, INTERVIEW_MAX_SCORE
    try:
        result = score_interview(session_id)
        if result.get('overall_score') is not None:
            result['overall_score'] = max(0.0, min(float(INTERVIEW_MAX_SCORE), float(result['overall_score'])))
        for item in result.get('question_scores') or []:
            QuestionScore.upsert(
                session_id=session_id,
                question_id=item['question_id'],
                answer_message_id=item.get('answer_message_id'),
                rule_score=item.get('rule_score'),
                llm_score=item.get('llm_score'),
                final_score=item.get('final_score', 0),
                covered_points=item.get('covered_points') or [],
                missing_points=item.get('missing_points') or [],
                evidence=item.get('evidence') or [],
                suggestion=item.get('suggestion'),
                knowledge_references=item.get('knowledge_references') or [],
                dimension_scores=item.get('dimension_scores') or {},
                scoring_source=item.get('scoring_source') or 'rule',
                scoring_version=item.get('scoring_version') or 'mvp-v3',
                commit=False,
            )
        report = InterviewReport.create(
            session_id=session_id,
            content_analysis=json.dumps(result.get('content_analysis') or {}),
            expression_analysis=json.dumps(result.get('expression_analysis') or {}),
            overall_score=float(result.get('overall_score', 0)),
            highlights=json.dumps(result.get('highlights') or []),
            improvements=json.dumps(result.get('improvements') or []),
            suggestions=json.dumps(result.get('suggestions') or []),
            training_tasks=json.dumps(
                result.get('training_tasks') or [],
                ensure_ascii=False,
            ),
            scoring_source=result.get('scoring_source') or 'rule',
            scoring_version=result.get('scoring_version') or 'mvp-v3',
            commit=False,
        )
        if (sess.mode or 'standard') == 'standard':
            TrainingTask.create_many(
                sess.user_id,
                sess.id,
                result.get('training_tasks') or [],
                commit=False,
            )
        elif sess.source_session_id and sess.training_task_id:
            task_row = TrainingTask.query.filter_by(
                user_id=sess.user_id,
                source_session_id=sess.source_session_id,
                task_id=sess.training_task_id,
            ).first()
            if task_row:
                task_row.training_session_id = sess.id
                task_row.mark_completed(commit=False)
        sess.scoring_version = result.get('scoring_version') or 'mvp-v3'
        sess.transition_to(SessionStatus.COMPLETED, commit=False)
        db.session.commit()
    except Exception as error:
        db.session.rollback()
        sess = InterviewSession.get_by_id_and_user(session_id, g.current_user.id)
        try:
            if sess and sess.status == SessionStatus.SCORING:
                sess.transition_to(SessionStatus.FAILED, failure_reason='scoring_failed')
        except Exception as status_error:
            db.session.rollback()
            current_app.logger.error(
                'finish: failed to mark session %s as failed: %s',
                session_id,
                status_error,
                exc_info=True,
            )
        current_app.logger.warning('finish: scoring failed %s', error, exc_info=True)
        return json_fail('报告生成失败，回答已保留，请稍后重试', 503)
    return json_ok({
        'session_id': session_id,
        'report_id': report.id,
        'message': '报告已生成',
    })


@bp.route('/sessions/active', methods=['GET'])
@login_required
def list_active_sessions():
    sessions = (
        InterviewSession.query
        .filter(
            InterviewSession.user_id == g.current_user.id,
            InterviewSession.status.in_([
                SessionStatus.INTERVIEWING,
                SessionStatus.SCORING,
                SessionStatus.FAILED,
            ]),
        )
        .order_by(InterviewSession.started_at.desc())
        .limit(10)
        .all()
    )
    items = []
    for sess in sessions:
        item = sess.to_dict()
        position = Position.get_by_code(sess.position_code)
        item['position_name'] = position.name if position else sess.position_code
        item['available_actions'] = _session_available_actions(sess)
        items.append(item)
    return json_ok(sessions=items, items=items)


@bp.route('/sessions/<int:session_id>/state', methods=['GET'])
@login_required
def get_session_state(session_id):
    with _session_lock(session_id):
        sess = InterviewSession.get_by_id_and_user(session_id, g.current_user.id)
        if not sess:
            return json_fail('场次不存在或无权访问', 404)
        return json_ok(_session_snapshot(sess))


@bp.route('/sessions/<int:session_id>/abandon', methods=['POST'])
@login_required
def abandon_session(session_id):
    with _session_lock(session_id):
        sess = InterviewSession.get_by_id_and_user(session_id, g.current_user.id)
        if not sess:
            return json_fail('场次不存在或无权访问', 404)
        if sess.status == SessionStatus.ABANDONED:
            return json_ok(_session_snapshot(sess), message='该场次已放弃')
        if sess.status not in (SessionStatus.INTERVIEWING, SessionStatus.FAILED):
            return json_fail('当前场次不能放弃；若正在评分，请先重试生成报告', 409)
        try:
            sess.transition_to(
                SessionStatus.ABANDONED,
                failure_reason='user_abandoned',
                commit=False,
            )
            if sess.mode == 'training' and sess.source_session_id and sess.training_task_id:
                task = TrainingTask.query.filter_by(
                    user_id=sess.user_id,
                    source_session_id=sess.source_session_id,
                    task_id=sess.training_task_id,
                    training_session_id=sess.id,
                ).first()
                if task and task.status != 'completed':
                    task.status = 'todo'
                    task.training_session_id = None
                    task.started_at = None
            db.session.commit()
        except ValueError as error:
            db.session.rollback()
            return json_fail(str(error), 409)
        return json_ok(_session_snapshot(sess), message='已放弃该场面试')


@bp.route('/sessions/<int:session_id>', methods=['DELETE'])
@login_required
def delete_session(session_id):
    sess = InterviewSession.get_by_id_and_user(session_id, g.current_user.id)
    if not sess:
        return json_fail('场次不存在或无权访问', 404)
    if InterviewSession.query.filter_by(source_session_id=session_id).first() is not None:
        return json_fail('该场次已被专项训练引用，需先删除关联专项训练', 409)
    from app import db

    if sess.mode == 'training' and sess.source_session_id and sess.training_task_id:
        task = TrainingTask.query.filter_by(
            user_id=sess.user_id,
            source_session_id=sess.source_session_id,
            task_id=sess.training_task_id,
            training_session_id=sess.id,
        ).first()
        if task:
            task.status = 'todo'
            task.training_session_id = None
            task.started_at = None
            task.completed_at = None
                     
    message_ids = [
        row.id for row in InterviewMessage.query.filter_by(session_id=session_id).all()
    ]
    if message_ids:
        ExpressionMetric.query.filter(ExpressionMetric.message_id.in_(message_ids)).delete(
            synchronize_session=False,
        )
    QuestionScore.query.filter_by(session_id=session_id).delete()
    InterviewMessage.query.filter_by(session_id=session_id).delete()
    InterviewReport.query.filter_by(session_id=session_id).delete()
    db.session.delete(sess)
    db.session.commit()
    return json_ok(message='已删除')


@bp.route('/sessions', methods=['GET'])
@login_required
def list_sessions():
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 20, type=int), 100)
    pagination = InterviewSession.list_by_user(g.current_user.id, page=page, per_page=per_page)
    session_ids = [s.id for s in pagination.items]
    reports = {r.session_id: r for r in InterviewReport.query.filter(InterviewReport.session_id.in_(session_ids)).all()} if session_ids else {}
    items = []
    for s in pagination.items:
        d = s.to_dict()
        r = reports.get(s.id)
        if r:
            d['report'] = {'overall_score': r.overall_score}
        items.append(d)
    return json_ok({
        'sessions': items,
        'items': items,
        'total': pagination.total,
        'page': pagination.page,
        'per_page': pagination.per_page,
    })


@bp.route('/sessions/<int:session_id>/report', methods=['GET'])
@login_required
def get_report(session_id):
    sess = InterviewSession.get_by_id_and_user(session_id, g.current_user.id)
    if not sess:
        return json_fail('场次不存在或无权访问', 404)
    report = InterviewReport.get_by_session_id(session_id)
    if not report:
        return json_fail('报告尚未生成', 404)
    def _parse_json_field(val, default=None):
        if val is None:
            return default if default is not None else {}
        if isinstance(val, (dict, list)):
            return val
        try:
            return json.loads(val)
        except Exception:
            return default if default is not None else {}

    content_analysis = _parse_json_field(report.content_analysis, {})
    expression_analysis = _parse_json_field(report.expression_analysis, {})
    highlights = _parse_json_field(report.highlights, [])
    improvements = _parse_json_field(report.improvements, [])
    suggestions = _parse_json_field(report.suggestions, [])
    training_tasks = _parse_json_field(report.training_tasks, [])
    task_rows = TrainingTask.list_by_source(session_id)
    if task_rows:
        training_tasks = [row.to_dict() for row in task_rows]

    def _comparison(source_report, training_report):
        if source_report is None or training_report is None:
            return None
        if source_report.scoring_version != training_report.scoring_version:
            return {
                'comparable': False,
                'reason': '评分版本不同，不进行数值对比',
                'source_version': source_report.scoring_version,
                'training_version': training_report.scoring_version,
            }
        source_content = _parse_json_field(source_report.content_analysis, {})
        training_content = _parse_json_field(training_report.content_analysis, {})
        source_dimensions = source_content.get('dimensions') or {}
        training_dimensions = training_content.get('dimensions') or {}
        dimension_deltas = {}
        for key in set(source_dimensions) & set(training_dimensions):
            source_item = source_dimensions.get(key) or {}
            training_item = training_dimensions.get(key) or {}
            if (
                source_item.get('status') == 'evaluated'
                and training_item.get('status') == 'evaluated'
                and source_item.get('score') is not None
                and training_item.get('score') is not None
            ):
                dimension_deltas[key] = round(
                    float(training_item['score']) - float(source_item['score']),
                    1,
                )
        return {
            'comparable': True,
            'scoring_version': source_report.scoring_version,
            'source_score': source_report.overall_score,
            'training_score': training_report.overall_score,
            'score_delta': round(
                float(training_report.overall_score or 0)
                - float(source_report.overall_score or 0),
                1,
            ),
            'dimension_deltas': dimension_deltas,
        }

    for task in training_tasks:
        training_session_id = task.get('training_session_id')
        if not training_session_id:
            continue
        training_report = InterviewReport.get_by_session_id(training_session_id)
        if training_report:
            task['comparison'] = _comparison(report, training_report)

    training_comparison = None
    if (sess.mode or 'standard') == 'training' and sess.source_session_id:
        source_report = InterviewReport.get_by_session_id(sess.source_session_id)
        training_comparison = _comparison(source_report, report)
    score_rows = QuestionScore.list_by_session(session_id)
    questions = {
        question.id: question
        for question in Question.query.filter(
            Question.id.in_([row.question_id for row in score_rows])
        ).all()
    } if score_rows else {}
    question_scores = []
    for row in score_rows:
        item = row.to_dict()
        question = questions.get(row.question_id)
        item['question_content'] = question.content if question else ''
        item['question_type'] = question.type if question else ''
        item['question_topic'] = question.topic if question else ''
        question_scores.append(item)
    retrieval_trace = [
        event.to_dict() for event in RetrievalEvent.list_by_session(session_id)
    ]
    retrieval_summary = _summarize_retrieval_trace(retrieval_trace)
    if highlights and all(
        isinstance(item, str) and '：得分 ' in item for item in highlights
    ):
        # Compatibility for reports produced before semantic highlight text was
        # introduced.  The stored scores remain unchanged.
        from app.services.scoring_service import build_report_highlights
        highlights = build_report_highlights(question_scores)
    return json_ok(report={
        'session_id': report.session_id,
        'overall_score': report.overall_score,
        'content_analysis': content_analysis,
        'expression_analysis': expression_analysis,
        'highlights': highlights,
        'improvements': improvements,
        'suggestions': suggestions,
        'training_tasks': training_tasks,
        'training_comparison': training_comparison,
        'question_scores': question_scores,
        'retrieval_trace': retrieval_trace,
        'retrieval_summary': retrieval_summary,
        'scoring_source': report.scoring_source,
        'scoring_version': report.scoring_version,
        'created_at': report.created_at.isoformat() if report.created_at else None,
        'completion_ratio': sess.completion_ratio,
        'session_mode': sess.mode or 'standard',
        'source_session_id': sess.source_session_id,
        'training_task_id': sess.training_task_id,
    })
