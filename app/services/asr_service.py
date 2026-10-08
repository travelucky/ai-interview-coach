                       
import io
import json
import base64
import math
import hashlib
import hmac
import logging
import threading
import time
from datetime import datetime
from urllib.parse import urlencode
from wsgiref.handlers import format_date_time
from time import mktime
from flask import current_app
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

logger = logging.getLogger(__name__)

RATE = 16000
CHUNK = 1280


class AudioValidationError(ValueError):
    pass


def create_transcription_receipt(wav_bytes: bytes, transcript: str) -> str:
    """Bind an ASR result to the exact audio so confirmation avoids a second call."""
    serializer = URLSafeTimedSerializer(
        current_app.secret_key,
        salt='interview-transcription-v1',
    )
    return serializer.dumps({
        'audio_sha256': hashlib.sha256(wav_bytes).hexdigest(),
        'transcript': transcript,
    })


def read_transcription_receipt(wav_bytes: bytes, receipt: str):
    if not receipt:
        return None
    serializer = URLSafeTimedSerializer(
        current_app.secret_key,
        salt='interview-transcription-v1',
    )
    try:
        payload = serializer.loads(
            receipt,
            max_age=current_app.config.get('ASR_RECEIPT_MAX_AGE_SECONDS', 900),
        )
    except (BadSignature, SignatureExpired, TypeError, ValueError):
        return None
    if payload.get('audio_sha256') != hashlib.sha256(wav_bytes).hexdigest():
        return None
    return (payload.get('transcript') or '').strip() or None


def _get_xfyun_credentials():
    return (
        (current_app.config.get('XFYUN_APP_ID') or '').strip(),
        (current_app.config.get('XFYUN_API_KEY') or '').strip(),
        (current_app.config.get('XFYUN_API_SECRET') or '').strip(),
    )


def is_wav_format(data: bytes) -> bool:
    return len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WAVE"


def inspect_wav_bytes(wav_bytes: bytes) -> dict:
    if not is_wav_format(wav_bytes):
        raise AudioValidationError('仅支持 WAV 格式音频')
    try:
        import wave
        with io.BytesIO(wav_bytes) as bio:
            with wave.open(bio, 'rb') as wf:
                channels = wf.getnchannels()
                sample_width = wf.getsampwidth()
                sample_rate = wf.getframerate()
                frame_count = wf.getnframes()
    except Exception as error:
        raise AudioValidationError('WAV 音频无法解析') from error
    duration_ms = round(frame_count * 1000 / sample_rate) if sample_rate else 0
    return {
        'channels': channels,
        'sample_width': sample_width,
        'sample_rate': sample_rate,
        'frame_count': frame_count,
        'duration_ms': duration_ms,
        'size_bytes': len(wav_bytes),
    }


def validate_wav_bytes(wav_bytes: bytes, max_size_bytes: int, max_duration_ms: int,
                       min_duration_ms: int = 500) -> dict:
    if not wav_bytes:
        raise AudioValidationError('语音文件为空，请重新录制')
    if len(wav_bytes) > max_size_bytes:
        raise AudioValidationError('录音文件过大，请缩短回答后重试')
    metadata = inspect_wav_bytes(wav_bytes)
    if metadata['channels'] != 1:
        raise AudioValidationError('录音必须为单声道音频')
    if metadata['sample_width'] != 2:
        raise AudioValidationError('录音必须为 16 位音频')
    if metadata['sample_rate'] != RATE:
        raise AudioValidationError('录音采样率必须为 16kHz')
    if metadata['duration_ms'] < min_duration_ms:
        raise AudioValidationError('录音时间过短，请至少说话 1 秒')
    if metadata['duration_ms'] > max_duration_ms:
        raise AudioValidationError(
            f'单次录音不能超过 {max_duration_ms // 1000} 秒，请缩短回答后重试'
        )
    return metadata


def analyze_wav_acoustics(wav_bytes: bytes, frame_ms: int = 20) -> dict:
    """Return deterministic signal measurements; no emotion/confidence inference."""
    import array
    import wave

    metadata = inspect_wav_bytes(wav_bytes)
    if metadata['channels'] != 1 or metadata['sample_width'] != 2:
        raise AudioValidationError('声学分析仅支持单声道 16 位 WAV')
    with io.BytesIO(wav_bytes) as bio:
        with wave.open(bio, 'rb') as wav:
            pcm = wav.readframes(wav.getnframes())
    samples = array.array('h')
    samples.frombytes(pcm)
    if not samples:
        raise AudioValidationError('录音没有可分析的采样数据')

    sample_rate = metadata['sample_rate']
    frame_size = max(1, round(sample_rate * frame_ms / 1000))
    frame_rms = []
    clipping_samples = 0
    peak = 0
    for sample in samples:
        absolute = abs(int(sample))
        peak = max(peak, absolute)
        if absolute >= 32760:
            clipping_samples += 1
    for start in range(0, len(samples), frame_size):
        frame = samples[start:start + frame_size]
        if not frame:
            continue
        square_mean = sum(float(value) ** 2 for value in frame) / len(frame)
        frame_rms.append(math.sqrt(square_mean) / 32768.0)

    def dbfs(value):
        return round(20 * math.log10(max(value, 1e-9)), 2)

    sorted_rms = sorted(frame_rms)
    noise_index = min(len(sorted_rms) - 1, max(0, int(len(sorted_rms) * 0.2)))
    noise_rms = sorted_rms[noise_index]
    noise_dbfs = 20 * math.log10(max(noise_rms, 1e-9))
    loudest_frame_dbfs = 20 * math.log10(max(max(frame_rms), 1e-9))
    # When the clip contains no quiet baseline (for example a constant test
    # tone), treating its 20th percentile as noise would place the threshold
    # above the signal itself. Fall back to a relative threshold in that case.
    if loudest_frame_dbfs - noise_dbfs < 6:
        threshold_dbfs = noise_dbfs - 6
    else:
        threshold_dbfs = noise_dbfs + 8
    threshold_dbfs = max(-55.0, min(-6.0, threshold_dbfs))
    threshold_rms = 10 ** (threshold_dbfs / 20)
    voiced_flags = [value >= threshold_rms for value in frame_rms]
    voiced_values = [value for value, voiced in zip(frame_rms, voiced_flags) if voiced]
    silent_values = [value for value, voiced in zip(frame_rms, voiced_flags) if not voiced]
    frame_duration_ms = frame_size * 1000 / sample_rate
    voiced_duration_ms = round(sum(voiced_flags) * frame_duration_ms)
    silence_ratio = round(1 - sum(voiced_flags) / max(1, len(voiced_flags)), 4)

    pause_lengths = []
    run = 0
    for index, voiced in enumerate(voiced_flags):
        if not voiced:
            run += 1
            continue
        if run and index - run > 0:
            pause_ms = round(run * frame_duration_ms)
            if pause_ms >= 300:
                pause_lengths.append(pause_ms)
        run = 0
    mean_rms = sum(frame_rms) / len(frame_rms)
    mean_dbfs = dbfs(mean_rms)
    frame_db_values = [dbfs(value) for value in voiced_values] or [mean_dbfs]
    mean_voiced_db = sum(frame_db_values) / len(frame_db_values)
    volume_std_db = round(math.sqrt(
        sum((value - mean_voiced_db) ** 2 for value in frame_db_values)
        / len(frame_db_values)
    ), 2)
    voiced_rms = sum(voiced_values) / len(voiced_values) if voiced_values else 0
    silent_rms = sum(silent_values) / len(silent_values) if silent_values else noise_rms
    snr_proxy_db = round(
        max(0.0, min(60.0, 20 * math.log10(
            max(voiced_rms, 1e-9) / max(silent_rms, 1e-9)
        ))),
        2,
    ) if voiced_values else 0.0
    return {
        'measurement_version': 'wav-rms-v1',
        'frame_ms': frame_ms,
        'voiced_duration_ms': voiced_duration_ms,
        'silence_ratio': silence_ratio,
        'pause_count': len(pause_lengths),
        'average_pause_ms': (
            round(sum(pause_lengths) / len(pause_lengths))
            if pause_lengths else 0
        ),
        'rms_dbfs': mean_dbfs,
        'volume_variation_db': volume_std_db,
        'peak_dbfs': dbfs(peak / 32768.0),
        'clipping_ratio': round(clipping_samples / len(samples), 6),
        'snr_proxy_db': snr_proxy_db,
        'silence_threshold_dbfs': round(threshold_dbfs, 2),
        'limitations': 'RMS 与信噪比为录音信号代理指标，不等同于情绪、自信度或发音准确度',
    }


def _create_url(api_key: str, api_secret: str):
    if not api_key or not api_secret:
        return None
    host = "ws-api.xfyun.cn"
    uri = "/v2/iat"
    url = "wss://" + host + uri
    now = datetime.now()
    date = format_date_time(mktime(now.timetuple()))
    signature_origin = f"host: {host}\ndate: {date}\nGET {uri} HTTP/1.1"
    signature_sha = hmac.new(
        api_secret.encode(),
        signature_origin.encode(),
        digestmod=hashlib.sha256,
    ).digest()
    signature = base64.b64encode(signature_sha).decode()
    authorization_origin = (
        f'api_key="{api_key}", algorithm="hmac-sha256", '
        f'headers="host date request-line", signature="{signature}"'
    )
    authorization = base64.b64encode(authorization_origin.encode()).decode()
    params = {"authorization": authorization, "date": date, "host": host}
    return url + "?" + urlencode(params)


def _extract_pcm_from_wav(wav_bytes: bytes) -> bytes:
    if len(wav_bytes) < 44:
        return b""
    try:
        import wave
        with io.BytesIO(wav_bytes) as bio:
            with wave.open(bio, "rb") as wf:
                nch, sampwidth, rate = wf.getnchannels(), wf.getsampwidth(), wf.getframerate()
                if nch != 1 or sampwidth != 2:
                    logger.warning("ASR: 仅支持单声道16bit，当前 channels=%s sampwidth=%s", nch, sampwidth)
                    return b""
                if rate != RATE:
                    logger.warning("ASR: 讯飞要求 16k，当前 rate=%s，可能识别异常", rate)
                return wf.readframes(wf.getnframes())
    except Exception as e:
        logger.warning("ASR: 解析 WAV 失败 %s，尝试跳过 44 字节", e)
    return wav_bytes[44:]


def recognize_wav_bytes(wav_bytes: bytes) -> str:
    if not wav_bytes or len(wav_bytes) < 44:
        logger.warning("ASR: 输入过短 len=%s", len(wav_bytes) if wav_bytes else 0)
        return ""
    appid, api_key, api_secret = _get_xfyun_credentials()
    if not appid or not api_key or not api_secret:
        logger.warning("ASR: 未配置讯飞凭据，请在 .env 中配置 XFYUN_APP_ID/XFYUN_API_KEY/XFYUN_API_SECRET")
        return ""
    url = _create_url(api_key, api_secret)
    if not url:
        return ""
    pcm = _extract_pcm_from_wav(wav_bytes)
    if not pcm:
        return ""

    result_list = []
    connection_state = {'error': None, 'completed': False}

    def on_message(ws, message):
        try:
            data = json.loads(message)
            if data.get("code") != 0:
                connection_state['error'] = f"code={data.get('code')} message={data.get('message') or ''}"
                logger.warning("ASR: 讯飞返回 %s", connection_state['error'])
                ws.close()
                return
            d = data.get("data") or {}
            if "result" in d and "ws" in d["result"]:
                for ws_item in d["result"]["ws"]:
                    for cw in ws_item.get("cw", []):
                        result_list.append(cw.get("w", ""))
            if d.get('status') == 2:
                connection_state['completed'] = True
                ws.close()
        except Exception as e:
            logger.warning("ASR: 解析讯飞消息异常 %s", e)

    def on_error(ws, error):
        connection_state['error'] = str(error)
        logger.warning("ASR: WebSocket 错误 %s", error)

    def on_close(ws, close_status_code, close_msg):
        logger.debug("ASR: WebSocket 连接关闭")

    def on_open(ws):
        def send_audio():
            try:
                                               
                first_chunk = pcm[:CHUNK]
                remaining = pcm[CHUNK:]
                frame0 = {
                    "common": {"app_id": appid},
                    "business": {
                        "domain": "iat",
                        "language": "zh_cn",
                        "accent": "mandarin",
                        "vad_eos": 5000,
                    },
                    "data": {
                        "status": 0,
                        "format": "audio/L16;rate=16000",
                        "audio": base64.b64encode(first_chunk).decode(),
                        "encoding": "raw",
                    },
                }
                ws.send(json.dumps(frame0))
                              
                offset = 0
                while offset < len(remaining):
                    chunk = remaining[offset: offset + CHUNK]
                    offset += len(chunk)
                    frame = {
                        "data": {
                            "status": 1,
                            "format": "audio/L16;rate=16000",
                            "audio": base64.b64encode(chunk).decode(),
                            "encoding": "raw",
                        },
                    }
                    ws.send(json.dumps(frame))
                    time.sleep(0.04)
                              
                end_frame = {
                    "data": {
                        "status": 2,
                        "format": "audio/L16;rate=16000",
                        "audio": "",
                        "encoding": "raw",
                    },
                }
                ws.send(json.dumps(end_frame))
            except Exception as e:
                connection_state['error'] = str(e)
                logger.warning("ASR: 发送音频异常 %s", e)

        threading.Thread(target=send_audio, daemon=True).start()

    try:
        import websocket
    except ImportError:
        logger.warning("ASR: 未安装 websocket-client，请执行 pip install websocket-client")
        return ""

    ws = websocket.WebSocketApp(
        url,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close,
        on_open=on_open,
    )
    audio_seconds = len(pcm) / (RATE * 2)
    configured_timeout = current_app.config.get('ASR_TIMEOUT_SECONDS', 20)
    total_timeout = max(float(configured_timeout), audio_seconds + 10)
    timeout_timer = threading.Timer(total_timeout, ws.close)
    timeout_timer.daemon = True
    timeout_timer.start()
    try:
        ws.run_forever(ping_interval=15, ping_timeout=5)
    finally:
        timeout_timer.cancel()
    text = "".join(result_list).strip()
    if connection_state['error']:
        logger.warning('ASR: 识别未完成：%s', connection_state['error'])
    if not text:
        logger.debug("ASR: 讯飞识别结果为空（可能太短或静音）")
    return text
