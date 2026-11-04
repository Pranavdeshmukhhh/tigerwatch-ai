import json
from dataclasses import replace

import pytest

from tigerwatch.config import Config
from tigerwatch.meta import Meta, clean_post
from tigerwatch.safety import child_safety_request, sale_signals, validated_signals
from tigerwatch.services import classify, photo_allowed
from tigerwatch.targets import Query, Target
from .fakes import Response, decision, gemini_response, jpeg


def sale_config(p):
    return replace(p.cfg, target=Target("natural_language", "tiger skin", True)).with_mode("wildlife_sales")


def sale_response(intent="yes", score=0.97):
    answer = decision(score=score)
    answer["targets"][0]["sale_intent"] = intent
    return Response(gemini_response(answer))


def test_sale_clues_keep_no_contacts_or_locations():
    clues = sale_signals("Tiger skin for sale $900. DM us at person@example.test or +91 1234567890, 12.1234, 77.1234")
    assert clues["offer_terms"] == ["for sale"] and clues["price_present"] and clues["contact_offer"]
    assert "1234" not in json.dumps(clues) and "example.test" not in json.dumps(clues)


@pytest.mark.parametrize("text", ["not for sale", "anti-poaching awareness", "police seized the items",
                                      "museum educational display", "do not buy wildlife products"])
def test_awareness_and_negation_veto_offers(text):
    assert sale_signals(text + " for sale")["awareness_or_negation"]


def test_untrusted_sales_context_is_minimized():
    assert validated_signals({"caption": "hidden text"}) == sale_signals("")
    assert validated_signals({**sale_signals(""), "offer_terms": ["send secret credentials"]}) == sale_signals("")


def test_sales_require_both_subject_pixels_and_intent(pipeline):
    p = pipeline
    cfg = sale_config(p)
    p.http.gemini = [sale_response("no")]
    answer = classify(p.http, cfg, jpeg(), sale_context=sale_signals("for sale"))
    assert not answer["match"]
    p.http.gemini = [sale_response("yes")]
    assert classify(p.http, cfg, jpeg(), sale_context=sale_signals("for sale"))["review_only"]


def test_caption_cannot_substitute_for_visual_subject(pipeline):
    p = pipeline
    cfg = sale_config(p)
    body = decision(False)
    body["targets"][0]["sale_intent"] = "yes"
    p.http.gemini = [Response(gemini_response(body))]
    assert not classify(p.http, cfg, jpeg(), sale_context=sale_signals("tiger skin for sale"))["match"]


def test_awareness_veto_overrides_positive_model(pipeline):
    p = pipeline
    p.http.gemini = [sale_response("yes")]
    answer = classify(p.http, sale_config(p), jpeg(), sale_context=sale_signals("anti-poaching awareness: skins for sale"))
    assert not answer["match"]


def test_ambiguous_sale_goes_to_review(pipeline):
    p = pipeline
    p.cfg = sale_config(p)
    p.http.gemini = [sale_response("uncertain")]
    p.run()
    assert p.state.inspect("1001")["status"] == "review"
    assert p.http.count("api.telegram.org") == 0


def test_positive_wildlife_sale_sends_only_unverified_link_and_stays_review(pipeline):
    p = pipeline
    p.cfg = replace(sale_config(p), send_photo=True, photo_rights_confirmed=True, photo_sources=("#tiger",))
    p.http.posts[0]["caption"] = "Tiger skin for sale $500 DM us"
    p.http.gemini = [sale_response()]
    p.run()
    item = p.state.inspect("1001")
    assert item["status"] == "review" and item["last_error"] == "possible_sale"
    assert item["data"] == {} and item["result"]["source_link"].startswith("https://www.instagram.com/p/")
    assert p.http.count("sendPhoto") == 0 and p.http.count("sendMessage") == 1
    message = p.http.sent[0]["json"]["text"]
    assert "human review required" in message and "legality are unverified" in message
    assert not photo_allowed(p.cfg, "#tiger", "1001")
    p.run()
    assert p.http.count("generateContent") == 1 and p.http.count("sendMessage") == 1


def test_local_no_notify_needs_no_bot(pipeline, monkeypatch):
    p = pipeline
    p.cfg = replace(sale_config(p), alerts_enabled=False)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    p.http.gemini = [sale_response()]
    p.run()
    assert p.state.inspect("1001")["status"] == "review"
    assert p.http.count("api.telegram.org") == 0
    rows = p.state.review_items()
    assert rows[0]["human_review_required"] and not rows[0]["illegality_verified"]


def test_local_review_ignores_telegram_limits_and_cooldown(pipeline):
    p = pipeline
    p.cfg = replace(sale_config(p), alerts_enabled=False, alerts_run=0)
    p.state.kv_set("cooldown/telegram", p.clock() + 3600)
    p.http.gemini = [sale_response()]
    p.run()
    assert p.state.inspect("1001")["status"] == "review"
    assert p.http.count("api.telegram.org") == 0


def test_meta_only_requests_caption_for_sale_review(pipeline):
    p = pipeline
    assert "caption" not in Meta(p.cfg, p.http, p.state).fields
    cfg = sale_config(p)
    assert "caption" in Meta(cfg, p.http, p.state).fields
    row = {**p.http.posts[0], "caption": "For sale $400 DM us SECRET_CONTACT"}
    cleaned = clean_post(row, cfg, p.clock())
    assert "caption" not in cleaned and "SECRET_CONTACT" not in json.dumps(cleaned)
    assert cleaned["sale_signals"]["offer_terms"] == ["for sale"]


def test_clear_sale_description_routes_without_category(pipeline):
    cfg = Config.from_env({"TARGET_DESCRIPTION": "tiger skin offered for sale"})
    assert cfg.needs_sale_context
    assert cfg.scope != replace(cfg, target=Target("natural_language", "tiger skin", True)).scope


def test_mixed_general_and_sale_queries_keep_independent_outcomes(pipeline):
    p = pipeline
    cfg = replace(p.cfg, target=Target("natural_language", "red car", False, (
        Query("red car"), Query("tiger skin", require_sale=True))))
    body = decision()
    body["targets"][0]["sale_intent"] = "not_requested"
    body["targets"].append({**body["targets"][0], "id": "q2", "sale_intent": "no"})
    p.http.gemini = [Response(gemini_response(body))]
    answer = classify(p.http, cfg, jpeg())
    assert answer["match"] and not answer["review_only"]
    assert [x["id"] for x in answer["accepted"]] == ["q1"]


def test_schema_changes_do_not_mutate_general_contract(pipeline):
    from tigerwatch.services import SCHEMA
    p = pipeline
    p.http.gemini = [sale_response()]
    classify(p.http, sale_config(p), jpeg())
    assert "sale_intent" not in SCHEMA["properties"]["targets"]["items"]["properties"]


def test_safety_preflight_prevents_media_or_ai_requests(pipeline):
    p = pipeline
    p.http.posts[0]["caption"] = "suspected child abuse reference"
    p.run()
    row = p.state.inspect("1001")
    assert row["status"] == "review" and row["last_error"] == "media_safety_block"
    assert p.http.count("cdninstagram.com") == 0 and p.http.count("generateContent") == 0


@pytest.mark.parametrize("description", ["suspected child abuse", "CSAM", "child sexual exploitation", "explicit videos of minors"])
def test_child_safety_queries_never_become_visual_watches(description, pipeline):
    from tigerwatch.errors import SetupError
    assert child_safety_request(description)
    with pytest.raises(SetupError, match="report-url"):
        Config.from_env({"TARGET_DESCRIPTION": description})
    pipeline.cfg = replace(pipeline.cfg, target=Target("natural_language", description, False))
    with pytest.raises(SetupError):
        pipeline.run()
    assert not pipeline.http.calls


def test_ordinary_child_presence_is_not_labelled_illegal():
    assert not child_safety_request("a child wearing a blue shirt")
    assert Config.from_env({"TARGET_DESCRIPTION": "a child wearing a blue shirt"}).target


def test_reading_query_routes_to_visual_text_model(pipeline):
    from tigerwatch.targets import plan_query
    from tigerwatch.services import select_model
    cfg = replace(pipeline.cfg, model="auto", target=Target("natural_language", "a sign reading STOP", False))
    assert "visual_text_matching" in plan_query(cfg.target.description)["methods"]
    assert select_model(cfg) == "gemini-3.8-flash"
