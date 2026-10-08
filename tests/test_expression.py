import io
import math
import struct
import wave

import pytest

from app import db
from app.services.asr_service import (
    AudioValidationError,
    analyze_wav_acoustics,
    validate_wav_bytes,
)
from app.services.expression_service import analyze_expression


def _wav_bytes(duration_ms=1000, sample_rate=16000, channels=1, sample_width=2):
    buffer = io.BytesIO()
    frame_count = round(sample_rate * duration_ms / 1000)
    with wave.open(buffer, 'wb') as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(sample_width)
        wav.setframerate(sample_rate)
        wav.writeframes(b'\x00' * frame_count * channels * sample_width)
    return buffer.getvalue()


def _pattern_wav(segments, sample_rate=16000):
    """Build deterministic mono 16-bit WAV from (duration_ms, amplitude)."""
    samples = []
    offset = 0
    for duration_ms, amplitude in segments:
        count = round(sample_rate * duration_ms / 1000)
        for index in range(count):
            value = amplitude * math.sin(2 * math.pi * 220 * (offset + index) / sample_rate)
            samples.append(max(-32768, min(32767, round(value * 32767))))
        offset += count
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(struct.pack('<' + ('h' * len(samples)), *samples))
    return buffer.getvalue()


def test_expression_metrics_are_reproducible():
    result = analyze_expression('嗯，这个方案然后然后说明核心原理。', 6000)

    assert result['duration_ms'] == 6000
    assert result['character_count'] > 0
    assert result['characters_per_minute'] > 0
    assert result['filler_word_count'] >= 3
    assert result['repetition_count'] >= 1


def test_wav_validation_checks_format_and_duration():
    metadata = validate_wav_bytes(
        _wav_bytes(duration_ms=1200),
        max_size_bytes=100000,
        max_duration_ms=60000,
    )
    assert metadata['sample_rate'] == 16000
    assert metadata['channels'] == 1
    assert metadata['duration_ms'] == 1200

    with pytest.raises(AudioValidationError, match='过短'):
        validate_wav_bytes(
            _wav_bytes(duration_ms=200),
            max_size_bytes=100000,
            max_duration_ms=60000,
        )


def test_acoustic_measurements_are_reproducible_for_fixed_wav_samples():
    silence = analyze_wav_acoustics(_wav_bytes(duration_ms=1000))
    assert silence['measurement_version'] == 'wav-rms-v1'
    assert silence['silence_ratio'] == 1.0
    assert silence['voiced_duration_ms'] == 0
    assert silence['pause_count'] == 0

    speech_with_pause = analyze_wav_acoustics(_pattern_wav([
        (1000, 0.25),
        (500, 0.0),
        (1000, 0.25),
    ]))
    assert 0.15 <= speech_with_pause['silence_ratio'] <= 0.25
    assert speech_with_pause['pause_count'] == 1
    assert speech_with_pause['average_pause_ms'] == 500
    assert speech_with_pause['voiced_duration_ms'] == 2000

    quiet = analyze_wav_acoustics(_pattern_wav([(1000, 0.005)]))
    assert quiet['voiced_duration_ms'] == 1000
    assert quiet['rms_dbfs'] < -45
    assert quiet['clipping_ratio'] == 0

    clipped = analyze_wav_acoustics(_pattern_wav([(1000, 2.0)]))
    assert clipped['clipping_ratio'] > 0.5
    assert clipped['peak_dbfs'] >= -0.01


def test_transcribe_preview_does_not_advance_interview(
        registered_client, monkeypatch):
    calls = {'count': 0}

    def recognize(_audio):
        calls['count'] += 1
        return '这是尚未提交的语音转写。'

    monkeypatch.setattr(
        'app.services.asr_service.recognize_wav_bytes',
        recognize,
    )
    start = registered_client.post(
        '/api/interview/start',
        json={'position_code': 'java_backend'},
    ).get_json()
    session_id = start['session_id']
    before = registered_client.get(
        f'/api/interview/sessions/{session_id}/state'
    ).get_json()

    wav_bytes = _pattern_wav([(1200, 0.2)])
    preview = registered_client.post(
        '/api/interview/transcribe',
        data={'audio': (io.BytesIO(wav_bytes), 'draft.wav')},
        content_type='multipart/form-data',
    )
    assert preview.status_code == 200
    payload = preview.get_json()
    assert payload['transcript'] == '这是尚未提交的语音转写。'
    assert payload['acoustic_metrics']['measurement_version'] == 'wav-rms-v1'

    after = registered_client.get(
        f'/api/interview/sessions/{session_id}/state'
    ).get_json()
    assert after['progress'] == before['progress']
    assert after['messages'] == before['messages']

    confirmed = registered_client.post(
        f'/api/interview/{session_id}/reply',
        data={
            'audio': (io.BytesIO(wav_bytes), 'draft.wav'),
            'confirmed_content': '这是用户确认后的回答。',
            'transcription_receipt': payload['transcription_receipt'],
            'request_id': 'voice-confirm-receipt-001',
        },
        content_type='multipart/form-data',
    )
    assert confirmed.status_code == 200
    assert confirmed.get_json()['user_content'] == '这是用户确认后的回答。'
    assert calls['count'] == 1


def test_asr_timeout_returns_retryable_error_without_advancing_session(
        registered_client, monkeypatch):
    monkeypatch.setattr(
        'app.services.asr_service.recognize_wav_bytes',
        lambda _audio: (_ for _ in ()).throw(TimeoutError('provider timeout')),
    )
    session_id = registered_client.post(
        '/api/interview/start', json={'position_code': 'java_backend'}
    ).get_json()['session_id']
    before = registered_client.get(
        f'/api/interview/sessions/{session_id}/state'
    ).get_json()

    response = registered_client.post(
        f'/api/interview/{session_id}/reply',
        data={
            'audio': (io.BytesIO(_pattern_wav([(1000, 0.2)])), 'timeout.wav'),
            'request_id': 'asr-timeout-001',
        },
        content_type='multipart/form-data',
    )

    assert response.status_code == 503
    assert '文字输入' in response.get_json()['message']
    after = registered_client.get(
        f'/api/interview/sessions/{session_id}/state'
    ).get_json()
    assert after['progress'] == before['progress']
    assert after['messages'] == before['messages']


def test_audio_reply_saves_expression_metric_and_report(
    app,
    registered_client,
    monkeypatch,
):
    monkeypatch.setattr(
        'app.services.asr_service.recognize_wav_bytes',
        lambda _audio: '嗯，这个回答说明核心原理，然后给出实际案例。',
    )
    start_response = registered_client.post(
        '/api/interview/start',
        json={'position_code': 'java_backend'},
    )
    session_id = start_response.get_json()['session_id']

    audio_response = registered_client.post(
        f'/api/interview/{session_id}/reply',
        data={
            'audio': (io.BytesIO(_pattern_wav([(5000, 0.2)])), 'answer.wav'),
            'request_id': 'voice-request-001',
            'duration_ms': '5000',
            'confirmed_content': '这个回答说明核心原理，并给出实际案例。',
        },
        content_type='multipart/form-data',
    )
    assert audio_response.status_code == 200
    metric = audio_response.get_json()['expression_metric']
    assert metric['duration_ms'] == 5000
    assert metric['character_count'] > 0
    assert metric['characters_per_minute'] > 0
    assert metric['filler_word_count'] == 1
    assert metric['acoustic_metrics']['measurement_version'] == 'wav-rms-v1'

    message_id = audio_response.get_json()['user_message_id']
    state = registered_client.get(
        f'/api/interview/sessions/{session_id}/state'
    ).get_json()
    voice_message = next(
        item for item in state['messages'] if item['id'] == message_id
    )
    assert voice_message['answer_source'] == 'voice'
    assert voice_message['content'] == '这个回答说明核心原理，并给出实际案例。'
    assert voice_message['raw_transcript'] == '嗯，这个回答说明核心原理，然后给出实际案例。'

    for answer_number in range(2):
        response = registered_client.post(
            f'/api/interview/{session_id}/reply',
            json={'content': f'第 {answer_number + 2} 个回答说明核心原理和实际案例。'},
        )
        assert response.status_code == 200

    finish_response = registered_client.post(f'/api/interview/{session_id}/finish')
    assert finish_response.status_code == 200
    report = registered_client.get(
        f'/api/interview/sessions/{session_id}/report'
    ).get_json()['report']
    expression = report['expression_analysis']
    assert expression['status'] == 'measured'
    assert expression['voice_answer_count'] == 1
    assert expression['total_duration_seconds'] == 5.0
    assert expression['filler_word_count'] == 1
    assert expression['acoustic_metrics']['status'] == 'measured'
    assert expression['model_inference']['status'] == 'not_enabled'

    from app.models import ExpressionMetric, InterviewSession, QuestionScore
    from app.models.interview_session import SessionStatus
    with app.app_context():
        assert ExpressionMetric.query.count() == 1
        assert QuestionScore.query.filter_by(session_id=session_id).count() == 3
        assert InterviewSession.get_by_id(session_id).status == SessionStatus.COMPLETED


def test_editing_voice_answer_keeps_raw_transcript_and_recalculates_text_metrics(
        app, registered_client, monkeypatch):
    raw_transcript = '嗯，这个这个方案然后然后说明核心原理。'
    monkeypatch.setattr(
        'app.services.asr_service.recognize_wav_bytes',
        lambda _audio: raw_transcript,
    )
    monkeypatch.setattr(
        'app.services.followup_service.decide_followup_or_next',
        lambda *_args, **_kwargs: ('follow_up', '请继续补充。'),
    )
    start_response = registered_client.post(
        '/api/interview/start',
        json={'position_code': 'java_backend'},
    )
    session_id = start_response.get_json()['session_id']
    audio_response = registered_client.post(
        f'/api/interview/{session_id}/reply',
        data={
            'audio': (io.BytesIO(_wav_bytes(duration_ms=5000)), 'answer.wav'),
            'request_id': 'voice-edit-001',
            'duration_ms': '5000',
        },
        content_type='multipart/form-data',
    )
    assert audio_response.status_code == 200
    before_metric = audio_response.get_json()['expression_metric']
    message_id = audio_response.get_json()['user_message_id']

    confirmed_text = '该方案说明核心原理、应用步骤以及实际案例。'
    update_response = registered_client.patch(
        f'/api/interview/{session_id}/messages/{message_id}',
        json={'content': confirmed_text},
    )
    assert update_response.status_code == 200
    payload = update_response.get_json()
    after_metric = payload['expression_metric']
    assert payload['raw_transcript'] == raw_transcript
    assert after_metric['duration_ms'] == before_metric['duration_ms'] == 5000
    assert after_metric['character_count'] != before_metric['character_count']
    assert after_metric['filler_word_count'] == 0

    from app.models import ExpressionMetric, InterviewMessage
    with app.app_context():
        message = db.session.get(InterviewMessage, message_id)
        metric = ExpressionMetric.query.filter_by(message_id=message_id).one()
        assert message.content == confirmed_text
        assert message.raw_transcript == raw_transcript
        assert message.answer_source == 'voice'
        assert metric.duration_ms == 5000
        assert metric.character_count == after_metric['character_count']
