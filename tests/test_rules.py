from dataclasses import replace

import pytest

from tigerwatch.errors import SetupError
from tigerwatch.rules import config_from_rules, preview_rules
from tigerwatch.watches import load_watch, save_watch


def request(**extra):
    return {"profiles": ["@example"], "targets": ["a red bicycle"], "source": "browser", "mode": "general", **extra}


def test_preview_normalizes_editable_rules_without_provider_calls(pipeline):
    p = pipeline
    result = preview_rules(p.cfg, request(targets=["a bicycle for sale", "a sign reading STOP"]))
    assert result["network_calls"] == 0 and not p.http.calls
    assert result["rules"][0]["require_sale"]
    assert "visual_text_matching" in result["rules"][1]["methods"]
    assert result["selected_model"] == "gemini-3.8-flash"
    assert result["watch"]["profiles"] == ["example"]


def test_exclusions_and_threshold_survive_watch_roundtrip(pipeline, tmp_path):
    cfg = config_from_rules(pipeline.cfg, request(exclusions=["toys", "drawings"], threshold=0.4))
    assert cfg.review_score == pipeline.cfg.review_score
    path = tmp_path / "watch.json"
    save_watch(path, cfg)
    loaded = load_watch(path, replace(cfg, model="auto"))
    assert loaded.scope == cfg.scope
    assert loaded.target.all_queries[0].description == "a red bicycle; exclude: toys; drawings"
    assert loaded.target.all_queries[0].threshold == 0.4


@pytest.mark.parametrize("target,exclusion,expected", [
    ("red bicycles for sale", "not for sale", True),
    ("red bicycles", "for sale", False),
])
def test_exclusions_do_not_change_positive_sale_intent(pipeline, target, exclusion, expected):
    cfg = config_from_rules(pipeline.cfg, request(targets=[target], exclusions=[exclusion]))
    assert cfg.needs_sale_context is expected


def test_exclusions_do_not_invent_temporal_or_segmentation_requirements(pipeline):
    result = preview_rules(pipeline.cfg, request(exclusions=["motion blur", "precise outline illustrations"]))
    assert result["rules"][0]["supported"] and not result["rules"][0]["requires_video"]


@pytest.mark.parametrize("extra", [
    {"profiles": []}, {"profiles": ["https://evil.test/name/"]},
    {"targets": []}, {"targets": ["x"] * 11}, {"targets": [True]},
    {"threshold": True}, {"threshold": float("nan")}, {"threshold": 1.1},
    {"photograph_only": "true"}, {"exclusions": ["x"] * 6},
    {"source": "private"}, {"mode": "abuse"}, {"secret": "no"},
    {"targets": ["suspected child sexual exploitation"]},
    {"targets": ["face recognition of a specific person"]},
])
def test_invalid_or_prohibited_rules_are_rejected(pipeline, extra):
    with pytest.raises(SetupError):
        config_from_rules(pipeline.cfg, request(**extra))


def test_sale_mode_is_explicit_and_disables_photos(pipeline):
    cfg = config_from_rules(pipeline.cfg, request(mode="wildlife_sales", targets=["tiger skin"]))
    assert cfg.needs_sale_context and not cfg.send_photo
    assert cfg.target.all_queries[0].photograph_only is True
    assert cfg.target.photograph_only


def test_photograph_constraint_keeps_same_scope_after_save(pipeline, tmp_path):
    cfg = config_from_rules(pipeline.cfg, request(photograph_only=True))
    path = tmp_path / "watch.json"
    save_watch(path, cfg)
    loaded = load_watch(path, pipeline.cfg)
    assert loaded.target.all_queries[0].photograph_only
    assert loaded.scope == cfg.scope
