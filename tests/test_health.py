import json
from dataclasses import replace

import pytest

from tigerwatch import cli
from tigerwatch.errors import ProviderError, SetupError
from tigerwatch.health import build_summary, run_monitor, send_digest
from .fakes import Response


def test_no_run_is_distinct_from_no_matches(pipeline):
    p = pipeline
    summary = build_summary(p.cfg, p.state, clock=p.clock)
    assert summary["status"] == "not_run" and summary["last_run"] is None
    assert summary["budgets"]["ai_remaining"] == p.cfg.ai_day


def configured(p):
    return replace(p.cfg, analysis_rights_confirmed=True)


def fake_worker(metrics):
    class Stub:
        def __init__(self, *args):
            pass
        def run(self, *, discover):
            return metrics
    return Stub


def test_completed_empty_run_is_healthy_not_failure(pipeline):
    p = pipeline
    cfg = configured(p)
    run_monitor(cfg, p.state, None, p.http, worker_factory=fake_worker({}), clock=p.clock)
    summary = build_summary(cfg, p.state, clock=p.clock)
    assert summary["status"] == "completed" and summary["last_run"]["metrics"] == {}


def test_partial_run_and_stale_detection(pipeline):
    p = pipeline
    cfg = configured(p)
    run_monitor(cfg, p.state, None, p.http, worker_factory=fake_worker({"source_errors": 1}), clock=p.clock)
    assert build_summary(cfg, p.state, clock=p.clock)["status"] == "partial"
    p.clock.sleep(10801)
    assert build_summary(cfg, p.state, clock=p.clock)["status"] == "stale"
    assert build_summary(cfg, p.state, clock=p.clock, expected_interval=86400)["status"] == "partial"


def test_failed_run_does_not_store_upstream_exception_text(pipeline):
    p = pipeline
    class Broken:
        def __init__(self, *a):
            pass
        def run(self, **kw):
            raise RuntimeError("secret https://private.example/location")
    with pytest.raises(RuntimeError):
        run_monitor(configured(p), p.state, None, p.http, worker_factory=Broken, clock=p.clock)
    summary = build_summary(p.cfg, p.state, clock=p.clock)
    assert summary["status"] == "failed"
    assert "private.example" not in json.dumps(summary) and "secret" not in json.dumps(summary)


def test_missing_credentials_are_names_only(pipeline, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY")
    summary = build_summary(pipeline.cfg, pipeline.state, clock=pipeline.clock)
    assert "GEMINI_API_KEY" in summary["configuration"]["missing_credentials"]
    assert "meta-secret" not in json.dumps(summary)


def test_backlog_pressure_budget_and_cooldown_visible(pipeline):
    p = pipeline
    cfg = replace(p.cfg, ai_day=0)
    p.state.enqueue([{"id": "1", "source": "#tiger", "data": {}}])
    p.state.kv_set("cooldown/gemini", p.clock() + 3600)
    result = build_summary(cfg, p.state, clock=p.clock)
    assert set(result["warnings"]) >= {"ai_budget_exhausted", "backlog_may_expire_before_analysis", "provider_cooldown"}
    assert result["cooldowns_seconds"]["gemini"] == 3600


def test_digest_is_once_daily_private_and_uses_alert_budget(pipeline):
    p = pipeline
    assert send_digest(p.cfg, p.state, p.http, clock=p.clock)["status"] == "sent"
    assert send_digest(p.cfg, p.state, p.http, clock=p.clock)["status"] == "already_attempted_today"
    assert p.http.count("sendMessage") == 1
    msg = p.http.sent[0]["json"]["text"]
    assert "https://" not in msg and "meta-secret" not in msg
    assert p.state.stats()["today"]["alerts"] == 1


def test_digest_never_escapes_zero_alert_cap(pipeline):
    p = pipeline
    assert send_digest(replace(p.cfg, alerts_day=0), p.state, p.http)["status"] == "alert_budget_or_pacing"
    assert p.http.count("api.telegram.org") == 0
    assert send_digest(p.cfg, p.state, p.http, clock=p.clock)["status"] == "sent"


def test_digest_never_retries_a_provider_cooldown(pipeline):
    p = pipeline
    p.state.kv_set("cooldown/telegram", p.clock() + 300)
    assert send_digest(p.cfg, p.state, p.http, clock=p.clock)["status"] == "telegram_cooldown"
    assert not p.http.calls and p.state.stats()["today"] == {}
    p.clock.sleep(301)
    assert send_digest(p.cfg, p.state, p.http, clock=p.clock)["status"] == "sent"


def test_digest_respects_pacing_after_a_recent_match(pipeline):
    p = pipeline
    assert p.state.reserve("alerts", p.cfg.alerts_day, p.cfg.alert_interval)["ok"]
    assert send_digest(p.cfg, p.state, p.http, clock=p.clock, sleep=p.clock.sleep)["status"] == "sent"
    assert p.state.stats()["today"]["alerts"] == 2


def test_digest_requires_explicit_alert_configuration(pipeline):
    p = pipeline
    with pytest.raises(SetupError):
        send_digest(replace(p.cfg, alerts_enabled=False), p.state, p.http)
    assert not p.http.calls


def test_failed_digest_not_automatically_repeated(pipeline):
    p = pipeline
    p.http.telegram = [Response({"ok": False}, 500)]
    with pytest.raises(ProviderError):
        send_digest(p.cfg, p.state, p.http)
    assert send_digest(p.cfg, p.state, p.http)["status"] == "already_attempted_today"
    assert p.http.count("sendMessage") == 1


def test_health_cli_no_meta_or_image_calls(pipeline, monkeypatch, capsys):
    p = pipeline
    monkeypatch.setenv("SQLITE_PATH", p.cfg.sqlite_path)
    monkeypatch.setattr(cli, "session", lambda: p.http)
    assert cli.main(["--health"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "not_run"
    assert not p.http.calls


def test_dashboard_cli_launches_without_provider_calls(pipeline, monkeypatch):
    from tigerwatch import dashboard
    p, launched = pipeline, []
    monkeypatch.setattr(cli, "session", lambda: p.http)
    monkeypatch.setattr(dashboard, "serve_dashboard", lambda *args, **kwargs: launched.append(kwargs))
    assert cli.main(["--dashboard"]) == 0
    assert launched == [{"watch_path": "watch.json", "port": 8765}]
    assert not p.http.calls
    assert cli.main(["--dashboard", "--port", "22"]) == 1


def test_evaluation_cli_uses_local_manifest_and_private_report(pipeline, tmp_path, monkeypatch):
    from .fakes import jpeg
    p = pipeline
    image = tmp_path / "example.jpg"
    image.write_bytes(jpeg())
    manifest = tmp_path / "examples.json"
    manifest.write_text(json.dumps({"examples": [{"path": "example.jpg", "expected": {"q1": True}}]}))
    monkeypatch.setenv("SQLITE_PATH", p.cfg.sqlite_path)
    monkeypatch.setenv("AI_ANALYSIS_RIGHTS_CONFIRMED", "true")
    monkeypatch.setattr(cli, "session", lambda: p.http)
    output = tmp_path / "report.json"
    assert cli.main(["--evaluate", str(manifest), "--output", str(output)]) == 0
    assert output.exists() and "example.jpg" not in output.read_text()
    assert p.http.count("generateContent") == 1 and not p.http.count("api.telegram.org")
