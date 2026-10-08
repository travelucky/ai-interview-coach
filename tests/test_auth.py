def test_register_login_profile_and_logout(client):
    register_response = client.post(
        '/api/auth/register',
        json={
            'username': 'new_user',
            'password': 'StrongPass123!',
            'confirm_password': 'StrongPass123!',
            'display_name': '新用户',
        },
    )
    assert register_response.status_code == 201

    login_response = client.post(
        '/api/auth/login',
        json={'username': 'new_user', 'password': 'StrongPass123!'},
    )
    assert login_response.status_code == 200
    assert login_response.get_json()['user']['username'] == 'new_user'

    profile_response = client.get('/api/user/profile')
    assert profile_response.status_code == 200
    assert profile_response.get_json()['user']['display_name'] == '新用户'

    assert client.post('/api/auth/logout').status_code == 200
    assert client.get('/api/user/profile').status_code == 401


def test_login_rejects_invalid_password(client):
    response = client.post(
        '/api/auth/login',
        json={'username': 'admin', 'password': 'wrong-password'},
    )
    assert response.status_code == 401


def test_registration_enforces_password_and_display_name_limits(client):
    weak = client.post(
        '/api/auth/register',
        json={
            'username': 'weak_user',
            'password': 'short7',
            'confirm_password': 'short7',
        },
    )
    assert weak.status_code == 400
    assert '8-128' in weak.get_json()['message']

    long_name = client.post(
        '/api/auth/register',
        json={
            'username': 'long_name_user',
            'password': 'StrongPass123!',
            'confirm_password': 'StrongPass123!',
            'display_name': 'x' * 65,
        },
    )
    assert long_name.status_code == 400
    assert '64' in long_name.get_json()['message']


def test_cross_origin_write_is_rejected_but_same_origin_is_allowed(client):
    payload = {
        'username': 'origin_user',
        'password': 'StrongPass123!',
        'confirm_password': 'StrongPass123!',
    }

    rejected = client.post(
        '/api/auth/register',
        json=payload,
        headers={'Origin': 'https://malicious.example'},
    )
    assert rejected.status_code == 403

    accepted = client.post(
        '/api/auth/register',
        json=payload,
        headers={'Origin': 'http://localhost'},
    )
    assert accepted.status_code == 201


def test_login_rate_limit_blocks_repeated_password_guessing(client):
    register_response = client.post(
        '/api/auth/register',
        json={
            'username': 'rate_limit_user',
            'password': 'StrongPass123!',
            'confirm_password': 'StrongPass123!',
        },
    )
    assert register_response.status_code == 201

    for _ in range(5):
        response = client.post(
            '/api/auth/login',
            json={'username': 'rate_limit_user', 'password': 'wrong-password'},
        )
        assert response.status_code == 401

    blocked = client.post(
        '/api/auth/login',
        json={'username': 'rate_limit_user', 'password': 'StrongPass123!'},
    )
    assert blocked.status_code == 429


def test_user_can_export_then_delete_only_their_own_data(app, registered_client):
    start_response = registered_client.post(
        '/api/interview/start',
        json={'position_code': 'java_backend'},
    )
    assert start_response.status_code == 200
    session_id = start_response.get_json()['session_id']

    export_response = registered_client.get('/api/user/data-export')
    assert export_response.status_code == 200
    exported = export_response.get_json()['export']
    assert exported['profile']['username'] == 'candidate'
    assert exported['interviews'][0]['session']['id'] == session_id
    assert 'password_hash' not in exported['profile']
    assert exported['excluded'] == [
        'password_hash', 'session_cookie', 'service_credentials'
    ]

    rejected = registered_client.delete(
        '/api/user/account', json={'password': 'wrong-password'}
    )
    assert rejected.status_code == 403

    deleted = registered_client.delete(
        '/api/user/account', json={'password': 'Candidate123!'}
    )
    assert deleted.status_code == 200
    assert registered_client.get('/api/user/profile').status_code == 401

    with app.app_context():
        from app.models import InterviewSession, User

        assert User.get_by_username('candidate') is None
        assert InterviewSession.get_by_id(session_id) is None
