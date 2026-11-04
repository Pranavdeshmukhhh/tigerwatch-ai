"""Visual subjects: animals, objects, fictional characters, generic person presence.

No human identity recognition, name-to-face matching, face templates or biometric
reference uploads. Target text is data; the model must independently reject a
request that attempts to identify a real person under any target category.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass

from .errors import SetupError
from .safety import require_visual_request_safe

KINDS = ("natural_language", "animal", "object", "fictional_character", "person_presence")
LEGACY_SCOPE = "legacy-tiger-v4"


@dataclass(frozen=True)
class Query:
    description: str
    threshold: float | None = None
    photograph_only: bool | None = None
    require_sale: bool = False

    @property
    def sale_required(self):
        text = self.description.casefold().split("; exclude:", 1)[0] if isinstance(self.description, str) else ""
        inferred = bool(re.search(r"\b(for sale|offered for sale|selling|sales? offer|sales? listing)\b", text)) and "not for sale" not in text
        return self.require_sale or inferred


def plan_query(text):
    """Transparent routing hints; no claim of running nonexistent model ensembles."""
    lower = text.casefold().split("; exclude:", 1)[0]
    methods = ["semantic_vision", "approximate_boxes"]
    temporal = bool(re.search(r"\b(moving|motion|tracking|across frames|approach|depart|enters|exits|speed)\b", lower))
    segmentation = bool(re.search(r"\b(segmentation|pixel mask|per-pixel|segment every|precise outline)\b", lower))
    if re.search(r"\b(text|read|reads|reading|says|written|lettering|license plate|number plate|ocr)\b|[\"“]", lower):
        methods.append("visual_text_matching")
    if temporal:
        methods.append("ordered_frames_and_session_tracking")
    if segmentation:
        return {"methods": methods, "requires_video": temporal, "supported": False,
                "limitation": "Precise segmentation masks are not implemented; approximate boxes are available"}
    return {"methods": methods, "requires_video": temporal, "supported": True, "limitation": ""}


@dataclass(frozen=True)
class Target:
    kind: str = "animal"
    description: str = "tiger (Panthera tigris)"
    photograph_only: bool = True
    queries: tuple[Query, ...] = ()

    @property
    def all_queries(self):
        return self.queries or (Query(self.description, photograph_only=self.photograph_only),)

    def validate(self):
        if self.kind not in KINDS:
            raise SetupError("Invalid optional TARGET_KIND hint; natural_language accepts custom descriptions")
        if (not isinstance(self.description, str) or not 1 <= len(self.description.strip()) <= 300
                or re.search(r"[\x00-\x1f\x7f]", self.description)):
            raise SetupError("TARGET_DESCRIPTION must be 1–300 characters without control characters")
        if not 1 <= len(self.all_queries) <= 10:
            raise SetupError("Configure between 1 and 10 simultaneous targets")
        for query in self.all_queries:
            if not isinstance(query.description, str) or not 1 <= len(query.description.strip()) <= 300 or re.search(r"[\x00-\x1f\x7f]", query.description):
                raise SetupError("Each target must be 1–300 characters without control characters")
            if query.threshold is not None and (type(query.threshold) not in (int, float) or not 0 <= query.threshold <= 1):
                raise SetupError("Target thresholds must be numbers between 0 and 1")
            if query.photograph_only is not None and type(query.photograph_only) is not bool:
                raise SetupError("Target photograph_only must be true or false")
            if type(query.require_sale) is not bool:
                raise SetupError("Target require_sale must be true or false")
        require_visual_request_safe(q.description for q in self.all_queries)
        text = " ".join(q.description for q in self.all_queries).casefold()
        if self.kind == "person_presence" and text not in ("person", "any person", "any visible person"):
            raise SetupError("Person mode supports only 'any visible person', without a name or face identity")
        if re.search(r"\b(face\s*(match|recognition|recognise|recognize)|identify\s+(this|that|the)\s+(person|human)|"
                     r"named\s+(?:real\s+)?person|specific\s+person|biometric|who\s+is\s+(this|that))\b", text):
            raise SetupError("Specific-person identification and face matching are not supported")
        return self

    def signature(self, model, threshold, review_threshold):
        if self == Target() and model == "gemini-3.1-flash-lite" and threshold == 0.85 and review_threshold == 0.65:
            return LEGACY_SCOPE
        sale = any(q.sale_required for q in self.all_queries)
        data = {"contract": "sale-review-v6" if sale else "visual-subject-v5", "kind": self.kind, "description": self.description,
                "photograph_only": self.photograph_only, "model": model,
                "queries": [{"description": q.description, "threshold": q.threshold, "photograph_only": q.photograph_only,
                             **({"require_sale": q.sale_required} if sale else {})} for q in self.all_queries],
                "threshold": threshold, "review_threshold": review_threshold}
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:24]

    def user_payload(self):
        self.validate()
        return json.dumps({"optional_subject_hint": self.kind,
                           "targets": [{"id": "q" + str(i), "description": q.description,
                                        "photograph_only": self.photograph_only if q.photograph_only is None else q.photograph_only,
                                        "require_sale": q.sale_required,
                                        "plan": plan_query(q.description)}
                                       for i, q in enumerate(self.all_queries, 1)]}, ensure_ascii=True)


def target_from_env(env, boolean):
    raw_queries = env.get("TARGETS_JSON")
    kind = (env.get("TARGET_KIND") or ("natural_language" if raw_queries or env.get("TARGET_DESCRIPTION") else "animal")).strip().lower()
    description = env.get("TARGET_DESCRIPTION") or ("any visible person" if kind == "person_presence" else
                                                    "tiger (Panthera tigris)")
    photograph_only = boolean(env, "REQUIRE_PHOTOGRAPH", default=kind not in ("fictional_character", "natural_language"))
    if env.get("REFERENCE_FACE") or env.get("FACE_IMAGE") or env.get("PERSON_NAME") or env.get("REFERENCE_IMAGE"):
        raise SetupError("Name/face identification and reference image matching are not supported")
    queries = ()
    if raw_queries:
        try:
            parsed = json.loads(raw_queries)
            if not isinstance(parsed, list) or not 1 <= len(parsed) <= 10:
                raise ValueError
            normalized = []
            for value in parsed:
                if isinstance(value, str):
                    normalized.append(Query(value.strip()))
                elif isinstance(value, dict) and not set(value) - {"description", "threshold", "photograph_only", "require_sale"}:
                    normalized.append(Query(value["description"], value.get("threshold"), value.get("photograph_only"), value.get("require_sale", False)))
                else:
                    raise ValueError
            queries = tuple(normalized)
            description = queries[0].description
        except (ValueError, TypeError, KeyError, RecursionError):
            raise SetupError("TARGETS_JSON must be an array of descriptions or {description, threshold, photograph_only, require_sale} objects") from None
    if not isinstance(description, str):
        raise SetupError("Each target description must be text")
    return Target(kind, description.strip(), photograph_only, queries).validate()
