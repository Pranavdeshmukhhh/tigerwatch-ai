from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import replace
from pathlib import Path

from dotenv import load_dotenv

from .config import Config
from .errors import SetupError, TigerWatchError
from .media import IMAGE_LIMIT, normalize
from .meta import Meta, numeric_id
from .net import Redact, session
from .services import classify, telegram
from .store import State


def parser():
    p = argparse.ArgumentParser(description="VisualWatch v8 — private glass dashboard and automated visual monitoring")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--dashboard", action="store_true", help="Open the local private control dashboard")
    mode.add_argument("--health", action="store_true", help="Budget, backlog and last-run diagnostics; no media fetching")
    mode.add_argument("--send-digest", action="store_true", help="Send one private health digest within shared daily alert caps")
    mode.add_argument("--feedback-id", metavar="ID", help="Record feedback without reprocessing or resending a post")
    mode.add_argument("--evaluate", metavar="MANIFEST", help="Evaluate authorized labeled local images within the free AI budget")
    mode.add_argument("--setup", action="store_true", help="Local guided setup with hidden secret prompts")
    mode.add_argument("--setup-public", action="store_true", help="Minimal public-browser/local setup; no Meta account token")
    mode.add_argument("--configure-watch", nargs="?", const="watch.json", metavar="FILE", help="Save a watch interactively")
    mode.add_argument("--save-watch", metavar="FILE", help="Save supplied profiles/targets without running them")
    mode.add_argument("--collect-only", action="store_true", help="Queue visible public profile links, without fetching images or calling AI")
    mode.add_argument("--review", action="store_true", help="List current watch review candidates; --output exports canonical links privately")
    mode.add_argument("--report-url", action="append", metavar="URL", help="Record a reference locally; never fetch or forward it")
    mode.add_argument("--cases", action="store_true", help="List local URL-only case references without opening them")
    mode.add_argument("--export-cases", metavar="FILE", help="Export local URL-only case references privately")
    mode.add_argument("--case-status", metavar="CASE-ID", help="Record a manual review disposition")
    mode.add_argument("--plan", action="store_true", help="Show query capabilities/limitations without API calls")
    mode.add_argument("--video", metavar="PATH", help="Assess a local video with a bounded free API budget")
    mode.add_argument("--camera", type=int, metavar="INDEX", help="Assess a local camera (computer stays on)")
    mode.add_argument("--demo", action="store_true", help="Credential-free simulated pipeline; no network")
    mode.add_argument("--check-access", action="store_true", help="Live source probe; browser collects links, Meta uses API quota")
    mode.add_argument("--test-telegram", action="store_true", help="Send one diagnostic message (uses alert budget)")
    mode.add_argument("--image", metavar="PATH", help="Live Gemini classification only; uses persistent AI budget")
    mode.add_argument("--stats", action="store_true", help="Queue counts and UTC daily reservations, no media URLs")
    mode.add_argument("--inspect-id", metavar="ID", help="Queue status/error only; no signed URLs")
    mode.add_argument("--retry-id", metavar="ID", help="Requeue a dead/review item after investigating it")
    mode.add_argument("--drain-only", action="store_true", help="Process queue without initial discovery")
    p.add_argument("--acknowledge-duplicate-risk", action="store_true", help="Permit manual retry of unknown Telegram delivery")
    p.add_argument("--target", action="append", help="Natural-language target; repeat for simultaneous queries")
    p.add_argument("--sample-seconds", type=int, default=2, help="Video/camera sample interval (1–60)")
    p.add_argument("--max-samples", type=int, default=60, help="Video/camera bound (1–300)")
    p.add_argument("--watch", metavar="FILE", help="Use a saved watch definition")
    p.add_argument("--scan-profile", action="append", metavar="ACCOUNT", help="Public profile to watch; repeat for several accounts")
    p.add_argument("--source", choices=("meta", "browser"), help="Discovery adapter")
    p.add_argument("--mode", choices=("general", "sale_review", "wildlife_sales"), help="Require sale intent for private review")
    p.add_argument("--no-notify", action="store_true", help="Save review candidates without Telegram")
    p.add_argument("--max-posts", type=int, help="Public links per profile, 1–500 (not an availability guarantee)")
    p.add_argument("--show-browser", action="store_true", help="Show normal browser window")
    p.add_argument("--output", metavar="FILE", help="Write a private JSON export")
    p.add_argument("--category", choices=("child_safety", "wildlife", "other"), default="other", help="URL-only case category")
    p.add_argument("--case-db", metavar="FILE", help="Private local case database (default review-cases.sqlite3)")
    p.add_argument("--status", choices=("needs_review", "reported", "dismissed"), default="needs_review")
    p.add_argument("--verdict", choices=("correct", "incorrect", "uncertain"), help="Review feedback verdict")
    p.add_argument("--port", type=int, default=8765, help="Local dashboard port, 1024–65535")
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    if args.demo:
        from .demo import run_demo
        run_demo()
        return 0
    load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False, interpolate=False)
    handler = logging.StreamHandler()
    handler.addFilter(Redact(os.getenv(x, "") for x in (
        "META_ACCESS_TOKEN", "META_APP_SECRET", "GEMINI_API_KEY", "TELEGRAM_BOT_TOKEN", "SUPABASE_SERVICE_ROLE_KEY")))
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    state, http = None, None
    try:
        if args.report_url or args.cases or args.export_cases or args.case_status:
            from .cases import CaseBook, REPORTING
            book = CaseBook(args.case_db or os.getenv("CASE_DB_PATH") or "review-cases.sqlite3")
            try:
                if args.report_url:
                    ids = [book.add(url, args.category) for url in args.report_url]
                    print(json.dumps({"case_ids": ids, "media_fetched": False, "automatic_submission": False,
                                      "reporting_resources": REPORTING}))
                elif args.export_cases:
                    book.export(args.export_cases)
                    print("Private reference export saved; no URLs fetched or reports submitted")
                elif args.case_status:
                    print("Updated" if book.update(args.case_status, args.status) else "Case not found")
                else:
                    print(json.dumps(book.entries(), indent=2))
            finally:
                book.close()
            return 0
        if args.setup or args.setup_public:
            if not sys.stdin.isatty():
                raise SetupError("Run --setup in a local interactive terminal so secrets are entered privately")
            from .setup import run_setup, run_public_setup
            (run_public_setup if args.setup_public else run_setup)(Path(__file__).resolve().parents[1])
            return 0
        cfg, http = Config.from_env(), session()
        if args.watch:
            from .watches import load_watch
            cfg = load_watch(args.watch, cfg)
        if args.target:
            from .targets import Query, Target
            target = Target("natural_language", args.target[0], False, tuple(Query(x) for x in args.target)).validate()
            cfg = replace(cfg, target=target, model=cfg.model if os.getenv("GEMINI_MODEL") else "auto")
        if args.scan_profile:
            from .watches import profile_handle
            profiles = tuple(dict.fromkeys(profile_handle(x) for x in args.scan_profile))
            if len(profiles) > 20:
                raise SetupError("At most 20 configured profiles")
            cfg = replace(cfg, accounts=profiles, tags=(), source_kind=args.source or "browser")
        elif args.source:
            cfg = replace(cfg, source_kind=args.source)
        cfg = cfg.with_mode(args.mode or cfg.monitor_mode)
        if args.no_notify:
            cfg = replace(cfg, alerts_enabled=False)
        if args.max_posts is not None:
            if not 1 <= args.max_posts <= 500:
                raise SetupError("--max-posts must be 1–500")
            cfg = replace(cfg, browser_posts=args.max_posts)
        if args.show_browser:
            cfg = replace(cfg, browser_headless=False)
        if cfg.source_kind == "browser" and cfg.tags:
            raise SetupError("Public browser collection supports profiles, not hashtag searches")
        if args.configure_watch or args.save_watch:
            from .watches import configure_watch, save_watch
            if args.configure_watch:
                if not sys.stdin.isatty():
                    raise SetupError("Run --configure-watch in an interactive terminal")
                configure_watch(args.configure_watch, cfg)
            else:
                save_watch(args.save_watch, cfg)
            print("Saved private watch definition; no live collection performed")
            return 0
        if args.plan:
            from .targets import plan_query
            from .services import select_model
            print(json.dumps({"queries": [{"description": q.description, **plan_query(q.description)} for q in cfg.target.all_queries],
                              "selected_model": select_model(cfg),
                              "state_scope": cfg.scope,
                              "backend": "Gemini multimodal vision; no paid fallback", "precise_masks": False,
                              "face_identification": False, "live_instagram_video": False}, indent=2))
            return 0
        if args.dashboard:
            from .dashboard import serve_dashboard
            if not 1024 <= args.port <= 65535:
                raise SetupError("Dashboard port must be 1024–65535")
            serve_dashboard(cfg, http, watch_path=args.watch or "watch.json", port=args.port)
            return 0
        state = State(cfg, http)
        if args.health:
            from .health import build_summary
            print(json.dumps(build_summary(cfg, state), indent=2))
        elif args.send_digest:
            from .health import send_digest
            print(json.dumps(send_digest(cfg, state, http)))
        elif args.feedback_id:
            if not numeric_id(args.feedback_id) or not args.verdict:
                raise SetupError("Use a numeric --feedback-id and --verdict correct/incorrect/uncertain")
            print("Feedback saved" if state.set_feedback(args.feedback_id, args.verdict) else "No completed item in this watch")
        elif args.evaluate:
            from .evaluate import evaluate_manifest
            from .cases import private_json
            result = evaluate_manifest(cfg, state, http, args.evaluate)
            if args.output:
                private_json(args.output, result)
                print("Private evaluation report saved")
            else:
                print(json.dumps(result, indent=2))
        elif args.collect_only:
            if cfg.source_kind != "browser" or not cfg.accounts:
                raise SetupError("Use --collect-only with --scan-profile or a saved browser watch")
            from .public_browser import PublicBrowser
            from .cases import private_json
            source, rows = PublicBrowser(cfg, state), []
            for account in cfg.accounts:
                rows.extend(source.source("@" + account))
            result = {"posts": [{"url": x["permalink"]} for x in rows], "status": source.last_status,
                      "media_fetched": False, "ai_calls": 0}
            if args.output:
                private_json(args.output, result)
            print(json.dumps({"links_queued": len(rows), "status": source.last_status, "media_fetched": False}))
        elif args.review:
            rows = state.review_items()
            if args.output:
                from .cases import private_json
                private_json(args.output, {"unverified_review_candidates": rows, "automatic_submission": False})
                print("Private review export saved")
            else:
                print(json.dumps([{k: v for k, v in row.items() if k != "source_link"} for row in rows], indent=2))
        elif args.video or args.camera is not None:
            from .video import run_video
            run_video(cfg, state, http, args.camera if args.camera is not None else args.video,
                      camera=args.camera is not None, interval=args.sample_seconds, max_samples=args.max_samples)
        elif args.stats:
            print(json.dumps(state.stats(), indent=2))
        elif args.inspect_id:
            if not numeric_id(args.inspect_id):
                raise SetupError("ID must be numeric")
            item = state.inspect(args.inspect_id)
            print(json.dumps({k: item[k] for k in ("id", "status", "attempts", "last_error", "next_attempt")} if item else None, indent=2))
        elif args.retry_id:
            if not numeric_id(args.retry_id):
                raise SetupError("ID must be numeric")
            item = state.inspect(args.retry_id)
            if item and item.get("last_error") == "telegram:delivery_unknown" and not args.acknowledge_duplicate_risk:
                raise SetupError("Check the destination first; --acknowledge-duplicate-risk is required to retry unknown delivery")
            ok = state.call("retry", id=args.retry_id, acknowledge=args.acknowledge_duplicate_risk)
            print("Requeued" if ok is True else "No dead/review item with this ID")
        elif args.test_telegram:
            cfg.require_free()
            cfg.require("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")
            value = state.reserve("alerts", cfg.alerts_day, cfg.alert_interval)
            if not value["ok"]:
                raise SetupError("Telegram diagnostic deferred by alert budget/pacing")
            telegram(http, "TigerWatch diagnostic: Telegram API accepted a test message.")
            print("Telegram test message accepted; no Instagram or AI test was performed")
        elif args.image:
            cfg.require_free()
            cfg.require("GEMINI_API_KEY")
            if not cfg.analysis_rights_confirmed:
                raise SetupError("Set AI_ANALYSIS_RIGHTS_CONFIRMED=true after reviewing provider/content terms")
            with Path(args.image).open("rb") as f:
                jpg = normalize(f.read(IMAGE_LIMIT + 1))
            value = state.reserve("ai", cfg.ai_day, cfg.ai_interval)
            if not value["ok"]:
                raise SetupError("Local image test deferred by AI budget/pacing")
            answer = classify(http, cfg, jpg)
            print(json.dumps({**answer, "score_is_uncalibrated": True, "authenticity_is_unverified": True}))
        elif args.check_access:
            if cfg.source_kind == "browser":
                from .public_browser import PublicBrowser
                print(json.dumps(PublicBrowser(cfg, state).check_access()))
            else:
                cfg.require_free()
                cfg.require("META_ACCESS_TOKEN", "IG_USER_ID")
                Meta(cfg, http, state).check_access()
        else:
            cfg.require_monitor()
            if cfg.source_kind == "browser":
                from .public_browser import PublicBrowser
                source = PublicBrowser(cfg, state)
            else:
                source = Meta(cfg, http, state)
            from .health import run_monitor
            metrics = run_monitor(cfg, state, source, http, discover=not args.drain_only)
            if metrics.get("source_errors") or metrics.get("stopped"):
                return 1
        return 0
    except TigerWatchError as exc:
        logging.error("%s; see README troubleshooting", exc)
        return 1
    except KeyboardInterrupt:
        logging.warning("Interrupted; leased work will become claimable after lease expiry")
        return 130
    except Exception as exc:
        logging.error("Unexpected %s; no upstream exception text logged. Run the offline tests.", type(exc).__name__)
        return 1
    finally:
        if state:
            state.close()
        if http:
            http.close()


if __name__ == "__main__":
    raise SystemExit(main())
