                       
import json
from collections import Counter
from datetime import datetime, timedelta
from flask import Blueprint, g
from sqlalchemy import func
from app import db
from app.models import (
    User, InterviewSession, InterviewReport, Question, Position,
    QuestionScore, TrainingTask,
)
from app.models.question import QuestionType
from app.controllers.decorators import login_required, admin_required
from app.controllers.utils import json_ok

bp = Blueprint('dashboard', __name__, url_prefix='/api/dashboard')

QUESTION_TYPE_NAMES = {
    QuestionType.TECHNICAL: '技术知识',
    QuestionType.PROJECT: '项目经历',
    QuestionType.SCENARIO: '场景题',
    QuestionType.BEHAVIORAL: '行为题',
}


LEGACY_DIMENSION_FIELDS = {
    'technical_correctness': 'technical_correctness',
    'knowledge_depth': 'knowledge_depth',
    'logic_structure': 'logic',
    'project_practice': 'project_practice',
    'job_fit': 'job_fit',
    'expression_performance': 'expression_performance',
}

DIMENSION_NAMES = {
    'technical_correctness': '技术正确性',
    'knowledge_depth': '知识深度',
    'logic_structure': '逻辑结构',
    'project_practice': '项目实践',
    'job_fit': '岗位匹配',
    'expression_performance': '表达表现',
}

WEAK_DIMENSION_THRESHOLD = 70


def _json_object(value):
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value or '{}')
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _dashboard_dimension_scores(content):
    dimensions = content.get('dimensions') or {}
    scores = {
        key: item.get('score')
        for key, item in dimensions.items()
        if isinstance(item, dict)
        and item.get('status') == 'evaluated'
        and item.get('score') is not None
    }
    if scores:
        return scores
    # Reports before mvp-v3 stored the same measurable dimensions as flat
    # numeric fields.  They remain valid inside their original scoring version
    # and can be plotted without relabelling or recalculating the score.
    for target, source in LEGACY_DIMENSION_FIELDS.items():
        value = content.get(source)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            scores[target] = value
    return scores


def _select_trend_cohort(reports):
    cohorts = {}
    for report in reports:
        session = getattr(report, 'session', None)
        if session is None or report.overall_score is None:
            continue
        key = (session.position_code, report.scoring_version)
        cohorts.setdefault(key, []).append(report)
    if not cohorts:
        return None, [], False

    latest_report = next((
        report for report in reports
        if getattr(report, 'session', None) is not None
        and report.overall_score is not None
    ), None)
    latest_key = (
        (latest_report.session.position_code, latest_report.scoring_version)
        if latest_report else None
    )
    comparable = [
        (key, rows) for key, rows in cohorts.items() if len(rows) >= 2
    ]
    if comparable:
        selected_key, selected_rows = max(
            comparable,
            key=lambda pair: max(row.session.started_at for row in pair[1]),
        )
    else:
        selected_key = latest_key or next(iter(cohorts))
        selected_rows = cohorts[selected_key]
    selected_rows = sorted(
        selected_rows,
        key=lambda row: row.session.started_at,
    )
    return selected_key, selected_rows, selected_key != latest_key


@bp.route('/user', methods=['GET'])
@login_required
def user_dashboard():
    user_id = g.current_user.id
    reports = InterviewReport.list_by_user_id(user_id, limit=50, mode='standard')
    training_reports = InterviewReport.list_by_user_id(
        user_id,
        limit=50,
        mode='training',
    )
    pagination = InterviewSession.list_by_user(user_id, page=1, per_page=1)
    total_sessions = pagination.total
    standard_total_sessions = InterviewSession.query.filter_by(
        user_id=user_id,
        mode='standard',
    ).count()
    training_total_sessions = InterviewSession.query.filter_by(
        user_id=user_id,
        mode='training',
    ).count()
    trend_key, comparable_reports, trend_uses_fallback = _select_trend_cohort(
        reports
    )
    trend_position_code = trend_key[0] if trend_key else None
    trend_scoring_version = trend_key[1] if trend_key else None
    trend = [
        (report.session.started_at, report.overall_score)
        for report in comparable_reports
    ]
    scores = [r.overall_score for r in reports if r.overall_score is not None]
    trend_scores = [t[1] for t in trend if t[1] is not None]
    average_score = sum(scores) / len(scores) if scores else None
    best_score = max(scores) if scores else None
    recent_5 = trend_scores[-5:]
    recent_5_avg = sum(recent_5) / len(recent_5) if recent_5 else None
    average_score_trend = [
        {'date': t[0].strftime('%Y-%m-%d') if hasattr(t[0], 'strftime') else str(t[0]), 'score': t[1]}
        for t in trend if t[1] is not None
    ]
    dimension_trend = []
    type_trend = []
    weakness_by_session = []
    for comparable_report in comparable_reports:
        content = _json_object(comparable_report.content_analysis)
        date_value = comparable_report.session.started_at
        date_label = date_value.strftime('%Y-%m-%d') if hasattr(date_value, 'strftime') else str(date_value)
        dimension_trend.append({
            'session_id': comparable_report.session_id,
            'date': date_label,
            'scores': _dashboard_dimension_scores(content),
        })
        type_trend.append({
            'session_id': comparable_report.session_id,
            'date': date_label,
            'scores': content.get('question_type_scores') or {},
        })
        counter = Counter()
        for score_row in QuestionScore.list_by_session(comparable_report.session_id):
            for point in score_row.to_dict().get('missing_points') or []:
                if point:
                    counter[str(point)[:120]] += 1
        # 渐进式规则评分可能给出“部分覆盖”而不是二元的缺失项。
        # 因此再按每场报告的能力维度识别低分项；每个维度每场只计一次，
        # 让“薄弱项变化”既能兼容旧报告，也能反映低分到高分的真实改善。
        for key, value in _dashboard_dimension_scores(content).items():
            if (
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and value < WEAK_DIMENSION_THRESHOLD
            ):
                counter[f'能力维度：{DIMENSION_NAMES.get(key, key)}'] += 1
        weakness_by_session.append(counter)

    total_weaknesses = sum(weakness_by_session, Counter())
    high_frequency_weaknesses = [
        {'label': label, 'count': count}
        for label, count in total_weaknesses.most_common(5)
    ]
    improved_weaknesses = []
    if len(weakness_by_session) >= 2:
        split = max(1, len(weakness_by_session) // 2)
        earlier = sum(weakness_by_session[:split], Counter())
        recent = sum(weakness_by_session[split:], Counter())
        improved_weaknesses = [
            {
                'label': label,
                'earlier_count': count,
                'recent_count': recent.get(label, 0),
            }
            for label, count in earlier.most_common()
            if count > recent.get(label, 0)
        ][:5]

    all_task_rows = TrainingTask.query.filter_by(user_id=user_id).all()
    available_training_tasks = sum(
        task.status in ('todo', 'in_progress') for task in all_task_rows
    )
    materialized_sources = {task.source_session_id for task in all_task_rows}
    for standard_report in reports:
        if standard_report.session_id in materialized_sources:
            continue
        try:
            legacy_tasks = json.loads(standard_report.training_tasks or '[]')
        except (TypeError, ValueError):
            legacy_tasks = []
        if isinstance(legacy_tasks, list):
            available_training_tasks += sum(
                isinstance(task, dict)
                and task.get('status', 'todo') in ('todo', 'in_progress')
                for task in legacy_tasks
            )

    training_comparisons = []
    for task in sorted(
        (row for row in all_task_rows if row.status == 'completed'),
        key=lambda row: row.completed_at or row.updated_at,
        reverse=True,
    )[:10]:
        source_report = InterviewReport.get_by_session_id(task.source_session_id)
        training_report = InterviewReport.get_by_session_id(task.training_session_id) if task.training_session_id else None
        if not source_report or not training_report:
            continue
        comparable = source_report.scoring_version == training_report.scoring_version
        training_comparisons.append({
            'task_id': task.task_id,
            'title': task.snapshot().get('title') or '专项训练',
            'source_session_id': task.source_session_id,
            'training_session_id': task.training_session_id,
            'comparable': comparable,
            'scoring_version': source_report.scoring_version if comparable else None,
            'source_score': source_report.overall_score,
            'training_score': training_report.overall_score,
            'score_delta': (
                round(float(training_report.overall_score or 0) - float(source_report.overall_score or 0), 1)
                if comparable else None
            ),
        })
    position_names = {p.code: p.name for p in Position.list_all()}
    recent_scores = []
    for r in reports[:10]:
        sess = getattr(r, 'session', None)
        if not sess:
            continue
        date_str = sess.started_at.strftime('%Y-%m-%d') if hasattr(sess.started_at, 'strftime') else str(sess.started_at)
        recent_scores.append({
            'session_id': r.session_id,
            'date': date_str,
            'score': r.overall_score,
            'position': position_names.get(sess.position_code, sess.position_code),
        })
                             
    pos_scores = db.session.query(
        InterviewSession.position_code,
        func.avg(InterviewReport.overall_score).label('avg_score'),
        func.count(InterviewReport.id).label('cnt'),
    ).join(InterviewReport, InterviewSession.id == InterviewReport.session_id).filter(
        InterviewSession.user_id == user_id,
        InterviewSession.mode == 'standard',
        InterviewReport.overall_score.isnot(None),
    ).group_by(InterviewSession.position_code).all()
    scores_by_position = [
        {
            'position_code': row.position_code,
            'position_name': position_names.get(row.position_code, row.position_code),
            'avg_score': round(float(row.avg_score), 1) if row.avg_score else 0,
            'count': row.cnt,
        }
        for row in pos_scores
    ]
                              
    buckets = [0, 0, 0]
    for s in scores:
        if s is None:
            continue
        if s < 60:
            buckets[0] += 1
        elif s < 80:
            buckets[1] += 1
        else:
            buckets[2] += 1
    score_distribution = [
        {'range': '0-59', 'label': '待提升', 'count': buckets[0]},
        {'range': '60-79', 'label': '良好', 'count': buckets[1]},
        {'range': '80-100', 'label': '优秀', 'count': buckets[2]},
    ]
    return json_ok({
        'total_sessions': total_sessions,
        'standard_total_sessions': standard_total_sessions,
        'training_total_sessions': training_total_sessions,
        'training_completed_sessions': len(training_reports),
        'average_score': average_score,
        'best_score': best_score,
        'recent_5_avg': recent_5_avg,
        'average_score_trend': average_score_trend,
        'dimension_trend': dimension_trend,
        'question_type_trend': type_trend,
        'high_frequency_weaknesses': high_frequency_weaknesses,
        'improved_weaknesses': improved_weaknesses,
        'training_comparisons': training_comparisons,
        'available_training_tasks': available_training_tasks,
        'trend_position_code': trend_position_code,
        'trend_position_name': position_names.get(trend_position_code, trend_position_code) if trend_position_code else None,
        'trend_scoring_version': trend_scoring_version,
        'trend_uses_fallback': trend_uses_fallback,
        'recent_scores': recent_scores,
        'scores_by_position': scores_by_position,
        'score_distribution': score_distribution,
    })


@bp.route('/admin', methods=['GET'])
@login_required
@admin_required
def admin_dashboard():
    total_users = User.count()
    total_sessions = InterviewSession.count_total()
    total_sessions_7d = InterviewSession.count_recent_days(7)
    total_questions = Question.count()
    questions_count_by_position = Question.count_by_position()
    position_names = {p.code: p.name for p in Position.list_all()}
    questions_by_position = [
        {'position_code': code, 'position_name': position_names.get(code, code), 'count': count}
        for code, count in questions_count_by_position.items()
    ]
            
    type_counts = Question.count_by_type()
    questions_by_type = [
        {'type': k, 'type_name': QUESTION_TYPE_NAMES.get(k, k), 'count': type_counts.get(k, 0)}
        for k in (QuestionType.TECHNICAL, QuestionType.PROJECT, QuestionType.SCENARIO, QuestionType.BEHAVIORAL)
    ]
                    
    status_rows = db.session.query(
        InterviewSession.status,
        func.count(InterviewSession.id).label('cnt'),
    ).group_by(InterviewSession.status).all()
    sessions_by_status = [
        {'status': 'completed', 'label': '已完成', 'count': next((r.cnt for r in status_rows if r.status == 'completed'), 0)},
        {'status': 'in_progress', 'label': '进行中', 'count': next((r.cnt for r in status_rows if r.status == 'in_progress'), 0)},
    ]
             
    pos_session_rows = db.session.query(
        InterviewSession.position_code,
        func.count(InterviewSession.id).label('cnt'),
    ).group_by(InterviewSession.position_code).all()
    sessions_by_position = [
        {'position_code': row.position_code, 'position_name': position_names.get(row.position_code, row.position_code), 'count': row.cnt}
        for row in pos_session_rows
    ]
             
    since = datetime.utcnow() - timedelta(days=7)
    day_counts = (
        db.session.query(
            func.date(InterviewSession.started_at).label('day'),
            func.count(InterviewSession.id).label('cnt'),
        )
        .filter(InterviewSession.started_at >= since)
        .group_by(func.date(InterviewSession.started_at))
        .all()
    )
    by_date = {str(d.day): d.cnt for d in day_counts}
    sessions_by_day = []
    for i in range(7):
        d = (datetime.utcnow() - timedelta(days=6 - i)).date()
        sessions_by_day.append({'date': str(d), 'count': by_date.get(str(d), 0)})
    recent = InterviewSession.list_all_page(page=1, per_page=10)
    user_ids = {s.user_id for s in recent.items}
    users_map = {}
    if user_ids:
        for u in User.query.filter(User.id.in_(user_ids)).all():
            users_map[u.id] = u.display_name or u.username
    recent_activity = [
        {
            'session_id': s.id,
            'user_id': s.user_id,
            'user_name': users_map.get(s.user_id, '-'),
            'position_code': s.position_code,
            'position_name': position_names.get(s.position_code, s.position_code),
            'started_at': s.started_at.isoformat() if s.started_at else None,
            'status': s.status,
            'status_label': '已完成' if s.status == 'completed' else '进行中',
        }
        for s in recent.items
    ]
                                          
    score_rows = db.session.query(InterviewReport.overall_score).join(
        InterviewSession, InterviewSession.id == InterviewReport.session_id
    ).filter(InterviewReport.overall_score.isnot(None)).all()
    buckets = [0, 0, 0]
    for row in score_rows:
        s = row.overall_score
        if s is None:
            continue
        if s < 60:
            buckets[0] += 1
        elif s < 80:
            buckets[1] += 1
        else:
            buckets[2] += 1
    score_distribution = [
        {'range': '0-59', 'label': '待提升', 'count': buckets[0]},
        {'range': '60-79', 'label': '良好', 'count': buckets[1]},
        {'range': '80-100', 'label': '优秀', 'count': buckets[2]},
    ]
    return json_ok({
        'total_users': total_users,
        'total_sessions': total_sessions,
        'total_sessions_7d': total_sessions_7d,
        'total_questions': total_questions,
        'questions_count_by_position': questions_count_by_position,
        'questions_by_position': questions_by_position,
        'questions_by_type': questions_by_type,
        'sessions_by_status': sessions_by_status,
        'sessions_by_position': sessions_by_position,
        'sessions_by_day': sessions_by_day,
        'recent_activity': recent_activity,
        'score_distribution': score_distribution,
    })
