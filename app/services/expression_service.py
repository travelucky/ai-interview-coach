import re

from app.models.expression_metric import ExpressionMetric


FILLER_WORDS = (
    '就是说', '怎么说', '然后呢', '我觉得', '那个', '这个',
    '然后', '其实', '基本上', '对吧', '嗯', '呃', '额',
)


def _count_characters(text):
    return len(re.findall(r'[\u4e00-\u9fffA-Za-z0-9]', text or ''))


def _count_fillers(text):
    source = text or ''
    counts = {}
    occupied = [False] * len(source)
    for word in FILLER_WORDS:
        count = 0
        for match in re.finditer(re.escape(word), source):
            start, end = match.span()
            if any(occupied[start:end]):
                continue
            for index in range(start, end):
                occupied[index] = True
            count += 1
        if count:
            counts[word] = count
    return counts


def _count_repetitions(text):
    compact = re.sub(r'[^\u4e00-\u9fffA-Za-z0-9]', '', text or '')
    if len(compact) < 4:
        return 0
    matches = re.findall(r'([\u4e00-\u9fffA-Za-z0-9]{2,8})\1+', compact)
    return len(matches)


def analyze_expression(text, duration_ms):
    duration_ms = max(1, int(duration_ms or 0))
    character_count = _count_characters(text)
    filler_words = _count_fillers(text)
    filler_word_count = sum(filler_words.values())
    repetition_count = _count_repetitions(text)
    characters_per_minute = round(character_count * 60000 / duration_ms, 1)
    repetition_rate = round(repetition_count / max(1, character_count), 4)
    return {
        'duration_ms': duration_ms,
        'character_count': character_count,
        'characters_per_minute': characters_per_minute,
        'filler_word_count': filler_word_count,
        'filler_words': filler_words,
        'repetition_count': repetition_count,
        'repetition_rate': repetition_rate,
    }


def save_expression_metric(message_id, text, duration_ms, acoustic_metrics=None,
                           commit=True):
    values = analyze_expression(text, duration_ms)
    values['acoustic_metrics'] = acoustic_metrics or {}
    return ExpressionMetric.create_for_message(message_id, values, commit=commit)


def aggregate_expression_metrics(session_id):
    rows = ExpressionMetric.list_by_session(session_id)
    if not rows:
        return {
            'status': 'not_measured',
            'pace': '本场没有语音回答，未计算语速',
            'clarity': '当前仅对语音转写结果统计填充词和重复表达',
            'confidence': '未启用经项目样本校准的自信度推断，不参与评分',
        }

    total_duration_ms = sum(max(0, row.duration_ms or 0) for row in rows)
    total_characters = sum(max(0, row.character_count or 0) for row in rows)
    total_fillers = sum(max(0, row.filler_word_count or 0) for row in rows)
    total_repetitions = sum(max(0, row.repetition_count or 0) for row in rows)
    acoustic_pairs = [
        (row, row._loads(row.acoustic_metrics, {})) for row in rows
    ]
    acoustic_pairs = [pair for pair in acoustic_pairs if pair[1]]
    acoustic_rows = [pair[1] for pair in acoustic_pairs]
    pace_value = round(total_characters * 60000 / total_duration_ms, 1) if total_duration_ms else 0
    filler_rate = round(total_fillers / max(1, total_characters) * 100, 2)
    repetition_rate = round(total_repetitions / max(1, total_characters) * 100, 2)

    if pace_value < 140:
        pace_label = '偏慢'
    elif pace_value > 300:
        pace_label = '偏快'
    else:
        pace_label = '适中'

    if filler_rate <= 1 and repetition_rate <= 1:
        clarity_label = '较流畅'
    elif filler_rate <= 3 and repetition_rate <= 3:
        clarity_label = '基本流畅，可适当减少口头填充词'
    else:
        clarity_label = '建议减少填充词或重复表达'

    acoustic_summary = {'status': 'not_measured'}
    if acoustic_rows:
        acoustic_duration_ms = sum(
            max(1, row.duration_ms) for row, _item in acoustic_pairs
        )
        total_voice_duration = sum(
            max(0, item.get('voiced_duration_ms') or 0) for item in acoustic_rows
        )
        weighted_silence = sum(
            (item.get('silence_ratio') or 0) * max(1, row.duration_ms)
            for row, item in acoustic_pairs
        ) / max(1, acoustic_duration_ms)
        acoustic_summary = {
            'status': 'measured',
            'measurement_version': 'wav-rms-v1',
            'voiced_duration_seconds': round(total_voice_duration / 1000, 1),
            'silence_ratio': round(weighted_silence, 4),
            'pause_count': sum(item.get('pause_count') or 0 for item in acoustic_rows),
            'average_rms_dbfs': round(sum(item.get('rms_dbfs') or -90 for item in acoustic_rows) / len(acoustic_rows), 2),
            'average_volume_variation_db': round(sum(item.get('volume_variation_db') or 0 for item in acoustic_rows) / len(acoustic_rows), 2),
            'clipping_ratio': round(sum(item.get('clipping_ratio') or 0 for item in acoustic_rows) / len(acoustic_rows), 6),
            'average_snr_proxy_db': round(sum(item.get('snr_proxy_db') or 0 for item in acoustic_rows) / len(acoustic_rows), 2),
            'limitations': '声学值是可复算的信号统计，不推断情绪、自信度或人格',
        }
    return {
        'status': 'measured',
        'voice_answer_count': len(rows),
        'total_duration_seconds': round(total_duration_ms / 1000, 1),
        'character_count': total_characters,
        'characters_per_minute': pace_value,
        'pace': f'{pace_label}（{pace_value} 字/分钟）',
        'filler_word_count': total_fillers,
        'filler_rate_percent': filler_rate,
        'repetition_count': total_repetitions,
        'repetition_rate_percent': repetition_rate,
        'clarity': clarity_label,
        'confidence': '未启用经项目样本校准的自信度推断，不参与评分',
        'text_metrics': {
            'character_count': total_characters,
            'characters_per_minute': pace_value,
            'filler_word_count': total_fillers,
            'filler_rate_percent': filler_rate,
            'repetition_count': total_repetitions,
            'repetition_rate_percent': repetition_rate,
        },
        'acoustic_metrics': acoustic_summary,
        'model_inference': {
            'status': 'not_enabled',
            'reason': '尚无经本项目样本校准的情绪、清晰度或自信度模型',
        },
    }
