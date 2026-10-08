                       
from flask import jsonify, request


def json_ok(data=None, message=None, **kwargs):
    body = {'success': True}
    if data is not None:
        if isinstance(data, dict):
            body.update(data)
        else:
            body['data'] = data
    if message is not None:
        body['message'] = message
    body.update(kwargs)
    return jsonify(body)


def json_fail(message, code=400, error_code=None):
    stable_code = error_code or {
        400: 'bad_request',
        401: 'authentication_required',
        403: 'forbidden',
        404: 'not_found',
        409: 'conflict',
        413: 'payload_too_large',
        429: 'rate_limited',
        503: 'service_unavailable',
    }.get(code, 'request_failed')
    return jsonify(
        success=False,
        message=message,
        error={'code': stable_code, 'message': message},
    ), code


def get_json():
    if not request.is_json:
        return None
    return request.get_json(silent=True) or None
