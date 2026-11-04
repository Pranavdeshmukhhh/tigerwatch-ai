"""Route explicitly suspected child-abuse content to no-fetch reporting only."""
from __future__ import annotations

import re

from .errors import SetupError


def child_safety_request(value):
    if not isinstance(value, str):
        return False
    text = value.casefold()
    if re.search(r"\b(csam|csem|child\s+(?:sexual\s+)?(?:abuse|exploitation)|child\s*porn(?:ography)?)\b", text):
        return True
    minor = re.search(r"\b(child(?:ren)?|minor(?:s)?|underage|kid(?:s)?|preteen|toddler)\b", text)
    sexual = re.search(r"\b(sex(?:ual|ually)?|nude(?:s)?|naked|porn(?:ography)?|explicit|exploit(?:ation|ed)?)\b", text)
    return bool(minor and sexual)


def require_visual_request_safe(descriptions):
    if any(child_safety_request(x) for x in descriptions):
        raise SetupError("Child-safety concerns use --report-url --category child_safety only; no media fetching or AI scanning")


def sale_signals(text):
    """Retain categorical English offer cues, never captions/contacts/locations.

    A clue is not evidence of legality, authenticity or completed commerce.
    Awareness/negation cues veto automatic sale confirmation.
    """
    if not isinstance(text, str):
        text = ""
    value = text[:8000].casefold()
    terms = ("for sale", "selling", "available for purchase", "buy now", "dm to buy", "taking orders", "shipping available")
    offers = [term for term in terms if re.search(r"\b" + re.escape(term) + r"\b", value)]
    negative = bool(re.search(r"\b(not for sale|do not buy|don't buy|stop (?:the )?(?:illegal )?trade|"
                              r"anti[- ]poaching|awareness|seized|confiscated|report (?:this|illegal)|news report|"
                              r"museum|educational|sold out)\b", value))
    price = bool(re.search(r"(?:[$€£₹]\s*\d|\b\d[\d,.]*\s*(?:usd|inr|eur|gbp)\b)", value))
    contact = bool(re.search(r"\b(dm|message|contact)\s+(?:me|us|for|to)\b", value))
    return {"offer_terms": offers, "price_present": price, "contact_offer": contact, "awareness_or_negation": negative}


def validated_signals(value):
    if not isinstance(value, dict) or set(value) != {"offer_terms", "price_present", "contact_offer", "awareness_or_negation"}:
        return sale_signals("")
    allowed = set(sale_signals("for sale selling available for purchase buy now dm to buy taking orders shipping available")["offer_terms"])
    if (not isinstance(value["offer_terms"], list) or len(value["offer_terms"]) > len(allowed)
            or any(not isinstance(x, str) or x not in allowed for x in value["offer_terms"])
            or any(type(value[k]) is not bool for k in ("price_present", "contact_offer", "awareness_or_negation"))):
        return sale_signals("")
    return {**value, "offer_terms": list(dict.fromkeys(value["offer_terms"]))}
