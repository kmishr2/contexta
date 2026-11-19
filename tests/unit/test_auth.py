import hashlib
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from app.core.settings import Settings
from app.main import create_app

TOKEN = 'a' * 40


def test_operator_identities_are_opt_in_and_no_auth_downgrade():
    configured = {'id': 'alice', 'role': 'analyst', 'token_sha256': hashlib.sha256(TOKEN.encode()).hexdigest(), 'connections': []}
    with pytest.raises(ValidationError):
        Settings(development_owner=True, identities=[configured])
    with TestClient(create_app(Settings(identities=[configured]))) as client:
        assert client.get('/me').status_code == 403
        assert client.get('/me', headers={'Authorization': 'Bearer ' + 'b' * 40}).status_code == 401
        assert client.get('/me', headers={'Authorization': 'Bearer ' + TOKEN}).json() == {'id': 'alice', 'role': 'analyst'}
        assert client.post('/connections', headers={'Authorization': 'Bearer ' + TOKEN}, json={}).status_code == 403
    with TestClient(create_app(Settings(development_owner=True))) as client:
        assert client.get('/me').json()['id'] == 'development-owner'
        assert client.get('/me', headers={'Authorization': 'Bearer invalid'}).status_code == 401
