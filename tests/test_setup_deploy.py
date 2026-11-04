import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from dotenv import dotenv_values

from tigerwatch.errors import SetupError
from tigerwatch.setup import run_setup, write_env
from .fakes import FakeHTTP, Response


class SetupHTTP(FakeHTTP):
    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if url.endswith("/me/accounts"):
            return Response({"data": [{"id": "456", "instagram_business_account": {"id": "123"}}]})
        if url.endswith("/getUpdates"):
            return Response({"ok": True, "result": [{"message": {"chat": {"id": 987}}}]})
        raise AssertionError("Wizard made an unexpected live API request")


def test_setup_discovers_ids_and_never_prints_secrets(tmp_path):
    http, output = SetupHTTP(), []
    def ask(prompt):
        if "yes/no" in prompt:
            return "yes"
        if "Describe targets" in prompt:
            return 'Pikachu; a person wearing a blue shirt; a sign that reads "STOP"'
        if "Approved hashtags" in prompt:
            return "pokemon"
        if "Supabase Free project URL" in prompt:
            return "https://example.supabase.co"
        return ""
    def secret(prompt):
        if "Instagram ID" in prompt or "destination ID" in prompt:
            return ""
        return "never-print-this-secret"
    cfg = run_setup(tmp_path, ask=ask, secret=secret, say=output.append, http=http)
    values = dotenv_values(tmp_path / ".env")
    assert values["IG_USER_ID"] == "123" and values["TELEGRAM_CHAT_ID"] == "987"
    assert len(cfg.target.all_queries) == 3 and cfg.free_plans_confirmed
    assert "never-print-this-secret" not in " ".join(output)
    assert len(http.calls) == 2
    assert "access_token" not in http.calls[0][2]["params"]
    assert not ((tmp_path / ".env").stat().st_mode & 0o077) or sys.platform == "win32"


def test_setup_stops_before_http_when_free_plans_not_confirmed(tmp_path):
    http = SetupHTTP()
    with pytest.raises(SetupError):
        run_setup(tmp_path, ask=lambda _: "no", say=lambda _: None, http=http)
    assert not http.calls and not (tmp_path / ".env").exists()


def test_env_writer_quotes_untrusted_strings_without_interpolation(tmp_path):
    value = 'a red car #2 with "quoted text" and $HOME and `literal`'
    write_env(tmp_path / ".env", {"TARGET_DESCRIPTION": value, "GEMINI_API_KEY": "private-token"})
    parsed = dotenv_values(tmp_path / ".env", interpolate=False)
    assert parsed["TARGET_DESCRIPTION"] == value
    assert parsed["GEMINI_API_KEY"] == "private-token"
    assert list(tmp_path.glob(".env-setup-*")) == []


def test_env_writer_rejects_newline_injection(tmp_path):
    with pytest.raises(SetupError):
        write_env(tmp_path / ".env", {"TARGET_DESCRIPTION": "car\nMALICIOUS=true"})


def load_publisher():
    path = Path(__file__).resolve().parents[1] / "scripts/deploy_github.py"
    spec = importlib.util.spec_from_file_location("visualwatch_test_publisher", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_deploy_helper_uses_stdin_for_secrets_and_ignores_env(tmp_path, monkeypatch):
    module = load_publisher()
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module.shutil, "which", lambda _: "/fake/tool")
    values = {k: "private-token" for k in module.SECRETS}
    values.update(IG_USER_ID="123", FREE_PLANS_CONFIRMED="true", AI_ANALYSIS_RIGHTS_CONFIRMED="true", HASHTAGS="pokemon",
                  UNKNOWN_PRIVATE_TOKEN="must-not-upload")
    write_env(tmp_path / ".env", values)
    (tmp_path / "main.py").write_text("print('public code')\n")
    (tmp_path / ".env.example").write_text("GEMINI_API_KEY=REPLACE_ME\nFREE_PLANS_CONFIRMED=false\nHASHTAGS=\n")
    (tmp_path / "MANIFEST.sha256").write_text("dummy  main.py\ndummy  .env.example\n")
    calls, copied = [], []
    def run(args, *, cwd=None, data=None, check=True):
        calls.append((args, data))
        if args[:3] == ["gh", "repo", "view"]:
            return SimpleNamespace(returncode=0, stdout="false\n")
        if args[:2] == ["gh", "api"]:
            return SimpleNamespace(returncode=1, stdout="")
        if args[:2] == ["git", "add"]:
            copied.extend(p.name for p in Path(cwd).iterdir())
        if args[:3] == ["gh", "variable", "set"]:
            body = Path(args[-1]).read_text()
            assert "private-token" not in body
            assert "must-not-upload" not in body
            assert "FREE_PLANS_CONFIRMED" in body
        return SimpleNamespace(returncode=0, stdout="")
    monkeypatch.setattr(module, "run", run)
    module.publish("example/visualwatch")
    assert ".env" not in copied and ".env.example" in copied
    assert all("private-token" not in json.dumps(args) for args, _ in calls)
    assert any(data == "private-token" for _, data in calls)
    assert any(args[:3] == ["gh", "workflow", "run"] for args, _ in calls)


def test_deploy_helper_refuses_private_repository_before_setting_secrets(tmp_path, monkeypatch):
    module = load_publisher()
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module.shutil, "which", lambda _: "/fake/tool")
    values = {k: "private-token" for k in module.SECRETS}
    values["FREE_PLANS_CONFIRMED"] = "true"
    write_env(tmp_path / ".env", values)
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout="true\n" if "isPrivate" in args else "")
    monkeypatch.setattr(module, "run", run)
    with pytest.raises(RuntimeError, match="private"):
        module.publish("example/visualwatch")
    assert not any("secret" in args for args in calls)
