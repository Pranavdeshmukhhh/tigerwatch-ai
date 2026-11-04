"""Local guided configuration. Secrets stay in the ignored .env file.

Account creation, provider consent and Meta App Review are owner actions. This
helper reads only documented account/chat discovery APIs; no browser scraping.
"""
from __future__ import annotations

import getpass
import json
import os
import re
import tempfile
from pathlib import Path

from dotenv import dotenv_values

from .config import Config
from .errors import SetupError, TigerWatchError
from .net import json_request, session

SECRETS = ("META_ACCESS_TOKEN", "IG_USER_ID", "META_APP_SECRET", "GEMINI_API_KEY",
           "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY")


def write_env(path, values):
    path = Path(path)
    if path.is_symlink():
        raise SetupError("Refusing to overwrite a symlink .env")
    content = "# Created locally by the setup wizard. Never commit this file.\n"
    for key, value in values.items():
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key) or not isinstance(value, str) or re.search(r"[\r\n\x00]", value):
            raise SetupError("Invalid configuration value")
        content += key + "=" + json.dumps(value, ensure_ascii=True) + "\n"
    fd, temporary = tempfile.mkstemp(prefix=".env-setup-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def choose_id(candidates, label, ask, say):
    candidates = list(dict.fromkeys(candidates))
    if len(candidates) == 1:
        say(f"Found one eligible {label}; saved its ID locally.")
        return candidates[0]
    if len(candidates) > 1:
        for i, candidate in enumerate(candidates, 1):
            say(f"{i}: {label} ending {candidate[-4:]}")
        selected = ask("Choose a number: ").strip()
        if selected.isdigit() and 1 <= int(selected) <= len(candidates):
            return candidates[int(selected) - 1]
    return ""


def discover_ig(http, token, version, ask, say):
    body = json_request(http, "GET", f"https://graph.facebook.com/{version}/me/accounts", "meta",
                        params={"fields": "id,instagram_business_account{id}", "limit": 100},
                        headers={"Authorization": "Bearer " + token}, timeout=(8, 25))
    rows = body.get("data", []) if isinstance(body, dict) else []
    candidates = []
    for row in rows if isinstance(rows, list) else []:
        account = row.get("instagram_business_account") if isinstance(row, dict) else None
        ident = account.get("id") if isinstance(account, dict) else None
        if isinstance(ident, str) and re.fullmatch(r"[0-9]{1,50}", ident):
            candidates.append(ident)
    return choose_id(candidates, "linked professional account", ask, say)


def discover_chat(http, token, ask, say):
    body = json_request(http, "GET", f"https://api.telegram.org/bot{token}/getUpdates", "telegram",
                        params={"limit": 100, "timeout": 0}, timeout=(8, 25))
    rows = body.get("result", []) if isinstance(body, dict) and body.get("ok") is True else []
    candidates = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        message = row.get("message") or row.get("channel_post") or {}
        chat = message.get("chat", {}) if isinstance(message, dict) else {}
        ident = chat.get("id") if isinstance(chat, dict) else None
        if type(ident) is int:
            candidates.append(str(ident))
    return choose_id(candidates, "Telegram destination", ask, say)


def run_setup(root, *, ask=input, secret=getpass.getpass, say=print, http=None):
    root = Path(root)
    existing = dotenv_values(root / ".env", interpolate=False) if (root / ".env").exists() else {}
    values = {k: str(v) for k, v in existing.items() if v is not None}
    say("VisualWatch setup — describe visible subjects naturally; multiple targets are supported.")
    say("No real-person identification, face matching or paid fallback is included.")
    say("Use Gemini with billing disabled, Supabase Free, and a public GitHub repository.")
    say("If a free service is unavailable/exhausted, monitoring pauses. The app cannot inspect billing plans.")
    if ask("Have you confirmed those free plans with no paid billing enabled? [yes/no]: ").strip().lower() != "yes":
        raise SetupError("Setup stopped: disable provider billing/select Free plans first; no live calls made")
    values.update(FREE_TIER_ONLY="true", FREE_PLANS_CONFIRMED="true")

    def field(name, label, default="", hidden=False):
        prior = values.get(name, "")
        if prior == "REPLACE_ME":
            prior = ""
        prompt = label + (" [Enter keeps existing]" if prior and hidden else
                          f" [{prior or default}]" if prior or default else "") + ": "
        result = (secret(prompt) if hidden else ask(prompt)).strip() or prior or default
        values[name] = result
        return result

    text = ask('Describe targets, separated with ; [Pikachu]: ').strip() or "Pikachu"
    values.update(TARGET_KIND="natural_language", REQUIRE_PHOTOGRAPH="false",
                  TARGETS_JSON=json.dumps([x.strip() for x in text.split(";") if x.strip()]))
    values.pop("TARGET_DESCRIPTION", None)
    field("HASHTAGS", "Approved hashtags, comma-separated", "")
    field("ACCOUNTS", "Eligible professional accounts, comma-separated", "")
    if ask("May this content be analyzed under Meta/Google terms and the owner's rights? [yes/no]: ").strip().lower() != "yes":
        raise SetupError("Setup stopped: content processing rights/terms must be confirmed")
    values["AI_ANALYSIS_RIGHTS_CONFIRMED"] = "true"
    values.update(SEND_PHOTO="false", PHOTO_RESHARE_RIGHTS_CONFIRMED="false",
                  GEMINI_MODEL="auto", GRAPH_API_VERSION="v26.0")
    values.setdefault("MAX_AI_CALLS_PER_DAY", "20")
    values.setdefault("MAX_AI_CALLS_PER_RUN", "4")
    values.setdefault("MATCH_THRESHOLD", "0.85")
    # Validate target/scope before collecting credentials or making any API request.
    early_cfg = Config.from_env(values)
    if not early_cfg.tags and not early_cfg.accounts:
        raise SetupError("At least one approved hashtag or professional account is needed")
    field("META_ACCESS_TOKEN", "Approved Facebook User token (hidden)", hidden=True)
    field("GEMINI_API_KEY", "Gemini FREE project API key (hidden)", hidden=True)
    field("TELEGRAM_BOT_TOKEN", "Telegram bot token (hidden)", hidden=True)
    say("Send /start to your bot once so its destination can be discovered.")
    own_http = http is None
    http = http or session()
    try:
        if not values.get("IG_USER_ID") or values.get("IG_USER_ID") == "REPLACE_ME":
            try:
                values["IG_USER_ID"] = discover_ig(http, values["META_ACCESS_TOKEN"], values["GRAPH_API_VERSION"], ask, say)
            except TigerWatchError:
                say("Linked account discovery was unavailable; enter its numeric professional ID.")
        field("IG_USER_ID", "Professional Instagram ID", hidden=True)
        if not values.get("TELEGRAM_CHAT_ID") or values.get("TELEGRAM_CHAT_ID") == "REPLACE_ME":
            try:
                values["TELEGRAM_CHAT_ID"] = discover_chat(http, values["TELEGRAM_BOT_TOKEN"], ask, say)
            except TigerWatchError:
                say("Chat discovery was unavailable; enter the destination ID privately.")
        field("TELEGRAM_CHAT_ID", "Telegram destination ID", hidden=True)
    finally:
        if own_http:
            http.close()
    field("SUPABASE_URL", "Supabase Free project URL")
    field("SUPABASE_SERVICE_ROLE_KEY", "Supabase legacy service_role key (hidden)", hidden=True)
    cfg = Config.from_env(values)
    if not cfg.tags and not cfg.accounts:
        raise SetupError("At least one approved hashtag or professional account is needed")
    for name in SECRETS:
        if name != "META_APP_SECRET" and not values.get(name):
            raise SetupError("Missing setup value: " + name)
    if not re.fullmatch(r"[0-9]{1,50}", values["IG_USER_ID"]):
        raise SetupError("Professional Instagram ID must be numeric")
    write_env(root / ".env", values)
    say("Saved .env locally with restricted file permissions. No secret values were printed.")
    say("One owner-only database step: run schema.sql in Supabase's SQL Editor.")
    say("Then run: python main.py --check-access")
    say("For cloud setup: python scripts/deploy_github.py YOUR-USER/YOUR-REPO")
    return cfg


def run_public_setup(root, *, ask=input, secret=getpass.getpass, say=print):
    """Small local path: no Meta token, Telegram or Supabase account required."""
    from .watches import profile_handle, save_watch
    from .targets import Query, Target
    from dataclasses import replace
    say("Public-browser setup: public pages only; login walls and blocks stop collection.")
    say("No Meta token is used. Collection alone needs no AI key; visual analysis needs eligible Gemini Free access.")
    confirmed = ask("Is Gemini billing disabled on a Free project you may use? [yes/no]: ").strip().lower() == "yes"
    rights = ask("Do you have the required content-processing rights under the provider terms? [yes/no]: ").strip().lower() == "yes"
    if not confirmed or not rights:
        raise SetupError("Live visual setup stopped. You can still collect public links with --collect-only")
    profile = profile_handle(ask("Instagram profile username or URL: "))
    descriptions = [x.strip() for x in ask("What should be monitored? Separate descriptions with ; : ").split(";") if x.strip()]
    if not descriptions:
        raise SetupError("Enter a target description")
    mode = ask("Mode [general / sale_review / wildlife_sales] (default general): ").strip() or "general"
    target = Target("natural_language", descriptions[0], False, tuple(Query(x) for x in descriptions)).validate()
    key = secret("Gemini Free API key (hidden): ").strip()
    if not key or key == "REPLACE_ME":
        raise SetupError("A free API key is needed for visual analysis; no paid fallback")
    values = {"SOURCE_KIND": "browser", "ACCOUNTS": profile, "HASHTAGS": "", "TARGETS_JSON": json.dumps(descriptions),
              "TARGET_KIND": "natural_language", "REQUIRE_PHOTOGRAPH": "false",
              "GEMINI_MODEL": "auto", "GEMINI_API_KEY": key, "FREE_TIER_ONLY": "true", "FREE_PLANS_CONFIRMED": "true",
              "AI_ANALYSIS_RIGHTS_CONFIRMED": "true", "ALERTS_ENABLED": "false", "SEND_PHOTO": "false",
              "MONITOR_MODE": mode, "SUPABASE_URL": "", "SUPABASE_SERVICE_ROLE_KEY": ""}
    cfg = replace(Config.from_env(values), target=target).with_mode(mode)
    path = Path(root)
    if (path / ".env").exists():
        prior = dotenv_values(path / ".env", interpolate=False)
        prior.update(values)
        values = {k: str(v) for k, v in prior.items() if v is not None}
    write_env(path / ".env", values)
    save_watch(path / "watch.json", cfg)
    say("Saved .env and watch.json privately. Run: python main.py --watch watch.json")
    say("Review/export: python main.py --watch watch.json --review --output review.json")
    return cfg
