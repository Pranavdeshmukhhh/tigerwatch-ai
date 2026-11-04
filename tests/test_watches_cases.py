import json
import os
from dataclasses import replace

import pytest
from dotenv import dotenv_values

from tigerwatch.cases import CaseBook, private_json, reference_url
from tigerwatch.cli import main
from tigerwatch.config import Config
from tigerwatch.errors import SetupError
from tigerwatch.setup import run_public_setup
from tigerwatch.targets import Query, Target
from tigerwatch.watches import configure_watch, load_watch, profile_handle, save_watch


def test_watch_round_trip_changes_targets_without_secret_keys(pipeline, tmp_path):
    cfg = replace(pipeline.cfg, source_kind="browser", accounts=("example",), tags=(), model="auto",
                  target=Target("natural_language", "tiger skin", True, (Query("tiger skin"), Query("elephant ivory"))))
    cfg = cfg.with_mode("wildlife_sales")
    path = tmp_path / "watch.json"
    save_watch(path, cfg)
    restored = load_watch(path, pipeline.cfg)
    assert restored.scope == cfg.scope and restored.source_kind == "browser"
    assert restored.needs_sale_context and restored.accounts == ("example",)
    assert "GEMINI" not in path.read_text() and "secret" not in path.read_text()


@pytest.mark.parametrize("bad", ["https://evil.test/example/", "https://user:pass@instagram.com/example/",
                                 "https://instagram.com:8080/example/", "accounts", "example/bad", "https://instagram.com/example/?token=private"])
def test_profile_validation_rejects_untrusted_urls(bad):
    with pytest.raises(SetupError):
        profile_handle(bad)


def test_profile_and_case_links_are_canonical():
    assert profile_handle("https://www.instagram.com/Example/") == "example"
    assert reference_url("https://instagram.com/p/Example/?tracking=private") == "https://www.instagram.com/p/Example/"
    assert reference_url("https://instagram.com/example/") == "https://www.instagram.com/example/"


def test_url_only_casebook_deduplicates_and_exports_no_media(tmp_path):
    path = tmp_path / "references.sqlite3"
    book = CaseBook(path)
    try:
        one = book.add("https://instagram.com/p/Reference/?x=1", "child_safety")
        two = book.add("https://www.instagram.com/p/Reference/", "child_safety")
        assert one == two and len(book.entries()) == 1
        assert "url" not in book.entries()[0]
        assert book.update(one, "reported") and book.entries()[0]["status"] == "reported"
        output = tmp_path / "reference-export.json"
        book.export(output)
        data = json.loads(output.read_text())
        assert data["cases"][0]["url"].endswith("/p/Reference/")
        assert not data["submitted_to_authorities"]
        assert set(data["cases"][0]) == {"id", "category", "status", "created", "updated", "url"}
        if os.name != "nt":
            assert not (path.stat().st_mode & 0o077) and not (output.stat().st_mode & 0o077)
    finally:
        book.close()


def test_reporting_cli_makes_no_network_or_ai_initialization(tmp_path, monkeypatch, capsys):
    from tigerwatch import cli
    def forbidden(*args, **kwargs):
        raise AssertionError("URL-only intake must not create an HTTP client or scan target")
    monkeypatch.setattr(cli, "session", forbidden)
    monkeypatch.setattr(cli.Config, "from_env", forbidden)
    path = str(tmp_path / "cases.sqlite3")
    assert main(["--report-url", "https://instagram.com/p/Reference/", "--category", "child_safety", "--case-db", path]) == 0
    result = json.loads(capsys.readouterr().out)
    assert not result["media_fetched"] and not result["automatic_submission"]
    assert "instagram.com/p/Reference" not in json.dumps(result)
    assert main(["--cases", "--case-db", path]) == 0
    assert "url" not in json.loads(capsys.readouterr().out)[0]


def test_casebook_refuses_untrusted_reference_and_unknown_disposition(tmp_path):
    book = CaseBook(tmp_path / "cases.sqlite3")
    try:
        with pytest.raises(SetupError):
            book.add("https://127.0.0.1/private", "child_safety")
        with pytest.raises(SetupError):
            book.add("https://instagram.com/p/Reference/", "unknown")
        ident = book.add("https://instagram.com/p/Reference/", "other")
        with pytest.raises(SetupError):
            book.update(ident, "criminal")
    finally:
        book.close()


def test_public_setup_needs_only_free_visual_key(tmp_path):
    output = []
    def ask(prompt):
        if "yes/no" in prompt:
            return "yes"
        if "profile" in prompt:
            return "https://instagram.com/example/"
        if "monitored" in prompt:
            return "tiger skin; a red car"
        return "wildlife_sales"
    cfg = run_public_setup(tmp_path, ask=ask, secret=lambda _: "private-gemini-key", say=output.append)
    values = dotenv_values(tmp_path / ".env", interpolate=False)
    assert cfg.source_kind == "browser" and not cfg.alerts_enabled and cfg.needs_sale_context
    assert values["GEMINI_API_KEY"] == "private-gemini-key" and values["SUPABASE_URL"] == ""
    assert "META_ACCESS_TOKEN" not in values
    assert "private-gemini-key" not in " ".join(output)
    assert load_watch(tmp_path / "watch.json", cfg).scope == cfg.scope


def test_public_setup_stops_before_requesting_keys_for_child_safety(tmp_path):
    def ask(prompt):
        if "yes/no" in prompt:
            return "yes"
        if "profile" in prompt:
            return "example"
        if "monitored" in prompt:
            return "child abuse"
        return "general"
    def secret(_):
        raise AssertionError("Should stop before collecting key")
    with pytest.raises(SetupError, match="report-url"):
        run_public_setup(tmp_path, ask=ask, secret=secret, say=lambda _: None)
    assert not (tmp_path / ".env").exists()


def test_watch_definition_rejects_credential_fields(tmp_path):
    path = tmp_path / "watch.json"
    private_json(path, {"version": 1, "source": "browser", "mode": "general", "profiles": ["example"],
                        "targets": ["red car"], "GEMINI_API_KEY": "private"})
    with pytest.raises(SetupError):
        load_watch(path, Config())


def test_watch_configurator_requires_no_model_or_source_calls(pipeline, tmp_path):
    answers = iter(["example", "Pikachu; a person wearing blue", "general", "browser"])
    path = tmp_path / "watch.json"
    chosen = configure_watch(path, pipeline.cfg, ask=lambda _: next(answers))
    assert len(chosen.target.all_queries) == 2 and not pipeline.http.calls


def test_save_watch_cli_works_without_credentials(tmp_path, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    path = str(tmp_path / "watch.json")
    assert main(["--save-watch", path, "--scan-profile", "example", "--target", "tiger skin", "--mode", "wildlife_sales"]) == 0
    assert load_watch(path, Config()).needs_sale_context
