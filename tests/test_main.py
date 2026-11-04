"""Entrypoint tests. Provider/persistence coverage lives in the adjacent modules."""
import json

from tigerwatch.cli import main
from .fakes import FakeHTTP, Response, post


def test_demo_requires_no_credentials_or_network(monkeypatch, capsys):
    monkeypatch.delenv("META_ACCESS_TOKEN", raising=False)
    assert main(["--demo"]) == 0
    assert "SIMULATED" in capsys.readouterr().out


def test_stats_works_without_meta_credentials(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "local.sqlite3"))
    monkeypatch.delenv("META_ACCESS_TOKEN", raising=False)
    assert main(["--stats"]) == 0
    assert json.loads(capsys.readouterr().out) == {"queue": {}, "today": {}}


def test_monitor_missing_credentials_fails_without_secret_logging(monkeypatch, tmp_path):
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "local.sqlite3"))
    monkeypatch.delenv("META_ACCESS_TOKEN", raising=False)
    assert main([]) == 1


def test_local_image_uses_budget_and_sends_no_telegram(monkeypatch, tmp_path, capsys):
    from .fakes import jpeg
    from tigerwatch import cli
    http = FakeHTTP()
    image = tmp_path / "my-image.jpg"
    image.write_bytes(jpeg())
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "local.sqlite3"))
    monkeypatch.setenv("AI_ANALYSIS_RIGHTS_CONFIRMED", "true")
    monkeypatch.setattr(cli, "session", lambda: http)
    assert main(["--image", str(image)]) == 0
    assert json.loads(capsys.readouterr().out)["score_is_uncalibrated"]
    assert http.count("generateContent") == 1 and http.count("api.telegram.org") == 0


def test_meta_auth_failure_keeps_backlog(pipeline):
    from tigerwatch.errors import ProviderError
    import pytest
    p = pipeline
    p.state.enqueue([{"id": "1001", "source": "#tiger", "data": post()}])
    p.http.meta_failure = Response({"error": {"code": 190, "message": "meta-secret"}}, 400)
    with pytest.raises(ProviderError):
        p.run()
    assert p.state.inspect("1001")["status"] == "pending"
    assert p.http.count("generateContent") == 0


def test_retry_command_requires_ack_for_unknown_delivery(pipeline, monkeypatch):
    p = pipeline
    p.state.enqueue([{"id": "1001", "source": "#tiger", "data": post()}])
    item = p.state.claim()
    p.state.save(item, release=True, status="review", last_error="telegram:delivery_unknown", result={"match": True, "sending": True})
    monkeypatch.setenv("SQLITE_PATH", p.cfg.sqlite_path)
    assert main(["--retry-id", "1001"]) == 1
    assert p.state.inspect("1001")["status"] == "review"
    assert main(["--retry-id", "1001", "--acknowledge-duplicate-risk"]) == 0
    assert p.state.inspect("1001")["status"] == "retry"
