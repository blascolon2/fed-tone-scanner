from __future__ import annotations

import io
import json
import time
from dataclasses import asdict
from typing import Any, Dict, Optional, Tuple

import pandas as pd
import streamlit as st
import yaml

from extractors import extract_text_from_upload
from scanner import (
    KeywordConfig,
    ScanResult,
    analyze_text,
    compare_results,
    config_from_dict,
    config_to_dict,
    results_to_csv_bytes,
    results_to_json_bytes,
)


st.set_page_config(page_title="Fed Tone Scanner", layout="wide")

st.title("Fed Tone Scanner")
st.caption(
    "Upload a Fed statement/speech (TXT/PDF/DOCX) and score hawkish vs dovish language. "
    "Optional baseline diff included."
)

# ---------- Load default keywords.yaml into session state ----------
def _load_default_yaml() -> str:
    try:
        with open("keywords.yaml", "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        # Fallback defaults if user forgot the file
        default = {
            "hawkish": {
                "higher for longer": 4,
                "restrictive": 2,
                "inflation remains elevated": 4,
                "further tightening": 3,
                "not appropriate to cut": 4,
                "strong labor market": 2,
            },
            "dovish": {
                "disinflation": 3,
                "inflation has eased": 4,
                "balance of risks": 2,
                "patient": 1,
                "rate cuts": 4,
                "policy adjustment": 2,
            },
        }
        return yaml.safe_dump(default, sort_keys=False)


if "keywords_yaml" not in st.session_state:
    st.session_state["keywords_yaml"] = _load_default_yaml()

# ---------- Sidebar controls ----------
with st.sidebar:
    st.header("Inputs")

    primary_file = st.file_uploader(
        "Primary document (required)",
        type=["txt", "pdf", "docx"],
        accept_multiple_files=False,
    )

    baseline_file = st.file_uploader(
        "Baseline document (optional)",
        type=["txt", "pdf", "docx"],
        accept_multiple_files=False,
        help="If provided, we compute delta scores and phrase changes vs baseline.",
    )

    st.divider()
    st.subheader("Keyword config (YAML)")

    keywords_yaml = st.text_area(
        "Edit hawkish/dovish phrases + weights",
        value=st.session_state["keywords_yaml"],
        height=320,
    )

    st.session_state["keywords_yaml"] = keywords_yaml

    analyze_btn = st.button("Analyze", type="primary", use_container_width=True)


# ---------- Helper display functions ----------
def _hits_df(result: ScanResult, category: str) -> pd.DataFrame:
    hits = result.hits.get(category, [])
    if not hits:
        return pd.DataFrame(columns=["phrase", "count", "weight", "contribution"])
    return pd.DataFrame(hits).sort_values(by="contribution", ascending=False)


def _delta_df(delta: Dict[str, Dict[str, Any]], category: str) -> pd.DataFrame:
    # delta[category] is list of dicts with phrase, count_current, count_baseline, diff
    rows = delta.get(category, [])
    if not rows:
        return pd.DataFrame(columns=["phrase", "count_current", "count_baseline", "diff"])
    df = pd.DataFrame(rows)
    # show biggest absolute diffs first
    df["absdiff"] = df["diff"].abs()
    df = df.sort_values(by="absdiff", ascending=False).drop(columns=["absdiff"])
    return df


def _validate_and_load_config(yaml_text: str) -> Tuple[Optional[KeywordConfig], Optional[str]]:
    try:
        data = yaml.safe_load(yaml_text)
        if not isinstance(data, dict):
            return None, "YAML must be a dictionary with keys: hawkish, dovish."

        cfg = config_from_dict(data)
        return cfg, None
    except yaml.YAMLError as e:
        return None, f"YAML parse error: {e}"
    except Exception as e:
        return None, f"Keyword config error: {e}"


# ---------- Main logic ----------
if analyze_btn:
    if primary_file is None:
        st.error("Please upload a primary document first.")
        st.stop()

    cfg, err = _validate_and_load_config(st.session_state["keywords_yaml"])
    if err:
        st.error(err)
        st.stop()

    # Extract text
    try:
        primary_text = extract_text_from_upload(primary_file)
    except Exception as e:
        st.error(f"Could not read primary document: {e}")
        st.stop()

    baseline_text = None
    if baseline_file is not None:
        try:
            baseline_text = extract_text_from_upload(baseline_file)
        except Exception as e:
            st.error(f"Could not read baseline document: {e}")
            st.stop()

    # Analyze
    primary_result = analyze_text(
        text=primary_text,
        cfg=cfg,
        filename=getattr(primary_file, "name", "primary"),
    )

    baseline_result = None
    comparison = None
    if baseline_text is not None:
        baseline_result = analyze_text(
            text=baseline_text,
            cfg=cfg,
            filename=getattr(baseline_file, "name", "baseline"),
        )
        comparison = compare_results(primary_result, baseline_result)

    # Display
    colA, colB, colC = st.columns(3)
    colA.metric("Net score (dovish - hawkish)", f"{primary_result.scores.net_score}")
    colB.metric("Dovish score", f"{primary_result.scores.dovish_score}")
    colC.metric("Hawkish score", f"{primary_result.scores.hawkish_score}")

    interp = primary_result.interpretation
    st.subheader(f"Interpretation: {interp}")

    st.write(
        f"**Document:** `{primary_result.metadata.filename}`  \n"
        f"**Total words (approx):** {primary_result.metadata.total_words}  \n"
        f"**Timestamp:** {primary_result.metadata.timestamp}"
    )

    if comparison is not None:
        st.info(
            f"Baseline: `{comparison['baseline_filename']}` | "
            f"Delta net (current - baseline): **{comparison['delta_net']}**"
        )

    st.divider()

    left, right = st.columns(2)

    with left:
        st.subheader("Dovish hits")
        df_dov = _hits_df(primary_result, "dovish")
        st.dataframe(df_dov, use_container_width=True, hide_index=True)

    with right:
        st.subheader("Hawkish hits")
        df_haw = _hits_df(primary_result, "hawkish")
        st.dataframe(df_haw, use_container_width=True, hide_index=True)

    if comparison is not None:
        st.divider()
        st.subheader("Changes vs baseline (phrase counts)")

        col1, col2 = st.columns(2)
        with col1:
            st.markdown("### Dovish phrase changes")
            st.dataframe(_delta_df(comparison["phrase_deltas"], "dovish"),
                         use_container_width=True, hide_index=True)
        with col2:
            st.markdown("### Hawkish phrase changes")
            st.dataframe(_delta_df(comparison["phrase_deltas"], "hawkish"),
                         use_container_width=True, hide_index=True)

    # Downloads
    st.divider()
    st.subheader("Download results")

    json_bytes = results_to_json_bytes(primary_result, baseline_result)
    csv_bytes = results_to_csv_bytes(primary_result, baseline_result)

    dl1, dl2 = st.columns(2)
    with dl1:
        st.download_button(
            label="Download JSON",
            data=json_bytes,
            file_name="fed_tone_results.json",
            mime="application/json",
            use_container_width=True,
        )
    with dl2:
        st.download_button(
            label="Download CSV",
            data=csv_bytes,
            file_name="fed_tone_results.csv",
            mime="text/csv",
            use_container_width=True,
        )

else:
    st.markdown(
        """
### How to use
1. Upload a **primary** document (TXT/PDF/DOCX).
2. Optionally upload a **baseline** document to compare.
3. (Optional) Edit the **keyword YAML** in the sidebar.
4. Click **Analyze**.

Tip: Markets move on **changes in wording**, so the baseline feature is the most powerful part.
"""
    )
