"""Deterministic claim verifier: every number in the draft must trace to results."""
from __future__ import annotations

import re
from typing import Any

REQUIRED_SECTIONS = ["## Cohort", "## Models and metrics",
                     "## Checks and abstentions", "## Limitations"]

FORBIDDEN_PHRASES = [
    "clinically validated",
    "proves",
    "causes",
    "should be used",
    "outperforms",
    "state-of-the-art",
]

_NUM_RE = re.compile(r"(?<![\w.%])\d[\d,]*(?:\.\d+)?\s*%?(?![\w.%])")
_SIG_RE = re.compile(r"\bsignificant\b", re.IGNORECASE)
_PNUM_RE = re.compile(r"p\s*[=<≤]\s*(0?\.\d+|1\.0+|<\s*0?\.\d+)", re.IGNORECASE)


def flatten_results(obj: Any, prefix: str = "") -> dict[str, float]:
    """Flatten every numeric leaf of a results-like dict to {dotted.path: value}."""
    out: dict[str, float] = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.update(flatten_results(v, f"{prefix}{k}."))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out.update(flatten_results(v, f"{prefix}{i}."))
    elif isinstance(obj, bool):
        pass
    elif isinstance(obj, (int, float)):
        out[prefix[:-1]] = float(obj)
    return out


def extract_numbers(text: str) -> list[dict]:
    """Numeric tokens with display precision and context."""
    tokens = []
    for m in _NUM_RE.finditer(text):
        raw = m.group(0).strip()
        is_pct = raw.endswith("%")
        val = raw.rstrip("%").replace(",", "")
        decimals = len(val.split(".")[1]) if "." in val else 0
        ctx = text[max(0, m.start() - 30): m.end() + 30].replace("\n", " ")
        tokens.append({"token": raw, "value": float(val), "is_pct": is_pct,
                       "decimals": decimals, "context": ctx.strip()})
    return tokens


def _checks_section(draft: str) -> str:
    m = re.search(r"##\s*Checks and abstentions\s*\n(.*?)(?=\n\s*##|\Z)",
                  draft, re.S | re.I)
    return m.group(1) if m else ""


def _has_section(draft: str, title: str) -> bool:
    return bool(re.search(r"^##\s*" + re.escape(title[3:]) + r"\s*$",
                          draft, re.I | re.M))


def verify_draft(draft: str, flat_values: dict[str, float],
                 checks: list[dict]) -> dict:
    values = list(flat_values.values())
    unverified, forbidden, missing = [], [], []

    has_time_keys = {
        t for t in (12, 24, 36)
        if any(k.endswith(f"_{t}m") or f"_{t}m" in k for k in flat_values)
    }

    for tok in extract_numbers(draft):
        v, tol = tok["value"], 0.5 * 10 ** (-tok["decimals"])
        ok = any(abs(v - fv) <= tol for fv in values)
        if not ok and tok["is_pct"]:
            ok = any(abs(v / 100.0 - fv) <= tol for fv in values)
        if not ok and tok["decimals"] == 0 and int(v) in (12, 24, 36) \
                and int(v) in has_time_keys:
            ok = True
        if not ok:
            unverified.append({"token": tok["token"], "context": tok["context"]})

    low = draft.lower()
    for phrase in FORBIDDEN_PHRASES:
        if phrase in low:
            forbidden.append(phrase)
    if re.search(r"\brobust\b", low):
        forbidden.append("robust")

    for m in _SIG_RE.finditer(draft):
        window = draft[m.end(): m.end() + 40]
        pm = _PNUM_RE.search(window)
        ok = False
        if pm:
            num = pm.group(1).replace("<", "").strip()
            pv = float(num)
            tol = 0.5 * 10 ** (-len(num.split(".")[1])) if "." in num else 0.5
            ok = any(abs(pv - fv) <= tol for fv in values)
        if not ok:
            forbidden.append(f"significant (unverified p-value near offset {m.start()})")

    for sec in REQUIRED_SECTIONS:
        if not _has_section(draft, sec):
            missing.append(sec)

    abstention_missing = False
    if any(c.get("passed") is False for c in checks):
        abstention_missing = "abstain" not in _checks_section(draft).lower()

    return {
        "passed": not unverified and not forbidden and not missing and not abstention_missing,
        "unverified_numbers": unverified,
        "forbidden": forbidden,
        "missing_sections": missing,
        "abstention_missing": abstention_missing,
    }
