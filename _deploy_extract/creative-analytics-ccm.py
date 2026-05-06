import streamlit as st
import pandas as pd
import re
import base64
import os
import glob
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from PIL import Image
from io import BytesIO
import plotly.express as px
import plotly.graph_objects as go
import plotly.io as pio
from plotly.subplots import make_subplots
import warnings
import textwrap
warnings.filterwarnings('ignore')

# ── Force a consistent light theme for all charts ────────────────────────────
# Some users view the app on machines with OS dark mode enabled. Without an
# explicit template, Plotly/Streamlit can render charts with a dark background
# which makes the bars/labels hard to read. We start from the built-in "plotly"
# template (which matches the app's prior look) and pin backgrounds + text
# colors so dark mode can't override them.
_light_template = pio.templates["plotly"]
_light_template.layout.paper_bgcolor = "#ffffff"
_light_template.layout.plot_bgcolor = "#ffffff"
_light_template.layout.font.color = "#1d2735"
_light_template.layout.xaxis.color = "#1d2735"
_light_template.layout.yaxis.color = "#1d2735"
# Hide axis lines (spines) — simple_white had solid black lines that weren't
# there before. Grid stays as a subtle gray so charts still read cleanly.
_light_template.layout.xaxis.showline = False
_light_template.layout.yaxis.showline = False
_light_template.layout.xaxis.gridcolor = "#eeeeee"
_light_template.layout.yaxis.gridcolor = "#eeeeee"
_light_template.layout.xaxis.zeroline = False
_light_template.layout.yaxis.zeroline = False
pio.templates["orcha_light"] = _light_template
pio.templates.default = "orcha_light"

# Bump this value whenever parsing/grouping logic changes so cached uploads are
# reprocessed with the latest rules.
PROCESSING_LOGIC_VERSION = "2026-04-28-topline-date-column-v1"


class _HealthHandler(BaseHTTPRequestHandler):
    """Serve a minimal liveness endpoint for deployment health checks."""

    def do_GET(self):
        if self.path == "/health":
            body = b"OK"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, format, *args):
        return


def _start_health_server():
    host = os.getenv("HEALTH_HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8080"))

    def _run_server():
        try:
            server = ThreadingHTTPServer((host, port), _HealthHandler)
            server.serve_forever()
        except OSError:
            pass

    thread = threading.Thread(target=_run_server, daemon=True)
    thread.start()


_start_health_server()

# ==============================
# Page Config
# ==============================
st.set_page_config(page_title="CREATIVE ANALYSIS TOOL", page_icon="chart_with_upwards_trend", layout="wide")

st.markdown(
    """
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&display=swap');

:root {
    --bg-soft: #f6f8fb;
    --panel: #ffffff;
    --text-strong: #1d2735;
    --text-muted: #5d6979;
    --accent: #3a4e66;
    --border-soft: #dde3ea;
}

.stApp {
    font-family: 'Space Grotesk', 'Segoe UI', sans-serif;
    background: var(--bg-soft);
    color: var(--text-strong);
}

.block-container {
    max-width: 1450px;
    padding-top: 1.4rem;
    padding-bottom: 2rem;
}

h1, h2, h3 {
    letter-spacing: 0.01em;
}

div[data-testid="stMarkdownContainer"] h3 {
    margin-top: 1.15rem;
    margin-bottom: 0.45rem;
    font-weight: 700;
}

div[data-testid="stMarkdownContainer"] h2 {
    margin-top: 1rem;
    margin-bottom: 0.5rem;
}

div[data-testid="stMarkdownContainer"] p {
    line-height: 1.45;
}

.hero-wrap {
    background: var(--panel);
    border: 1px solid var(--border-soft);
    border-radius: 16px;
    padding: 1rem 1.25rem 0.95rem 1.25rem;
    box-shadow: 0 6px 16px rgba(22, 35, 56, 0.05);
    margin-bottom: 0.85rem;
}

.hero-title {
    margin: 0;
    font-size: 1.95rem;
    font-weight: 700;
    color: var(--text-strong);
}

.hero-sub {
    margin: 0.25rem 0 0 0;
    color: var(--text-muted);
    font-size: 0.98rem;
}

.howto-wrap {
    background: var(--panel);
    border: 1px solid var(--border-soft);
    border-radius: 12px;
    padding: 0.7rem 0.9rem 0.6rem 0.9rem;
    margin-bottom: 0.5rem;
}

div[data-testid="stFileUploader"] {
    background: rgba(255, 255, 255, 0.86);
    border: 1px solid var(--border-soft);
    border-radius: 12px;
    padding: 0.55rem 0.6rem;
}

div[data-testid="stMetric"] {
    border-radius: 12px;
    border: 1px solid var(--border-soft);
    background: var(--panel);
    padding: 0.4rem;
}

div[data-testid="stMarkdownContainer"] hr {
    border-color: var(--border-soft);
    margin-top: 1rem;
    margin-bottom: 1rem;
}

div[data-testid="stPlotlyChart"] {
    border: 1px solid var(--border-soft);
    border-radius: 10px;
    background: #ffffff;
    padding: 0.25rem;
    margin-bottom: 0rem;
}

div[data-testid="stColumn"] {
    margin-top: -0.15rem;
}
</style>
""",
    unsafe_allow_html=True,
)

# ── Hero block ───────────────────────────────────────────────────────────────
st.markdown(
    """
<div class="hero-wrap">
  <h1 class="hero-title">Creative Analysis Tool</h1>
  <p class="hero-sub">Automates the creative reporting process by visualizing top to low-performing creatives, with interactive filtering capabilities. Add results in your client presentations and use insights to drive A/Rs!</p>
</div>
""",
    unsafe_allow_html=True,
)

# ── How-to section ───────────────────────────────────────────────────────────
st.markdown(
    """
<div class="howto-wrap">
  <strong>How to use:</strong>
  <ol style="margin-top:0.4rem;margin-bottom:0;color:#5d6979;line-height:1.8;">
    <li>Download the Amazon DSP report <a href="https://advertising.amazon.com/dsp/ENTITYA6I16E0BHHHY/report/custom-report/new" target="_blank">here</a> &mdash; set time unit to <strong>DAILY</strong>, click <strong>SELECT ALL</strong> columns, and set report period to <strong>ALL TIME</strong>.</li>
    <li>Download creative images/videos <em>*recommend all same size!</em> Name them by creative identifier for auto-mapping or drag and drop them in below using the checkbox.</li>
    <li>Upload the report and images below.</li>
  </ol>
</div>
""",
    unsafe_allow_html=True,
)

# Inline click-to-zoom lightbox: stays in the app (no new page), full-screen overlay
# with an X button to close. Uses CSS :target so no JavaScript needed.
st.markdown(
    """
<style>
.howto-lightbox-thumb {
    display: inline-block;
    cursor: zoom-in;
    border: 1px solid var(--border-soft);
    border-radius: 6px;
    overflow: hidden;
    margin-bottom: 0.5rem;
    transition: transform 0.15s ease, box-shadow 0.15s ease;
}
.howto-lightbox-thumb:hover {
    transform: scale(1.02);
    box-shadow: 0 4px 12px rgba(22, 35, 56, 0.15);
}
.howto-lightbox-thumb img {
    display: block;
    width: 200px;
    height: auto;
}
.howto-lightbox-overlay {
    position: fixed;
    top: 0;
    left: 0;
    width: 100vw;
    height: 100vh;
    background: rgba(0, 0, 0, 0.88);
    z-index: 999999;
    display: none;
    align-items: center;
    justify-content: center;
    padding: 40px;
    box-sizing: border-box;
}
.howto-lightbox-overlay:target {
    display: flex;
}
.howto-lightbox-overlay img {
    max-width: 95vw;
    max-height: 90vh;
    object-fit: contain;
    border-radius: 6px;
    box-shadow: 0 10px 40px rgba(0, 0, 0, 0.5);
}
.howto-lightbox-close {
    position: absolute;
    top: 18px;
    right: 24px;
    color: #fff;
    background: rgba(255, 255, 255, 0.15);
    border: 2px solid rgba(255, 255, 255, 0.6);
    border-radius: 50%;
    width: 44px;
    height: 44px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 22px;
    font-weight: 700;
    text-decoration: none;
    cursor: pointer;
    transition: background 0.15s ease;
}
.howto-lightbox-close:hover {
    background: rgba(255, 255, 255, 0.3);
}
.howto-lightbox-backdrop {
    position: absolute;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    cursor: zoom-out;
}
</style>
""",
    unsafe_allow_html=True,
)

def _howto_image(path, anchor_id):
    """Render a clickable thumbnail that opens an in-app full-screen lightbox."""
    if not path or not os.path.exists(path):
        return
    try:
        with open(path, "rb") as f:
            img_b64 = base64.b64encode(f.read()).decode("utf-8")
        ext = os.path.splitext(path)[1].lower().lstrip(".") or "png"
        if ext == "jpg":
            ext = "jpeg"
        src = f"data:image/{ext};base64,{img_b64}"
        st.markdown(
            f"""
<a class="howto-lightbox-thumb" href="#{anchor_id}">
  <img src="{src}" alt="{anchor_id}" />
</a>
<div id="{anchor_id}" class="howto-lightbox-overlay">
  <a class="howto-lightbox-backdrop" href="#"></a>
  <a class="howto-lightbox-close" href="#" title="Close">&times;</a>
  <img src="{src}" alt="{anchor_id} expanded" />
</div>
""",
            unsafe_allow_html=True,
        )
    except Exception:
        pass

_daily_path     = os.path.join(os.path.dirname(__file__), "assets", "dsp-daily-example.png")
_select_path    = os.path.join(os.path.dirname(__file__), "assets", "dsp-select-all-example.png")
_alltime_path   = os.path.join(os.path.dirname(__file__), "assets", "dsp-alltime-example.png")

with st.expander("📋 How to download the DSP report (screenshots)"):
    st.markdown("_Tip: click any screenshot to enlarge._")
    st.markdown("**1 — Set Time Unit to Daily**")
    _howto_image(_daily_path, "howto-img-daily")
    st.markdown("**2 — Click SELECT ALL columns**")
    _howto_image(_select_path, "howto-img-select")
    st.markdown("**3 — Set Report Period to ALL TIME**")
    _howto_image(_alltime_path, "howto-img-alltime")

st.markdown(
    '<p style="font-size:0.82rem;color:#6b7280;margin-top:0.6rem;">' +
    'Questions? Slack <strong>@esawhney</strong> or join <strong>#ccm-creative-analysis-tool</strong></p>',
    unsafe_allow_html=True,
)

# ==============================
# GET CREATIVE IDENTIFIER
# ==============================
# Extracts the creative identifier ("Unique ID" / creative version name) from
# the ad-name string.  Amazon DSP reports use underscore-delimited naming with
# product-specific conventions:
#
#   Global template:
#     Locale_OrderName_CreativeType_ProductType_Size_ASIN_FlightDate_Placement_DCP-ID_UniqueID
#
#   Product variations:
#     DSP (AAP):   ..._CreativeType_ProductType_Size_ASIN_FlightDate_Placement_UniqueID
#     IMDb:        ..._CreativeType_ProductType_Size_ASIN_FlightDate_Placement_DCP-ID_UniqueID
#     Devices (FTV/FireTablet/Kindle): ..._OP Single/Multi_CreativeName_CTA_Format__WxH_
#     STV - PVA:   OrderConvention + Ad1/Ad2/Ad3 suffixes
#     STV - Twitch: TWITCH_[LOCALE]_DESKTOP_STREAM_DISPLAY_ADS_GUARANTEED
#     Class 1:     Class 1: AMZN [LOCALE] ... _DCP-ID_UniqueID
#     Audio Ads:   Audio Ads - Guaranteed - Cross Device - RON - US
#
# The function applies a priority chain of pattern-matching strategies to
# reliably extract the creative identifier across all products.

# -- Precompiled patterns for noise-token detection --
_SIZE_PATTERN = re.compile(r'^\d{2,4}x\d{2,4}$')
_DATE_RANGE_PATTERN = re.compile(r'\d{4}-\d{2}-\d{2}\s*-\s*\d{4}-\d{2}-\d{2}')

# Tokens that are NOT creative names -- they are CTAs, format codes, or placement labels
_CTA_TOKENS = frozenset({
    'watch now', 'play now', 'shop now', 'learn more', 'subscribe now',
    'buy now', 'stream now', 'listen now', 'sign up', 'get started',
    'order now', 'explore now', 'discover more', 'see more', 'download now',
    'try now', 'view now', 'book now', 'apply now', 'save now',
})
_FORMAT_TOKENS = frozenset({
    'dp', 'video', 'static', 'image', 'gif', 'html5', 'mp4', 'mov',
})
_PLACEMENT_TOKENS = frozenset({
    'guaranteed', 'auction', 'programmatic', 'reserved', 'desktop',
    'mobile', 'stream', 'display', 'ads', 'feed', 'preroll', 'bumper',
    'ron', 'ros',
})
_CREATIVE_TYPE_TOKENS = frozenset({
    'video 6s', 'video 10s', 'video 15s', 'video 20s', 'video 30s',
    'video 60s', 'image (static)', 'image (static)', 'image - mobile o&o',
    'image', 'static',
})
# Month/date-range shorthand tokens common in line item names
_MONTH_TOKENS = frozenset({
    'jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct',
    'nov', 'dec', 'jan-mar', 'apr-jun', 'jul-sep', 'oct-dec', 'jan-feb',
    'feb-mar', 'mar-apr', 'apr-may', 'may-jun', 'jun-jul', 'jul-aug',
    'aug-sep', 'sep-oct', 'oct-nov', 'nov-dec', 'jan-dec',
})


def _is_noise_token(t):
    """Return True if token is non-creative noise (dimensions, CTA, format, placement, etc.)."""
    t_clean = t.strip()
    if not t_clean:
        return True
    t_lower = t_clean.lower()

    # Dimensions like 1920x1080, 320x180, 980x55x250
    if _SIZE_PATTERN.match(t_lower):
        return True
    # Also catch multi-dimension tokens like "980x55x250"
    if re.fullmatch(r'\d{2,4}x\d{2,4}(x\d{2,4})?', t_lower):
        return True

    # Call-to-action phrases
    if t_lower in _CTA_TOKENS:
        return True

    # Format/placement codes
    if t_lower in _FORMAT_TOKENS:
        return True

    # Placement tokens (Twitch / STV line items)
    if t_lower in _PLACEMENT_TOKENS:
        return True

    # Campaign promo suffixes
    if t_lower.startswith('pvc promo'):
        return True

    # Month/flight-window shorthand
    if t_lower in _MONTH_TOKENS:
        return True

    # Locale-only tokens (2-3 letter country codes at very start)
    # We don't strip these here -- they are handled contextually

    return False


def _looks_like_dcp(s):
    """Return True if the token looks like a DCP code or long numeric ID."""
    if not s:
        return False
    s_low = s.lower()
    if re.search(r"\bdcp\d+\b", s_low):
        return True
    # numeric-only tokens of length >= 5 are also likely IDs (e.g. ASIN, Campaign ID)
    if re.fullmatch(r"\d{5,}", s_low):
        return True
    return False


def _looks_like_size_token(s):
    """Return True if the token is an ad-size dimension string."""
    if not s:
        return False
    return bool(_SIZE_PATTERN.match(s.strip().lower())) or bool(re.fullmatch(r'\d{2,4}x\d{2,4}(x\d{2,4})?', s.strip().lower()))


def _looks_like_creative_type(s):
    """Return True if the token matches a known creative-type label."""
    if not s:
        return False
    s_low = s.strip().lower()
    if s_low in _CREATIVE_TYPE_TOKENS:
        return True
    # Patterns like "Video 15s", "Video 30s", "Image (Static)"
    if re.match(r'^video\s+\d+s$', s_low):
        return True
    if re.match(r'^image\s*(\(.*\))?$', s_low):
        return True
    if re.match(r'^image\s*-\s*mobile', s_low):
        return True
    return False


def _looks_like_class_label(s):
    """Return True if the token is a Class label like 'Class 1'."""
    if not s:
        return False
    return bool(re.match(r'^class\s+\d+$', s.strip().lower()))


def _pick_first_matching_column(normed_cols, aliases):
    """Return first source column whose normalized name matches any alias."""
    for alias in aliases:
        if alias in normed_cols:
            return normed_cols[alias]
    return None


def _pick_video_column_by_tokens(normed_cols, include_tokens):
    """Fallback matcher that picks a normalized column containing all required tokens."""
    for norm_name, original_col in normed_cols.items():
        if all(token in norm_name for token in include_tokens):
            return original_col
    return None


def _resolve_video_columns_with_fallback(df, normed_cols, standard_start, standard_complete, pg_start, pg_complete, row_mask=None):
    """Pick the video start/complete columns that ACTUALLY have data.

    Some non-guaranteed Online Video (OLV) reports populate "Video start" /
    "Video complete" (the PG-style columns) even when the campaign isn't PG
    — e.g., "Non-Guaranteed - OLV - VCR" ads. The standard-path "Video started"
    / "Video completed" columns are zero for those rows, so VCR calculations
    return 0 unless we fall back.

    Rules:
    - If `standard_complete` exists AND has non-zero data in the target rows,
      use the standard pair (preserves existing behavior for reports that work).
    - Else if `pg_complete` exists AND has non-zero data in the target rows,
      use the PG-style pair as a fallback.
    - Else return whatever was passed (unchanged).

    `row_mask` (optional) restricts the zero-check to a subset of rows (e.g.,
    only the non-PG rows when resolving standard columns).
    """
    def _col_has_data(col_name):
        if not col_name or col_name not in df.columns:
            return False
        try:
            series = pd.to_numeric(df[col_name], errors="coerce").fillna(0)
            if row_mask is not None and len(row_mask) == len(series):
                series = series[row_mask]
            return bool(series.sum() > 0)
        except Exception:
            return False

    # Prefer the standard pair if its "complete" column has data.
    if _col_has_data(standard_complete):
        return standard_start, standard_complete

    # Fall back to the PG-style columns only if they have data AND the
    # standard columns don't. Keeps existing PG logic untouched.
    if _col_has_data(pg_complete):
        return pg_start, pg_complete

    # No data in either — return what we had so downstream code can still
    # treat absence gracefully (VCR will be 0).
    return standard_start, standard_complete


def _get_standard_video_metric_columns(normed_cols):
    """Find standard non-PG video started/completed columns."""
    start_aliases = (
        "videostarted",
        "videostarts",
    )
    complete_aliases = (
        "videocompleted",
        "videocompletes",
        "videocompletion",
        "videocompletions",
    )
    video_start_col = _pick_first_matching_column(normed_cols, start_aliases)
    video_complete_col = _pick_first_matching_column(normed_cols, complete_aliases)

    # Fallback for alternate standard exports such as "Video Starts" / "Video Completions"
    if not video_start_col:
        video_start_col = _pick_video_column_by_tokens(normed_cols, ("video", "started"))
    if not video_start_col:
        video_start_col = _pick_first_matching_column(normed_cols, ("videostarts",))
    if not video_complete_col:
        video_complete_col = _pick_video_column_by_tokens(normed_cols, ("video", "completed"))
    if not video_complete_col:
        video_complete_col = _pick_first_matching_column(normed_cols, ("videocompletes", "videocompletions", "videocompletion"))

    return video_start_col, video_complete_col


def _get_programmatic_guaranteed_video_metric_columns(normed_cols):
    """Find exact PG video metric columns: Video Start and Video Complete."""
    return normed_cols.get("videostart"), normed_cols.get("videocomplete")


def _get_video_metric_columns(normed_cols):
    """Backward-compatible wrapper for existing callers."""
    return _get_standard_video_metric_columns(normed_cols)


def _has_vcr_source_columns(df):
    """Return True when the dataset has valid VCR inputs for any applicable row set."""
    if df is None or df.empty:
        return False

    def norm_col(col):
        return col.strip().lower().replace("-", "").replace(" ", "")

    normed_cols = {norm_col(c): c for c in df.columns}
    standard_start_col, standard_complete_col = _get_standard_video_metric_columns(normed_cols)
    pg_start_col, pg_complete_col = _get_programmatic_guaranteed_video_metric_columns(normed_cols)
    # Rows with 'guaranteed' in ad name should follow PG metric logic too.
    pg_mask = _get_programmatic_guaranteed_mask(df) | _get_guaranteed_ad_name_mask(df)

    # Option A fallback: if the standard "Video completed" column is all zeros
    # but the "Video complete" alternate has real data (typical for non-PG OLV
    # / VCR campaigns), use the alternate so VCR isn't silently reported as 0.
    non_pg_mask = ~pg_mask if len(pg_mask) else None
    standard_start_col, standard_complete_col = _resolve_video_columns_with_fallback(
        df, normed_cols,
        standard_start_col, standard_complete_col,
        pg_start_col, pg_complete_col,
        row_mask=non_pg_mask,
    )

    has_pg_rows = bool(pg_mask.any())
    has_non_pg_rows = bool((~pg_mask).any()) if len(pg_mask) else True

    # Guaranteed rows can provide Total % Purchases NTB directly as a rate column.
    ntb_rate_col = normed_cols.get("newtobrandpurchaserate")
    if ntb_rate_col:
        rate_numeric = pd.to_numeric(
            df[ntb_rate_col].astype(str).str.replace("%", "", regex=False),
            errors="coerce",
        )
        # Normalize fractional values like 0.12 to percentage points (12.0).
        rate_numeric = rate_numeric.where((rate_numeric > 1) | rate_numeric.isna(), rate_numeric * 100)
        if "Total_Purchases" in df.columns:
            ntb_weight = pd.to_numeric(df["Total_Purchases"], errors="coerce").fillna(0.0)
        elif "Purchases" in df.columns:
            ntb_weight = pd.to_numeric(df["Purchases"], errors="coerce").fillna(0.0)
        else:
            ntb_weight = pd.Series(0.0, index=df.index)

        df["_guaranteed_total_ntb_weight"] = 0.0
        df["_guaranteed_total_ntb_est"] = 0.0
        if len(pg_mask):
            valid_rate_mask = pg_mask & rate_numeric.notna()
            df.loc[valid_rate_mask, "_guaranteed_total_ntb_weight"] = ntb_weight.loc[valid_rate_mask]
            df.loc[valid_rate_mask, "_guaranteed_total_ntb_est"] = (
                rate_numeric.loc[valid_rate_mask] / 100.0
            ) * df.loc[valid_rate_mask, "_guaranteed_total_ntb_weight"]

    # Keep track of which grouped rows include guaranteed rows.
    df["_has_guaranteed_row"] = pg_mask.astype(int)

    has_standard_sources = bool(standard_start_col and standard_complete_col)
    has_pg_sources = bool(pg_start_col and pg_complete_col)

    return (has_non_pg_rows and has_standard_sources) or (has_pg_rows and has_pg_sources)


def _get_programmatic_guaranteed_mask(df):
    """Return mask for rows whose campaign/order name indicates Programmatic Guaranteed."""
    if df is None or df.empty:
        return pd.Series(dtype=bool)

    def norm_col(col):
        return str(col).strip().lower().replace("_", " ").replace("-", " ")

    candidate_cols = []

    # Prefer canonical names first when available.
    for preferred in ["Campaign_Name", "campaign_name", "order name", "order_name", "Order_Name"]:
        if preferred in df.columns and preferred not in candidate_cols:
            candidate_cols.append(preferred)

    # Fallback to any descriptive text field that typically carries PG naming.
    for col in df.columns:
        ncol = norm_col(col)
        if any(token in ncol for token in ["campaign", "order", "line item", "lineitem", "ad group", "placement"]):
            if col not in candidate_cols:
                candidate_cols.append(col)

    if not candidate_cols:
        return pd.Series(False, index=df.index)

    # Match both explicit and shorthand PG naming conventions.
    pg_patterns = [
        r"programmatic\s*[-_/]?\s*guaranteed",
        r"\bprog(?:rammatic)?\s*[-_/]?\s*guaranteed\b",
        r"(^|[^a-z0-9])pg([^a-z0-9]|$)",
    ]

    mask = pd.Series(False, index=df.index)
    for col in candidate_cols:
        col_values = df[col].astype(str)
        col_mask = pd.Series(False, index=df.index)
        for pat in pg_patterns:
            col_mask = col_mask | col_values.str.contains(pat, case=False, na=False, regex=True)
        mask = mask | col_mask

    return mask


def _get_fire_tv_feature_rotator_mask(df):
    """Return mask for rows whose campaign/order indicates Fire TV Feature Rotator."""
    if df is None or df.empty:
        return pd.Series(dtype=bool)

    def norm_col(col):
        return str(col).strip().lower().replace("_", " ").replace("-", " ")

    candidate_cols = []
    for preferred in ["Campaign_Name", "campaign_name", "order name", "order_name", "Order_Name"]:
        if preferred in df.columns and preferred not in candidate_cols:
            candidate_cols.append(preferred)

    for col in df.columns:
        ncol = norm_col(col)
        if any(token in ncol for token in ["campaign", "order", "line item", "lineitem", "ad group", "placement"]):
            if col not in candidate_cols:
                candidate_cols.append(col)

    if not candidate_cols:
        return pd.Series(False, index=df.index)

    pattern = r"fire\s*tv\s*feature\s*rotator"
    mask = pd.Series(False, index=df.index)
    for col in candidate_cols:
        mask = mask | df[col].astype(str).str.contains(pattern, case=False, na=False, regex=True)

    return mask


def _get_guaranteed_ad_name_mask(df):
    """Return mask for rows whose ad name/creative contains the word 'guaranteed'."""
    if df is None or df.empty:
        return pd.Series(dtype=bool)

    if "Ad_Name_Source" in df.columns:
        source_col = "Ad_Name_Source"
    elif "Creative" in df.columns:
        source_col = "Creative"
    elif "ad name" in df.columns:
        source_col = "ad name"
    elif "ad_name" in df.columns:
        source_col = "ad_name"
    else:
        return pd.Series(False, index=df.index)

    # Use a plain substring check so ad-name formatting differences still match.
    return (
        df[source_col]
        .astype(str)
        .str.lower()
        .str.contains("guaranteed", na=False, regex=False)
    )


def get_group_key(text):
    """Extract the creative identifier from an ad-name string.

    Applies multiple strategies in priority order to handle naming differences
    across DSP, IMDb, Devices (FTV), STV, Twitch, Class 1, and Audio products.
    """
    txt = str(text or "").strip()

    if not txt:
        return txt[:30]

    # ==================================================================
    # STRATEGY 0 -- REC-ASIN-Creative pattern (Component-Based Creative)
    # ==================================================================
    # Handle patterns like "...DCP04845031_REC- B0G3R4WM4T- Bright idea_Lifestyle"
    # Extract everything after "REC-" and ASIN, including underscores in creative name
    rec_match = re.search(r'REC-\s*([A-Z0-9]+)\s*-\s*(.+?)$', txt, re.IGNORECASE)
    if rec_match:
        creative_part = rec_match.group(2).strip()
        # Clean up extra spaces and normalize, but preserve underscores as spaces
        creative_part = creative_part.replace('_', ' ')
        # Remove trailing non-alphanumeric except spaces
        creative_part = re.sub(r'[^0-9A-Za-z ]+$', '', creative_part).strip()
        if creative_part:
            return creative_part

    # If no underscores at all, use simple word-based fallback
    if '_' not in txt:
        stop_words = {"image", "static", "class", "sov", "ad", "v1", "v2",
                      "copy", "final", "png", "jpg"}
        words = [w for w in re.split(r"[_.\-]+", txt)
                 if w and w.lower() not in stop_words and len(w) > 1]
        if len(words) >= 2:
            return " ".join(words[-2:]).title()
        if words:
            return words[0].title()
        return txt[:30]

    parts = [p.strip() for p in txt.split('_')]
    non_empty = [p for p in parts if p.strip()]

    # ==================================================================
    # STRATEGY 1 -- Devices / FTV / FireTablet / Kindle pattern
    # ==================================================================
    # These use "OP Single" or "OP Multi" as a marker.  The creative name
    # is the token immediately after the OP marker.
    #   Example: ..._OP Single_Alice's Adventures In Wonderland__Watch Now_DP__320x180
    #   Example: ..._OP Multi_MarqueeTV Sizzle Reel_Watch now_Video__1920x1080_
    op_idx = None
    for i, p in enumerate(non_empty):
        if re.match(r'^OP\s+(Single|Multi)$', p.strip(), re.IGNORECASE):
            op_idx = i
            break

    if op_idx is not None and op_idx + 1 < len(non_empty):
        creative = non_empty[op_idx + 1]
        # Strip trailing non-alphanumeric chars but keep internal punctuation
        creative = re.sub(r"[^0-9A-Za-z /\-':.,&]+$", "", creative).strip()
        if creative:
            return creative

    # ==================================================================
    # STRATEGY 2 -- Component-Based Creative with DCP pattern
    # ==================================================================
    # For Component-Based Creatives, collect all tokens AFTER the DCP code
    # Example: "...DCP04855766_Bold beats_Lifestyle" -> "Bold beats Lifestyle"
    dcp_idx = None
    for i, p in enumerate(non_empty):
        if _looks_like_dcp(p):
            dcp_idx = i
            break
    
    if dcp_idx is not None and dcp_idx + 1 < len(non_empty):
        # Collect all tokens after the DCP code
        creative_tokens = []
        for j in range(dcp_idx + 1, len(non_empty)):
            token = non_empty[j]
            # Skip noise tokens but keep everything else
            if _is_noise_token(token):
                continue
            if _DATE_RANGE_PATTERN.match(token):
                continue
            if _looks_like_size_token(token):
                continue
            # Clean the token but keep it
            clean = re.sub(r"[^0-9A-Za-z \-':.,/&]+", "", token).strip()
            if clean:
                creative_tokens.append(clean)
        
        if creative_tokens:
            return " ".join(creative_tokens)
    
    # ==================================================================
    # STRATEGY 3 -- DSP / IMDb / Class 1 / STV / Audio / Generic pattern
    # ==================================================================
    # Walk backwards from the end, skipping noise tokens (dimensions, CTAs,
    # format codes, DCP codes, date ranges, placement labels).
    # The first meaningful token encountered is the creative identifier.
    #
    # DSP:     ..._DCP04585381_Q4 - DTM Holiday        -> "Q4 - DTM Holiday"
    # IMDb:    ..._DCP########_UniqueID                 -> "UniqueID"
    # Class 1: ..._2025-02-26 - 2025-03-31_March Madness -> "March Madness"
    # STV:     ..._Ad1 / Ad2 suffix                     -> handled naturally
    for i in range(len(non_empty) - 1, -1, -1):
        token = non_empty[i]

        # Skip noise
        if _is_noise_token(token):
            continue

        # Skip DCP codes
        if _looks_like_dcp(token):
            continue

        # Skip date-range tokens like "2025-01-01 - 2025-03-31"
        if _DATE_RANGE_PATTERN.match(token):
            continue

        # Skip creative-type tokens ("Video 15s", "Image (Static)", etc.)
        if _looks_like_creative_type(token):
            continue

        # Skip Class labels ("Class 1")
        if _looks_like_class_label(token):
            continue

        # Skip ad-size tokens that may not match the simple WxH pattern
        if _looks_like_size_token(token):
            continue

        # Clean the token
        clean = re.sub(r"[^0-9A-Za-z \-':.,/&]+", "", token).strip()
        clean = re.sub(r"[-_.\s]+$", "", clean).strip()
        if clean:
            return clean

    # ==================================================================
    # STRATEGY 4 -- Final fallback
    # ==================================================================
    stop_words = {"image", "static", "class", "sov", "ad", "v1", "v2",
                  "copy", "final", "png", "jpg"}
    words = [w for w in re.split(r"[_.\-]+", txt)
             if w and w.lower() not in stop_words and len(w) > 1]
    if len(words) >= 2:
        return " ".join(words[-2:]).title()
    if words:
        return words[0].title()

    return txt[:30]


def normalize_columns(df):
    df.columns = (df.columns
                  .str.replace(r"\s+", " ", regex=True)
                  .str.replace("\u00A0", " ")
                  .str.strip()
                  .str.lower())
    return df

def find_column(df, candidates):
    cols = {c.lower(): c for c in df.columns}
    
    # First pass: exact matches
    for cand in candidates:
        cl = cand.lower()
        if cl in cols:
            return cols[cl]
    
    # Second pass: partial matches (contains)
    for cand in candidates:
        cl = cand.lower()
        for c in cols:
            if cl in c.lower():
                return cols[c]
    
    return None


def find_date_column(df, candidates):
    """Find date columns while avoiding false matches like 'video start'."""
    cols = {c.lower(): c for c in df.columns}
    excluded_tokens = ("video", "creative", "campaign")

    for cand in candidates:
        cl = cand.lower()
        if cl in cols:
            return cols[cl]

    for cand in candidates:
        cl = cand.lower()
        for c in cols:
            if any(token in c for token in excluded_tokens):
                continue
            if cl in c:
                return cols[c]

    return None

@st.cache_data(show_spinner=False, max_entries=3)
def load_and_process(file_bytes, file_name, logic_version=PROCESSING_LOGIC_VERSION):
    import time as _time_module
    _t0 = _time_module.time()

    # ── Column keep-list for Excel memory optimization ───────────────────────
    # DSP exports ship with 600+ columns but the tool uses ~30. Reading all of
    # them wastes hundreds of MB on constrained deploy environments (e.g.,
    # Canopy containers) and has caused OOM crashes on large files.
    #
    # We filter to columns whose name contains ANY of these tokens (case-
    # insensitive substring match). This mirrors the tolerance of `find_column`
    # elsewhere — anything the tool might look for gets kept, plus a safety
    # margin of loosely-related columns. If the keep-list is ever incomplete
    # (e.g., a new KPI gets added and its source column isn't listed here),
    # ADD THE COLUMN NAME TOKENS BELOW so the filter keeps them.
    _KEEP_TOKENS = (
        # Identity
        "creative", "ad name", "ad_name", "adname", "ad id",
        # Campaign / order / placement (needed for PG/FTV detection + Order_ID)
        "campaign", "order", "line item", "lineitem", "ad group", "placement",
        # Basic performance metrics
        "impressions", "impression", "imps",
        "click-throughs", "clicks", "click throughs", "click",
        "dpv", "detail page views",
        "purchases", "purchase", "units",
        "total purchases", "total dpv",
        # Financial / ROAS
        "sales usd", "sales", "revenue",
        "total sales usd", "total sales",
        "total cost", "cost", "spend", "media cost",
        # Subscriptions / appstore
        "subscription sign-ups", "subscription signups", "subscription sign ups",
        "subscriptions", "app subscription",
        "appstore opens", "appstore open", "app store opens", "app store open",
        "appstoreopens", "cost per subscription",
        # New-to-brand family (NTB)
        "new-to-brand", "newtobrand", "total new-to-brand",
        # Video metrics (both standard and PG variants)
        "video start", "video started", "video starts",
        "video complete", "video completed", "video completes",
        "video completion", "video completions",
        # Dates (for filters + topline chart)
        "interval start", "interval end",
        "start date", "end date",
        "line item start date", "line item end date",
        "date", "report date", "day",
        "campaign start date", "campaign end date",
        # Ad size (for size performance chart)
        "size", "ad size",
        # Advertiser context (informational)
        "advertiser",
    )

    def _should_keep_column(col_name):
        n = str(col_name).strip().lower()
        return any(tok in n for tok in _KEEP_TOKENS)

    # Detect file type and read accordingly
    if file_name.lower().endswith('.csv'):
        # CSV files are already fast and memory-light; leave them unfiltered
        # to avoid any risk of missing a column in small reports.
        df = pd.read_csv(BytesIO(file_bytes), dtype=str, keep_default_na=False)
    else:
        # Speed + memory optimization: prefer the `calamine` engine (Rust-based,
        # 5-10x faster than openpyxl on large DSP reports) AND filter columns
        # via usecols so we only load what the tool needs. Falls back gracefully
        # to openpyxl (also with column filter) if calamine isn't available, and
        # to an unfiltered read as a final safety net.
        _read_kwargs = dict(dtype=str, keep_default_na=False)
        df = None
        try:
            df = pd.read_excel(
                BytesIO(file_bytes),
                engine='calamine',
                usecols=_should_keep_column,
                **_read_kwargs,
            )
        except Exception as _calamine_err:
            print(f"[load_and_process] calamine unavailable ({type(_calamine_err).__name__}: {_calamine_err}); falling back to openpyxl")
            try:
                df = pd.read_excel(
                    BytesIO(file_bytes),
                    engine='openpyxl',
                    engine_kwargs={'read_only': True, 'data_only': True},
                    usecols=_should_keep_column,
                    **_read_kwargs,
                )
            except Exception as _openpyxl_err:
                print(f"[load_and_process] openpyxl read_only + usecols failed ({type(_openpyxl_err).__name__}: {_openpyxl_err}); falling back to unfiltered read")
                df = pd.read_excel(BytesIO(file_bytes), **_read_kwargs)

        # If usecols returned unexpectedly few columns (e.g., an unusual report
        # naming scheme our tokens don't cover), retry without the filter so
        # the tool still works. Threshold of 5 is arbitrary but catches the
        # pathological case where filtering accidentally keeps almost nothing.
        if df is not None and df.shape[1] < 5:
            print(f"[load_and_process] column filter kept only {df.shape[1]} cols; retrying without filter")
            df = pd.read_excel(BytesIO(file_bytes), **_read_kwargs)

    _t1 = _time_module.time()
    df = normalize_columns(df)
    _t2 = _time_module.time()
    _t1 = _time_module.time()
    df = normalize_columns(df)
    _t2 = _time_module.time()
    result = process_campaign_data(df)
    _t3 = _time_module.time()

    # Print to server console so we can diagnose slowness without affecting UI.
    print(f"[load_and_process] read={_t1-_t0:.2f}s normalize={_t2-_t1:.2f}s process={_t3-_t2:.2f}s total={_t3-_t0:.2f}s rows={len(df)} cols={len(df.columns)}")

    return result
def process_campaign_data(df):
    try:
        creative_col = find_column(df, ["creative", "creative name", "ad name", "ad", "creative_name", "ad_name", "adname"])
        ad_name_source_col = find_column(df, ["ad name", "ad_name", "adname"])
        imp_col      = find_column(df, ["impressions", "impression", "imps", "imp"])
        click_col    = find_column(df, ["click-throughs", "clicks", "click throughs", "click"])
        dpv_col      = find_column(df, ["dpv", "detail page views", "dpvs", "dpv views"])
        purch_col    = find_column(df, ["purchases", "purchase", "sales", "units"])
        total_purch_col = find_column(df, ["total purchases", "total_purchases", "total_purchases_usd", "total_purchases_count"])
        total_dpv_col = find_column(df, ["total dpv", "total_dpv", "total dpvs", "total_dpv_count", "total_dpvs"]) 
        
        # Detect both campaign name and campaign ID separately
        campaign_name_col = find_column(df, ["campaign name", "campaign", "campaign_name", "order name", "order_name"])
        campaign_id_col = find_column(df, ["campaign id", "campaign_id", "campaignid", "order id", "order_id", "orderid"])
        
        # If campaign_id_col matches campaign_name_col, search for a distinct ID column
        if campaign_id_col == campaign_name_col:
            campaign_id_col = find_column(df, ["campaign id", "campaign_id", "campaignid"])

        # Detect Sales USD, Total Sales USD and Total Cost columns for ROAS calculation
        sales_col = find_column(df, ["sales usd", "sales", "revenue", "revenue usd"])
        total_sales_col = find_column(df, ["total sales usd", "total sales", "total_sales", "total_sales_usd"])
        cost_col = find_column(df, ["total cost", "cost", "spend", "media cost"])
        subscription_col = find_column(df, ["subscription sign-ups", "subscription signups", "subscription sign ups", "subscriptions"])
        app_subscription_col = find_column(df, ["app subscription sign-ups", "app subscription signups", "app subscription sign ups", "app subscriptions"])
        appstore_opens_col = find_column(df, ["appstore opens", "appstore open", "app store opens", "app store open", "appstoreopens"])

        # Detect start/end date columns (common names). Keep as Start_Date / End_Date
        start_col = find_date_column(df, ["interval start", "interval_start", "line item start date", "start date", "start_date", "line_item_start_date", "start"])
        end_col = find_date_column(df, ["interval end", "interval_end", "line item end date", "end date", "end_date", "line_item_end_date", "end"])

        rename_map = {}
        if creative_col: rename_map[creative_col] = "Creative"
        if ad_name_source_col and ad_name_source_col != creative_col:
            rename_map[ad_name_source_col] = "Ad_Name_Source"
        # NOTE: removed preserving of Input_Creative_ID per user request
        if imp_col:      rename_map[imp_col]      = "Impressions"
        if click_col:    rename_map[click_col]    = "Click-throughs"
        if dpv_col:      rename_map[dpv_col]      = "DPV"
        if purch_col:    rename_map[purch_col]    = "Purchases"
        if total_purch_col: rename_map[total_purch_col] = "Total_Purchases"
        if total_dpv_col: rename_map[total_dpv_col] = "Total_DPV"
        # Handle campaign name and ID separately
        if campaign_name_col: rename_map[campaign_name_col] = "Campaign_Name"
        if campaign_id_col and campaign_id_col != campaign_name_col: 
            rename_map[campaign_id_col] = "Campaign_ID"
        if sales_col:    rename_map[sales_col]    = "Sales_USD"
        if total_sales_col: rename_map[total_sales_col] = "Total_Sales_USD"
        if cost_col:     rename_map[cost_col]     = "Total_Cost"
        if subscription_col: rename_map[subscription_col] = "Subscription sign-ups"
        if app_subscription_col: rename_map[app_subscription_col] = "App subscription sign-ups"
        if appstore_opens_col: rename_map[appstore_opens_col] = "Appstore Opens"
        if start_col:    rename_map[start_col]    = "Start_Date"
        if end_col:      rename_map[end_col]      = "End_Date"

        df = df.rename(columns=rename_map)

        required = ["Creative", "Impressions", "Click-throughs"]
        missing = [c for c in required if c not in df.columns]
        if missing:
            st.error(f"Missing required columns: {', '.join(missing)}")
            return None, df

        df["Creative"] = df["Creative"].astype(str).str.strip()
        # Normalize and preserve any input-provided creative id column
        # No Input_Creative_ID column is preserved
        df["Group_Key"] = df["Creative"].apply(lambda x: get_group_key(x))

        # Programmatic Guaranteed and Fire TV Feature Rotator lines should use
        # full ad name as identifier instead of extracted creative identifier.
        pg_mask = _get_programmatic_guaranteed_mask(df) | _get_guaranteed_ad_name_mask(df)
        ftv_fr_mask = _get_fire_tv_feature_rotator_mask(df)
        full_ad_name_mask = pg_mask | ftv_fr_mask

        if full_ad_name_mask.any():
            full_ad_name_col = "Ad_Name_Source" if "Ad_Name_Source" in df.columns else "Creative"
            df.loc[full_ad_name_mask, "Group_Key"] = (
                df.loc[full_ad_name_mask, full_ad_name_col]
                .astype(str)
                .str.strip()
            )

        # Attach a small "Product_Tag" marker to each row so the chart/table can
        # prepend a clarifying prefix (e.g., "PG · ad_name") when the chart
        # contains a mix of tagged and untagged creatives. FTV Feature Rotator
        # takes priority over PG when both match — it's more specific.
        df["Product_Tag"] = ""
        if pg_mask.any():
            df.loc[pg_mask, "Product_Tag"] = "PG"
        if ftv_fr_mask.any():
            df.loc[ftv_fr_mask, "Product_Tag"] = "FTV Feature Rotator"

        # Parse dates if present
        for col in ["Start_Date", "End_Date"]:
            if col in df.columns:
                # coerce invalid dates to NaT
                df[col] = pd.to_datetime(df[col], errors="coerce")

        for col in ["Impressions", "Click-throughs", "DPV", "Purchases"]:
            if col not in df.columns:
                df[col] = 0
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)

        # Process Sales, Total Sales, DPV, Purchases, Cost and Subscription columns (keep as float for numeric calcs)
        for col in ["Sales_USD", "Total_Sales_USD", "Total_Cost", "DPV", "Total_DPV", "Purchases", "Total_Purchases", "Subscription sign-ups", "App subscription sign-ups", "Appstore Opens"]:
            if col not in df.columns:
                # For counts like DPV/Purchases keep as ints where appropriate later; initialize to 0.0 for safe math
                df[col] = 0.0
            else:
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

        # Create composite Order_ID from Campaign_Name and Campaign_ID
        if "Campaign_Name" in df.columns and "Campaign_ID" in df.columns:
            # Clean up both columns
            df["Campaign_Name"] = df["Campaign_Name"].astype(str).str.strip()
            df["Campaign_Name"] = df["Campaign_Name"].replace({"nan": "", "<NA>": ""}).str.strip()
            df["Campaign_ID"] = df["Campaign_ID"].astype(str).str.strip()
            df["Campaign_ID"] = df["Campaign_ID"].replace({"nan": "", "<NA>": ""}).str.strip()
            
            # Create composite Order_ID: "Campaign Name (ID: Campaign_ID)"
            # Use Campaign_ID as the unique key to differentiate orders with same name
            df["Order_ID"] = df.apply(
                lambda row: f"{row['Campaign_Name']} (ID: {row['Campaign_ID']})" 
                if row['Campaign_Name'] and row['Campaign_ID']
                else (row['Campaign_Name'] if row['Campaign_Name'] else (row['Campaign_ID'] if row['Campaign_ID'] else None)),
                axis=1
            )
        elif "Campaign_Name" in df.columns:
            # Only campaign name available
            df["Campaign_Name"] = df["Campaign_Name"].astype(str).str.strip()
            df["Campaign_Name"] = df["Campaign_Name"].replace({"nan": "", "<NA>": ""}).str.strip()
            df["Order_ID"] = df["Campaign_Name"].replace({"": None})
        elif "Campaign_ID" in df.columns:
            # Only campaign ID available
            df["Campaign_ID"] = df["Campaign_ID"].astype(str).str.strip()
            df["Campaign_ID"] = df["Campaign_ID"].replace({"nan": "", "<NA>": ""}).str.strip()
            df["Order_ID"] = df["Campaign_ID"].replace({"": None})

        return df, df

    except Exception as e:
        st.error(f"Error processing file: {e}")
        return None, None

def aggregate_by_creative(df, order_filters=None, separate_by_campaign=False):
    """Aggregate the uploaded dataframe by (start_date, end_date, creative_id) or by quarter.

    Args:
        df: processed dataframe (as returned by process_campaign_data)
        order_filter: optional Order_ID filter value
        group_by_quarter: if True, group by Start_Quarter/End_Quarter instead of full dates

    Returns:
        aggregated DataFrame or None
    """
    if df is None or df.empty:
        return None

    df = df.copy()

    # Apply order filter if requested. order_filters is a list; 'All Orders' or empty list means no filtering.
    if order_filters and "All Orders" not in order_filters and "Order_ID" in df.columns:
        df = df[df["Order_ID"].isin(order_filters)]
    if df.empty:
        return None

    # Extract a simple creative id from the Creative text
    def extract_creative_id(text):
        if text is None:
            return None
        txt = str(text).strip()
        if not txt:
            return None
        # split on underscores, hyphens or spaces and take last meaningful token(s)
        tokens = [t.strip() for t in re.split(r"[_\s-]+", txt) if t.strip()]
        if not tokens:
            return None
        # prefer last token cleaned of trailing punctuation
        last = re.sub(r"[^0-9A-Za-z ]+", "", tokens[-1]).strip()
        last = re.sub(r"[-_.\s]+$", "", last).strip()
        if last:
            return last
        if len(tokens) >= 2:
            cand = " ".join(tokens[-2:])
            cand = re.sub(r"[^0-9A-Za-z ]+", "", cand).strip()
            return cand or None
        return None

    # Prefer the pre-computed Group_Key (which implements the documented underscore split logic)
    if "Group_Key" in df.columns:
        def _from_group_key(x):
            try:
                v = str(x).strip()
                return v if v and v.lower() not in {"nan", "none"} else None
            except Exception:
                return None
        df["Creative_ID"] = df["Group_Key"].apply(_from_group_key)
        # fallback to extracting from full creative text when Group_Key is missing or blank
        df.loc[df["Creative_ID"].isna(), "Creative_ID"] = df.loc[df["Creative_ID"].isna(), "Creative"].apply(extract_creative_id)
    else:
        df["Creative_ID"] = df["Creative"].apply(extract_creative_id)

    # Prepare aggregation keys
    df["_agg_cid"] = df["Creative_ID"].fillna("").astype(str)
    if separate_by_campaign and "Campaign_ID" in df.columns:
        df["_agg_campaign_id"] = (
            df["Campaign_ID"]
            .fillna("")
            .astype(str)
            .replace({"nan": "", "<NA>": ""})
            .str.strip()
        )
    else:
        df["_agg_campaign_id"] = ""

    # Dates: create year key for grouping (End_Date required for grouping)
    if "End_Date" in df.columns:
        # End year (string) for grouping
        df["End_Year"] = df["End_Date"].dt.year
        df["_agg_end_year"] = df["End_Year"].apply(lambda x: str(int(x)) if pd.notna(x) else "")
    else:
        df["End_Year"] = None
        df["_agg_end_year"] = ""

    # Ensure subscription and appstore columns exist for aggregation (fill with 0 if missing)
    if "Subscription sign-ups" not in df.columns:
        df["Subscription sign-ups"] = 0
    if "App subscription sign-ups" not in df.columns:
        df["App subscription sign-ups"] = 0
    if "Appstore Opens" not in df.columns:
        df["Appstore Opens"] = 0
    
    def norm_col(col):
        return col.strip().lower().replace("-", "").replace(" ", "")
    normed_cols = {norm_col(c): c for c in df.columns}

    # Keep explicit Programmatic Guaranteed video columns separate so PG rows use
    # only Video Start / Video Complete, never Video Started / Video Completed.
    pg_video_start_col, pg_video_complete_col = _get_programmatic_guaranteed_video_metric_columns(normed_cols)

    # Default (non-PG) video metric columns.
    video_started_col, video_completed_col = _get_standard_video_metric_columns(normed_cols)

    # PG metric routing applies to explicit PG rows and any ad name containing 'guaranteed'.
    pg_mask = _get_programmatic_guaranteed_mask(df) | _get_guaranteed_ad_name_mask(df)
    has_pg_rows = bool(pg_mask.any())
    has_non_pg_rows = bool((~pg_mask).any()) if len(pg_mask) else True

    # Option A fallback: same logic as _has_vcr_source_columns. If the standard
    # "Video completed" column is all zeros for non-PG rows but "Video complete"
    # has real data, switch non-PG rows to read from the alternate columns.
    non_pg_mask = ~pg_mask if len(pg_mask) else None
    video_started_col, video_completed_col = _resolve_video_columns_with_fallback(
        df, normed_cols,
        video_started_col, video_completed_col,
        pg_video_start_col, pg_video_complete_col,
        row_mask=non_pg_mask,
    )

    # Guaranteed rows can provide Total % Purchases NTB directly as a rate column.
    ntb_rate_col = normed_cols.get("newtobrandpurchaserate")
    if ntb_rate_col:
        rate_numeric = pd.to_numeric(
            df[ntb_rate_col].astype(str).str.replace("%", "", regex=False),
            errors="coerce",
        )
        # Normalize fractional values like 0.12 to percentage points (12.0).
        rate_numeric = rate_numeric.where((rate_numeric > 1) | rate_numeric.isna(), rate_numeric * 100)

        if "Total_Purchases" in df.columns:
            ntb_weight = pd.to_numeric(df["Total_Purchases"], errors="coerce").fillna(0.0)
        elif "Purchases" in df.columns:
            ntb_weight = pd.to_numeric(df["Purchases"], errors="coerce").fillna(0.0)
        else:
            ntb_weight = pd.Series(0.0, index=df.index)

        df["_guaranteed_total_ntb_weight"] = 0.0
        df["_guaranteed_total_ntb_est"] = 0.0
        if len(pg_mask):
            df.loc[pg_mask, "_guaranteed_total_ntb_weight"] = ntb_weight.loc[pg_mask]
            df.loc[pg_mask, "_guaranteed_total_ntb_est"] = (
                rate_numeric.loc[pg_mask].fillna(0.0) / 100.0
            ) * df.loc[pg_mask, "_guaranteed_total_ntb_weight"]

    # Keep track of which grouped rows include guaranteed rows.
    df["_has_guaranteed_row"] = pg_mask.astype(int)

    has_any_vcr_sources = bool(
        (has_non_pg_rows and video_started_col and video_completed_col) or
        (has_pg_rows and pg_video_start_col and pg_video_complete_col)
    )

    if has_any_vcr_sources:
        df["_vcr_video_start"] = 0.0
        df["_vcr_video_complete"] = 0.0

        non_pg_mask = ~pg_mask if len(pg_mask) else pd.Series(True, index=df.index)
        if has_non_pg_rows and video_started_col and video_completed_col:
            df.loc[non_pg_mask, "_vcr_video_start"] = pd.to_numeric(
                df.loc[non_pg_mask, video_started_col], errors="coerce"
            ).fillna(0.0)
            df.loc[non_pg_mask, "_vcr_video_complete"] = pd.to_numeric(
                df.loc[non_pg_mask, video_completed_col], errors="coerce"
            ).fillna(0.0)

        if has_pg_rows and pg_video_start_col and pg_video_complete_col:
            df.loc[pg_mask, "_vcr_video_start"] = pd.to_numeric(
                df.loc[pg_mask, pg_video_start_col], errors="coerce"
            ).fillna(0.0)
            df.loc[pg_mask, "_vcr_video_complete"] = pd.to_numeric(
                df.loc[pg_mask, pg_video_complete_col], errors="coerce"
            ).fillna(0.0)
    agg_dict = {
        "Impressions": "sum",
        "Click-throughs": "sum",
        "DPV": "sum",
        "Total_DPV": "sum",
        "Purchases": "sum",
        "Total_Purchases": "sum",
        "Sales_USD": "sum",
        "Total_Sales_USD": "sum",
        "Total_Cost": "sum",
        "Subscription sign-ups": "sum",
        "App subscription sign-ups": "sum",
        "Appstore Opens": "sum",
        "_has_guaranteed_row": "max",
        "Creative": "first",
    }
    # Carry Product_Tag through aggregation. Rows with the same Group_Key share
    # the same tag (because Group_Key is derived from PG/FTV status), so "first"
    # is a safe aggregator.
    if "Product_Tag" in df.columns:
        agg_dict["Product_Tag"] = "first"
    if ntb_rate_col and "_guaranteed_total_ntb_weight" in df.columns and "_guaranteed_total_ntb_est" in df.columns:
        agg_dict["_guaranteed_total_ntb_weight"] = "sum"
        agg_dict["_guaranteed_total_ntb_est"] = "sum"
    # Aggregate resolved VCR source columns (PG-aware).
    if has_any_vcr_sources and "_vcr_video_start" in df.columns and "_vcr_video_complete" in df.columns:
        agg_dict["_vcr_video_start"] = "sum"
        agg_dict["_vcr_video_complete"] = "sum"
    else:
        if video_started_col:
            agg_dict[video_started_col] = "sum"
        if video_completed_col:
            agg_dict[video_completed_col] = "sum"
    # Find NTB columns by normalized name
    ntb_col = normed_cols.get("newtobrandpurchases")
    total_ntb_col = normed_cols.get("totalnewtobrandpurchases")
    if ntb_col:
        agg_dict[ntb_col] = "sum"
    if total_ntb_col:
        agg_dict[total_ntb_col] = "sum"
    # Note: Input_Creative_ID is not preserved/aggregated (user requested removal)

    # Choose grouping keys depending on quarter option
    # group by creative id + end year (legacy), or include campaign id (breakout view)
    group_keys = ["_agg_cid", "_agg_end_year"]
    if separate_by_campaign:
        group_keys.insert(1, "_agg_campaign_id")

    grp = df.groupby(group_keys, as_index=False).agg(agg_dict)

    # Restore readable columns
    grp["Creative_ID"] = grp["_agg_cid"].replace({"": None})
    grp = grp.drop(columns=["_agg_cid"], errors="ignore")

    if "_agg_campaign_id" in grp.columns:
        grp["Campaign_ID"] = grp["_agg_campaign_id"].replace({"": None})
        grp = grp.drop(columns=["_agg_campaign_id"], errors="ignore")
    else:
        grp["Campaign_ID"] = None

    grp["End_Year"] = grp["_agg_end_year"].replace({"": None})
    grp = grp.drop(columns=["_agg_end_year"], errors="ignore")

    # Show campaign/order ID in labels only when the same creative identifier
    # appears under multiple campaign IDs (within the same end year).
    if separate_by_campaign and "Creative_ID" in grp.columns and "Campaign_ID" in grp.columns and len(grp):
        dedupe_base = grp[["Creative_ID", "End_Year", "Campaign_ID"]].copy()
        dedupe_base["_dedupe_campaign"] = dedupe_base["Campaign_ID"].fillna("").astype(str).str.strip()
        dedupe_base["_has_campaign"] = dedupe_base["_dedupe_campaign"] != ""
        multi_campaign_mask = (
            dedupe_base[dedupe_base["_has_campaign"]]
            .groupby(["Creative_ID", "End_Year"])["_dedupe_campaign"]
            .transform("nunique")
            .fillna(0)
            .gt(1)
        )
        grp["_show_campaign_id"] = False
        grp.loc[dedupe_base["_has_campaign"].values, "_show_campaign_id"] = multi_campaign_mask.values
    else:
        grp["_show_campaign_id"] = False

    # Compute rates (avoid division by zero)
    denom = grp["Impressions"].replace(0, 1)
    grp["CTR"] = (grp["Click-throughs"] / denom * 100).round(4)
    grp["DPVR"] = (grp["DPV"] / denom * 100).round(4)
    grp["Purchase_Rate"] = (grp["Purchases"] / denom * 100).round(4)
    # Calculate VCR (Video Completion Rate)
    if "_vcr_video_start" in grp.columns and "_vcr_video_complete" in grp.columns:
        started = pd.to_numeric(grp["_vcr_video_start"], errors="coerce").replace(0, 1)
        completed = pd.to_numeric(grp["_vcr_video_complete"], errors="coerce")
        grp["VCR"] = (completed / started * 100).round(4)
    elif video_started_col and video_completed_col and video_started_col in grp.columns and video_completed_col in grp.columns:
        started = pd.to_numeric(grp[video_started_col], errors="coerce").replace(0, 1)
        completed = pd.to_numeric(grp[video_completed_col], errors="coerce")
        grp["VCR"] = (completed / started * 100).round(4)
    else:
        grp["VCR"] = 0.0
    
    # Calculate Promoted ROAS (from promoted Sales_USD) and Total ROAS (from Total_Sales_USD)
    if "Total_Cost" in grp.columns:
        cost_denom = grp["Total_Cost"].replace(0, 0.01)  # Use small value to avoid division by zero
        if "Sales_USD" in grp.columns:
            grp["Promoted_ROAS"] = (grp["Sales_USD"] / cost_denom).round(4)
        else:
            grp["Promoted_ROAS"] = 0.0

        if "Total_Sales_USD" in grp.columns:
            grp["Total_ROAS"] = (grp["Total_Sales_USD"] / cost_denom).round(4)
        else:
            grp["Total_ROAS"] = 0.0
    else:
        grp["Promoted_ROAS"] = 0.0
        grp["Total_ROAS"] = 0.0


    # Calculate Promoted vs Total DPVR and Purchase Rate
    denom = grp["Impressions"].replace(0, 1)
    grp["Promoted_DPVR"] = (grp["DPV"] / denom * 100).round(4) if "DPV" in grp.columns else 0.0
    grp["Promoted_Purchase_Rate"] = (grp["Purchases"] / denom * 100).round(4) if "Purchases" in grp.columns else 0.0

    # Total versions use Total_DPV / Total_Purchases if present
    if "Total_DPV" in grp.columns:
        grp["Total_DPVR"] = (grp["Total_DPV"] / denom * 100).round(4)
    else:
        grp["Total_DPVR"] = 0.0

    if "Total_Purchases" in grp.columns:
        grp["Total_Purchase_Rate"] = (grp["Total_Purchases"] / denom * 100).round(4)
    else:
        grp["Total_Purchase_Rate"] = 0.0

    # Appstore Open Rate (Appstore Opens / Impressions * 100)
    if "Appstore Opens" in grp.columns:
        grp["Appstore_Open_Rate"] = (pd.to_numeric(grp["Appstore Opens"], errors="coerce").fillna(0) / denom * 100).round(4)
    else:
        grp["Appstore_Open_Rate"] = 0.0

    # Promoted % NTB (NTB_Purchases / Purchases * 100)
    ntb_col = normed_cols.get("newtobrandpurchases")
    if ntb_col and ntb_col in grp.columns and "Purchases" in grp.columns:
        purchases_denom = grp["Purchases"].replace(0, 1)
        ntb_numeric = pd.to_numeric(grp[ntb_col], errors="coerce")
        grp["Promoted_%_NTB"] = (ntb_numeric / purchases_denom * 100).round(4)
    else:
        grp["Promoted_%_NTB"] = 0.0

    # Total % NTB (Total_NTB_Purchases / Total_Purchases * 100)
    total_ntb_col = normed_cols.get("totalnewtobrandpurchases")
    if total_ntb_col and total_ntb_col in grp.columns and "Total_Purchases" in grp.columns:
        total_purchases_denom = grp["Total_Purchases"].replace(0, 1)
        total_ntb_numeric = pd.to_numeric(grp[total_ntb_col], errors="coerce")
        grp["Total_%_NTB"] = (total_ntb_numeric / total_purchases_denom * 100).round(4)
    else:
        grp["Total_%_NTB"] = 0.0

    # For guaranteed campaigns, use New-to-brand purchase rate as the source for Total_%_NTB.
    guaranteed_group_mask = grp["_has_guaranteed_row"] > 0 if "_has_guaranteed_row" in grp.columns else pd.Series(False, index=grp.index)
    if (
        ntb_rate_col
        and "_guaranteed_total_ntb_weight" in grp.columns
        and "_guaranteed_total_ntb_est" in grp.columns
        and guaranteed_group_mask.any()
    ):
        guaranteed_denom = pd.to_numeric(grp["_guaranteed_total_ntb_weight"], errors="coerce").replace(0, 1)
        guaranteed_total_ntb_rate = (
            pd.to_numeric(grp["_guaranteed_total_ntb_est"], errors="coerce") / guaranteed_denom * 100
        ).round(4)
        has_guaranteed_rate_source = pd.to_numeric(grp["_guaranteed_total_ntb_weight"], errors="coerce") > 0
        override_mask = guaranteed_group_mask & has_guaranteed_rate_source
        grp.loc[override_mask, "Total_%_NTB"] = guaranteed_total_ntb_rate.loc[override_mask]

    grp = grp.rename(columns={"Creative": "Full_Creative_Name"})

    def make_group_key(row):
        cid = row.get("Creative_ID")
        campaign_id = row.get("Campaign_ID")
        campaign_id_text = str(campaign_id).strip() if campaign_id not in [None, "", "nan", "<NA>"] else ""
        show_campaign_id = bool(row.get("_show_campaign_id", False)) and bool(campaign_id_text)
        s = row.get("End_Year") or ""
        if cid:
            cid_text = str(cid)
            if "guaranteed" in cid_text.lower() or "feature rotator" in cid_text.lower():
                if separate_by_campaign and show_campaign_id:
                    return f"{cid_text} | {campaign_id_text}".strip(" | ")
                return cid_text
            if separate_by_campaign and show_campaign_id:
                return f"{cid} | {campaign_id_text} | {s}".strip(" | ")
            return f"{cid} | {s}".strip(" | ")
        return f"{campaign_id_text} | {s}".strip(" | ")

    grp["Group_Key"] = grp.apply(make_group_key, axis=1)

    # Reorder columns to keep compatibility
    base_cols = ["Group_Key", "Creative_ID", "Campaign_ID", "Full_Creative_Name", "Impressions", "Click-throughs", "CTR", "DPV", "DPVR", "Purchases", "Purchase_Rate", "VCR", "Sales_USD", "Total_Cost", "Subscription sign-ups"]
    # include End_Year column near the front
    front = ["End_Year"]

    # Ensure financial, ROAS, and total-rate columns are present in order if they exist
    for extra in ["Total_Sales_USD", "Promoted_ROAS", "Total_ROAS", "Total_DPV", "Total_DPVR", "Total_Purchases", "Total_Purchase_Rate", "App subscription sign-ups", "Appstore Opens", "Appstore_Open_Rate", "_vcr_video_start", "_vcr_video_complete", "_has_guaranteed_row"]:
        if extra in grp.columns and extra not in base_cols:
            base_cols.append(extra)

    col_order = front + base_cols
    col_order = [c for c in col_order if c in grp.columns]
    return grp[col_order]

# ==============================
# 1. UPLOAD FILES
# ==============================
with st.container(border=True):
    st.markdown("### 📁 UPLOAD SECTION")
    st.markdown("Upload your campaign data and creative images to get started.")

    col1, col2 = st.columns([1, 3])
    with col1:
        uploaded_file = st.file_uploader("Upload an Excel or CSV file", type=["xlsx", "xls", "csv"])
    with col2:
        _imgs_key = f"imgs_{st.session_state.get('imgs_key_counter', 0)}"
        uploaded_images = st.file_uploader(
            "Upload images/videos",
            type=["png", "jpg", "jpeg", "mp4", "mov", "avi", "webm"],
            accept_multiple_files=True,
            key=_imgs_key
        )
        st.caption("*Please compress video files if over 10 MB or they will fail to upload.")
        if uploaded_images:
            if st.button("🗑️ Clear creatives", key="clear_imgs_btn"):
                st.session_state["imgs_key_counter"] = st.session_state.get("imgs_key_counter", 0) + 1
                st.session_state["manual_uploaded_assets"] = {}
                st.rerun()
            # Warn if any uploaded video is large enough to risk a 413 on the deployed platform
            _large_videos = [f.name for f in uploaded_images if f.name.lower().split('.')[-1] in ('mp4','mov','avi','webm') and f.size > 8 * 1024 * 1024]
            if _large_videos:
                st.warning(
                    f"⚠️ **Video file(s) too large for the app:** "
                    "The server rejects uploads over ~10 MB. Please compress your video(s) to under 10 MB before uploading ",
                    icon=None,
                )
st.markdown("---")

# ==============================
# Image/Video Mapping (Fixed)
# ==============================
image_dict = {}  # Will store tuples: (asset, asset_type) where asset_type is 'image' or 'video'
uploaded_asset_lookup = {}  # Original uploaded filename -> asset tuple for manual assignment
unmatched_images = []
matched_summary = []

# Helper: normalize filenames / keys for robust matching
def _norm_key(s):
    if not s:
        return ""
    # Lowercase and keep only alphanumeric characters.
    # Do NOT strip a trailing ".xxx" as a fake "extension" — that destroys version
    # numbers like "4.04" and "4.06" which are the only differences between ad lines.
    # Image filenames always have their real extension stripped by callers before
    # passing to this function.
    s = s.strip().lower()
    s = re.sub(r"[^a-z0-9]", "", s)
    return s

def _key_variants(s):
    """Generate robust lookup keys (year-insensitive and separator-insensitive)."""
    if not s:
        return []
    raw = str(s).strip()
    if not raw:
        return []

    variants = {raw}

    # Common case: identifiers like "Name | 2026" should also match "Name".
    left_of_pipe = raw.split("|")[0].strip()
    if left_of_pipe:
        variants.add(left_of_pipe)

    # Remove trailing year tokens (e.g., "name 2026", "name-2026").
    no_year = re.sub(r"[\s\-_|]*(19|20)\d{2}\s*$", "", raw).strip(" -_|")
    if no_year:
        variants.add(no_year)

    normalized = {_norm_key(v) for v in variants if v}
    return [v for v in normalized if v]

def get_display_name(original_name):
    """Get the display name (edited name if available, otherwise original)"""
    if 'edited_creative_names' in st.session_state:
        return st.session_state.edited_creative_names.get(original_name, original_name)
    return original_name

# Match images to rows.
# - Guaranteed campaigns: match ONLY by full ad name (Group_Key / Full_Creative_Name).
#   The full ad name contains unique identifiers like "4.04" or "4.06" that differentiate
#   lines, so we normalize and score purely on full-name overlap — no creative ID used.
# - Non-guaranteed campaigns: match by creative ID first, then fall back to full name.
def _find_image_for_row(row, img_dict):
    # Determine if this is a guaranteed campaign row.
    guaranteed_text = f"{row.get('Group_Key') or ''} {row.get('Full_Creative_Name') or ''}"
    has_guaranteed_flag = bool(row.get("_has_guaranteed_row", 0))
    is_guaranteed_row = has_guaranteed_flag or ("guaranteed" in str(guaranteed_text).lower())

    full_ad_name = str(row.get("Group_Key") or row.get("Full_Creative_Name") or "")
    cid = str(row.get("Creative_ID") or "")

    # Collect both individually so the guaranteed path can try both as candidates.
    _group_key = str(row.get("Group_Key") or "")
    _full_creative_name = str(row.get("Full_Creative_Name") or "")

    # Also check for an edited display name.
    original_group_key = row.get("Group_Key", "")
    edited_ad_name = ""
    if original_group_key and 'edited_creative_names' in st.session_state:
        edited_ad_name = st.session_state.edited_creative_names.get(original_group_key, "")
        if edited_ad_name == original_group_key:
            edited_ad_name = ""

    if is_guaranteed_row:
        # ── Guaranteed path ──────────────────────────────────────────────────
        # Build ordered candidate list. For PG campaigns the creative ID is often
        # a numeric ID so Group_Key won't match the filename; Full_Creative_Name
        # carries the actual ad name and must be tried too.
        source_names = []
        if edited_ad_name:
            source_names.append(edited_ad_name)
        for v in [_full_creative_name, _group_key]:
            if v and v not in source_names:
                source_names.append(v)
        if not source_names:
            source_names = [full_ad_name]

        candidates = []
        for name in source_names:
            n = _norm_key(name)
            if n:
                candidates.append(n)
            candidates.extend(_key_variants(name))
            # For guaranteed ad names like "Campaign - 4.06__Video 15s_OP Single...",
            # the part before the first "__" is the campaign-name-only segment.
            # Image filenames often contain this segment as a suffix
            # (e.g. "WBD prefix - Campaign - 4.06"), so add it as an extra candidate
            # so the scoring's substring check can find the overlap.
            if "__" in name:
                pre_spec = name.split("__")[0].strip()
                if pre_spec:
                    n_pre = _norm_key(pre_spec)
                    if n_pre and n_pre not in candidates:
                        candidates.append(n_pre)
                    for v in _key_variants(pre_spec):
                        if v and v not in candidates:
                            candidates.append(v)
        candidates = list(dict.fromkeys([c for c in candidates if c]))

        # 1. Exact normalized match.
        for c in candidates:
            if c in img_dict:
                return img_dict[c]

        # 2. Best-overlap scored match against full ad name — ranked purely by
        #    how much of the normalized ad name appears in the image key.
        #    Penalise partial-prefix matches: if the image key is a substring of
        #    n_full (e.g. "camera" matching "camerabonus"), subtract the leftover
        #    length so the exact-name row always wins.
        n_full = _norm_key(source_names[0])
        scored = []
        for key in img_dict.keys():
            score = 0
            if n_full and n_full in key:
                score = len(n_full)
            elif n_full and key in n_full and len(key) >= 5:
                leftover = len(n_full) - len(key)
                score = max(0, len(key) - leftover)
            else:
                for c in candidates:
                    if c and c in key:
                        score = max(score, len(c))
                    elif c and key in c and len(key) >= 5:
                        leftover_c = len(c) - len(key)
                        score = max(score, max(0, len(key) - leftover_c))
            if score > 0:
                scored.append((score, key))

        if scored:
            scored.sort(reverse=True)
            return img_dict[scored[0][1]]

        return None

    else:
        # ── Non-guaranteed path ──────────────────────────────────────────────
        # Match by creative ID first, then full ad name as fallback.
        n_cid = _norm_key(cid)
        n_full = _norm_key(full_ad_name)

        candidates = []
        if n_cid:
            candidates.extend([n_cid, n_cid + "_", n_cid + "-", n_cid + "|"])
        if n_full:
            candidates.append(n_full)
        for source_val in [cid, full_ad_name]:
            candidates.extend(_key_variants(source_val))
        if edited_ad_name:
            n_e = _norm_key(edited_ad_name)
            if n_e:
                candidates.extend([n_e, n_e + "_", n_e + "-", n_e + "|"])
            candidates.extend(_key_variants(edited_ad_name))
        candidates = list(dict.fromkeys([c for c in candidates if c]))

        # 1. Exact normalized match.
        for c in candidates:
            if c in img_dict:
                return img_dict[c]

        # 2. Best-overlap scored match.
        scored = []
        for key in img_dict.keys():
            best_len = 0
            if n_cid and n_cid in key:
                best_len = max(best_len, len(n_cid))
            if n_cid and key in n_cid and len(key) >= 5:
                best_len = max(best_len, len(key))
            if n_full and n_full in key:
                best_len = max(best_len, len(n_full))
            if n_full and key in n_full and len(key) >= 5:
                best_len = max(best_len, len(key))
            for c in candidates:
                if c and c in key:
                    best_len = max(best_len, len(c))
                if c and key in c and len(key) >= 5:
                    best_len = max(best_len, len(key))
            if best_len > 0:
                scored.append((best_len, key))

        if scored:
            scored.sort(reverse=True)
            return img_dict[scored[0][1]]

        return None

if uploaded_images:
    progress_bar = st.progress(0)
    for i, f in enumerate(uploaded_images):
        try:
            name = f.name
            file_ext = name.lower().split('.')[-1] if '.' in name else ''
            
            # Determine if this is a video or image file
            video_extensions = ['mp4', 'mov', 'avi', 'webm']
            is_video = file_ext in video_extensions
            
            # use normalized filename (no ext, alnum only) as the key
            clean_name = re.sub(r"\.[^.]+$", "", name).strip()
            key = _norm_key(clean_name)
            alias_keys = _key_variants(clean_name)

            if key:
                if is_video:
                    # Store video as bytes with type marker
                    video_bytes = f.getvalue()
                    uploaded_asset_lookup[name] = (video_bytes, 'video', file_ext)
                    image_dict[key] = (video_bytes, 'video', file_ext)
                    for alias in alias_keys:
                        image_dict.setdefault(alias, (video_bytes, 'video', file_ext))
                    matched_summary.append(f"{name} → {key} (video)")
                else:
                    # Store image as PIL Image with type marker
                    img = Image.open(BytesIO(f.getvalue()))
                    uploaded_asset_lookup[name] = (img, 'image', file_ext)
                    image_dict[key] = (img, 'image', file_ext)
                    for alias in alias_keys:
                        image_dict.setdefault(alias, (img, 'image', file_ext))
                    matched_summary.append(f"{name} → {key} (image)")
            else:
                unmatched_images.append(f.name)

        except Exception as e:
            st.warning(f"Cannot read {f.name}: {e}")
        progress_bar.progress((i + 1) / len(uploaded_images))
    progress_bar.empty()
    


# ==============================
# Process File
# ==============================
if uploaded_file is not None:
    file_bytes = uploaded_file.getvalue()
    file_name = uploaded_file.name
    with st.spinner("Loading… large files may take a moment :)"):
        processed, raw_df = load_and_process(file_bytes, file_name, PROCESSING_LOGIC_VERSION)
    if processed is None:
        st.stop()

    # Order Filter Options
    order_options = ["All Orders"]
    if "Order_ID" in processed.columns:
        unique_orders = (processed["Order_ID"]
                         .dropna()
                         .astype(str)
                         .unique())
        # Order_ID already contains the composite "Name (ID: xxx)" format from process_campaign_data
        order_options.extend(sorted([o for o in unique_orders if o]))

    # ==============================
    # CREATIVE ANALYSIS
    # ==============================
    st.subheader("🎯 CREATIVE PERFORMANCE")
    st.markdown("Visualize creative performance from top to lowest performing by KPI. Configure filters below by order, KPI, time period, creative ID and more. Note: creatives are aggregated by creative identifiers in the same year. ")
    
    # Check if date columns exist for time period filtering
    has_date_cols = "Start_Date" in processed.columns and "End_Date" in processed.columns
    
    # Main filters in a compact 3-column layout with smaller fields
    # Support both 'size' and 'ad size' columns (case-insensitive) - for size performance chart only
    size_col_candidates = [col for col in processed.columns if col.lower() in ("size", "ad size")]
    has_size_col = processed is not None and bool(size_col_candidates)
    size_col = None
    if has_size_col:
        size_col = size_col_candidates[0]

    metric_options = ["CTR", "DPVR", "Purchase_Rate"]
    # Add volume KPIs (Purchases / Total Purchases) if data contains them
    if processed is not None and "Purchases" in processed.columns and processed["Purchases"].sum() > 0:
        metric_options.append("Purchases")
    if processed is not None and "Total_Purchases" in processed.columns and processed["Total_Purchases"].sum() > 0:
        metric_options.append("Total_Purchases")
    # Add Subscription sign-ups and Cost per subscription if columns exist
    if processed is not None and "Subscription sign-ups" in processed.columns:
        metric_options.append("Subscription sign-ups")
    if processed is not None and "App subscription sign-ups" in processed.columns:
        metric_options.append("App subscription sign-ups")
    if processed is not None and "Appstore Opens" in processed.columns and processed["Appstore Opens"].sum() > 0:
        metric_options.append("Appstore Opens")
    if processed is not None and "Appstore Opens" in processed.columns and "Impressions" in processed.columns and processed["Appstore Opens"].sum() > 0:
        metric_options.append("Appstore_Open_Rate")
    if processed is not None and "Total_Cost" in processed.columns and "Subscription sign-ups" in processed.columns:
        metric_options.append("Cost per subscription")
    # Add VCR only when valid source columns exist under the PG/non-PG rules.
    if _has_vcr_source_columns(processed):
        metric_options.append("VCR")
    if processed is not None and "Sales_USD" in processed.columns and "Total_Cost" in processed.columns:
        metric_options.append("Promoted_ROAS")
    if processed is not None and "Total_Sales_USD" in processed.columns and "Total_Cost" in processed.columns:
        metric_options.append("Total_ROAS")
    if processed is not None and "Total_DPV" in processed.columns:
        metric_options.append("Total_DPVR")
    if processed is not None and "Total_Purchases" in processed.columns:
        metric_options.append("Total_Purchase_Rate")
    # Add NTB KPIs if normalized columns exist
    def norm_col(col):
        return col.strip().lower().replace("-", "").replace(" ", "")
    normed_cols = {norm_col(c): c for c in processed.columns}
    ntb_col = normed_cols.get("newtobrandpurchases")
    total_ntb_col = normed_cols.get("totalnewtobrandpurchases")
    if ntb_col and "Purchases" in processed.columns:
        metric_options.append("Promoted_%_NTB")
    if total_ntb_col and "Total_Purchases" in processed.columns:
        metric_options.append("Total_%_NTB")
    metric_labels = {
        "CTR": "CTR",
        "DPVR": "Promoted DPVR",
        "Purchase_Rate": "Promoted Purchase Rate",
        "Promoted_ROAS": "Promoted ROAS",
        "Total_ROAS": "Total ROAS",
        "Total_DPVR": "Total DPVR",
        "Total_Purchase_Rate": "Total Purchase Rate",
        "Promoted_%_NTB": "Promoted % Purchases NTB",
        "Total_%_NTB": "Total % Purchases NTB",
        "VCR": "Video Completion Rate (VCR)"
        ,"Subscription sign-ups": "Subscription Sign-ups"
        ,"App subscription sign-ups": "App Subscription Sign-ups"
        ,"Cost per subscription": "Cost per Subscription"
        ,"Appstore Opens": "Appstore Opens"
        ,"Appstore_Open_Rate": "Appstore Open Rate"
        ,"Purchases": "Promoted Purchases"
        ,"Total_Purchases": "Total Purchases"
    }
    # Order metric_options alphabetically by their user-friendly label
    metric_options = sorted(metric_options, key=lambda x: metric_labels.get(x, x))
    default_index = metric_options.index("CTR") if "CTR" in metric_options else 0

    # Read filter values from session state so controls can render below chart.
    selected_orders = st.session_state.get("order_filter", ["All Orders"])
    if not selected_orders:
        selected_orders = ["All Orders"]
    selected_orders = [o for o in selected_orders if o in order_options]
    # Keep "All Orders" available in the dropdown, but not alongside specific picks.
    if "All Orders" in selected_orders and len(selected_orders) > 1:
        selected_orders = [o for o in selected_orders if o != "All Orders"]
    if not selected_orders:
        selected_orders = ["All Orders"]
    st.session_state["order_filter"] = selected_orders

    metric = st.session_state.get("metric_filter", "CTR")
    if metric not in metric_options:
        metric = "CTR" if "CTR" in metric_options else metric_options[0]
        # Also sync session state so the widget doesn't crash on stale value
        st.session_state["metric_filter"] = metric

    # Same guard for the other metric selectboxes (Order/Size/CreativexCampaign).
    # If a previous upload had extra KPIs (e.g., VCR) and the new upload doesn't,
    # the stored session value can be invalid — Streamlit will raise when the
    # widget tries to locate it in its new options list.
    for _k in ("order_metric_filter", "cc_metric_filter", "size_metric_filter"):
        _v = st.session_state.get(_k)
        if _v is not None and _v not in metric_options:
            st.session_state[_k] = "CTR" if "CTR" in metric_options else (metric_options[0] if metric_options else "CTR")

    min_imps = int(st.session_state.get("min_imps_filter", 100) or 0)

    filter_start_date = None
    filter_end_date = None
    if has_date_cols:
        min_date = processed["Start_Date"].min()
        max_date = processed["End_Date"].max()
        if not pd.isna(min_date) and not pd.isna(max_date):
            filter_start_date = st.session_state.get("start_date_filter", min_date)
            filter_end_date = st.session_state.get("end_date_filter", max_date)

            # Guard against stale session-state values from a previous upload.
            # If the persisted filter dates fall outside the new file's data range
            # (e.g., user uploaded a March file after running a January file), the
            # date filter would silently drop every row. Reset to the file's own
            # min/max in that case — the widgets will also re-sync on next render.
            try:
                _min_ts = pd.Timestamp(min_date)
                _max_ts = pd.Timestamp(max_date)
                _fs_ts = pd.Timestamp(filter_start_date)
                _fe_ts = pd.Timestamp(filter_end_date)
                # If the saved window doesn't overlap the data window, reset.
                if _fe_ts < _min_ts or _fs_ts > _max_ts:
                    filter_start_date = min_date
                    filter_end_date = max_date
                    st.session_state["start_date_filter"] = min_date
                    st.session_state["end_date_filter"] = max_date
                else:
                    # Clamp each end individually so partial overlaps still work.
                    if _fs_ts < _min_ts:
                        filter_start_date = min_date
                        st.session_state["start_date_filter"] = min_date
                    if _fe_ts > _max_ts:
                        filter_end_date = max_date
                        st.session_state["end_date_filter"] = max_date
            except Exception:
                filter_start_date = min_date
                filter_end_date = max_date
    
    # Apply filters BEFORE aggregation
    filtered_processed = processed.copy()
    initial_rows = len(filtered_processed)
    
    # Apply date filter if dates are selected
    if has_date_cols and 'filter_start_date' in locals() and 'filter_end_date' in locals() and filter_start_date and filter_end_date:
        # Filter for ads where the interval overlaps with the selected date range.
        # An ad is included if: (ad_start <= filter_end) AND (ad_end >= filter_start).
        # NaT (missing date) is treated as "unknown → keep the row" so we never
        # silently drop creatives just because the report lacks start/end dates.
        filter_start_dt = pd.Timestamp(filter_start_date)
        filter_end_dt = pd.Timestamp(filter_end_date)

        start_ok = (
            filtered_processed["Start_Date"].isna()
            | (filtered_processed["Start_Date"] <= filter_end_dt)
        )
        end_ok = (
            filtered_processed["End_Date"].isna()
            | (filtered_processed["End_Date"] >= filter_start_dt)
        )
        filtered_processed = filtered_processed[start_ok & end_ok]
        rows_after_date_filter = len(filtered_processed)
    else:
        rows_after_date_filter = initial_rows
    if min_imps > 0:
        filtered_processed = filtered_processed[filtered_processed["Impressions"] >= min_imps]
    rows_after_imps_filter = len(filtered_processed)

    # ...existing code...

    # Aggregate now (so the identifier filter can show the aggregated tuples).
    # Keep historical behavior: aggregate creatives across orders.
    grouped = aggregate_by_creative(filtered_processed, selected_orders, separate_by_campaign=False)
    if grouped is None or grouped.empty:
        st.error("⚠️ No data after filtering. Please check your filters:")
        st.markdown(f"""
        **Filter Diagnostics:**
        - Initial rows in data: **{initial_rows:,}**
        - After date filter: **{rows_after_date_filter:,}** rows
        - After min impressions filter (>= {min_imps}): **{rows_after_imps_filter:,}** rows
        - After order filter: **0 rows** (no data remaining)
        
        **Suggestions:**
        1. Try **lowering** the minimum impressions from {min_imps} to 0
        2. Check if your **date range** matches the data (dates in your file: {processed["Start_Date"].min()} to {processed["End_Date"].max() if has_date_cols else 'N/A'})
        3. Try selecting **"All Orders"** in the order filter
        4. Verify the uploaded file has the correct DSP report data
        """)
        st.stop()
    else:
        filtered = grouped.copy()

    # Creative identifier filter (with 'Select All' option)
    identifier_options = []
    if grouped is not None and not grouped.empty and "Group_Key" in grouped.columns:
        try:
            original_options = sorted(grouped["Group_Key"].astype(str).unique().tolist())
            if 'edited_creative_names' in st.session_state:
                identifier_options = [
                    st.session_state.edited_creative_names.get(opt, opt)
                    for opt in original_options
                ]
            else:
                identifier_options = original_options
        except Exception:
            identifier_options = []
    # Remove any existing 'Select All' to prevent duplicates, then add it at the top
    identifier_options = [opt for opt in identifier_options if opt != "Select All"]
    identifier_options = ["Select All"] + identifier_options

    # Apply any pending creative-identifier renames BEFORE we read the filter.
    # When a user edits a name in the "Edit Creative Identifiers" panel, we
    # can't modify the widget's session_state key directly (Streamlit raises).
    # Instead, the edit handler stashes the rename in a buffer, and here on
    # the next rerun we translate the old name → new name in the filter so
    # the creative stays selected under its new name.
    _pending_renames = st.session_state.get("_pending_identifier_renames", {})
    if _pending_renames and "identifier_filter" in st.session_state:
        _cur = st.session_state.get("identifier_filter", [])
        if isinstance(_cur, list) and any(n in _cur for n in _pending_renames):
            _cur = [_pending_renames.get(v, v) for v in _cur]
            st.session_state["identifier_filter"] = _cur
        # Clear the buffer so we don't re-apply next rerun.
        st.session_state["_pending_identifier_renames"] = {}

    identifier_filter = st.session_state.get('identifier_filter', [])
    if not isinstance(identifier_filter, list):
        identifier_filter = []
    identifier_filter = [v for v in identifier_filter if v in identifier_options]
    if "Select All" in identifier_filter:
        identifier_filter = identifier_options[1:]  # All except 'Select All'

    # Chart overlay values are read from session state so controls can render below the chart.
    benchmark_ctr = 2.0
    benchmark_dpvr = 1.5
    benchmark_pr = 0.5
    benchmark_promoted = 4.0
    benchmark_total = 6.0
    benchmark_total_dpvr = 2.5
    benchmark_total_pr = 0.8
    benchmark_subscriptions = 100.0
    benchmark_app_subscriptions = 50.0
    benchmark_cost_per_sub = 10.0
    benchmark_ctr_category = 2.2
    benchmark_dpvr_category = 1.8
    benchmark_pr_category = 0.6
    benchmark_promoted_category = 4.5
    benchmark_total_category = 6.5
    benchmark_total_dpvr_category = 3.0
    benchmark_total_pr_category = 1.0
    benchmark_subscriptions_category = 120.0
    benchmark_app_subscriptions_category = 60.0
    benchmark_cost_per_sub_category = 8.0
    show_advertiser_benchmark = bool(st.session_state.get("show_advertiser_benchmark", False))
    show_category_benchmark = bool(st.session_state.get("show_category_benchmark", False))
    advertiser_benchmark = st.session_state.get("advertiser_benchmark")
    category_benchmark = st.session_state.get("category_benchmark")

    if metric == "CTR":
        benchmark_ctr = advertiser_benchmark or benchmark_ctr
        benchmark_ctr_category = category_benchmark or benchmark_ctr_category
    elif metric == "DPVR":
        benchmark_dpvr = advertiser_benchmark or benchmark_dpvr
        benchmark_dpvr_category = category_benchmark or benchmark_dpvr_category
    elif metric == "Purchase_Rate":
        benchmark_pr = advertiser_benchmark or benchmark_pr
        benchmark_pr_category = category_benchmark or benchmark_pr_category
    elif metric == "Promoted_ROAS":
        benchmark_promoted = advertiser_benchmark or benchmark_promoted
        benchmark_promoted_category = category_benchmark or benchmark_promoted_category
    elif metric == "Total_ROAS":
        benchmark_total = advertiser_benchmark or benchmark_total
        benchmark_total_category = category_benchmark or benchmark_total_category
    elif metric == "Total_DPVR":
        benchmark_total_dpvr = advertiser_benchmark or benchmark_total_dpvr
        benchmark_total_dpvr_category = category_benchmark or benchmark_total_dpvr_category
    elif metric == "Total_Purchase_Rate":
        benchmark_total_pr = advertiser_benchmark or benchmark_total_pr
        benchmark_total_pr_category = category_benchmark or benchmark_total_pr_category
    elif metric == "Subscription sign-ups":
        benchmark_subscriptions = advertiser_benchmark or benchmark_subscriptions
        benchmark_subscriptions_category = category_benchmark or benchmark_subscriptions_category
    elif metric == "App subscription sign-ups":
        benchmark_app_subscriptions = advertiser_benchmark or benchmark_app_subscriptions
        benchmark_app_subscriptions_category = category_benchmark or benchmark_app_subscriptions_category
    elif metric == "Cost per subscription":
        benchmark_cost_per_sub = advertiser_benchmark or benchmark_cost_per_sub
        benchmark_cost_per_sub_category = category_benchmark or benchmark_cost_per_sub_category

    # Filter grouped data based on creative identifier selection
    selected_group_keys = set()
    filtered = grouped.copy()
    if identifier_filter:
        # Map selected filter values to original Group_Key values
        edited_map = {}
        for k in grouped["Group_Key"].astype(str).unique():
            if 'edited_creative_names' in st.session_state:
                edited_map[st.session_state.edited_creative_names.get(k, k)] = k
            else:
                edited_map[k] = k
        original_names = [edited_map.get(name, name) for name in identifier_filter]
        original_names_no_year = [name.split(' | ')[0] for name in original_names]
        all_matches = set(original_names + original_names_no_year)
        selected_group_keys = set(all_matches)
        filtered = filtered[filtered["Group_Key"].isin(all_matches)]

    # Re-aggregate if any creative identifiers have been edited to the same name
    if st.session_state.get('edited_creative_names'):
        # Apply edited names to create a grouping column
        filtered["Edited_Group_Key"] = filtered["Group_Key"].apply(
            lambda x: st.session_state.edited_creative_names.get(x, x)
        )
        
        # Check if there are duplicate edited names (need to aggregate)
        if filtered["Edited_Group_Key"].duplicated().any():
            # Define aggregation functions for each column
            agg_dict = {
                "Impressions": "sum",
                "Click-throughs": "sum",
                "DPV": "sum",
                "Purchases": "sum",
                "Full_Creative_Name": "first",  # Take first creative name
            }
            
            # Add optional columns to aggregation
            if "Sales_USD" in filtered.columns:
                agg_dict["Sales_USD"] = "sum"
            if "Total_Sales_USD" in filtered.columns:
                agg_dict["Total_Sales_USD"] = "sum"
            if "Total_Cost" in filtered.columns:
                agg_dict["Total_Cost"] = "sum"
            if "Total_DPV" in filtered.columns:
                agg_dict["Total_DPV"] = "sum"
            if "Total_Purchases" in filtered.columns:
                agg_dict["Total_Purchases"] = "sum"
            if "Subscription sign-ups" in filtered.columns:
                agg_dict["Subscription sign-ups"] = "sum"
            if "App subscription sign-ups" in filtered.columns:
                agg_dict["App subscription sign-ups"] = "sum"
            if "_vcr_video_start" in filtered.columns:
                agg_dict["_vcr_video_start"] = "sum"
            if "_vcr_video_complete" in filtered.columns:
                agg_dict["_vcr_video_complete"] = "sum"
            
            # Add video columns if present
            def norm_col(col):
                return col.strip().lower().replace("-", "").replace(" ", "")
            normed_cols = {norm_col(c): c for c in filtered.columns}
            video_started_col, video_completed_col = _get_video_metric_columns(normed_cols)
            if video_started_col and video_started_col in filtered.columns:
                agg_dict[video_started_col] = "sum"
            if video_completed_col and video_completed_col in filtered.columns:
                agg_dict[video_completed_col] = "sum"
            
            # Add NTB columns if present
            ntb_col = normed_cols.get("newtobrandpurchases")
            total_ntb_col = normed_cols.get("totalnewtobrandpurchases")
            if ntb_col and ntb_col in filtered.columns:
                agg_dict[ntb_col] = "sum"
            if total_ntb_col and total_ntb_col in filtered.columns:
                agg_dict[total_ntb_col] = "sum"
            
            # Aggregate by edited identifier
            filtered = filtered.groupby("Edited_Group_Key", as_index=False).agg(agg_dict)
            
            # Recalculate rates after aggregation
            denom = filtered["Impressions"].replace(0, 1)
            filtered["CTR"] = (filtered["Click-throughs"] / denom * 100).round(4)
            filtered["DPVR"] = (filtered["DPV"] / denom * 100).round(4)
            filtered["Purchase_Rate"] = (filtered["Purchases"] / denom * 100).round(4)
            
            # Recalculate VCR if video columns exist
            if "_vcr_video_start" in filtered.columns and "_vcr_video_complete" in filtered.columns:
                started = pd.to_numeric(filtered["_vcr_video_start"], errors="coerce").replace(0, 1)
                completed = pd.to_numeric(filtered["_vcr_video_complete"], errors="coerce")
                filtered["VCR"] = (completed / started * 100).round(4)
            elif video_started_col and video_completed_col and video_started_col in filtered.columns and video_completed_col in filtered.columns:
                started = pd.to_numeric(filtered[video_started_col], errors="coerce").replace(0, 1)
                completed = pd.to_numeric(filtered[video_completed_col], errors="coerce")
                filtered["VCR"] = (completed / started * 100).round(4)
            
            # Recalculate ROAS if present
            if "Total_Cost" in filtered.columns:
                cost_denom = filtered["Total_Cost"].replace(0, 0.01)
                if "Sales_USD" in filtered.columns:
                    filtered["Promoted_ROAS"] = (filtered["Sales_USD"] / cost_denom).round(4)
                if "Total_Sales_USD" in filtered.columns:
                    filtered["Total_ROAS"] = (filtered["Total_Sales_USD"] / cost_denom).round(4)
            
            # Recalculate total rates if present
            if "Total_DPV" in filtered.columns:
                filtered["Total_DPVR"] = (filtered["Total_DPV"] / denom * 100).round(4)
            if "Total_Purchases" in filtered.columns:
                filtered["Total_Purchase_Rate"] = (filtered["Total_Purchases"] / denom * 100).round(4)
            
            # Recalculate NTB percentages if present
            if ntb_col and ntb_col in filtered.columns and "Purchases" in filtered.columns:
                purchases_denom = filtered["Purchases"].replace(0, 1)
                ntb_numeric = pd.to_numeric(filtered[ntb_col], errors="coerce")
                filtered["Promoted_%_NTB"] = (ntb_numeric / purchases_denom * 100).round(4)
            if total_ntb_col and total_ntb_col in filtered.columns and "Total_Purchases" in filtered.columns:
                total_purchases_denom = filtered["Total_Purchases"].replace(0, 1)
                total_ntb_numeric = pd.to_numeric(filtered[total_ntb_col], errors="coerce")
                filtered["Total_%_NTB"] = (total_ntb_numeric / total_purchases_denom * 100).round(4)
            
            # Use edited identifier as the new Group_Key
            filtered["Group_Key"] = filtered["Edited_Group_Key"]
            # Mark that these are already edited (so get_display_name doesn't try to look them up again)
            filtered["_is_aggregated"] = True
        else:
            # No aggregation needed, but still mark rows
            filtered["_is_aggregated"] = False
        
        # Drop the temporary column
        filtered = filtered.drop(columns=["Edited_Group_Key"], errors="ignore")
    else:
        # No edits, mark all as not aggregated
        filtered["_is_aggregated"] = False

    # Aggregate
    if grouped is None or grouped.empty:
        st.warning("No data after filtering.")
        st.stop()

    if filtered.empty:
        st.warning("No creatives match your filters.")
        st.stop()

    # Sort
    if metric not in filtered.columns:
        denom = filtered["Impressions"].replace(0, 1)
        if metric == "Total_DPVR" and "Total_DPV" in filtered.columns:
            filtered["Total_DPVR"] = (filtered["Total_DPV"] / denom * 100).round(4)
        elif metric == "Total_Purchase_Rate" and "Total_Purchases" in filtered.columns:
            filtered["Total_Purchase_Rate"] = (filtered["Total_Purchases"] / denom * 100).round(4)
        elif metric == "Promoted_DPVR" and "DPV" in filtered.columns:
            filtered["Promoted_DPVR"] = (filtered["DPV"] / denom * 100).round(4)
        elif metric == "Promoted_Purchase_Rate" and "Purchases" in filtered.columns:
            filtered["Promoted_Purchase_Rate"] = (filtered["Purchases"] / denom * 100).round(4)
        elif metric == "Cost per subscription" and "Total_Cost" in filtered.columns and "Subscription sign-ups" in filtered.columns:
            filtered["Cost per subscription"] = (filtered["Total_Cost"] / filtered["Subscription sign-ups"].replace(0, float('nan'))).round(4)
            # Filter out creatives with NaN cost per subscription (those with 0 sign-ups)
            filtered = filtered[filtered["Cost per subscription"].notna()].copy()
        if metric not in filtered.columns:
            filtered[metric] = 0.0

    # Sort - Cost per subscription goes lowest to highest, all others highest to lowest
    ascending_order = True if metric == "Cost per subscription" else False
    sorted_df = filtered.sort_values(metric, ascending=ascending_order).reset_index(drop=True)
    total_creatives = len(sorted_df)

    if total_creatives == 0:
        if metric == "Cost per subscription":
            st.warning("No creatives have subscription sign-ups data to calculate cost per subscription.")
        else:
            st.warning("No creatives meet the impression threshold.")
        st.stop()

    # ==============================
    # Chart: Top N (Fixed for 1 item)
    # ==============================

    # Helper: wrap long text into HTML <br> segments for Plotly tick labels and Streamlit markdown titles
    def _wrap_into_html(s, width=25, max_lines=None):
        if s is None:
            return ""
        s = str(s)
        # normalize underscores
        s = s.replace("_", " ")
        words = s.split()
        if not words:
            return ""
        lines = []
        cur = ""
        for w in words:
            if not cur:
                cur = w
            elif len(cur) + 1 + len(w) <= width:
                cur = cur + " " + w
            else:
                lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)

        if max_lines is not None and len(lines) > max_lines:
            lines = lines[:max_lines]
            if lines:
                truncated = lines[-1].rstrip()
                if len(truncated) >= width:
                    truncated = truncated[:max(1, width - 1)].rstrip()
                lines[-1] = f"{truncated}..."
        return "<br>".join(lines)

    # Set chart appearance values (can be customized by user after viewing chart)
    default_num_to_show = min(15, total_creatives) if total_creatives > 1 else 1
    
    # Use session state or widget values if they exist, otherwise use defaults
    # Reset to default if total_creatives changed (e.g., identifier filter changed)
    prev_total = st.session_state.get("prev_total_creatives", 0)
    if prev_total != total_creatives:
        st.session_state["prev_total_creatives"] = total_creatives
        num_to_show = default_num_to_show
    else:
        num_to_show = st.session_state.get("num_to_show_slider", default_num_to_show)
    bar_width = st.session_state.get("bar_width_slider", 0.8)
    bar_color = st.session_state.get("bar_color_picker", "#1f77b4")
    text_size = st.session_state.get("text_size_slider", 16)
    
    # Handle case where total_creatives is 1
    if total_creatives == 1:
        num_to_show = 1

    # ==============================
    # CHART CREATION
    # ==============================
    # Create chart data based on number to show (determined in design section)
    if total_creatives == 1:
        # If the user explicitly filtered by a single identifier or by a single order,
        # don't show the prompting info message — they intentionally chose a single
        # value. Only show the info when there was no explicit identifier filter and
        # the orders selection is either 'All Orders' or multiple orders.
        explicitly_filtered_by_one_order = bool(selected_orders and "All Orders" not in selected_orders and len(selected_orders) == 1)
        if not identifier_filter and not explicitly_filtered_by_one_order:
            st.info("**Only 1 creative matches your filters.** Please add more creative identifiers to compare performance.")
        chart_df = sorted_df.copy()
        if metric == "Cost per subscription":
            title = f"**Top Creatives by lowest {metric}**"
        else:
            title = f"**Top Creatives by {metric}**"
    else:
        chart_df = sorted_df.head(num_to_show).copy()
        if metric == "Cost per subscription":
            title = f"Top Creatives by lowest {metric}"
        else:
            title = f"Top Creatives by {metric}"

    # Use wrapped labels for the chart's x-axis so long creative names don't get visually cut off.
    # Use edited names if available, but if already aggregated, use Group_Key as-is
    def get_chart_label(row):
        if row.get("_is_aggregated", False):
            return row["Group_Key"]
        else:
            return get_display_name(row["Group_Key"])

    chart_df["Display_Name"] = chart_df.apply(get_chart_label, axis=1)

    # ── Product tag prefixing ────────────────────────────────────────────────
    # When the chart contains BOTH tagged (PG / FTV Feature Rotator) rows AND
    # untagged rows, prepend the tag to the display name so users can tell at a
    # glance why some labels are long full ad names and others are short
    # creative IDs (e.g., "PG · xyz_NYE_..." vs "NYE"). When the chart is
    # uniform (all tagged or all untagged), we leave labels alone.
    if "Product_Tag" in chart_df.columns:
        _tags_present = chart_df["Product_Tag"].astype(str).str.strip()
        _has_tagged = (_tags_present != "").any()
        _has_untagged = (_tags_present == "").any()
        if _has_tagged and _has_untagged:
            def _prefix_with_tag(row):
                tag = str(row.get("Product_Tag") or "").strip()
                name = str(row["Display_Name"])
                if tag:
                    return f"{tag} · {name}"
                return name
            chart_df["Display_Name"] = chart_df.apply(_prefix_with_tag, axis=1)
    axis_font_size = max(8, int(text_size))
    n_bars = len(chart_df)
    _bar_slot_px = 920 / max(1, n_bars)

    # Always use straight (0°) labels; rely on line-wrapping to keep text within each bar slot.
    if n_bars <= 5:
        label_wrap_width = max(10, int(_bar_slot_px * 0.70 / (axis_font_size * 0.60)))
        label_max_lines = 4
    else:
        label_wrap_width = max(6, int(_bar_slot_px * 0.70 / (axis_font_size * 0.60)))
        label_max_lines = 3
    axis_tick_angle = 0

    def _format_label_with_campaign_breaks(s):
        txt = str(s or "").strip()
        if not txt:
            return ""
        if "|" in txt:
            parts = [p.strip() for p in txt.split("|") if p.strip()]
            return "<br>".join(_wrap_into_html(p, width=max(10, label_wrap_width - 2), max_lines=label_max_lines) for p in parts)
        return _wrap_into_html(txt, width=label_wrap_width, max_lines=label_max_lines)

    chart_df["Label"] = chart_df["Display_Name"].apply(_format_label_with_campaign_breaks)
    max_label_lines = int(chart_df["Label"].astype(str).str.count("<br>").max() + 1) if len(chart_df) else 1
    if axis_tick_angle != 0:
        # With rotation the label extends diagonally; vertical budget ≈ text_width × sin(45°).
        max_label_chars = chart_df["Label"].astype(str).str.len().max()
        bottom_margin = max(80, int(max_label_chars * axis_font_size * 0.60 * 0.707) + 20)
    else:
        bottom_margin = max(80, int(axis_font_size * max_label_lines * 2.4))
    chart_df["Chart_X"] = [f"creative_{idx}" for idx in range(len(chart_df))]
    x_tickvals = chart_df["Chart_X"].tolist()
    x_ticktext = chart_df["Label"].tolist()
    plain_title = str(title).replace("**", "")
    
    # Create figure
    has_order_data = False

    # Choose display formats depending on metric type
    is_percent_metric = metric in ["CTR", "DPVR", "Purchase_Rate", "Total_DPVR", "Total_Purchase_Rate", "Promoted_%_NTB", "Total_%_NTB", "VCR", "Appstore_Open_Rate"]
    is_cost_metric = metric == "Cost per subscription"
    # Integer count metrics — display as whole numbers with thousands separators
    is_count_metric = metric in ["Purchases", "Total_Purchases", "Subscription sign-ups", "App subscription sign-ups", "Appstore Opens"]

    # Grow chart height when labels are tall so bars don't get squashed.
    chart_height = max(620, 380 + bottom_margin)

    if is_percent_metric:
        text_template = "%{text:.4f}%"
        hover_y_template = "%{y:.4f}%"
    elif is_cost_metric:
        text_template = "$%{text:.2f}"
        hover_y_template = "$%{y:.2f}"
    elif is_count_metric:
        text_template = "%{text:,.0f}"
        hover_y_template = "%{y:,.0f}"
    else:
        text_template = "%{text:.2f}"
        hover_y_template = "%{y:.2f}"
    
    if has_order_data:
        # Create subplots to handle both bars and lines
        fig = make_subplots(specs=[[{"secondary_y": False}]])
        
        # Add bar chart
        if identifier_filter and len(identifier_filter) >= 1:
            chart_df["Color_Group"] = chart_df["Group_Key"].apply(
                lambda x: "Selected" if x in selected_group_keys else "Others"
            )
            
            # Add bars for selected and others with different colors
            for group in ["Selected", "Others"]:
                group_data = chart_df[chart_df["Color_Group"] == group]
                if not group_data.empty:
                    color = bar_color if group == "Selected" else "#cccccc"
                    fig.add_trace(go.Bar(
                        x=group_data["Chart_X"],
                        y=group_data[metric],
                        name=f"Creative {metric} ({group})",
                        marker_color=color,
                        width=bar_width,
                        text=group_data[metric].round(4),
                        texttemplate=text_template,
                        textposition="outside",
                        hovertemplate=f"<b>%{{customdata[0]}}</b><br>{metric}: {hover_y_template}<br>Impressions: %{{customdata[1]:,}}<br>Purchases: %{{customdata[2]:,}}<extra></extra>",
                        customdata=group_data[["Display_Name", "Impressions", "Purchases"]].values
                    ))
        else:
            # Single color scheme for all bars
            fig.add_trace(go.Bar(
                x=chart_df["Chart_X"],
                y=chart_df[metric],
                name=f"Creative {metric}",
                marker=dict(
                    color=bar_color,
                    showscale=False
                ),
                width=bar_width,
                text=chart_df[metric].round(4),
                texttemplate=text_template,
                textposition="outside",
                hovertemplate=f"<b>%{{customdata[0]}}</b><br>{metric}: {hover_y_template}<br>Impressions: %{{customdata[1]:,}}<br>Purchases: %{{customdata[2]:,}}<extra></extra>",
                customdata=chart_df[["Display_Name", "Impressions", "Purchases"]].values
            ))
        
        # Add benchmark lines if enabled
        if show_advertiser_benchmark:
            benchmark_values = {"CTR": benchmark_ctr, "DPVR": benchmark_dpvr, "Purchase_Rate": benchmark_pr, "Promoted_ROAS": benchmark_promoted, "Total_ROAS": benchmark_total, "Total_DPVR": benchmark_total_dpvr, "Total_Purchase_Rate": benchmark_total_pr, "Subscription sign-ups": benchmark_subscriptions, "App subscription sign-ups": benchmark_app_subscriptions, "Cost per subscription": benchmark_cost_per_sub}
            benchmark_value = benchmark_values.get(metric)
            
            if benchmark_value is not None:
                fig.add_trace(go.Scatter(
                    x=chart_df["Chart_X"],
                    y=[benchmark_value] * len(chart_df),
                    mode="lines",
                    name=f"Advertiser Benchmark",
                    line=dict(color="orange", width=4, dash="dot"),
                    hovertemplate=f"<b>Advertiser Benchmark {metric}</b><br>Value: %{{y:.4f}}<extra></extra>"
                ))
        
        if show_category_benchmark:
            benchmark_values_category = {"CTR": benchmark_ctr_category, "DPVR": benchmark_dpvr_category, "Purchase_Rate": benchmark_pr_category, "Promoted_ROAS": benchmark_promoted_category, "Total_ROAS": benchmark_total_category, "Total_DPVR": benchmark_total_dpvr_category, "Total_Purchase_Rate": benchmark_total_pr_category, "Subscription sign-ups": benchmark_subscriptions_category, "App subscription sign-ups": benchmark_app_subscriptions_category, "Cost per subscription": benchmark_cost_per_sub_category}
            benchmark_value_category = benchmark_values_category.get(metric)
            
            if benchmark_value_category is not None:
                fig.add_trace(go.Scatter(
                    x=chart_df["Chart_X"],
                    y=[benchmark_value_category] * len(chart_df),
                    mode="lines",
                    name=f"Category Benchmark",
                    line=dict(color="purple", width=4, dash="dashdot"),
                    hovertemplate=f"<b>Category Benchmark {metric}</b><br>Value: %{{y:.4f}}<extra></extra>"
                ))
        
        fig.update_layout(
            title=dict(text=plain_title, x=0.5, xanchor="center", font=dict(size=18)),
            xaxis_title="", 
            yaxis_title=metric,
            xaxis_tickangle=axis_tick_angle,
            showlegend=True,
            legend=dict(
                orientation="h", 
                yanchor="bottom", 
                y=1.02, 
                xanchor="right", 
                x=1,
                font=dict(size=16)  # Larger legend font size
            ),
            margin=dict(l=80, r=20, b=bottom_margin, t=60),
            height=chart_height,
            xaxis=dict(
                automargin=True,
                tickfont=dict(size=axis_font_size),
                categoryorder="array",
                categoryarray=x_tickvals,
                tickmode="array",
                tickvals=x_tickvals,
                ticktext=x_ticktext,
            )
        )
        
    else:
        # Original chart without order performance
        if identifier_filter and len(identifier_filter) >= 1:
            chart_df["Color_Group"] = chart_df["Group_Key"].apply(
                lambda x: "Selected" if x in selected_group_keys else "Others"
            )
            fig = px.bar(
                chart_df,
                x="Chart_X",
                y=metric,
                text=metric,
                color="Color_Group",
                color_discrete_map={"Selected": bar_color, "Others": "#cccccc"},
                height=chart_height,
                hover_data={"Impressions": ":,", "Purchases": ":,"}
            )
            fig.update_layout(
                xaxis_title="", yaxis_title=metric, xaxis_tickangle=axis_tick_angle,
                title=dict(text=plain_title, x=0.5, xanchor="center", font=dict(size=18)),
                showlegend=True, legend_title="Filter", margin=dict(l=80, r=20, b=bottom_margin, t=60),
                xaxis={'categoryorder': 'array', 'categoryarray': x_tickvals, 'tickfont': {'size': axis_font_size}, 'automargin': True, 'tickmode': 'array', 'tickvals': x_tickvals, 'ticktext': x_ticktext}
            )
        else:
            fig = px.bar(
                chart_df,
                x="Chart_X",
                y=metric,
                text=metric,
                color_discrete_sequence=[bar_color], 
                height=chart_height,
                hover_data={"Impressions": ":,", "Purchases": ":,"}
            )
            fig.update_layout(
                xaxis_title="", yaxis_title=metric, xaxis_tickangle=axis_tick_angle,
                title=dict(text=plain_title, x=0.5, xanchor="center", font=dict(size=18)),
                showlegend=False, margin=dict(l=80, r=20, b=bottom_margin, t=60),
                xaxis={'categoryorder': 'array', 'categoryarray': x_tickvals, 'tickfont': {'size': axis_font_size}, 'automargin': True, 'tickmode': 'array', 'tickvals': x_tickvals, 'ticktext': x_ticktext}
            )

        fig.update_traces(
            texttemplate=text_template,
            textposition="outside",
            width=bar_width,
            customdata=chart_df[["Display_Name", "Impressions", "Purchases"]].values,
            hovertemplate=f"<b>%{{customdata[0]}}</b><br>{metric}: {hover_y_template}<br>Impressions: %{{customdata[1]:,}}<br>Purchases: %{{customdata[2]:,}}<extra></extra>"
        )
        
        # Add benchmark lines if enabled (for charts without order performance)
        if show_advertiser_benchmark:
            benchmark_values = {"CTR": benchmark_ctr, "DPVR": benchmark_dpvr, "Purchase_Rate": benchmark_pr, "Promoted_ROAS": benchmark_promoted, "Total_ROAS": benchmark_total, "Total_DPVR": benchmark_total_dpvr, "Total_Purchase_Rate": benchmark_total_pr, "Subscription sign-ups": benchmark_subscriptions, "App subscription sign-ups": benchmark_app_subscriptions, "Cost per subscription": benchmark_cost_per_sub}
            benchmark_value = benchmark_values.get(metric)
            
            if benchmark_value is not None:
                fig.add_trace(go.Scatter(
                    x=chart_df["Chart_X"],
                    y=[benchmark_value] * len(chart_df),
                    mode="lines",
                    name=f"Advertiser Benchmark",
                    line=dict(color="orange", width=4, dash="dot"),
                    hovertemplate=f"<b>Advertiser Benchmark {metric}</b><br>Value: {hover_y_template}<extra></extra>"
                ))
        
        if show_category_benchmark:
            benchmark_values_category = {"CTR": benchmark_ctr_category, "DPVR": benchmark_dpvr_category, "Purchase_Rate": benchmark_pr_category, "Promoted_ROAS": benchmark_promoted_category, "Total_ROAS": benchmark_total_category, "Total_DPVR": benchmark_total_dpvr_category, "Total_Purchase_Rate": benchmark_total_pr_category, "Subscription sign-ups": benchmark_subscriptions_category, "App subscription sign-ups": benchmark_app_subscriptions_category, "Cost per subscription": benchmark_cost_per_sub_category}
            benchmark_value_category = benchmark_values_category.get(metric)
            
            if benchmark_value_category is not None:
                fig.add_trace(go.Scatter(
                    x=chart_df["Chart_X"],
                    y=[benchmark_value_category] * len(chart_df),
                    mode="lines",
                    name=f"Category Benchmark",
                    line=dict(color="purple", width=4, dash="dashdot"),
                    hovertemplate=f"<b>Category Benchmark {metric}</b><br>Value: {hover_y_template}<extra></extra>"
                ))
    

        
    
    with st.container(border=True):

        # Creative images under chart - keep in the same visual container as bars.
        image_size_scale = int(st.session_state.get("image_size_scale", 100))

        if "manual_uploaded_assets" not in st.session_state:
            st.session_state["manual_uploaded_assets"] = {}
        enable_direct_drop = st.checkbox(
            "Directly drop image/video under each bar",
            value=st.session_state.get("enable_direct_drop", False),
            key="enable_direct_drop",
            help="Upload a file directly under a specific bar to override auto image mapping",
        )

        def _resolve_row_asset_data(row_idx, row_obj):
            row_key_local = str(row_obj.get("Group_Key") or row_obj.get("Display_Name") or f"row_{row_idx}")
            manual_asset_local = st.session_state.get("manual_uploaded_assets", {}).get(row_key_local)
            if manual_asset_local is not None:
                return row_key_local, manual_asset_local
            return row_key_local, _find_image_for_row(row_obj, image_dict)

        # Optional: embed mapped images directly into the Plotly figure so
        # the built-in Plotly fullscreen button includes them.
        _labels_handled_by_images = False
        if len(chart_df) > 0:
            n_bars_pre = len(chart_df)
            sizex_val = 0.88
            # Estimate each bar slot's pixel width (1100px = typical 1200px browser minus margins).
            sizex_px = sizex_val * 1100.0 / max(1, n_bars_pre)
            # Cap rendered image height so bars are never squeezed away.
            max_image_zone_px = 300

            # ── Pass 1: decode images; compute the natural rendered height per image. ──
            # sizex and sizey are in *different* unit spaces (data vs paper), so we
            # compute each image's rendered pixel height from its actual aspect ratio
            # and the estimated per-slot pixel width, then set sizey to match exactly.
            # This means contain() never has anything to letterbox → zero gap above images.
            pre_images = []   # [(chart_x, pil_or_None)]
            for embed_i, (_, embed_row) in enumerate(chart_df.iterrows()):
                _, embed_asset_data = _resolve_row_asset_data(embed_i, embed_row)
                if not embed_asset_data:
                    pre_images.append((embed_row["Chart_X"], None))
                    continue
                embed_asset, embed_type, _ = embed_asset_data
                if embed_type != 'image':
                    pre_images.append((embed_row["Chart_X"], None))
                    continue
                pre_images.append((embed_row["Chart_X"], embed_asset))

            rendered_heights = {}  # chart_x → rendered px height
            for x_val, img in pre_images:
                if img is None:
                    rendered_heights[x_val] = 0
                    continue
                iw, ih = img.size
                img_ar = iw / max(1, ih)
                # Width-constrained render height: height = slot_width / aspect_ratio.
                rh = min(max_image_zone_px, max(40, sizex_px / max(0.05, img_ar)))
                rendered_heights[x_val] = rh

            max_rendered_h = max(rendered_heights.values()) if rendered_heights else 0

            if max_rendered_h > 0:
                # image_band_top: all images are TOP-anchored here, so there is never
                # a gap between a bar's base and its image top.
                image_band_height = max_rendered_h / chart_height   # paper fraction
                image_band_top = 0.06 + image_band_height
                bar_domain_start = min(0.98, image_band_top + 0.015)

                # ── Pass 2: encode images. ──
                embedded_layout_images = []   # [(chart_x, sizey_paper, src_uri)]
                for x_val, img in pre_images:
                    if img is None:
                        continue
                    try:
                        rh = rendered_heights[x_val]
                        sizey_paper = rh / chart_height
                        buf = BytesIO()
                        img.convert("RGB").save(buf, format="PNG")
                        b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
                        embedded_layout_images.append(
                            (x_val, sizey_paper, f"data:image/png;base64,{b64}")
                        )
                    except Exception:
                        continue

                if embedded_layout_images:
                    _labels_handled_by_images = True
                    label_lines = int(chart_df["Label"].astype(str).str.count("<br>").max() + 1) if len(chart_df) else 1
                    embedded_bottom_margin = max(30, 6 + label_lines * max(10, int(axis_font_size)))
                    fig.update_layout(margin=dict(b=embedded_bottom_margin))
                    fig.update_yaxes(domain=[bar_domain_start, 1.0])
                    fig.update_xaxes(showticklabels=False)

                    sizey_lookup = {x: sy for x, sy, _ in embedded_layout_images}

                    for x_val, sizey_paper, src_uri in embedded_layout_images:
                        scale_ratio = max(0.6, min(1.25, image_size_scale / 100.0))
                        fig.add_layout_image(
                            dict(
                                source=src_uri,
                                xref="x",
                                yref="paper",
                                x=x_val,
                                # Top-anchor: image starts flush against the bar area.
                                y=image_band_top,
                                sizex=min(1.10, sizex_val * scale_ratio),
                                # sizey exactly matches the image's rendered height → no letterbox.
                                sizey=sizey_paper * scale_ratio,
                                xanchor="center",
                                yanchor="top",
                                sizing="contain",
                                layer="above",
                            )
                        )

                    # Labels: placed just below each image's own bottom edge.
                    n_bars = len(chart_df)
                    per_bar_px = 920 / max(1, n_bars)
                    # crowd_font_cap only reduces size when bars are very crowded;
                    # it must not cap below the slider value for uncrowded layouts.
                    crowd_font_cap = max(7, int(per_bar_px * 0.20))
                    label_ann_font = max(8, min(axis_font_size, crowd_font_cap))
                    for _, label_row in chart_df.iterrows():
                        x_val = label_row["Chart_X"]
                        this_sizey = sizey_lookup.get(x_val, image_band_height)
                        # When scale_ratio > 1 the image grows downward; label must move down too.
                        scaled_sizey = this_sizey * scale_ratio
                        label_y_this = image_band_top - scaled_sizey - 0.008
                        fig.add_annotation(
                            x=x_val,
                            y=label_y_this,
                            xref="x",
                            yref="paper",
                            text=str(label_row["Label"]),
                            showarrow=False,
                            align="center",
                            xanchor="center",
                            yanchor="top",
                            font=dict(size=label_ann_font),
                        )

        # If images didn't already place label annotations, add them now so labels
        # are always centered straight under each bar (no rotation / overlap).
        if not _labels_handled_by_images and len(chart_df) > 0:
            _n = len(chart_df)
            _per_bar = 920 / max(1, _n)
            _crowd_cap = max(7, int(_per_bar * 0.20))
            _ann_font = max(8, min(axis_font_size, _crowd_cap))
            fig.update_xaxes(showticklabels=False)
            for _, _lrow in chart_df.iterrows():
                fig.add_annotation(
                    x=_lrow["Chart_X"],
                    y=-0.01,
                    xref="x",
                    yref="paper",
                    text=str(_lrow["Label"]),
                    showarrow=False,
                    align="center",
                    xanchor="center",
                    yanchor="top",
                    font=dict(size=_ann_font),
                )

        st.plotly_chart(fig, use_container_width=True)

        # Determine whether any bar has a video asset (Plotly can't embed video,
        # so we always show a video strip for those rows even without the checkbox).
        def _row_has_video(row_idx, row_obj):
            _, asset = _resolve_row_asset_data(row_idx, row_obj)
            return asset is not None and asset[1] == 'video'

        has_any_video = any(_row_has_video(i, r) for i, (_, r) in enumerate(chart_df.iterrows()))

        # Build the shared column layout once if either strip needs it.
        def _build_strip_cols(n):
            if n == 1:
                return st.columns(1, gap="medium")
            gap = "medium" if n <= 3 else "small"
            left_spacer = round(n * 80 / 920, 4)
            right_spacer = round(n * 20 / 920, 4)
            row_cols = st.columns([left_spacer] + [1.0] * n + [right_spacer], gap=gap)
            return row_cols[1:-1]

        # ── Direct-drop strip (only when checkbox is checked) ──
        if enable_direct_drop:
            actual_creatives_shown = len(chart_df)
            if actual_creatives_shown == 0:
                st.write("*No creatives to display*")
            else:
                cols = _build_strip_cols(actual_creatives_shown)
                for i, (_, r) in enumerate(chart_df.iterrows()):
                    with cols[i]:
                        row_key = str(r.get("Group_Key") or r.get("Display_Name") or f"row_{i}")

                        dropped_asset = st.file_uploader(
                            "Drop image/video for this bar",
                            type=["png", "jpg", "jpeg", "mp4", "mov", "avi", "webm"],
                            key=f"direct_drop_{_norm_key(row_key)}_{i}",
                            label_visibility="collapsed",
                        )
                        if dropped_asset is not None:
                            dropped_name = dropped_asset.name
                            dropped_ext = dropped_name.lower().split('.')[-1] if '.' in dropped_name else ''
                            dropped_video_exts = ['mp4', 'mov', 'avi', 'webm']
                            if dropped_ext in dropped_video_exts:
                                st.session_state["manual_uploaded_assets"][row_key] = (
                                    dropped_asset.getvalue(),
                                    'video',
                                    dropped_ext,
                                )
                            else:
                                st.session_state["manual_uploaded_assets"][row_key] = (
                                    Image.open(BytesIO(dropped_asset.getvalue())),
                                    'image',
                                    dropped_ext,
                                )

                        if row_key in st.session_state.get("manual_uploaded_assets", {}):
                            if st.button("Clear dropped asset", key=f"clear_drop_{_norm_key(row_key)}_{i}"):
                                st.session_state["manual_uploaded_assets"].pop(row_key, None)
                                try:
                                    st.rerun()
                                except AttributeError:
                                    st.experimental_rerun()

        # ── Video playback strip (always shown when videos are mapped) ──
        # Videos cannot be embedded in the Plotly chart, so they are shown here.
        # Always use the bar-aligned column layout so each video sits under its bar.
        if has_any_video:
            actual_creatives_shown = len(chart_df)
            if actual_creatives_shown > 0:
                cols = _build_strip_cols(actual_creatives_shown)
                for i, (_, r) in enumerate(chart_df.iterrows()):
                    _, auto_asset = _resolve_row_asset_data(i, r)
                    with cols[i]:
                        if auto_asset is not None and auto_asset[1] == 'video':
                            asset_bytes, _, file_ext = auto_asset
                            st.video(asset_bytes, format=f"video/{file_ext}", start_time=0)
                        else:
                            st.caption("*No image/video available*")

        st.markdown("**Chart Overlays**")
        col1, col2, col3 = st.columns([1, 1, 1])
        with col1:
            st.checkbox(
                "Overlay Advertiser Benchmark",
                value=show_advertiser_benchmark,
                help="Show advertiser benchmark line",
                key="show_advertiser_benchmark",
            )
        with col2:
            st.checkbox(
                "Overlay Category Benchmark",
                value=show_category_benchmark,
                help="Show category benchmark line",
                key="show_category_benchmark",
            )
        with col3:
            pass

        show_advertiser_benchmark = bool(st.session_state.get("show_advertiser_benchmark", False))
        show_category_benchmark = bool(st.session_state.get("show_category_benchmark", False))

        if show_advertiser_benchmark or show_category_benchmark:
            units = {"CTR": "%", "DPVR": "%", "Purchase_Rate": "%", "Promoted_ROAS": "$", "Total_ROAS": "$", "Total_DPVR": "%", "Total_Purchase_Rate": "%", "Subscription sign-ups": "#", "App subscription sign-ups": "#", "Cost per subscription": "$"}
            examples = {"CTR": "2.0", "DPVR": "1.5", "Purchase_Rate": "0.5", "Promoted_ROAS": "4.0", "Total_ROAS": "6.0", "Total_DPVR": "2.5", "Total_Purchase_Rate": "0.8", "Subscription sign-ups": "100", "App subscription sign-ups": "50", "Cost per subscription": "10.0"}
            if metric in units:
                bench_col1, bench_col2 = st.columns([1, 1])
                with bench_col1:
                    if show_advertiser_benchmark:
                        max_val = 10000.0 if metric in ["Subscription sign-ups", "App subscription sign-ups", "Cost per subscription"] else 100.0
                        st.number_input(
                            f"Advertiser Benchmark ({units[metric]})",
                            min_value=0.0,
                            max_value=max_val,
                            value=advertiser_benchmark,
                            step=0.1,
                            help="Enter advertiser benchmark value",
                            placeholder=f"e.g., {examples[metric]}",
                            key="advertiser_benchmark",
                        )
                with bench_col2:
                    if show_category_benchmark:
                        max_val = 10000.0 if metric in ["Subscription sign-ups", "App subscription sign-ups", "Cost per subscription"] else 100.0
                        st.number_input(
                            f"Category Benchmark ({units[metric]})",
                            min_value=0.0,
                            max_value=max_val,
                            value=category_benchmark,
                            step=0.1,
                            help="Enter category benchmark value",
                            placeholder=f"e.g., {examples[metric]}",
                            key="category_benchmark",
                        )

                legend_items = []
                if show_advertiser_benchmark:
                    legend_items.append('<span style="display: flex; align-items: center;"><span style="width: 32px; height: 0; border-top: 4px dotted orange; margin-right: 8px;"></span><span style="font-size: 15px;">Advertiser Benchmark</span></span>')
                if show_category_benchmark:
                    legend_items.append('<span style="display: flex; align-items: center;"><span style="width: 32px; height: 0; border-top: 4px dashed purple; margin-right: 8px;"></span><span style="font-size: 15px;">Category Benchmark</span></span>')

                if legend_items:
                    st.markdown(
                        f'<div style="display: flex; align-items: center; gap: 24px; margin-top: 8px;">{"" .join(legend_items)}</div>',
                        unsafe_allow_html=True,
                    )

        st.markdown("---")
    
    st.markdown("**Creative Performance Filters**")
    col1, col2, col3 = st.columns([2.0, 0.9, 1])
    with col1:
        st.multiselect(
            "Order",
            options=order_options,
            key="order_filter",
            help="Filter by order name or campaign ID",
            format_func=lambda x: x,
        )
    with col2:
        selected_metric_idx = metric_options.index(metric) if metric in metric_options else default_index
        st.selectbox(
            "Sort by KPI",
            metric_options,
            index=selected_metric_idx,
            key="metric_filter",
            format_func=lambda x: metric_labels.get(x, x),
        )
    with col3:
        st.number_input("Min Imps", min_value=0, value=min_imps, step=50, key="min_imps_filter")

    if has_date_cols:
        min_date = processed["Start_Date"].min()
        max_date = processed["End_Date"].max()
        if pd.isna(min_date) or pd.isna(max_date):
            st.info("⚠️ Some date values are missing in the data. Showing all data.")
        else:
            col1, col2, col3 = st.columns([1.0, 1.0, 1.9])
            with col1:
                st.date_input(
                    "From Date",
                    value=filter_start_date if filter_start_date is not None else min_date,
                    min_value=min_date,
                    max_value=max_date,
                    key="start_date_filter",
                    help="Filter ads that were live on or after this date",
                )
            with col2:
                st.date_input(
                    "To Date",
                    value=filter_end_date if filter_end_date is not None else max_date,
                    min_value=min_date,
                    max_value=max_date,
                    key="end_date_filter",
                    help="Filter ads that were live on or before this date",
                )
            with col3:
                st.write("")
                if st.button("Reset Dates", key="reset_dates"):
                    st.session_state.start_date_filter = min_date
                    st.session_state.end_date_filter = max_date
                    try:
                        st.rerun()
                    except AttributeError:
                        st.experimental_rerun()

            # Warn if the date range is inverted (From > To)
            _cur_start = st.session_state.get("start_date_filter")
            _cur_end = st.session_state.get("end_date_filter")
            if _cur_start is not None and _cur_end is not None:
                try:
                    if pd.Timestamp(_cur_start) > pd.Timestamp(_cur_end):
                        st.warning("⚠️ **From Date is after To Date** — no data will show. Swap the dates or click Reset Dates.")
                except Exception:
                    pass

    prev_identifier_filter = st.session_state.get("identifier_filter", [])
    st.multiselect(
        "Creative identifiers",
        options=identifier_options,
        default=identifier_options[1:] if "Select All" in prev_identifier_filter else [v for v in prev_identifier_filter if v in identifier_options],
        key="identifier_filter",
    )



    # ==============================
    # 3. GRAPH DESIGN OPTIONS
    # ==============================
    st.markdown("---")
    with st.expander("🎨 GRAPH DESIGN OPTIONS", expanded=False):
        st.markdown("Customize the appearance of your chart and images. Changes will update dynamically.")
        
        # Chart controls
        st.markdown("**Chart Appearance**")
        col1, col2, col3 = st.columns([1, 1, 1])
        
        with col1:
            if total_creatives > 1:
                num_to_show_new = st.slider(
                    "Creatives to show in chart",
                    min_value=1,
                    max_value=total_creatives,
                    value=num_to_show,
                    step=1,
                    key="num_to_show_slider"
                )
            else:
                # When only one creative exists, use a fixed value rather than a slider (Streamlit slider requires min < max)
                st.write("Creatives to show in chart")
                num_to_show_new = 1
                st.caption("Only 1 creative available")
        
        with col2:
            bar_width_new = st.slider(
                "Bar Width", 
                min_value=0.1, 
                max_value=1.0, 
                value=bar_width, 
                step=0.1,
                help="Adjust the width of the bars in the chart",
                key="bar_width_slider"
            )
        
        with col3:
            st.markdown("**Bar Color**")
            # Create sub-columns for color picker and button side by side
            subcol1, subcol2, subcol3 = st.columns([0.12, 0.22, 0.66])
            with subcol1:
                # Store temporary color selection
                temp_color = st.color_picker(
                    "Color",
                    value=bar_color,
                    help="Click the colored box to open the color picker",
                    key="temp_bar_color_picker",
                    label_visibility="collapsed",
                )
            with subcol2:
                # Apply Color button - positioned to the right of color picker
                if st.button("Apply Color", key="apply_color_btn", help="Click to apply the selected color to the chart"):
                    st.session_state["bar_color_picker"] = temp_color
                    try:
                        st.rerun()
                    except AttributeError:
                        # For older Streamlit versions
                        st.experimental_rerun()
            bar_color_new = st.session_state.get("bar_color_picker", bar_color)
        
        st.markdown("**Text Size**")
        col1, col2, col3 = st.columns([1, 1, 1])
        
        with col1:
            text_size_new = st.slider(
                "X-Axis Label Size",
                min_value=8,
                max_value=24,
                value=text_size,
                step=1,
                help="Adjust the font size of creative names under the chart",
                key="text_size_slider"
            )
        
        # Image controls
        st.markdown("**Image Appearance**")
        st.slider(
            "Image Size (%)",
            min_value=70,
            max_value=130,
            value=100,
            step=5,
            key="image_size_scale",
            help="Scale embedded and under-bar image size relative to default",
        )

        # Tip for users about automatic updates
        if num_to_show_new != num_to_show or bar_width_new != bar_width or bar_color_new != bar_color:
            st.info("💡 **Tip:** The chart and images above will update automatically as you adjust these settings. Scroll up to see the changes!")

    # ==============================
    # Full Table
    # ==============================
    # Initialize session state for edited creative names
    if 'edited_creative_names' not in st.session_state:
        st.session_state.edited_creative_names = {}
    
    # Create display table with proper column names
    table_df = sorted_df.copy()

    # Rename columns for display
    table_df = table_df.rename(columns={
        "Group_Key": "Creative Identifier",
        "Full_Creative_Name": "Full Creative Name",
        "Purchase_Rate": "Purchase Rate"
    })

    # Same product-tag prefixing used in the chart — keeps labels consistent
    # between the chart and the Creative Performance Summary table. Only applies
    # when the table contains both tagged (PG / FTV Feature Rotator) AND
    # untagged rows.
    if "Product_Tag" in table_df.columns:
        _t_tags = table_df["Product_Tag"].astype(str).str.strip()
        if (_t_tags != "").any() and (_t_tags == "").any():
            table_df["Creative Identifier"] = table_df.apply(
                lambda r: (
                    f"{str(r.get('Product_Tag') or '').strip()} · {r['Creative Identifier']}"
                    if str(r.get('Product_Tag') or '').strip() else r['Creative Identifier']
                ),
                axis=1,
            )
    
    # Re-aggregate if any creative identifiers have been edited to the same name
    if st.session_state.edited_creative_names:
        # Apply edited names to create a grouping column
        table_df["Edited_Identifier"] = table_df["Creative Identifier"].apply(
            lambda x: st.session_state.edited_creative_names.get(x, x)
        )
        
        # Check if there are duplicate edited names (need to aggregate)
        if table_df["Edited_Identifier"].duplicated().any():
            # Define aggregation functions for each column
            agg_dict = {
                "Impressions": "sum",
                "Click-throughs": "sum",
                "DPV": "sum",
                "Purchases": "sum",
                "Full Creative Name": "first",  # Take first creative name
            }
            
            # Add optional columns to aggregation
            if "Sales_USD" in table_df.columns:
                agg_dict["Sales_USD"] = "sum"
            if "Total_Sales_USD" in table_df.columns:
                agg_dict["Total_Sales_USD"] = "sum"
            if "Total_Cost" in table_df.columns:
                agg_dict["Total_Cost"] = "sum"
            if "Total_DPV" in table_df.columns:
                agg_dict["Total_DPV"] = "sum"
            if "Total_Purchases" in table_df.columns:
                agg_dict["Total_Purchases"] = "sum"
            if "Subscription sign-ups" in table_df.columns:
                agg_dict["Subscription sign-ups"] = "sum"
            if "App subscription sign-ups" in table_df.columns:
                agg_dict["App subscription sign-ups"] = "sum"
            if "_vcr_video_start" in table_df.columns:
                agg_dict["_vcr_video_start"] = "sum"
            if "_vcr_video_complete" in table_df.columns:
                agg_dict["_vcr_video_complete"] = "sum"
            
            # Add video columns if present
            def norm_col(col):
                return col.strip().lower().replace("-", "").replace(" ", "")
            normed_cols = {norm_col(c): c for c in table_df.columns}
            video_started_col, video_completed_col = _get_video_metric_columns(normed_cols)
            if video_started_col and video_started_col in table_df.columns:
                agg_dict[video_started_col] = "sum"
            if video_completed_col and video_completed_col in table_df.columns:
                agg_dict[video_completed_col] = "sum"
            
            # Aggregate by edited identifier
            table_df = table_df.groupby("Edited_Identifier", as_index=False).agg(agg_dict)
            
            # Recalculate rates after aggregation
            denom = table_df["Impressions"].replace(0, 1)
            table_df["CTR"] = (table_df["Click-throughs"] / denom * 100).round(4)
            table_df["DPVR"] = (table_df["DPV"] / denom * 100).round(4)
            table_df["Purchase Rate"] = (table_df["Purchases"] / denom * 100).round(4)
            
            # Recalculate VCR if video columns exist
            if "_vcr_video_start" in table_df.columns and "_vcr_video_complete" in table_df.columns:
                started = pd.to_numeric(table_df["_vcr_video_start"], errors="coerce").replace(0, 1)
                completed = pd.to_numeric(table_df["_vcr_video_complete"], errors="coerce")
                table_df["VCR"] = (completed / started * 100).round(4)
            elif video_started_col and video_completed_col and video_started_col in table_df.columns and video_completed_col in table_df.columns:
                started = pd.to_numeric(table_df[video_started_col], errors="coerce").replace(0, 1)
                completed = pd.to_numeric(table_df[video_completed_col], errors="coerce")
                table_df["VCR"] = (completed / started * 100).round(4)
            
            # Recalculate ROAS if present
            if "Total_Cost" in table_df.columns:
                cost_denom = table_df["Total_Cost"].replace(0, 0.01)
                if "Sales_USD" in table_df.columns:
                    table_df["Promoted_ROAS"] = (table_df["Sales_USD"] / cost_denom).round(4)
                if "Total_Sales_USD" in table_df.columns:
                    table_df["Total_ROAS"] = (table_df["Total_Sales_USD"] / cost_denom).round(4)
            
            # Recalculate total rates if present
            if "Total_DPV" in table_df.columns:
                table_df["Total_DPVR"] = (table_df["Total_DPV"] / denom * 100).round(4)
            if "Total_Purchases" in table_df.columns:
                table_df["Total_Purchase_Rate"] = (table_df["Total_Purchases"] / denom * 100).round(4)
            
            # Use edited identifier as the new Creative Identifier
            table_df["Creative Identifier"] = table_df["Edited_Identifier"]
        
        # Drop the temporary column
        table_df = table_df.drop(columns=["Edited_Identifier"], errors="ignore")
    
    disp_cols = ["Creative Identifier", "Impressions", "Click-throughs",
                 "CTR", "DPV", "DPVR", "Purchases", "Purchase Rate"]
    
    # Add financial and ROAS columns if present
    if "Sales_USD" in table_df.columns:
        disp_cols.append("Sales_USD")
    if "Total_Sales_USD" in table_df.columns:
        disp_cols.append("Total_Sales_USD")
    if "Total_Cost" in table_df.columns:
        disp_cols.append("Total_Cost")
    if "Promoted_ROAS" in table_df.columns:
        disp_cols.append("Promoted_ROAS")
    if "Total_ROAS" in table_df.columns:
        disp_cols.append("Total_ROAS")
    # Add total DPV / purchases and total-rate columns if present
    if "Total_DPV" in table_df.columns:
        disp_cols.append("Total_DPV")
    if "Total_DPVR" in table_df.columns:
        disp_cols.append("Total_DPVR")
    if "Total_Purchases" in table_df.columns:
        disp_cols.append("Total_Purchases")
    if "Total_Purchase_Rate" in table_df.columns:
        disp_cols.append("Total_Purchase_Rate")
    # Add subscription columns if present
    if "Subscription sign-ups" in table_df.columns:
        disp_cols.append("Subscription sign-ups")
    if "App subscription sign-ups" in table_df.columns:
        disp_cols.append("App subscription sign-ups")

    with st.expander("📋 EDIT CREATIVE IDENTIFIERS", expanded=False):
        st.markdown("Ability to edit creative identifiers to consolidate or correct names. Changes will be reflected in the aggregated graph and raw data below.")
        st.markdown("**💡 Tip:** Edit creative identifiers below. When you give multiple creatives the same name, they will be automatically aggregated together.")
        
        # Create editable interface for creative identifiers (use original sorted_df to show all creatives before aggregation)
        st.markdown("**Edit Creative Identifiers:**")
        original_creatives = sorted_df["Group_Key"].unique().tolist()
        col_count = min(3, len(original_creatives))
        if col_count > 0:
            cols = st.columns(col_count)
            
            for idx, original_name in enumerate(original_creatives):
                with cols[idx % col_count]:
                    # Use original name as key, but display edited name if available
                    current_name = st.session_state.edited_creative_names.get(original_name, original_name)
                    
                    edited_name = st.text_input(
                        f"Creative {idx + 1}:",
                        value=current_name,
                        key=f"edit_creative_{idx}_{original_name}",
                        help=f"Original: {original_name}"
                    )
                    
                    # Update session state if name was changed
                    if edited_name != current_name:
                        st.session_state.edited_creative_names[original_name] = edited_name

                        # If this creative identifier was currently selected in
                        # the main "Creative identifiers" filter, stash the
                        # rename so the next rerun can apply it BEFORE the
                        # widget is rendered (we can't write to the widget's
                        # session_state key after it's instantiated).
                        _filter_key = "identifier_filter"
                        _current_filter = st.session_state.get(_filter_key, [])
                        if isinstance(_current_filter, list) and current_name in _current_filter:
                            if "_pending_identifier_renames" not in st.session_state:
                                st.session_state["_pending_identifier_renames"] = {}
                            st.session_state["_pending_identifier_renames"][current_name] = edited_name

                        st.rerun()
    
    # Note: Creative Identifier column already has edited names applied from re-aggregation above

    # Calculate totals
    total_impressions = table_df["Impressions"].sum()
    total_clicks = table_df["Click-throughs"].sum()
    total_dpv = table_df["DPV"].sum()
    total_purchases = table_df["Purchases"].sum()
    total_total_dpv = table_df["Total_DPV"].sum() if "Total_DPV" in table_df.columns else 0
    total_total_purchases = table_df["Total_Purchases"].sum() if "Total_Purchases" in table_df.columns else 0
    
    # Calculate overall rates
    overall_ctr = (total_clicks / total_impressions * 100) if total_impressions > 0 else 0
    overall_dpvr = (total_dpv / total_impressions * 100) if total_impressions > 0 else 0
    overall_pr = (total_purchases / total_impressions * 100) if total_impressions > 0 else 0
    overall_total_dpvr = (total_total_dpv / total_impressions * 100) if total_impressions > 0 else 0
    overall_total_pr = (total_total_purchases / total_impressions * 100) if total_impressions > 0 else 0
    
    # Create totals row
    totals_row = {
        "Creative Identifier": "📊 TOTALS",
        "Impressions": total_impressions,
        "Click-throughs": total_clicks,
        "CTR": overall_ctr,
        "DPV": total_dpv,
        "DPVR": overall_dpvr,
        "Purchases": total_purchases,
        "Purchase Rate": overall_pr
    }
    
    # Add financial metrics to totals if they exist
    if any(c in table_df.columns for c in ["Sales_USD", "Total_Sales_USD", "Total_Cost"]):
        total_sales = table_df["Sales_USD"].sum() if "Sales_USD" in table_df.columns else 0.0
        total_total_sales = table_df["Total_Sales_USD"].sum() if "Total_Sales_USD" in table_df.columns else 0.0
        total_cost = table_df["Total_Cost"].sum() if "Total_Cost" in table_df.columns else 0.0

        overall_promoted_roas = (total_sales / total_cost) if total_cost > 0 else 0.0
        overall_total_roas = (total_total_sales / total_cost) if total_cost > 0 else 0.0

        if "Sales_USD" in table_df.columns:
            totals_row["Sales_USD"] = total_sales
        if "Total_Sales_USD" in table_df.columns:
            totals_row["Total_Sales_USD"] = total_total_sales
        if "Total_Cost" in table_df.columns:
            totals_row["Total_Cost"] = total_cost
        if "Promoted_ROAS" in table_df.columns:
            totals_row["Promoted_ROAS"] = overall_promoted_roas
        if "Total_ROAS" in table_df.columns:
            totals_row["Total_ROAS"] = overall_total_roas
        # Add total DPV / purchase totals and rates if available
        if "Total_DPV" in table_df.columns:
            totals_row["Total_DPV"] = total_total_dpv
        if "Total_DPVR" in table_df.columns:
            totals_row["Total_DPVR"] = overall_total_dpvr
        if "Total_Purchases" in table_df.columns:
            totals_row["Total_Purchases"] = total_total_purchases
        if "Total_Purchase_Rate" in table_df.columns:
            totals_row["Total_Purchase_Rate"] = overall_total_pr
    
    # Add totals row to table
    table_with_totals = pd.concat([table_df, pd.DataFrame([totals_row])], ignore_index=True)

    # Display table without thumbnail functionality
    format_dict = {
        "CTR": "{:.4f}%", "DPVR": "{:.4f}%", "Purchase Rate": "{:.4f}%",
        "Impressions": "{:,.0f}", "Click-throughs": "{:,.0f}",
        "DPV": "{:,.0f}", "Purchases": "{:,.0f}",
        "Sales_USD": "${:,.2f}", "Total_Sales_USD": "${:,.2f}", "Total_Cost": "${:,.2f}",
        "Promoted_ROAS": "${:.2f}", "Total_ROAS": "${:.2f}",
        "Total_DPV": "{:,.0f}", "Total_Purchases": "{:,.0f}",
        "Total_DPVR": "{:.4f}%", "Total_Purchase_Rate": "{:.4f}%",
        "Subscription sign-ups": "{:,.0f}", "App subscription sign-ups": "{:,.0f}",
    }
    
    # Style the table with totals row highlighted
    styled = table_with_totals[disp_cols].style.format(format_dict).set_properties(**{
        'text-align': 'left', 'font-size': '14px'
    })
    
    # Highlight the totals row (last row)
    styled = styled.apply(lambda x: ['background-color: #f0f8ff; font-weight: bold' if x.name == len(table_with_totals) - 1 else '' for i in x], axis=1)
    
    st.markdown("**Creative Performance Summary**")
    st.dataframe(styled, use_container_width=True)

    # CSV download (use original column names)
    csv_data = sorted_df.to_csv(index=False)
    st.download_button("Download Full Results CSV", csv_data, "creative_analytics.csv", "text/csv")

    # ==============================
    # TOPLINE PERFORMANCE CHART
    # ==============================
    st.markdown("---")
    st.subheader("📊 TOPLINE PERFORMANCE")
    st.markdown("Campaign performance overview. Impressions display as bars by default. Add KPI overlays via the options below; all rate KPIs render as line overlays.")

    # Strict detection: only consider a true per-day "Date" / "Report Date" /
    # "Day" column as a valid source for the topline chart. Substring matching
    # would wrongly pick up "Interval Start Date" — which is NOT daily data and
    # produces a misleading chart that just shows each creative's flight as a
    # single bar.
    _topline_date_candidates = ("date", "report date", "report_date", "day")
    _topline_date_col = None
    _proc_cols_lc = {c.lower(): c for c in processed.columns}
    for _cand in _topline_date_candidates:
        if _cand in _proc_cols_lc:
            _topline_date_col = _proc_cols_lc[_cand]
            break
    if _topline_date_col is None:
        # Prominent, action-oriented callout. The topline chart needs a per-day
        # 'Date' column, which only exists when the DSP report is downloaded
        # with TIME UNIT = Daily. Reports using only Interval Start / Interval
        # End (i.e., Total or Weekly/Monthly time units) cannot produce a
        # granular trend chart.
        st.warning("⚠️ Re-download the DSP report with **time unit set to DAILY** to view the topline chart. Note: other charts still work without daily data included.")
    else:
        _TOPLINE_VOLUME_KPIS = ["Impressions"]
        _TOPLINE_RATE_KPIS   = ["CTR", "DPVR", "Purchase_Rate", "Promoted_ROAS",
                                 "Total_ROAS", "Total_DPVR", "Total_Purchase_Rate",
                                 "VCR", "Promoted_%_NTB", "Total_%_NTB",
                                 "Appstore_Open_Rate", "Cost per subscription"]
        _TOPLINE_LABELS = {
            "Impressions": "Impressions", "CTR": "CTR", "DPVR": "Promoted DPVR",
            "Purchase_Rate": "Purchase Rate", "Promoted_ROAS": "Promoted ROAS",
            "Total_ROAS": "Total ROAS", "Total_DPVR": "Total DPVR",
            "Total_Purchase_Rate": "Total Purchase Rate", "VCR": "VCR",
            "Promoted_%_NTB": "% NTB (Promoted)", "Total_%_NTB": "% NTB (Total)",
            "Appstore_Open_Rate": "Appstore Open Rate", "Cost per subscription": "Cost/Sub",
        }
        _TOPLINE_COLORS = [
            "#1f77b4","#ff7f0e","#2ca02c","#d62728","#9467bd",
            "#8c564b","#e377c2","#7f7f7f","#bcbd22","#17becf",
        ]
        _TOPLINE_RATE_REQUIRES = {
            "CTR":                  {"num": "Click-throughs",        "den": "Impressions",          "scale": 100},
            "DPVR":                 {"num": "DPV",                   "den": "Impressions",          "scale": 100},
            "Purchase_Rate":        {"num": "Purchases",             "den": "Impressions",          "scale": 100},
            "Promoted_ROAS":        {"num": "Sales_USD",             "den": "Total_Cost",           "scale": 1},
            "Total_ROAS":           {"num": "Total_Sales_USD",       "den": "Total_Cost",           "scale": 1},
            "Total_DPVR":           {"num": "Total_DPV",             "den": "Impressions",          "scale": 100},
            "Total_Purchase_Rate":  {"num": "Total_Purchases",       "den": "Impressions",          "scale": 100},
            "VCR":                  {"num": "_vcr_video_complete",   "den": "_vcr_video_start",     "scale": 100},
            "Appstore_Open_Rate":   {"num": "Appstore Opens",        "den": "Impressions",          "scale": 100},
            "Cost per subscription":{"num": "Total_Cost",           "den": "Subscription sign-ups","scale": 1},
        }
        _vol_kpis_avail = [k for k in _TOPLINE_VOLUME_KPIS
                           if k in processed.columns
                           and pd.to_numeric(processed[k], errors="coerce").sum() > 0]
        _rate_kpis_avail = []
        for _rk in _TOPLINE_RATE_KPIS:
            if _rk in _TOPLINE_RATE_REQUIRES:
                _req = _TOPLINE_RATE_REQUIRES[_rk]
                if (_req["num"] in processed.columns and _req["den"] in processed.columns
                        and pd.to_numeric(processed[_req["num"]], errors="coerce").sum() > 0):
                    _rate_kpis_avail.append(_rk)
        _all_topline_kpis = _vol_kpis_avail + _rate_kpis_avail
        if not _all_topline_kpis:
            st.info("No numeric KPI data found for topline chart.")
        else:
            if "tl_slot_0" not in st.session_state and "Impressions" in _all_topline_kpis:
                st.session_state["tl_slot_0"] = "Impressions"
            _tl_f1, _tl_f2 = st.columns([2, 1.2])
            with _tl_f1:
                # Seed session state once, then let the widget's key= own the value.
                if "tl_order_filter" not in st.session_state:
                    st.session_state["tl_order_filter"] = ["All Orders"]

                # Callback: auto-deselect "All Orders" when specific orders are picked.
                # Runs BEFORE the widget returns → session_state writes are safe.
                def _dedupe_all_orders_tl():
                    _v = st.session_state.get("tl_order_filter", [])
                    if isinstance(_v, list) and "All Orders" in _v and len(_v) > 1:
                        st.session_state["tl_order_filter"] = [o for o in _v if o != "All Orders"]

                _tl_orders = st.multiselect(
                    "Filter by Order",
                    options=order_options,
                    key="tl_order_filter",
                    on_change=_dedupe_all_orders_tl,
                )
                if not _tl_orders: _tl_orders = ["All Orders"]
                # Sanitize local list for this run (callback handles session_state).
                if "All Orders" in _tl_orders and len(_tl_orders) > 1:
                    _tl_orders = [o for o in _tl_orders if o != "All Orders"]
            with _tl_f2:
                if "tl_granularity" not in st.session_state:
                    st.session_state["tl_granularity"] = "Best Fit"
                _tl_granularity = st.selectbox("Granularity", ["Best Fit", "Daily", "Weekly", "Monthly"], key="tl_granularity")

            # Date filter row — parallel to the Order Performance chart's filter.
            # Uses the topline's own "Date" column (per-day) for min/max, falling
            # back to Start/End dates only as a last resort.
            _tl_date_min = None
            _tl_date_max = None
            try:
                _tl_dates_all = pd.to_datetime(processed[_topline_date_col], errors="coerce")
                _tl_date_min = _tl_dates_all.min()
                _tl_date_max = _tl_dates_all.max()
            except Exception:
                pass
            if pd.isna(_tl_date_min) or pd.isna(_tl_date_max):
                if has_date_cols:
                    _tl_date_min = processed["Start_Date"].min()
                    _tl_date_max = processed["End_Date"].max()

            if _tl_date_min is not None and _tl_date_max is not None and not pd.isna(_tl_date_min) and not pd.isna(_tl_date_max):
                # Clamp stale session-state values so a previous upload doesn't
                # accidentally filter out the new file's entire date range.
                for _k, _default in (("tl_start_date_filter", _tl_date_min), ("tl_end_date_filter", _tl_date_max)):
                    _saved = st.session_state.get(_k)
                    if _saved is not None:
                        try:
                            _saved_ts = pd.Timestamp(_saved)
                            if _saved_ts < pd.Timestamp(_tl_date_min) or _saved_ts > pd.Timestamp(_tl_date_max):
                                st.session_state[_k] = _default
                        except Exception:
                            st.session_state[_k] = _default
                    else:
                        st.session_state[_k] = _default

                _tl_d1, _tl_d2, _tl_d3 = st.columns([1.0, 1.0, 1.9])
                with _tl_d1:
                    st.date_input(
                        "From Date",
                        min_value=_tl_date_min,
                        max_value=_tl_date_max,
                        key="tl_start_date_filter",
                        help="Filter topline chart to dates on or after this date",
                    )
                with _tl_d2:
                    st.date_input(
                        "To Date",
                        min_value=_tl_date_min,
                        max_value=_tl_date_max,
                        key="tl_end_date_filter",
                        help="Filter topline chart to dates on or before this date",
                    )
                with _tl_d3:
                    st.write("")
                    if st.button("Reset Topline Dates", key="reset_tl_dates"):
                        st.session_state.tl_start_date_filter = _tl_date_min
                        st.session_state.tl_end_date_filter = _tl_date_max
                        try:
                            st.rerun()
                        except AttributeError:
                            st.experimental_rerun()

                # Warn if the date range is inverted (From > To)
                _tl_cur_start = st.session_state.get("tl_start_date_filter")
                _tl_cur_end = st.session_state.get("tl_end_date_filter")
                if _tl_cur_start is not None and _tl_cur_end is not None:
                    try:
                        if pd.Timestamp(_tl_cur_start) > pd.Timestamp(_tl_cur_end):
                            st.warning("⚠️ **From Date is after To Date** — no data will show. Swap the dates or click Reset Topline Dates.")
                    except Exception:
                        pass
            st.markdown("<div style='font-size:13px;color:#555;margin-bottom:4px;'>Select KPIs to add as line overlays on the chart:</div>", unsafe_allow_html=True)
            _BLANK_OPT = "\u2014 select KPI \u2014"
            _card_cols = st.columns(8)
            for _ci, _col in enumerate(_card_cols):
                _color = _TOPLINE_COLORS[_ci % len(_TOPLINE_COLORS)]
                _opts = [_BLANK_OPT] + _all_topline_kpis

                # Seed session state BEFORE the widget renders, then omit `index=`.
                # Passing both `index=` and `key=` when session_state already has
                # the key throws "widget created with default value but also had
                # its value set via the Session State API".
                _slot_key = f"tl_slot_{_ci}"
                _saved = st.session_state.get(_slot_key, _BLANK_OPT)
                if _saved not in _opts:
                    # A previous upload may have saved a KPI that isn't valid for
                    # this upload's columns — reset it before rendering.
                    st.session_state[_slot_key] = _BLANK_OPT
                elif _slot_key not in st.session_state:
                    st.session_state[_slot_key] = _BLANK_OPT

                with _col:
                    st.markdown(f"<div style='font-size:12px;font-weight:600;color:{_color};border-left:4px solid {_color};padding-left:6px;margin-bottom:2px;'>Overlay {_ci+1}</div>", unsafe_allow_html=True)
                    st.selectbox(
                        f"overlay_{_ci}",
                        options=_opts,
                        format_func=lambda x: x if x == _BLANK_OPT else _TOPLINE_LABELS.get(x, x),
                        key=_slot_key,
                        label_visibility="collapsed",
                    )
            _active_selections = {_ci: st.session_state[f"tl_slot_{_ci}"] for _ci in range(8)
                if st.session_state.get(f"tl_slot_{_ci}", _BLANK_OPT) != _BLANK_OPT}
            _tl_df = processed.copy()
            if "Order_ID" in _tl_df.columns and "All Orders" not in _tl_orders:
                _tl_df = _tl_df[_tl_df["Order_ID"].isin(_tl_orders)]
            _tl_vol_cols = [c for c in ["Impressions","Click-throughs","DPV","Purchases",
                "Sales_USD","Total_Sales_USD","Total_Cost","Total_DPV","Total_Purchases",
                "Subscription sign-ups","App subscription sign-ups","Appstore Opens",
                "_vcr_video_start","_vcr_video_complete"] if c in _tl_df.columns]
            for _vc in _tl_vol_cols:
                _tl_df[_vc] = pd.to_numeric(_tl_df[_vc], errors="coerce").fillna(0)
            _tl_df["_date"] = pd.to_datetime(_tl_df[_topline_date_col], errors="coerce").dt.normalize()
            _tl_df = _tl_df.dropna(subset=["_date"])

            # Apply the topline date filter (from the From/To inputs above).
            _tl_fs = st.session_state.get("tl_start_date_filter")
            _tl_fe = st.session_state.get("tl_end_date_filter")
            if _tl_fs is not None and _tl_fe is not None:
                try:
                    _tl_fs_ts = pd.Timestamp(_tl_fs)
                    _tl_fe_ts = pd.Timestamp(_tl_fe)
                    _tl_df = _tl_df[(_tl_df["_date"] >= _tl_fs_ts) & (_tl_df["_date"] <= _tl_fe_ts)]
                except Exception:
                    pass
            if _tl_df.empty:
                st.info("No data rows with a valid date found for the topline chart.")
            else:
                _date_range_days = max(1, (_tl_df["_date"].max() - _tl_df["_date"].min()).days)
                _gran = st.session_state.get("tl_granularity", "Best Fit")
                if _gran == "Best Fit":
                    _gran_actual = "D" if _date_range_days <= 31 else ("W" if _date_range_days <= 180 else "MS")
                elif _gran == "Daily": _gran_actual = "D"
                elif _gran == "Weekly": _gran_actual = "W"
                else: _gran_actual = "MS"
                _tl_df["_period"] = (
                    _tl_df["_date"]
                    .dt.to_period("D" if _gran_actual=="D" else ("W" if _gran_actual=="W" else "M"))
                    .dt.to_timestamp().dt.floor("D"))
                _tl_grouped = _tl_df.groupby("_period")[_tl_vol_cols].sum(numeric_only=True).reset_index()
                _tl_grouped = _tl_grouped.sort_values("_period").reset_index(drop=True)
                if _gran_actual == "D": _tl_grouped["_x"] = _tl_grouped["_period"].dt.strftime("%b %d, %Y")
                elif _gran_actual == "W": _tl_grouped["_x"] = _tl_grouped["_period"].dt.strftime("Wk of %b %d, %Y")
                else: _tl_grouped["_x"] = _tl_grouped["_period"].dt.strftime("%b %Y")
                for _rk, _req in _TOPLINE_RATE_REQUIRES.items():
                    _n, _d, _s = _req["num"], _req["den"], _req["scale"]
                    if _n in _tl_grouped.columns and _d in _tl_grouped.columns:
                        _safe_den = _tl_grouped[_d].replace(0, 0.000001 if _s==1 else 1)
                        _tl_grouped[_rk] = (_tl_grouped[_n] / _safe_den * _s).round(4)
                _active_layers = [(_ci, _k) for _ci, _k in _active_selections.items() if _k in _tl_grouped.columns]
                if not _active_layers:
                    st.info("Select one or more KPIs from the dropdowns above to populate the chart.")
                else:
                    _bar_kpis_active  = [(ci, k) for ci, k in _active_layers if k in _TOPLINE_VOLUME_KPIS]
                    _line_kpis_active = [(ci, k) for ci, k in _active_layers if k in _TOPLINE_RATE_KPIS]
                    _n_y_axes = 1 + (1 if _line_kpis_active else 0)
                    _tl_fig = make_subplots(specs=[[{"secondary_y": _n_y_axes > 1}]])
                    for _ci, _k in _bar_kpis_active:
                        _c = _TOPLINE_COLORS[_ci % len(_TOPLINE_COLORS)]
                        _tl_fig.add_trace(go.Bar(x=_tl_grouped["_x"], y=_tl_grouped[_k],
                            name=_TOPLINE_LABELS.get(_k,_k), marker_color=_c, opacity=0.8,
                            hovertemplate=f"<b>{_TOPLINE_LABELS.get(_k,_k)}</b><br>%{{x}}: %{{y:,.0f}}<extra></extra>",
                        ), secondary_y=False)
                    for _ci, _k in _line_kpis_active:
                        _c = _TOPLINE_COLORS[_ci % len(_TOPLINE_COLORS)]
                        _tl_fig.add_trace(go.Scatter(x=_tl_grouped["_x"], y=_tl_grouped[_k],
                            name=_TOPLINE_LABELS.get(_k,_k), mode="lines+markers",
                            line=dict(color=_c, width=2), marker=dict(size=5),
                            hovertemplate=f"<b>{_TOPLINE_LABELS.get(_k,_k)}</b><br>%{{x}}: %{{y:.4f}}<extra></extra>",
                        ), secondary_y=(_n_y_axes > 1))
                    _tl_fig.update_layout(height=420, margin=dict(l=60,r=60,t=30,b=60),
                        legend=dict(orientation="h",yanchor="bottom",y=1.02,xanchor="right",x=1),
                        hovermode="x unified", plot_bgcolor="white",
                        xaxis=dict(showgrid=False, title="", tickangle=-45 if len(_tl_grouped)>6 else 0),
                        barmode="group")
                    _tl_fig.update_yaxes(showgrid=True, gridcolor="#eeeeee", secondary_y=False,
                                          title_text="Volume" if _bar_kpis_active else "")
                    if _n_y_axes > 1:
                        _tl_fig.update_yaxes(showgrid=False, secondary_y=True, title_text="Rate / Efficiency")
                    st.plotly_chart(_tl_fig, use_container_width=True)

    # ==============================
    # ORDER PERFORMANCE CHART
    # ==============================
    if "Order_ID" in processed.columns:
        st.markdown("---")
        st.subheader("📈 ORDER PERFORMANCE")
        
        # Dedicated filters for order analysis
        st.markdown("**Compare the performance of each order. Filter by date and/or key KPI.**")
        col1, col2 = st.columns([2.1, 0.9])
        
        with col1:
            # Callback: auto-deselect "All Orders" when specific orders are picked.
            # Runs BEFORE the widget's value is finalized, so session_state writes are safe.
            def _dedupe_all_orders_order_analysis():
                _v = st.session_state.get("order_analysis_order_filter", [])
                if isinstance(_v, list) and "All Orders" in _v and len(_v) > 1:
                    st.session_state["order_analysis_order_filter"] = [o for o in _v if o != "All Orders"]

            # Order filter for order analysis - select which orders to include
            order_analysis_selected_orders_display = st.multiselect(
                "Orders to Compare",
                options=order_options,
                default=["All Orders"],  # Default to all orders
                key="order_analysis_order_filter",
                on_change=_dedupe_all_orders_order_analysis,
                help="Select which orders to include in the comparison"
            )
            
            # Use the selected labels directly — they already match Order_ID
            # in the data (composite "Name (ID: 12345)" format). Stripping the
            # (ID: ...) suffix would cause matching to fail and show "No order
            # data available" even when orders are selected.
            order_analysis_selected_orders = list(order_analysis_selected_orders_display)

            # The on_change callback handles "All Orders" deduplication before
            # the widget returns — local list is also sanitized here for this run.
            if "All Orders" in order_analysis_selected_orders and len(order_analysis_selected_orders) > 1:
                order_analysis_selected_orders = [o for o in order_analysis_selected_orders if o != "All Orders"]
        with col2:
            # Metric selection for order analysis
            order_metric = st.selectbox(
                "Sort by KPI",
                metric_options,
                index=default_index,
                key="order_metric_filter",
                format_func=lambda x: metric_labels.get(x, x)
            )
        
        # Reset button on its own row
        col1, col2, col3 = st.columns([1, 1, 1])
        with col1:
            if st.button("Reset Order Filters", key="reset_order_filters"):
                st.session_state.order_analysis_order_filter = ["All Orders"]
                # Fall back to first available metric if CTR isn't present
                st.session_state.order_metric_filter = "CTR" if "CTR" in metric_options else (metric_options[0] if metric_options else "CTR")
                if has_date_cols:
                    st.session_state.order_start_date_filter = processed["Start_Date"].min()
                    st.session_state.order_end_date_filter = processed["End_Date"].max()
                try:
                    st.rerun()
                except AttributeError:
                    st.experimental_rerun()
        
        # Time period filter for order analysis (if date columns exist)
        if has_date_cols:
            col1, col2 = st.columns([1.0, 1.0])
            
            min_date = processed["Start_Date"].min()
            max_date = processed["End_Date"].max()
            
            if not pd.isna(min_date) and not pd.isna(max_date):
                with col1:
                    order_filter_start_date = st.date_input(
                        "From Date",
                        value=min_date,
                        min_value=min_date,
                        max_value=max_date,
                        key="order_start_date_filter",
                        help="Filter data from this date"
                    )
                with col2:
                    order_filter_end_date = st.date_input(
                        "To Date",
                        value=max_date,
                        min_value=min_date,
                        max_value=max_date,
                        key="order_end_date_filter",
                        help="Filter data to this date"
                    )

                # Warn if the date range is inverted (From > To)
                if order_filter_start_date is not None and order_filter_end_date is not None:
                    try:
                        if pd.Timestamp(order_filter_start_date) > pd.Timestamp(order_filter_end_date):
                            st.warning("⚠️ **From Date is after To Date** — no data will show. Swap the dates or click Reset Order Filters.")
                    except Exception:
                        pass
            else:
                order_filter_start_date = None
                order_filter_end_date = None
        
        # Apply order-specific filters
        order_filtered_data = processed.copy()
        
        # Apply date filter
        if has_date_cols and 'order_filter_start_date' in locals() and 'order_filter_end_date' in locals() and order_filter_start_date and order_filter_end_date:
            order_filter_start_dt = pd.Timestamp(order_filter_start_date)
            order_filter_end_dt = pd.Timestamp(order_filter_end_date)
            
            order_filtered_data = order_filtered_data[
                (order_filtered_data["Start_Date"] <= order_filter_end_dt) & 
                (order_filtered_data["End_Date"] >= order_filter_start_dt)
            ]
        
        # Filter out empty Order_IDs
        order_filtered_data = order_filtered_data[order_filtered_data["Order_ID"].notna() & (order_filtered_data["Order_ID"] != "")]
        
        # Apply order selection filter
        if "All Orders" not in order_analysis_selected_orders:
            order_filtered_data = order_filtered_data[order_filtered_data["Order_ID"].isin(order_analysis_selected_orders)]
        
        # Aggregate by order
        if order_filtered_data.empty:
            st.info("ℹ️ No order data available with current filters.")
        else:
            order_agg = order_filtered_data.groupby("Order_ID").agg({
                "Impressions": "sum",
                "Click-throughs": "sum",
                "DPV": "sum",
                "Purchases": "sum"
            }).reset_index()
            
            # Calculate metrics
            order_agg["CTR"] = (order_agg["Click-throughs"] / order_agg["Impressions"]).replace([float('inf'), -float('inf')], 0).fillna(0)
            order_agg["DPVR"] = (order_agg["DPV"] / order_agg["Impressions"]).replace([float('inf'), -float('inf')], 0).fillna(0)
            order_agg["Purchase_Rate"] = (order_agg["Purchases"] / order_agg["Impressions"]).replace([float('inf'), -float('inf')], 0).fillna(0)
            
            # Add ROAS if available
            if "Sales_USD" in order_filtered_data.columns and "Total_Cost" in order_filtered_data.columns:
                order_roas_agg = order_filtered_data.groupby("Order_ID").agg({
                    "Sales_USD": "sum",
                    "Total_Cost": "sum"
                }).reset_index()
                order_agg = order_agg.merge(order_roas_agg, on="Order_ID", how="left")
                order_agg["Promoted_ROAS"] = (order_agg["Sales_USD"] / order_agg["Total_Cost"]).replace([float('inf'), -float('inf')], 0).fillna(0)
            
            if "Total_Sales_USD" in order_filtered_data.columns and "Total_Cost" in order_filtered_data.columns:
                order_total_roas_agg = order_filtered_data.groupby("Order_ID").agg({
                    "Total_Sales_USD": "sum",
                    "Total_Cost": "sum"
                }).reset_index()
                order_agg = order_agg.merge(order_total_roas_agg, on="Order_ID", how="left", suffixes=('', '_y'))
                # Use Total_Cost from the merge if it exists, otherwise keep the original
                if "Total_Cost_y" in order_agg.columns:
                    order_agg["Total_Cost"] = order_agg["Total_Cost"].fillna(order_agg["Total_Cost_y"])
                    order_agg = order_agg.drop(columns=["Total_Cost_y"])
                order_agg["Total_ROAS"] = (order_agg["Total_Sales_USD"] / order_agg["Total_Cost"]).replace([float('inf'), -float('inf')], 0).fillna(0)
            
            # Add Total DPVR and Total Purchase Rate if available
            if "Total_DPV" in order_filtered_data.columns:
                order_total_dpv_agg = order_filtered_data.groupby("Order_ID").agg({"Total_DPV": "sum"}).reset_index()
                order_agg = order_agg.merge(order_total_dpv_agg, on="Order_ID", how="left")
                order_agg["Total_DPVR"] = (order_agg["Total_DPV"] / order_agg["Impressions"]).replace([float('inf'), -float('inf')], 0).fillna(0)
            
            if "Total_Purchases" in order_filtered_data.columns:
                order_total_purch_agg = order_filtered_data.groupby("Order_ID").agg({"Total_Purchases": "sum"}).reset_index()
                order_agg = order_agg.merge(order_total_purch_agg, on="Order_ID", how="left")
                order_agg["Total_Purchase_Rate"] = (order_agg["Total_Purchases"] / order_agg["Impressions"]).replace([float('inf'), -float('inf')], 0).fillna(0)
            
            # Remove any potential duplicates and sort by selected metric
            order_agg = order_agg.drop_duplicates(subset=['Order_ID']).reset_index(drop=True)
            
            if order_metric in order_agg.columns:
                order_agg = order_agg.sort_values(by=order_metric, ascending=False).reset_index(drop=True)
            
            # Create order performance chart
            if not order_agg.empty and len(order_agg) > 0 and order_metric in order_agg.columns:
                # Keep full order labels, but wrap them to avoid overlap.
                order_wrap_width = 20 if len(order_agg) >= 10 else 24 if len(order_agg) >= 6 else 30
                order_agg["Order_Display"] = order_agg["Order_ID"].astype(str).apply(
                    lambda s: "<br>".join(textwrap.wrap(s, width=order_wrap_width)) if s else ""
                )
                order_agg["Order_X"] = [f"order_{idx}" for idx in range(len(order_agg))]

                max_label_lines = int(order_agg["Order_Display"].astype(str).str.count("<br>").max() + 1) if len(order_agg) else 1
                order_bottom_margin = max(120, int(20 + (max_label_lines * 26)))
                
                # Format text based on metric type
                if order_metric in ["CTR", "DPVR", "Purchase_Rate", "Total_DPVR", "Total_Purchase_Rate"]:
                    text_template = "%{y:.4f}"
                else:
                    text_template = "%{y:.2f}"
                
                # Create figure with go.Bar for explicit control
                fig_order = go.Figure()
                fig_order.add_trace(go.Bar(
                    x=order_agg["Order_X"],
                    y=order_agg[order_metric],
                    text=order_agg[order_metric].round(4 if order_metric in ["CTR", "DPVR", "Purchase_Rate", "Total_DPVR", "Total_Purchase_Rate"] else 2),
                    texttemplate=text_template,
                    textposition="outside",
                    marker=dict(color=bar_color),
                    customdata=order_agg[["Order_ID"]].values,
                    hovertemplate="<b>%{customdata[0]}</b><br>" + metric_labels.get(order_metric, order_metric) + ": " + text_template + "<extra></extra>",
                    name=""
                ))
                
                # Adaptive tick font: shrink for many orders to prevent label overlap.
                n_orders = len(order_agg)
                order_tick_font = max(8, min(13, int(160 / max(1, n_orders))))
                fig_order.update_layout(
                    title="",
                    xaxis_title="Order / Campaign",
                    yaxis_title=metric_labels.get(order_metric, order_metric),
                    xaxis_tickangle=0,
                    showlegend=False,
                    margin=dict(b=order_bottom_margin, t=40),
                    xaxis=dict(
                        tickmode="array",
                        tickvals=order_agg["Order_X"].tolist(),
                        ticktext=order_agg["Order_Display"].tolist(),
                        automargin=True,
                        tickfont=dict(size=order_tick_font),
                    ),
                    height=400
                )
                
                st.plotly_chart(fig_order, use_container_width=True)
                
                # Show order summary table
                st.markdown("**Order Performance Summary**")
                order_display = order_agg.copy()
                # Format percentages (multiply by 100 for display)
                if "CTR" in order_display.columns:
                    order_display["CTR"] = (order_display["CTR"] * 100).map("{:.4f}%".format)
                if "DPVR" in order_display.columns:
                    order_display["DPVR"] = (order_display["DPVR"] * 100).map("{:.4f}%".format)
                if "Purchase_Rate" in order_display.columns:
                    order_display["Purchase_Rate"] = (order_display["Purchase_Rate"] * 100).map("{:.4f}%".format)
                # Format numbers with commas
                if "Impressions" in order_display.columns:
                    order_display["Impressions"] = order_display["Impressions"].map("{:,.0f}".format)
                if "Click-throughs" in order_display.columns:
                    order_display["Click-throughs"] = order_display["Click-throughs"].map("{:,.0f}".format)
                if "DPV" in order_display.columns:
                    order_display["DPV"] = order_display["DPV"].map("{:,.0f}".format)
                if "Purchases" in order_display.columns:
                    order_display["Purchases"] = order_display["Purchases"].map("{:,.0f}".format)
                
                display_cols = ["Order_ID", "Impressions", "Click-throughs", "CTR", "DPV", "DPVR", "Purchases", "Purchase_Rate"]
                if "Promoted_ROAS" in order_display.columns:
                    order_display["Promoted_ROAS"] = order_display["Promoted_ROAS"].map("${:.2f}".format)
                    display_cols.append("Promoted_ROAS")
                if "Total_ROAS" in order_display.columns:
                    order_display["Total_ROAS"] = order_display["Total_ROAS"].map("${:.2f}".format)
                    display_cols.append("Total_ROAS")
                if "Total_DPVR" in order_display.columns:
                    order_display["Total_DPVR"] = (order_display["Total_DPVR"] * 100).map("{:.4f}%".format)
                    display_cols.append("Total_DPVR")
                if "Total_Purchase_Rate" in order_display.columns:
                    order_display["Total_Purchase_Rate"] = (order_display["Total_Purchase_Rate"] * 100).map("{:.4f}%".format)
                    display_cols.append("Total_Purchase_Rate")
                
                # Filter to only show columns that exist
                display_cols = [col for col in display_cols if col in order_display.columns]
                st.dataframe(order_display[display_cols], use_container_width=True, hide_index=True)
            else:
                st.info("ℹ️ No order data available with current filters.")

    # ==============================

    # ==============================
    # CREATIVE x CAMPAIGN PIVOT TABLE
    # (unaggregated - each creative shown separately per campaign)
    # ==============================
    _cc_camp_col = "Order_ID" if "Order_ID" in processed.columns else ("Campaign_Name" if "Campaign_Name" in processed.columns else None)
    if _cc_camp_col is not None:
        st.markdown("---")
        st.subheader("🔀 CREATIVE PERFORMANCE BY ORDER")
        st.markdown("Each creative's performance broken out by campaign. Filter by key KPI.")

        # Independent filters
        _cc_all_camps = sorted(processed[_cc_camp_col].dropna().astype(str).str.strip().replace("", float("nan")).dropna().unique().tolist())
        _cc_col1, _cc_col2 = st.columns([2.1, 0.9])
        with _cc_col1:
            cc_selected_campaigns = st.multiselect(
                "Campaigns to Include",
                options=["All Campaigns"] + _cc_all_camps,
                default=["All Campaigns"],
                key="cc_campaign_filter",
            )
        with _cc_col2:
            cc_metric = st.selectbox(
                "KPI",
                metric_options,
                index=default_index,
                key="cc_metric_filter",
                format_func=lambda x: metric_labels.get(x, x),
            )

        _cc_rc1, _cc_rc2, _cc_rc3 = st.columns([1, 1, 1])
        with _cc_rc1:
            if st.button("Reset Filters", key="reset_cc_filters"):
                st.session_state.cc_campaign_filter = ["All Campaigns"]
                st.session_state.cc_metric_filter = "CTR" if "CTR" in metric_options else (metric_options[0] if metric_options else "CTR")
                try:
                    st.rerun()
                except AttributeError:
                    st.experimental_rerun()

        # Build working dataset (independent of main chart filters)
        cc_data = processed.copy()
        cc_data = cc_data[cc_data[_cc_camp_col].notna() & (cc_data[_cc_camp_col].astype(str).str.strip() != "")]

        if "All Campaigns" not in cc_selected_campaigns and cc_selected_campaigns:
            cc_data = cc_data[cc_data[_cc_camp_col].isin(cc_selected_campaigns)]

        if cc_data.empty:
            st.info("ℹ️ No data available with current filters.")
        else:
            _cc_gk = "Group_Key" if "Group_Key" in cc_data.columns else "Creative_ID"
            _cc_sum = {
                "Impressions": "sum",
                "Click-throughs": "sum",
                "DPV": "sum",
                "Purchases": "sum",
            }
            for _c in ["Sales_USD", "Total_Sales_USD", "Total_Cost", "Total_DPV", "Total_Purchases"]:
                if _c in cc_data.columns:
                    _cc_sum[_c] = "sum"

            cc_agg = cc_data.groupby([_cc_gk, _cc_camp_col], as_index=False).agg(_cc_sum)

            _cc_pct_metrics = ["CTR", "DPVR", "Purchase_Rate", "Total_DPVR", "Total_Purchase_Rate"]
            cc_agg["CTR"] = (cc_agg["Click-throughs"] / cc_agg["Impressions"]).replace([float("inf"), -float("inf")], 0).fillna(0)
            cc_agg["DPVR"] = (cc_agg["DPV"] / cc_agg["Impressions"]).replace([float("inf"), -float("inf")], 0).fillna(0)
            cc_agg["Purchase_Rate"] = (cc_agg["Purchases"] / cc_agg["Impressions"]).replace([float("inf"), -float("inf")], 0).fillna(0)
            if "Sales_USD" in cc_agg.columns and "Total_Cost" in cc_agg.columns:
                cc_agg["Promoted_ROAS"] = (cc_agg["Sales_USD"] / cc_agg["Total_Cost"]).replace([float("inf"), -float("inf")], 0).fillna(0)
            if "Total_Sales_USD" in cc_agg.columns and "Total_Cost" in cc_agg.columns:
                cc_agg["Total_ROAS"] = (cc_agg["Total_Sales_USD"] / cc_agg["Total_Cost"]).replace([float("inf"), -float("inf")], 0).fillna(0)
            if "Total_DPV" in cc_agg.columns:
                cc_agg["Total_DPVR"] = (cc_agg["Total_DPV"] / cc_agg["Impressions"]).replace([float("inf"), -float("inf")], 0).fillna(0)
            if "Total_Purchases" in cc_agg.columns:
                cc_agg["Total_Purchase_Rate"] = (cc_agg["Total_Purchases"] / cc_agg["Impressions"]).replace([float("inf"), -float("inf")], 0).fillna(0)

            if not cc_agg.empty and cc_metric in cc_agg.columns:
                # Flat ranked table: one row per creative+campaign, sorted by KPI descending
                cc_sorted = cc_agg[[_cc_gk, _cc_camp_col, cc_metric]].copy()
                cc_sorted = cc_sorted.sort_values(by=cc_metric, ascending=False).reset_index(drop=True)

                # Clean up creative name: prefer Full_Creative_Name lookup, otherwise replace underscores
                if "Full_Creative_Name" in cc_data.columns:
                    _name_map = (
                        cc_data[[_cc_gk, "Full_Creative_Name"]]
                        .drop_duplicates(subset=[_cc_gk])
                        .set_index(_cc_gk)["Full_Creative_Name"]
                        .to_dict()
                    )
                    cc_sorted["Creative"] = cc_sorted[_cc_gk].map(lambda k: _name_map.get(k, str(k).replace("_", " ")))
                else:
                    cc_sorted["Creative"] = cc_sorted[_cc_gk].astype(str).str.replace("_", " ", regex=False)

                # Format KPI value
                _cc_pct = cc_metric in _cc_pct_metrics
                _cc_roas = cc_metric in ["Promoted_ROAS", "Total_ROAS"]

                def _cc_fmt_val(v):
                    if pd.isna(v):
                        return "—"
                    if _cc_pct:
                        return f"{v * 100:.4f}%"
                    if _cc_roas:
                        return f"${v:.2f}"
                    return f"{v:,.2f}"

                kpi_label = metric_labels.get(cc_metric, cc_metric)
                cc_sorted[kpi_label] = cc_sorted[cc_metric].map(_cc_fmt_val)

                cc_display = cc_sorted[["Creative", _cc_camp_col, kpi_label]].rename(
                    columns={_cc_camp_col: "Campaign"}
                )

                tbl_height = min(600, max(200, 40 + len(cc_display) * 35))
                st.dataframe(
                    cc_display,
                    use_container_width=True,
                    hide_index=True,
                    height=tbl_height,
                    column_config={
                        "Campaign": st.column_config.TextColumn("Campaign", width="large"),
                        "Creative": st.column_config.TextColumn("Creative", width="large"),
                    },
                )
                st.caption(f"Sorted by {kpi_label} from highest to lowest. Each row = one creative in one campaign.")
            else:
                st.info("ℹ️ No data available with current filters.")


    # ==============================
    # AD SIZE PERFORMANCE CHART
    # ==============================
    if has_size_col and size_col:
        st.markdown("---")
        st.subheader("📐 AD SIZE PERFORMANCE")
        
        # Dedicated filters for size analysis
        st.markdown("**Size Analysis Filters**")
        col1, col2, col3 = st.columns([2.0, 0.9, 1.1])
        
        with col1:
            # Callback handles "All Orders" auto-deselect (runs before value finalizes).
            def _dedupe_all_orders_size():
                _v = st.session_state.get("size_order_filter", [])
                if isinstance(_v, list) and "All Orders" in _v and len(_v) > 1:
                    st.session_state["size_order_filter"] = [o for o in _v if o != "All Orders"]

            # Order filter for size analysis
            size_selected_orders_display = st.multiselect(
                "Order",
                options=order_options,
                default=["All Orders"],
                key="size_order_filter",
                on_change=_dedupe_all_orders_size,
                help="Filter by order name or campaign ID for size analysis"
            )
            
            # Use the selected labels directly — they already match Order_ID
            # in the data (composite "Name (ID: 12345)" format).
            size_selected_orders = list(size_selected_orders_display)

            # Callback handles session_state; sanitize local list for this run.
            if "All Orders" in size_selected_orders and len(size_selected_orders) > 1:
                size_selected_orders = [o for o in size_selected_orders if o != "All Orders"]
        
        with col2:
            # Metric selection for size analysis
            size_metric = st.selectbox(
                "Sort by KPI",
                metric_options,
                index=default_index,
                key="size_metric_filter",
                format_func=lambda x: metric_labels.get(x, x)
            )
        
        with col3:
            # Reset button for size filters
            if st.button("Reset Size Filters", key="reset_size_filters"):
                st.session_state.size_order_filter = ["All Orders"]
                st.session_state.size_metric_filter = "CTR" if "CTR" in metric_options else (metric_options[0] if metric_options else "CTR")
                if has_date_cols:
                    st.session_state.size_start_date_filter = processed["Start_Date"].min()
                    st.session_state.size_end_date_filter = processed["End_Date"].max()
                try:
                    st.rerun()
                except AttributeError:
                    st.experimental_rerun()
        
        # Time period filter for size analysis (if date columns exist)
        if has_date_cols:
            col1, col2 = st.columns([1.0, 1.0])
            
            min_date = processed["Start_Date"].min()
            max_date = processed["End_Date"].max()
            
            if not pd.isna(min_date) and not pd.isna(max_date):
                with col1:
                    size_filter_start_date = st.date_input(
                        "From Date",
                        value=min_date,
                        min_value=min_date,
                        max_value=max_date,
                        key="size_start_date_filter",
                        help="Filter ads that were live on or after this date"
                    )
                with col2:
                    size_filter_end_date = st.date_input(
                        "To Date",
                        value=max_date,
                        min_value=min_date,
                        max_value=max_date,
                        key="size_end_date_filter",
                        help="Filter ads that were live on or before this date"
                    )

                # Warn if the date range is inverted (From > To)
                if size_filter_start_date is not None and size_filter_end_date is not None:
                    try:
                        if pd.Timestamp(size_filter_start_date) > pd.Timestamp(size_filter_end_date):
                            st.warning("⚠️ **From Date is after To Date** — no data will show. Swap the dates or click Reset Size Filters.")
                    except Exception:
                        pass
            else:
                size_filter_start_date = None
                size_filter_end_date = None
        
        # Apply size-specific filters
        size_filtered_data = processed.copy()
        
        # Apply order filter
        if "All Orders" not in size_selected_orders:
            if "Order_ID" in size_filtered_data.columns:
                size_filtered_data = size_filtered_data[size_filtered_data["Order_ID"].isin(size_selected_orders)]
        
        # Apply date filter
        if has_date_cols and 'size_filter_start_date' in locals() and 'size_filter_end_date' in locals() and size_filter_start_date and size_filter_end_date:
            size_filter_start_dt = pd.Timestamp(size_filter_start_date)
            size_filter_end_dt = pd.Timestamp(size_filter_end_date)
            
            size_filtered_data = size_filtered_data[
                (size_filtered_data["Start_Date"] <= size_filter_end_dt) & 
                (size_filtered_data["End_Date"] >= size_filter_start_dt)
            ]
        
        # Aggregate by size
        if size_filtered_data.empty or size_col not in size_filtered_data.columns:
            st.info("ℹ️ No size data available with current filters.")
        else:
            size_agg = size_filtered_data.groupby(size_col).agg({
                "Impressions": "sum",
                "Click-throughs": "sum",
                "DPV": "sum",
                "Purchases": "sum"
            }).reset_index()
            
            # Calculate metrics
            size_agg["CTR"] = (size_agg["Click-throughs"] / size_agg["Impressions"]).replace([float('inf'), -float('inf')], 0).fillna(0)
            size_agg["DPVR"] = (size_agg["DPV"] / size_agg["Impressions"]).replace([float('inf'), -float('inf')], 0).fillna(0)
            size_agg["Purchase_Rate"] = (size_agg["Purchases"] / size_agg["Impressions"]).replace([float('inf'), -float('inf')], 0).fillna(0)
        
            # Add ROAS if available
            if "Sales_USD" in size_filtered_data.columns and "Total_Cost" in size_filtered_data.columns:
                size_roas_agg = size_filtered_data.groupby(size_col).agg({
                    "Sales_USD": "sum",
                    "Total_Cost": "sum"
                }).reset_index()
                size_agg = size_agg.merge(size_roas_agg, on=size_col, how="left")
                size_agg["Promoted_ROAS"] = (size_agg["Sales_USD"] / size_agg["Total_Cost"]).replace([float('inf'), -float('inf')], 0).fillna(0)
            
            if "Total_Sales_USD" in size_filtered_data.columns and "Total_Cost" in size_filtered_data.columns:
                size_total_roas_agg = size_filtered_data.groupby(size_col).agg({
                    "Total_Sales_USD": "sum",
                    "Total_Cost": "sum"
                }).reset_index()
                size_agg = size_agg.merge(size_total_roas_agg, on=size_col, how="left", suffixes=('', '_y'))
                # Use Total_Cost from the merge if it exists, otherwise keep the original
                if "Total_Cost_y" in size_agg.columns:
                    size_agg["Total_Cost"] = size_agg["Total_Cost"].fillna(size_agg["Total_Cost_y"])
                    size_agg = size_agg.drop(columns=["Total_Cost_y"])
                size_agg["Total_ROAS"] = (size_agg["Total_Sales_USD"] / size_agg["Total_Cost"]).replace([float('inf'), -float('inf')], 0).fillna(0)
            
            # Add Total DPVR and Total Purchase Rate if available
            if "Total_DPV" in size_filtered_data.columns:
                size_total_dpv_agg = size_filtered_data.groupby(size_col).agg({"Total_DPV": "sum"}).reset_index()
                size_agg = size_agg.merge(size_total_dpv_agg, on=size_col, how="left")
                size_agg["Total_DPVR"] = (size_agg["Total_DPV"] / size_agg["Impressions"]).replace([float('inf'), -float('inf')], 0).fillna(0)
            
            if "Total_Purchases" in size_filtered_data.columns:
                size_total_purch_agg = size_filtered_data.groupby(size_col).agg({"Total_Purchases": "sum"}).reset_index()
                size_agg = size_agg.merge(size_total_purch_agg, on=size_col, how="left")
                size_agg["Total_Purchase_Rate"] = (size_agg["Total_Purchases"] / size_agg["Impressions"]).replace([float('inf'), -float('inf')], 0).fillna(0)
            
            # Sort by selected metric for size analysis
            if size_metric in size_agg.columns:
                size_agg = size_agg.sort_values(by=size_metric, ascending=False)
            
            # Create size performance chart
            if not size_agg.empty and len(size_agg) > 0 and size_metric in size_agg.columns:
                fig_size = px.bar(
                    size_agg,
                    x=size_col,
                    y=size_metric,
                    text=size_metric,
                    color_discrete_sequence=[bar_color],
                    height=400
                )
                
                # Format text based on metric type
                if size_metric in ["CTR", "DPVR", "Purchase_Rate", "Total_DPVR", "Total_Purchase_Rate"]:
                    text_template = "%{y:.4f}"
                else:
                    text_template = "%{y:.2f}"
                
                fig_size.update_traces(
                    texttemplate=text_template,
                    textposition="outside"
                )
                
                fig_size.update_layout(
                    title="",
                    xaxis_title="Ad Size",
                    yaxis_title=metric_labels.get(size_metric, size_metric),
                    xaxis_tickangle=45,
                    showlegend=False,
                    margin=dict(b=100, t=40)
                )
                
                st.plotly_chart(fig_size, use_container_width=True)
                
                # Show size summary table
                st.markdown("**Size Performance Summary**")
                size_display = size_agg.copy()
                # Format percentages (multiply by 100 for display)
                if "CTR" in size_display.columns:
                    size_display["CTR"] = (size_display["CTR"] * 100).map("{:.4f}%".format)
                if "DPVR" in size_display.columns:
                    size_display["DPVR"] = (size_display["DPVR"] * 100).map("{:.4f}%".format)
                if "Purchase_Rate" in size_display.columns:
                    size_display["Purchase_Rate"] = (size_display["Purchase_Rate"] * 100).map("{:.4f}%".format)
                # Format numbers with commas
                if "Impressions" in size_display.columns:
                    size_display["Impressions"] = size_display["Impressions"].map("{:,.0f}".format)
                if "Click-throughs" in size_display.columns:
                    size_display["Click-throughs"] = size_display["Click-throughs"].map("{:,.0f}".format)
                if "DPV" in size_display.columns:
                    size_display["DPV"] = size_display["DPV"].map("{:,.0f}".format)
                if "Purchases" in size_display.columns:
                    size_display["Purchases"] = size_display["Purchases"].map("{:,.0f}".format)
                
                display_cols = [size_col, "Impressions", "Click-throughs", "CTR", "DPV", "DPVR", "Purchases", "Purchase_Rate"]
                if "Promoted_ROAS" in size_display.columns:
                    size_display["Promoted_ROAS"] = size_display["Promoted_ROAS"].map("${:.2f}".format)
                    display_cols.append("Promoted_ROAS")
                if "Total_ROAS" in size_display.columns:
                    size_display["Total_ROAS"] = size_display["Total_ROAS"].map("${:.2f}".format)
                    display_cols.append("Total_ROAS")
                if "Total_DPVR" in size_display.columns:
                    size_display["Total_DPVR"] = (size_display["Total_DPVR"] * 100).map("{:.4f}%".format)
                    display_cols.append("Total_DPVR")
                if "Total_Purchase_Rate" in size_display.columns:
                    size_display["Total_Purchase_Rate"] = (size_display["Total_Purchase_Rate"] * 100).map("{:.4f}%".format)
                    display_cols.append("Total_Purchase_Rate")
                
                # Filter to only show columns that exist
                display_cols = [col for col in display_cols if col in size_display.columns]
                st.dataframe(size_display[display_cols], use_container_width=True, hide_index=True)
            else:
                st.info("ℹ️ No size data available with current filters.")

