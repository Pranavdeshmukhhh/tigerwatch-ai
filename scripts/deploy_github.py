"""Owner-invoked publisher; uses an authenticated local GitHub CLI, never shell interpolation.

Creates a public repository when missing, copies only committed release files,
sets secrets through stdin and variables through temporary files, then pushes.
The user authenticates gh in their own browser. No tokens are printed/exported.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tigerwatch.config import Config  # noqa: E402
from tigerwatch.setup import SECRETS  # noqa: E402


def run(args, *, cwd=None, data=None, check=True):
    result = subprocess.run(args, cwd=cwd, input=data, text=True, capture_output=True, shell=False)
    if check and result.returncode:
        raise RuntimeError("Command failed: " + args[0] + " " + args[1] + "; check CLI authorization and repository permissions")
    return result


def publish(repo):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]{1,100}", repo):
        raise RuntimeError("Repository must have the form OWNER/NAME")
    if not shutil.which("gh") or not shutil.which("git"):
        raise RuntimeError("Install Git and GitHub CLI, run gh auth login, then repeat this command")
    values = {k: str(v) for k, v in dotenv_values(ROOT / ".env", interpolate=False).items() if v is not None}
    cfg = Config.from_env(values)
    # This helper does not inherit a CI identity or automatically enable billing.
    if not cfg.free_plans_confirmed:
        raise RuntimeError("Run python main.py --setup and confirm no paid plans first")
    required = {"GEMINI_API_KEY", "SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"}
    if cfg.source_kind == "meta":
        required.update(("META_ACCESS_TOKEN", "IG_USER_ID"))
    if cfg.alerts_enabled:
        required.update(("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"))
    for key in required:
        if not values.get(key):
            raise RuntimeError("Missing local setup value: " + key)
    run(["gh", "auth", "status"])
    existing = run(["gh", "repo", "view", repo, "--json", "isPrivate", "--jq", ".isPrivate"], check=False)
    if existing.returncode == 0 and existing.stdout.strip() != "false":
        raise RuntimeError("Existing repository is private. Free-only deployment requires a public repository")
    if existing.returncode != 0:
        run(["gh", "repo", "create", repo, "--public", "--description", "Free-tier visual subject monitoring with official Meta APIs"])
    # Never overwrite a populated repository automatically.
    contents = run(["gh", "api", f"repos/{repo}/contents", "--jq", "length"], check=False)
    if contents.returncode == 0 and contents.stdout.strip() not in ("0", ""):
        raise RuntimeError("Repository contains files. Use an empty dedicated public repository to avoid overwriting work")
    for key in SECRETS:
        if values.get(key):
            run(["gh", "secret", "set", key, "--repo", repo], data=values[key])
    allowed_variables = set(dotenv_values(ROOT / ".env.example", interpolate=False)) - set(SECRETS) - {"SQLITE_PATH", "CASE_DB_PATH"}
    public = {k: v for k, v in values.items() if k in allowed_variables}
    with tempfile.TemporaryDirectory(prefix="visualwatch-publish-") as temporary:
        checkout = Path(temporary) / "project"
        checkout.mkdir()
        # Release manifest is an explicit file allowlist; exclude historical test
        # output and manifests from the source repository to keep it small.
        manifest = ROOT / "MANIFEST.sha256"
        if not manifest.exists():
            raise RuntimeError("Release manifest missing; use the complete ZIP")
        for line in manifest.read_text().splitlines():
            _, relative = line.split("  ", 1)
            source = (ROOT / relative).resolve()
            if not source.is_relative_to(ROOT) or source.is_symlink() or source.name.startswith(".env") and source.name != ".env.example":
                raise RuntimeError("Unsafe release manifest entry")
            if relative.startswith("docs/evidence/"):
                continue
            content = source.read_bytes()
            if any(len(values.get(key, "")) >= 8 and values[key].encode() in content for key in SECRETS):
                raise RuntimeError("A release source file contains a configured secret; remove it before publishing")
            target = checkout / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        variable_file = Path(temporary) / "variables.env"
        variable_file.write_text("\n".join(k + "=" + json.dumps(v) for k, v in public.items()) + "\n")
        os.chmod(variable_file, 0o600)
        run(["gh", "variable", "set", "--repo", repo, "--env-file", str(variable_file)])
        run(["git", "init", "--initial-branch=main"], cwd=checkout)
        run(["git", "config", "user.name", "VisualWatch setup"], cwd=checkout)
        run(["git", "config", "user.email", "noreply@users.noreply.github.com"], cwd=checkout)
        run(["git", "add", "."], cwd=checkout)
        run(["git", "commit", "-m", "Install free-only configurable visual monitoring"], cwd=checkout)
        run(["git", "remote", "add", "origin", f"https://github.com/{repo}.git"], cwd=checkout)
        run(["gh", "auth", "setup-git"], cwd=checkout)
        run(["git", "push", "--set-upstream", "origin", "main"], cwd=checkout)
    run(["gh", "workflow", "run", "monitor.yml", "--repo", repo])
    print(f"Published source/configuration and requested the first workflow run: https://github.com/{repo}/actions")
    print("Supabase schema and Meta approval still need to be valid; inspect that run's result.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Publish the configured release to a new/empty PUBLIC GitHub repository")
    parser.add_argument("repository", help="OWNER/NAME")
    args = parser.parse_args()
    try:
        publish(args.repository)
    except Exception as exc:
        # Helpers raise sanitized messages, never a subprocess stderr containing credentials.
        print(str(exc) if isinstance(exc, RuntimeError) else "Setup failed; check local configuration and tool availability", file=sys.stderr)
        raise SystemExit(1)
