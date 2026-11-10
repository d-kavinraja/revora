import time
from types import SimpleNamespace

from app.github import auth


def test_app_jwt_uses_clock_skew_safe_exp(monkeypatch):
    captured = {}

    def fake_encode(payload, key, algorithm):
        captured.update(payload)
        assert key == "dummy-key"
        assert algorithm == "RS256"
        return "encoded"

    monkeypatch.setattr(
        auth,
        "settings",
        SimpleNamespace(
            GITHUB_APP_ID="4399003",
            GITHUB_APP_PRIVATE_KEY="dummy-key",
        ),
    )
    monkeypatch.setattr(auth.jwt, "encode", fake_encode)

    before = int(time.time())
    result = auth.GitHubAppAuth()._create_app_jwt()
    after = int(time.time())

    assert result == "encoded"
    assert captured["iss"] == "4399003"
    assert captured["iat"] <= before
    assert before - 60 <= captured["iat"] <= after - 60
    assert captured["exp"] - captured["iat"] == 9 * 60
    assert before + 8 * 60 <= captured["exp"] <= after + 8 * 60
