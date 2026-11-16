from fastapi.testclient import TestClient
from app.main import create_app


def test_local_review_page_and_connection_access():
    with TestClient(create_app()) as client:
        page = client.get('/')
        assert page.status_code == 200
        assert 'Give your data meaning.' in page.text
        assert client.get('/connections').status_code == 403
        assert client.get('/connections/00000000-0000-0000-0000-000000000000/metrics').status_code == 403
