"""API integration tests for LLM config router."""
import pytest

pytestmark = pytest.mark.skipif(
    True,  # Skip by default — requires running backend
    reason="Backend must be running for API tests",
)


@pytest.fixture
def api_client(api_base_url):
    import requests

    class Client:
        def __init__(self, base_url):
            self.base = base_url
            self.session = requests.Session()
            self.session.headers["Content-Type"] = "application/json"
            self.session.headers["Accept"] = "application/json"

        def get(self, path, **kwargs):
            return self.session.get(
                f"{self.base}{path}", timeout=10, **kwargs
            )

        def post(self, path, json=None, **kwargs):
            return self.session.post(
                f"{self.base}{path}", json=json, timeout=10, **kwargs
            )

        def put(self, path, json=None, **kwargs):
            return self.session.put(
                f"{self.base}{path}", json=json, timeout=10, **kwargs
            )

        def delete(self, path, **kwargs):
            return self.session.delete(
                f"{self.base}{path}", timeout=10, **kwargs
            )

    with Client(api_base_url) as client:
        yield client


class TestLLMConfigRouter:

    def test_list_configs_returns_200(self, api_client):
        resp = api_client.get("/llm/configs")
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert isinstance(data["data"], list)

    def test_create_and_delete_config(self, api_client):
        resp = api_client.post(
            "/llm/configs",
            json={
                "name": "Test Model",
                "provider_type": "openai_chat",
                "base_url": "https://api.openai.com/v1",
                "api_key": "sk-test-delete-me",
                "model": "gpt-4o",
            },
        )
        assert resp.status_code == 201
        config_id = resp.json()["data"]["id"]

        resp = api_client.get("/llm/configs")
        ids = [c["id"] for c in resp.json()["data"]]
        assert config_id in ids

        resp = api_client.delete(f"/llm/configs/{config_id}")
        assert resp.status_code == 200

    def test_api_key_masked_in_response(self, api_client):
        resp = api_client.post(
            "/llm/configs",
            json={
                "name": "Mask Test",
                "provider_type": "openai_chat",
                "base_url": "https://api.openai.com/v1",
                "api_key": "sk-secret-key-123",
                "model": "gpt-4o",
            },
        )
        data = resp.json()["data"]
        assert data["api_key"] == "****"
        api_client.delete(f"/llm/configs/{data['id']}")

    def test_set_default_config(self, api_client):
        """Create a config, set it as default, verify it is flagged."""
        resp = api_client.post(
            "/llm/configs",
            json={
                "name": "Default Test",
                "provider_type": "openai_chat",
                "base_url": "https://api.openai.com/v1",
                "api_key": "sk-test-default",
                "model": "gpt-4o",
            },
        )
        assert resp.status_code == 201
        config_id = resp.json()["data"]["id"]

        resp = api_client.put(f"/llm/configs/{config_id}/default")
        assert resp.status_code == 200
        assert resp.json()["data"]["is_default"] is True

        api_client.delete(f"/llm/configs/{config_id}")
