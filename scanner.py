from __future__ import annotations

import csv
import io
import json
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


@dataclass(frozen=True)
class Scores:
    hawkish_score: int
    dovish_score: int
    net_score: int


@dataclass(frozen=True)
class Metadata:
    filename: str
    timestamp: str
    total_words: int


@dataclass(frozen=True)
class ScanResult:
    scores: Scores
    hits: Dict[str, List[Dict[str, Any]]]
    interpretation: str
    metadata: Metadata


@dataclass(frozen=True)
class KeywordConfig:
    hawkish: Dict[str, int]
    dovish: Dict[str, int]


def normalize_text(text: str) -> str:
    """Lowercase and collapse whitespace for consistent phrase matching."""
    t = text.lower()
    t = re.sub(r"\s+", " ", t).strip()
    return t


def count_overlapping(text: str, phrase: str) -> int:
    """
    Count occurrences of a phrase allowing overlaps using a regex lookahead.
    Example: text='aaaa', phrase='aa' => 3 overlaps.
    """
    if not phrase:
        return 0
    pattern = re.compile(r"(?=" + re.escape(phrase) + r")")
    return len(pattern.findall(text))


def _hits_for_category(text_norm: str, phrase_weights: Dict[str, int]) -> Tuple[List[Dict[str, Any]], int]:
    hits: List[Dict[str, Any]] = []
    total = 0
    for phrase, weight in phrase_weights.items():
        p_norm = normalize_text(phrase)
        c = count_overlapping(text_norm, p_norm)
        if c > 0:
            contribution = c * int(weight)
            total += contribution
            hits.append(
                {
                    "phrase": phrase,
                    "count": c,
                    "weight": int(weight),
                    "contribution": contribution,
                }
            )
    return hits, total


def interpret(net_score: int) -> str:
    if net_score > 0:
        return "Dovish tilt"
    if net_score < 0:
        return "Hawkish tilt"
    return "Neutral"


def analyze_text(text: str, cfg: KeywordConfig, filename: str = "document") -> ScanResult:
    text_norm = normalize_text(text)
    total_words = len(text_norm.split()) if text_norm else 0
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")

    dov_hits, dov_score = _hits_for_category(text_norm, cfg.dovish)
    haw_hits, haw_score = _hits_for_category(text_norm, cfg.hawkish)

    net = dov_score - haw_score

    return ScanResult(
        scores=Scores(hawkish_score=haw_score, dovish_score=dov_score, net_score=net),
        hits={"dovish": dov_hits, "hawkish": haw_hits},
        interpretation=interpret(net),
        metadata=Metadata(filename=filename, timestamp=timestamp, total_words=total_words),
    )


def config_from_dict(d: Dict[str, Any]) -> KeywordConfig:
    """
    Validate and convert dict loaded from YAML into KeywordConfig.
    Expected:
      { "hawkish": {phrase: weight, ...}, "dovish": {...} }
    """
    if "hawkish" not in d or "dovish" not in d:
        raise ValueError("YAML must include top-level keys: 'hawkish' and 'dovish'.")

    haw = d["hawkish"]
    dov = d["dovish"]

    if not isinstance(haw, dict) or not isinstance(dov, dict):
        raise ValueError("'hawkish' and 'dovish' must each be dictionaries of phrase -> weight.")

    def _clean_map(m: Dict[str, Any]) -> Dict[str, int]:
        out: Dict[str, int] = {}
        for k, v in m.items():
            if not isinstance(k, str) or not k.strip():
                raise ValueError("All phrases must be non-empty strings.")
            try:
                out[k] = int(v)
            except Exception:
                raise ValueError(f"Weight for phrase '{k}' must be an integer.")
        return out

    return KeywordConfig(hawkish=_clean_map(haw), dovish=_clean_map(dov))


def config_to_dict(cfg: KeywordConfig) -> Dict[str, Dict[str, int]]:
    return {"hawkish": dict(cfg.hawkish), "dovish": dict(cfg.dovish)}


def compare_results(current: ScanResult, baseline: ScanResult) -> Dict[str, Any]:
    """
    Compare phrase counts between current and baseline for the union of phrases in BOTH configs.
    Returns phrase deltas and delta_net.
    """
    delta_net = current.scores.net_score - baseline.scores.net_score

    # Build phrase -> count maps
    def _count_map(result: ScanResult, category: str) -> Dict[str, int]:
        m: Dict[str, int] = {}
        for row in result.hits.get(category, []):
            m[row["phrase"]] = int(row["count"])
        return m

    cur_d = _count_map(current, "dovish")
    cur_h = _count_map(current, "hawkish")
    base_d = _count_map(baseline, "dovish")
    base_h = _count_map(baseline, "hawkish")

    def _delta_rows(cur: Dict[str, int], base: Dict[str, int]) -> List[Dict[str, Any]]:
        phrases = sorted(set(cur.keys()) | set(base.keys()))
        rows: List[Dict[str, Any]] = []
        for p in phrases:
            ccur = cur.get(p, 0)
            cbase = base.get(p, 0)
            diff = ccur - cbase
            if diff != 0:
                rows.append(
                    {
                        "phrase": p,
                        "count_current": ccur,
                        "count_baseline": cbase,
                        "diff": diff,
                    }
                )
        return rows

    phrase_deltas = {
        "dovish": _delta_rows(cur_d, base_d),
        "hawkish": _delta_rows(cur_h, base_h),
    }

    return {
        "delta_net": delta_net,
        "baseline_filename": baseline.metadata.filename,
        "phrase_deltas": phrase_deltas,
    }


def results_to_json_bytes(current: ScanResult, baseline: Optional[ScanResult] = None) -> bytes:
    out: Dict[str, Any] = {
        "scores": {
            "hawkish": current.scores.hawkish_score,
            "dovish": current.scores.dovish_score,
            "net": current.scores.net_score,
        },
        "hits": current.hits,
        "metadata": {
            "filename": current.metadata.filename,
            "timestamp": current.metadata.timestamp,
            "total_words": current.metadata.total_words,
        },
    }

    if baseline is not None:
        out["baseline"] = {
            "scores": {
                "hawkish": baseline.scores.hawkish_score,
                "dovish": baseline.scores.dovish_score,
                "net": baseline.scores.net_score,
            },
            "metadata": {
                "filename": baseline.metadata.filename,
                "timestamp": baseline.metadata.timestamp,
                "total_words": baseline.metadata.total_words,
            },
        }
        out["scores"]["delta_net"] = current.scores.net_score - baseline.scores.net_score

    return json.dumps(out, indent=2).encode("utf-8")


def results_to_csv_bytes(current: ScanResult, baseline: Optional[ScanResult] = None) -> bytes:
    """
    CSV rows:
    category, phrase, count, weight, contribution
    and (if baseline) same for baseline in separate block.
    """
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["section", "category", "phrase", "count", "weight", "contribution"])

    def _write_block(section_name: str, result: ScanResult) -> None:
        for category in ("dovish", "hawkish"):
            for row in result.hits.get(category, []):
                writer.writerow(
                    [
                        section_name,
                        category,
                        row["phrase"],
                        row["count"],
                        row["weight"],
                        row["contribution"],
                    ]
                )

    _write_block("current", current)
    if baseline is not None:
        _write_block("baseline", baseline)

    return buf.getvalue().encode("utf-8")
