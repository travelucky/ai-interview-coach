def test_health_reports_database_and_optional_services(client):
    response = client.get('/api/health')

    assert response.status_code == 200
    payload = response.get_json()
    assert payload['success'] is True
    assert payload['status'] == 'ok'
    assert payload['services']['database']['status'] == 'ok'
    assert payload['services']['llm']['configured'] is False
    assert payload['services']['asr']['configured'] is False
    assert payload['services']['embedding']['configured'] is False
    assert payload['services']['embedding']['indexed'] == 0
    assert payload['services']['embedding']['pending'] == payload['knowledge']
    assert payload['positions'] == 1
    assert payload['questions'] == 5


def test_responses_include_browser_security_headers(client):
    response = client.get('/api/health')

    assert response.headers['X-Content-Type-Options'] == 'nosniff'
    assert response.headers['X-Frame-Options'] == 'DENY'
    assert response.headers['Referrer-Policy'] == 'same-origin'
    assert response.headers['Cache-Control'] == 'no-store'
    assert "default-src 'self'" in response.headers['Content-Security-Policy']
    assert 'microphone=(self)' in response.headers['Permissions-Policy']


def test_frontend_dependencies_are_served_locally(client):
    login_page = client.get('/login')
    html = login_page.get_data(as_text=True)

    assert login_page.status_code == 200
    assert 'cdn.jsdelivr.net' not in html
    assert client.get('/static/vendor/bootstrap/bootstrap.min.css').status_code == 200
    assert client.get('/static/vendor/bootstrap/bootstrap.bundle.min.js').status_code == 200
    assert client.get('/static/vendor/chart/chart.umd.min.js').status_code == 200


def test_api_errors_are_json_and_large_payloads_are_rejected(client):
    missing = client.get('/api/does-not-exist')
    assert missing.status_code == 404
    assert missing.is_json
    assert missing.get_json()['error']['code'] == 'not_found'

    oversized = client.post(
        '/api/auth/register',
        data=b'x' * (6 * 1024 * 1024 + 1),
        content_type='application/json',
    )
    assert oversized.status_code == 413
    assert oversized.get_json()['error']['code'] == 'payload_too_large'
