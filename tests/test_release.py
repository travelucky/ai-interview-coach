from scripts.verify_release import REQUIRED, verify


def _minimal_release_entries():
    return {name: b'placeholder' for name in REQUIRED}


def test_release_verifier_accepts_minimal_clean_package():
    assert verify(_minimal_release_entries()) == []


def test_release_verifier_accepts_single_archive_root_prefix():
    prefixed = {
        'ai-interview-mvp/' + name: data
        for name, data in _minimal_release_entries().items()
    }

    assert verify(prefixed) == []


def test_release_verifier_rejects_runtime_data_secret_and_cdn():
    entries = _minimal_release_entries()
    entries['instance/interview.db'] = b'user records'
    entries['app/config.js'] = b'const key = "' + b'sk-' + b'123456789012345678901234";'
    entries['app/templates/page.html'] = b'https://cdn.' + b'jsdelivr.net/npm/example'

    errors = verify(entries)

    assert any('runtime' in item for item in errors)
    assert any('OpenAI-style key' in item for item in errors)
    assert any('CDN' in item for item in errors)
