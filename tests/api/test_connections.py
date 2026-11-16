from fastapi.testclient import TestClient
from app.main import create_app


def test_connection_routes_are_disabled_by_default():
    with TestClient(create_app()) as client:
        assert client.get('/connections/00000000-0000-0000-0000-000000000000/catalog').status_code == 403
