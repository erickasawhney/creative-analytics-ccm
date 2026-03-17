import streamlit as st
import pandas as pd
import re
import base64
from PIL import Image
from io import BytesIO
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import warnings
import textwrap
warnings.filterwarnings('ignore')

# ==============================
# Page Config
# ==============================
st.set_page_config(page_title="CREATIVE ANALYSIS TOOL", page_icon="chart_with_upwards_trend", layout="wide")
st.title("CREATIVE ANALYSIS TOOL")
# Show usage as an ordered list so each step is on its own row
st.markdown(
    """
How to use:

1. Download Amazon DSP report [here](https://advertising.amazon.com/dsp/ENTITYA6I16E0BHHHY/report/custom-report/new) (click 'select all' so all columns are included in report)
2. Download creative images (JPGs) and name them by creative identifier (Recommend all same size)
4. Upload the report and images below
5. Select filters
5. Enjoy!
"""
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

@st.cache_data(show_spinner=False)
def load_and_process(file_bytes):
    df = pd.read_excel(BytesIO(file_bytes), dtype=str, keep_default_na=False)
    df = normalize_columns(df)
    return process_campaign_data(df)

def process_campaign_data(df):
    try:
        creative_col = find_column(df, ["creative", "creative name", "ad name", "ad", "creative_name", "ad_name", "adname"])
        imp_col      = find_column(df, ["impressions", "impression", "imps", "imp"])
        click_col    = find_column(df, ["click-throughs", "clicks", "click throughs", "click"])
        dpv_col      = find_column(df, ["dpv", "detail page views", "dpvs", "dpv views"])
        purch_col    = find_column(df, ["purchases", "purchase", "sales", "units"])
        total_purch_col = find_column(df, ["total purchases", "total_purchases", "total_purchases_usd", "total_purchases_count"])
        total_dpv_col = find_column(df, ["total dpv", "total_dpv", "total dpvs", "total_dpv_count", "total_dpvs"]) 
        order_col    = find_column(df, [
            "order", "orders", "order id", "order_id", "order number",
            "orderid", "order#", "order #", "ordernum", "order id #",
            "campaign name", "campaign", "campaign_name"
        ])
        
        # Detect Campaign ID column separately
        campaign_id_col = find_column(df, ["campaign id", "campaign_id", "campaignid", "campaign #"])

        # Detect Sales USD, Total Sales USD and Total Cost columns for ROAS calculation
        sales_col = find_column(df, ["sales usd", "sales", "revenue", "revenue usd"])
        total_sales_col = find_column(df, ["total sales usd", "total sales", "total_sales", "total_sales_usd"])
        cost_col = find_column(df, ["total cost", "cost", "spend", "media cost"])
        subscription_col = find_column(df, ["subscription sign-ups", "subscription signups", "subscription sign ups", "subscriptions"])
        app_subscription_col = find_column(df, ["app subscription sign-ups", "app subscription signups", "app subscription sign ups", "app subscriptions"])

        # Detect start/end date columns (common names). Keep as Start_Date / End_Date
        start_col = find_column(df, ["interval start", "interval_start", "line item start date", "start date", "start_date", "line_item_start_date", "start"])
        end_col = find_column(df, ["interval end", "interval_end", "line item end date", "end date", "end_date", "line_item_end_date", "end"])

        rename_map = {}
        if creative_col: rename_map[creative_col] = "Creative"
        # NOTE: removed preserving of Input_Creative_ID per user request
        if imp_col:      rename_map[imp_col]      = "Impressions"
        if click_col:    rename_map[click_col]    = "Click-throughs"
        if dpv_col:      rename_map[dpv_col]      = "DPV"
        if purch_col:    rename_map[purch_col]    = "Purchases"
        if total_purch_col: rename_map[total_purch_col] = "Total_Purchases"
        if total_dpv_col: rename_map[total_dpv_col] = "Total_DPV"
        if order_col:    rename_map[order_col]    = "Order_ID"
        if campaign_id_col: rename_map[campaign_id_col] = "Campaign_ID"
        if sales_col:    rename_map[sales_col]    = "Sales_USD"
        if total_sales_col: rename_map[total_sales_col] = "Total_Sales_USD"
        if cost_col:     rename_map[cost_col]     = "Total_Cost"
        if subscription_col: rename_map[subscription_col] = "Subscription sign-ups"
        if app_subscription_col: rename_map[app_subscription_col] = "App subscription sign-ups"
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
        for col in ["Sales_USD", "Total_Sales_USD", "Total_Cost", "DPV", "Total_DPV", "Purchases", "Total_Purchases", "Subscription sign-ups", "App subscription sign-ups"]:
            if col not in df.columns:
                # For counts like DPV/Purchases keep as ints where appropriate later; initialize to 0.0 for safe math
                df[col] = 0.0
            else:
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

        if "Order_ID" in df.columns:
            df["Order_ID"] = df["Order_ID"].astype(str).str.strip()
            df["Order_ID"] = df["Order_ID"].replace({"nan": "", "<NA>": ""}).str.strip()
            df["Order_ID"] = df["Order_ID"].replace({"": None})
        
        if "Campaign_ID" in df.columns:
            df["Campaign_ID"] = df["Campaign_ID"].astype(str).str.strip()
            df["Campaign_ID"] = df["Campaign_ID"].replace({"nan": "", "<NA>": ""}).str.strip()
            df["Campaign_ID"] = df["Campaign_ID"].replace({"": None})

        return df, df

    except Exception as e:
        st.error(f"Error processing file: {e}")
        return None, None

def aggregate_by_creative(df, order_filters=None):
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

    # Dates: create year key for grouping (End_Date required for grouping)
    if "End_Date" in df.columns:
        # End year (string) for grouping
        df["End_Year"] = df["End_Date"].dt.year
        df["_agg_end_year"] = df["End_Year"].apply(lambda x: str(int(x)) if pd.notna(x) else "")
    else:
        df["End_Year"] = None
        df["_agg_end_year"] = ""

    # Ensure subscription columns exist for aggregation (fill with 0 if missing)
    if "Subscription sign-ups" not in df.columns:
        df["Subscription sign-ups"] = 0
    if "App subscription sign-ups" not in df.columns:
        df["App subscription sign-ups"] = 0
    
    def norm_col(col):
        return col.strip().lower().replace("-", "").replace(" ", "")
    normed_cols = {norm_col(c): c for c in df.columns}
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
        "Creative": "first",
    }
    # Add video started/completed columns if present
    video_started_col = normed_cols.get("videostarted")
    video_completed_col = normed_cols.get("videocompleted")
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
    # group by creative id + end year
    group_keys = ["_agg_cid", "_agg_end_year"]

    grp = df.groupby(group_keys, as_index=False).agg(agg_dict)

    # Restore readable columns
    grp["Creative_ID"] = grp["_agg_cid"].replace({"": None})
    grp = grp.drop(columns=["_agg_cid"], errors="ignore")

    grp["End_Year"] = grp["_agg_end_year"].replace({"": None})
    grp = grp.drop(columns=["_agg_end_year"], errors="ignore")

    # Compute rates (avoid division by zero)
    denom = grp["Impressions"].replace(0, 1)
    grp["CTR"] = (grp["Click-throughs"] / denom * 100).round(4)
    grp["DPVR"] = (grp["DPV"] / denom * 100).round(4)
    grp["Purchase_Rate"] = (grp["Purchases"] / denom * 100).round(4)
    # Calculate VCR (Video Completion Rate)
    if video_started_col and video_completed_col and video_started_col in grp.columns and video_completed_col in grp.columns:
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

    grp = grp.rename(columns={"Creative": "Full_Creative_Name"})

    def make_group_key(row):
        cid = row.get("Creative_ID")
        s = row.get("End_Year") or ""
        if cid:
            return f"{cid} | {s}".strip(" | ")
        return f"{s}".strip()

    grp["Group_Key"] = grp.apply(make_group_key, axis=1)

    # Reorder columns to keep compatibility
    base_cols = ["Group_Key", "Creative_ID", "Full_Creative_Name", "Impressions", "Click-throughs", "CTR", "DPV", "DPVR", "Purchases", "Purchase_Rate", "Sales_USD", "Total_Cost", "Subscription sign-ups"]
    # include End_Year column near the front
    front = ["End_Year"]

    # Ensure financial, ROAS, and total-rate columns are present in order if they exist
    for extra in ["Total_Sales_USD", "Promoted_ROAS", "Total_ROAS", "Total_DPV", "Total_DPVR", "Total_Purchases", "Total_Purchase_Rate", "App subscription sign-ups"]:
        if extra in grp.columns and extra not in base_cols:
            base_cols.append(extra)

    col_order = front + base_cols
    col_order = [c for c in col_order if c in grp.columns]
    return grp[col_order]

# ==============================
# 1. UPLOAD FILES
# ==============================
st.markdown("### 📁 UPLOAD SECTION")
st.markdown("Upload your campaign data and creative images to get started.")

col1, col2 = st.columns([3, 1])
with col1:
    uploaded_file = st.file_uploader("Upload an Excel file", type=["xlsx", "xls"])
with col2:
    st.markdown("<br>", unsafe_allow_html=True)
    st.caption("*ensure you have added all columns in DSP")
uploaded_images = st.file_uploader(
    "Upload images – ensure file name includes creative identifier/name - RECOMMEND ALL SAME SIZE",
    type=["png", "jpg", "jpeg"],
    accept_multiple_files=True,
    key="imgs"
)
st.markdown("---")

# ==============================
# Image Mapping (Fixed)
# ==============================
image_dict = {}
unmatched_images = []
matched_summary = []

# Helper: normalize filenames / keys for robust matching
def _norm_key(s):
    if not s:
        return ""
    # remove extension if present, lowercase, keep only alnum
    s = re.sub(r"\.[^.]+$", "", s)
    s = s.strip().lower()
    s = re.sub(r"[^a-z0-9]", "", s)
    return s

def get_display_name(original_name):
    """Get the display name (edited name if available, otherwise original)"""
    if 'edited_creative_names' in st.session_state:
        return st.session_state.edited_creative_names.get(original_name, original_name)
    return original_name

# Best-effort match: look for exact normalized cid+dcp, then cid, then dcp, then substring matches
def _find_image_for_row(row, img_dict):
    # img_dict keys are normalized strings
    cid = (row.get("Creative_ID") or "")
    full = (row.get("Full_Creative_Name") or row.get("Group_Key") or "")
    n_cid = _norm_key(cid)
    n_full = _norm_key(full)

    candidates = []
    if n_cid:
        candidates.extend([n_cid, n_cid + "_", n_cid + "-", n_cid + "|"])
    if n_full:
        candidates.append(n_full)
    
    # Also try matching with edited creative names
    original_group_key = row.get("Group_Key", "")
    if original_group_key and 'edited_creative_names' in st.session_state:
        edited_name = st.session_state.edited_creative_names.get(original_group_key, "")
        if edited_name and edited_name != original_group_key:
            n_edited = _norm_key(edited_name)
            if n_edited:
                candidates.extend([n_edited, n_edited + "_", n_edited + "-", n_edited + "|"])

    # exact candidate match first
    for c in candidates:
        if c in img_dict:
            return img_dict[c]

    # fallback: substring-based matching in any image key
    for key in img_dict:
        if n_cid and n_cid in key:
            return img_dict[key]
        if n_full and n_full in key:
            return img_dict[key]
        # Also try edited name substring matching
        if original_group_key and 'edited_creative_names' in st.session_state:
            edited_name = st.session_state.edited_creative_names.get(original_group_key, "")
            if edited_name and edited_name != original_group_key:
                n_edited = _norm_key(edited_name)
                if n_edited and n_edited in key:
                    return img_dict[key]

    return None

if uploaded_images:
    progress_bar = st.progress(0)
    for i, f in enumerate(uploaded_images):
        try:
            img = Image.open(BytesIO(f.getvalue()))
            name = f.name
            # use normalized filename (no ext, alnum only) as the key
            clean_name = re.sub(r"\.[^.]+$", "", name).strip()
            key = _norm_key(clean_name)

            if key:
                image_dict[key] = img
                matched_summary.append(f"{name} → {key}")
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
    with st.spinner("Processing data…"):
        processed, raw_df = load_and_process(file_bytes)
    if processed is None:
        st.stop()

    # Order Filter Options
    order_options = ["All Orders"]
    order_to_campaign = {}  # Map order names to campaign IDs
    if "Order_ID" in processed.columns:
        # Build mapping of Order_ID to Campaign_ID (if available)
        if "Campaign_ID" in processed.columns:
            temp_df = processed[["Order_ID", "Campaign_ID"]].drop_duplicates()
            for _, row in temp_df.iterrows():
                order_id = str(row["Order_ID"]) if pd.notna(row["Order_ID"]) else None
                campaign_id = str(row["Campaign_ID"]) if pd.notna(row["Campaign_ID"]) else None
                if order_id and campaign_id:
                    order_to_campaign[order_id] = campaign_id
        
        unique_orders = (processed["Order_ID"]
                         .dropna()
                         .astype(str)
                         .unique())
        # Create display labels with campaign IDs
        for order in sorted([o for o in unique_orders if o]):
            if order in order_to_campaign:
                display_label = f"{order} (ID: {order_to_campaign[order]})"
            else:
                display_label = order
            order_options.append(display_label)

    # ==============================
    # CREATIVE ANALYSIS
    # ==============================
    st.markdown("---")
    st.subheader("🎯 CREATIVE PERFORMANCE")
    st.markdown("Visualize creative performance from top to lowest performing by KPI. Configure filters below to customize your view.")
    
    st.markdown("**Creative Performance Filters**")
    
    # Check if date columns exist for time period filtering
    has_date_cols = "Start_Date" in processed.columns and "End_Date" in processed.columns
    
    # Main filters in a compact 3-column layout with smaller fields
    # Support both 'size' and 'ad size' columns (case-insensitive) - for size performance chart only
    size_col_candidates = [col for col in processed.columns if col.lower() in ("size", "ad size")]
    has_size_col = processed is not None and bool(size_col_candidates)
    size_col = None
    if has_size_col:
        size_col = size_col_candidates[0]

    col1, col2, col3 = st.columns([2.0, 0.9, 1])

    with col1:
        # Add tooltips for order options
        order_tooltips = {order: order for order in order_options}
        selected_orders_display = st.multiselect(
            "Order",
            options=order_options,
            default=["All Orders"],
            key="order_filter",
            help="Filter by order name or campaign ID",
            format_func=lambda x: x,
        )
        
        # Extract actual order names from display labels (remove campaign ID suffix)
        selected_orders = []
        for display_label in selected_orders_display:
            if display_label == "All Orders":
                selected_orders.append("All Orders")
            elif " (ID: " in display_label:
                # Extract order name before the campaign ID
                order_name = display_label.split(" (ID: ")[0]
                selected_orders.append(order_name)
            else:
                selected_orders.append(display_label)
    with col2:
        metric_options = ["CTR", "DPVR", "Purchase_Rate"]
        # Add Subscription sign-ups and Cost per subscription if columns exist
        if processed is not None and "Subscription sign-ups" in processed.columns:
            metric_options.append("Subscription sign-ups")
        if processed is not None and "App subscription sign-ups" in processed.columns:
            metric_options.append("App subscription sign-ups")
        if processed is not None and "Total_Cost" in processed.columns and "Subscription sign-ups" in processed.columns:
            metric_options.append("Cost per subscription")
        # Add VCR if both columns exist
        def norm_col(col):
            return col.strip().lower().replace("-", "").replace(" ", "")
        normed_cols = {norm_col(c): c for c in processed.columns}
        video_started_col = normed_cols.get("videostarted")
        video_completed_col = normed_cols.get("videocompleted")
        if video_started_col and video_completed_col:
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
    }
    # Order metric_options alphabetically by their user-friendly label
    metric_options = sorted(metric_options, key=lambda x: metric_labels.get(x, x))
    # Set CTR as the default metric
    default_index = metric_options.index("CTR") if "CTR" in metric_options else 0
    metric = st.selectbox("Sort by KPI", metric_options, index=default_index, key="metric_filter", format_func=lambda x: metric_labels.get(x, x))
    with col3:
        min_imps = st.number_input("Min Imps", min_value=0, value=100, step=50, key="min_imps_filter")

    # Time period filter (if date columns exist)
    if has_date_cols:
        col1, col2, col3 = st.columns([1.0, 1.0, 1.9])
        
        # Get min and max dates from the data
        min_date = processed["Start_Date"].min()
        max_date = processed["End_Date"].max()
        
        # Handle NaT (missing dates)
        if pd.isna(min_date) or pd.isna(max_date):
            st.info("⚠️ Some date values are missing in the data. Showing all data.")
            filter_start_date = None
            filter_end_date = None
        else:
            with col1:
                filter_start_date = st.date_input(
                    "From Date",
                    value=min_date,
                    min_value=min_date,
                    max_value=max_date,
                    key="start_date_filter",
                    help="Filter ads that were live on or after this date"
                )
            with col2:
                filter_end_date = st.date_input(
                    "To Date",
                    value=max_date,
                    min_value=min_date,
                    max_value=max_date,
                    key="end_date_filter",
                    help="Filter ads that were live on or before this date"
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
    
    # Apply filters BEFORE aggregation
    filtered_processed = processed.copy()
    
    # Apply date filter if dates are selected
    if has_date_cols and 'filter_start_date' in locals() and 'filter_end_date' in locals() and filter_start_date and filter_end_date:
        # Filter for ads where the interval overlaps with the selected date range
        # An ad is included if: (ad_start <= filter_end) AND (ad_end >= filter_start)
        filter_start_dt = pd.Timestamp(filter_start_date)
        filter_end_dt = pd.Timestamp(filter_end_date)
        
        filtered_processed = filtered_processed[
            (filtered_processed["Start_Date"] <= filter_end_dt) & 
            (filtered_processed["End_Date"] >= filter_start_dt)
        ]
    
    if min_imps > 0:
        filtered_processed = filtered_processed[filtered_processed["Impressions"] >= min_imps]

    # ...existing code...

    # Aggregate now (so the identifier filter can show the aggregated tuples)
    grouped = aggregate_by_creative(filtered_processed, selected_orders)
    if grouped is None or grouped.empty:
        st.warning("No data after filtering. Please check your filters or uploaded file.")
        st.stop()
    else:
        filtered = grouped.copy()


    # Creative identifier filter (updated to include edited names)

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
        # Always add 'Select All' option at the top
        identifier_options = ["Select All"] + identifier_options
        prev_identifier_filter = st.session_state.get('identifier_filter', [])
        identifier_filter = st.multiselect(
            "Creative identifiers",
            options=identifier_options,
            default=identifier_options[1:] if "Select All" in prev_identifier_filter else [],
            key="identifier_filter"
        )
        if "Select All" in identifier_filter:
            identifier_filter = identifier_options[1:]  # All except 'Select All'

    # Chart overlay controls
    st.markdown("**Chart Overlays**")
    col1, col2, col3 = st.columns([1, 1, 1])
    with col1:
        show_advertiser_benchmark = st.checkbox(
            "Overlay Advertiser Benchmark",
            value=False,
            help="Show advertiser benchmark line",
            key="show_advertiser_benchmark"
        )
    with col2:
        show_category_benchmark = st.checkbox(
            "Overlay Category Benchmark",
            value=False,
            help="Show category benchmark line",
            key="show_category_benchmark"
        )
    with col3:
        pass

    st.markdown("---")

    # Filter grouped data based on creative identifier selection
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
        filtered = filtered[filtered["Group_Key"].isin(all_matches)]

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
    def _wrap_into_html(s, width=25):
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
    # Use edited names if available
    chart_df["Label"] = chart_df["Group_Key"].apply(lambda s: _wrap_into_html(get_display_name(s), width=25))
    # Wrap the title as markdown so long titles will wrap onto multiple lines instead of being cut off
    wrapped_title = _wrap_into_html(title, width=80)
    st.markdown(f"<h3 style='text-align: center;'>{wrapped_title}</h3>", unsafe_allow_html=True)
    
    # Default benchmark values
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

    # Show benchmark inputs only for current metric if either benchmark is enabled
    if show_advertiser_benchmark or show_category_benchmark:
        benchmark_labels = {
            "CTR": "CTR",
            "DPVR": "Promoted DPVR",
            "Purchase_Rate": "Promoted Purchase Rate",
            "Promoted_ROAS": "Promoted ROAS",
            "Total_ROAS": "Total ROAS",
            "Total_DPVR": "Total DPVR",
            "Total_Purchase_Rate": "Total Purchase Rate",
            "Subscription sign-ups": "Subscription Sign-ups",
            "App subscription sign-ups": "App Subscription Sign-ups",
            "Cost per subscription": "Cost per Subscription",
        }
        units = {"CTR": "%", "DPVR": "%", "Purchase_Rate": "%", "Promoted_ROAS": "$", "Total_ROAS": "$", "Total_DPVR": "%", "Total_Purchase_Rate": "%", "Subscription sign-ups": "#", "App subscription sign-ups": "#", "Cost per subscription": "$"}
        examples = {"CTR": "2.0", "DPVR": "1.5", "Purchase_Rate": "0.5", "Promoted_ROAS": "4.0", "Total_ROAS": "6.0", "Total_DPVR": "2.5", "Total_Purchase_Rate": "0.8", "Subscription sign-ups": "100", "App subscription sign-ups": "50", "Cost per subscription": "10.0"}

        if metric in benchmark_labels:
            bench_col1, bench_col2 = st.columns([1, 1])
            with bench_col1:
                if show_advertiser_benchmark:
                    # Adjust max_value based on metric type
                    max_val = 10000.0 if metric in ["Subscription sign-ups", "App subscription sign-ups", "Cost per subscription"] else 100.0
                    advertiser_benchmark = st.number_input(
                        f"Advertiser Benchmark ({units[metric]})",
                        min_value=0.0,
                        max_value=max_val,
                        value=None,
                        step=0.1,
                        help=f"Enter advertiser benchmark value",
                        placeholder=f"e.g., {examples[metric]}",
                        key="advertiser_benchmark"
                    )
                else:
                    advertiser_benchmark = None
                # Update the specific benchmark value
                if metric == "CTR": benchmark_ctr = advertiser_benchmark or benchmark_ctr
                elif metric == "DPVR": benchmark_dpvr = advertiser_benchmark or benchmark_dpvr
                elif metric == "Purchase_Rate": benchmark_pr = advertiser_benchmark or benchmark_pr
                elif metric == "Promoted_ROAS": benchmark_promoted = advertiser_benchmark or benchmark_promoted
                elif metric == "Total_ROAS": benchmark_total = advertiser_benchmark or benchmark_total
                elif metric == "Total_DPVR": benchmark_total_dpvr = advertiser_benchmark or benchmark_total_dpvr
                elif metric == "Total_Purchase_Rate": benchmark_total_pr = advertiser_benchmark or benchmark_total_pr
                elif metric == "Subscription sign-ups": benchmark_subscriptions = advertiser_benchmark or benchmark_subscriptions
                elif metric == "App subscription sign-ups": benchmark_app_subscriptions = advertiser_benchmark or benchmark_app_subscriptions
                elif metric == "Cost per subscription": benchmark_cost_per_sub = advertiser_benchmark or benchmark_cost_per_sub
            
            with bench_col2:
                if show_category_benchmark:
                    # Adjust max_value based on metric type
                    max_val = 10000.0 if metric in ["Subscription sign-ups", "App subscription sign-ups", "Cost per subscription"] else 100.0
                    category_benchmark = st.number_input(
                        f"Category Benchmark ({units[metric]})",
                        min_value=0.0,
                        max_value=max_val,
                        value=None,
                        step=0.1,
                        help=f"Enter category benchmark value",
                        placeholder=f"e.g., {examples[metric]}",
                        key="category_benchmark"
                    )
                else:
                    category_benchmark = None
                # Update the specific benchmark value
                if metric == "CTR": benchmark_ctr_category = category_benchmark or benchmark_ctr_category
                elif metric == "DPVR": benchmark_dpvr_category = category_benchmark or benchmark_dpvr_category
                elif metric == "Purchase_Rate": benchmark_pr_category = category_benchmark or benchmark_pr_category
                elif metric == "Promoted_ROAS": benchmark_promoted_category = category_benchmark or benchmark_promoted_category
                elif metric == "Total_ROAS": benchmark_total_category = category_benchmark or benchmark_total_category
                elif metric == "Total_DPVR": benchmark_total_dpvr_category = category_benchmark or benchmark_total_dpvr_category
                elif metric == "Total_Purchase_Rate": benchmark_total_pr_category = category_benchmark or benchmark_total_pr_category
                elif metric == "Subscription sign-ups": benchmark_subscriptions_category = category_benchmark or benchmark_subscriptions_category
                elif metric == "App subscription sign-ups": benchmark_app_subscriptions_category = category_benchmark or benchmark_app_subscriptions_category
                elif metric == "Cost per subscription": benchmark_cost_per_sub_category = category_benchmark or benchmark_cost_per_sub_category

            # Add a color key for the benchmark lines
            legend_items = []
            if show_advertiser_benchmark:
                legend_items.append('<span style="display: flex; align-items: center;"><span style="width: 32px; height: 0; border-top: 4px dotted orange; margin-right: 8px;"></span><span style="font-size: 15px;">Advertiser Benchmark</span></span>')
            if show_category_benchmark:
                legend_items.append('<span style="display: flex; align-items: center;"><span style="width: 32px; height: 0; border-top: 4px dashed purple; margin-right: 8px;"></span><span style="font-size: 15px;">Category Benchmark</span></span>')
            
            if legend_items:
                st.markdown(
                    f'<div style="display: flex; align-items: center; gap: 24px; margin-top: 8px;">{"".join(legend_items)}</div>',
                    unsafe_allow_html=True
                )
    


    # Create figure
    has_order_data = False

    # Choose display formats depending on metric type
    is_percent_metric = metric in ["CTR", "DPVR", "Purchase_Rate", "Total_DPVR", "Total_Purchase_Rate", "Promoted_%_NTB", "Total_%_NTB", "VCR"]
    is_cost_metric = metric == "Cost per subscription"
    
    # Set chart order: lowest to highest for costs, highest to lowest for everything else
    category_order = 'total ascending' if is_cost_metric else 'total descending'
    
    if is_percent_metric:
        text_template = "%{text:.4f}%"
        hover_y_template = "%{y:.4f}%"
    elif is_cost_metric:
        text_template = "$%{text:.2f}"
        hover_y_template = "$%{y:.2f}"
    else:
        text_template = "%{text:.2f}"
        hover_y_template = "$%{y:.2f}"
    
    if has_order_data:
        # Create subplots to handle both bars and lines
        fig = make_subplots(specs=[[{"secondary_y": False}]])
        
        # Add bar chart
        if identifier_filter and len(identifier_filter) >= 1:
            chart_df["Color_Group"] = chart_df["Group_Key"].apply(
                lambda x: "Selected" if x in identifier_filter else "Others"
            )
            
            # Add bars for selected and others with different colors
            for group in ["Selected", "Others"]:
                group_data = chart_df[chart_df["Color_Group"] == group]
                if not group_data.empty:
                    color = bar_color if group == "Selected" else "#cccccc"
                    fig.add_trace(go.Bar(
                        x=group_data["Label"],
                        y=group_data[metric],
                        name=f"Creative {metric} ({group})",
                        marker_color=color,
                        width=bar_width,
                        text=group_data[metric].round(4),
                        texttemplate=text_template,
                        textposition="outside",
                        hovertemplate=f"<b>%{{x}}</b><br>{metric}: {hover_y_template}<br>Impressions: %{{customdata[0]:,}}<br>Purchases: %{{customdata[1]:,}}<extra></extra>",
                        customdata=group_data[["Impressions", "Purchases"]].values
                    ))
        else:
            # Single color scheme for all bars
            fig.add_trace(go.Bar(
                x=chart_df["Label"],
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
                hovertemplate=f"<b>%{{x}}</b><br>{metric}: {hover_y_template}<br>Impressions: %{{customdata[0]:,}}<br>Purchases: %{{customdata[1]:,}}<extra></extra>",
                customdata=chart_df[["Impressions", "Purchases"]].values
            ))
        
        # Add benchmark lines if enabled
        if show_advertiser_benchmark:
            benchmark_values = {"CTR": benchmark_ctr, "DPVR": benchmark_dpvr, "Purchase_Rate": benchmark_pr, "Promoted_ROAS": benchmark_promoted, "Total_ROAS": benchmark_total, "Total_DPVR": benchmark_total_dpvr, "Total_Purchase_Rate": benchmark_total_pr, "Subscription sign-ups": benchmark_subscriptions, "App subscription sign-ups": benchmark_app_subscriptions, "Cost per subscription": benchmark_cost_per_sub}
            benchmark_value = benchmark_values.get(metric)
            
            if benchmark_value is not None:
                fig.add_trace(go.Scatter(
                    x=chart_df["Label"],
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
                    x=chart_df["Label"],
                    y=[benchmark_value_category] * len(chart_df),
                    mode="lines",
                    name=f"Category Benchmark",
                    line=dict(color="purple", width=4, dash="dashdot"),
                    hovertemplate=f"<b>Category Benchmark {metric}</b><br>Value: %{{y:.4f}}<extra></extra>"
                ))
        
        fig.update_layout(
            title="",
            xaxis_title="", 
            yaxis_title=metric,
            xaxis_tickangle=45,
            showlegend=True,
            legend=dict(
                orientation="h", 
                yanchor="bottom", 
                y=1.02, 
                xanchor="right", 
                x=1,
                font=dict(size=16)  # Larger legend font size
            ),
            margin=dict(b=160, t=60),
            height=600
        )
        
    else:
        # Original chart without order performance
        if identifier_filter and len(identifier_filter) >= 1:
            chart_df["Color_Group"] = chart_df["Group_Key"].apply(
                lambda x: "Selected" if x in identifier_filter else "Others"
            )
            fig = px.bar(
                chart_df,
                x="Label",
                y=metric,
                text=metric,
                color="Color_Group",
                color_discrete_map={"Selected": bar_color, "Others": "#cccccc"},
                height=600,
                hover_data={"Impressions": ":,", "Purchases": ":,"}
            )
            fig.update_layout(
                xaxis_title="", yaxis_title=metric, xaxis_tickangle=45,
                showlegend=True, legend_title="Filter", margin=dict(b=160),
                xaxis={'categoryorder': category_order, 'tickfont': {'size': text_size}}
            )
        else:
            fig = px.bar(
                chart_df,
                x="Label",
                y=metric,
                text=metric,
                color_discrete_sequence=[bar_color], 
                height=600,
                hover_data={"Impressions": ":,", "Purchases": ":,"}
            )
            fig.update_layout(
                xaxis_title="", yaxis_title=metric, xaxis_tickangle=45,
                showlegend=False, margin=dict(b=160),
                xaxis={'categoryorder': category_order, 'tickfont': {'size': text_size}}
            )

        fig.update_traces(
            texttemplate=text_template,
            textposition="outside",
            width=bar_width
        )
        
        # Add benchmark lines if enabled (for charts without order performance)
        if show_advertiser_benchmark:
            benchmark_values = {"CTR": benchmark_ctr, "DPVR": benchmark_dpvr, "Purchase_Rate": benchmark_pr, "Promoted_ROAS": benchmark_promoted, "Total_ROAS": benchmark_total, "Total_DPVR": benchmark_total_dpvr, "Total_Purchase_Rate": benchmark_total_pr, "Subscription sign-ups": benchmark_subscriptions, "App subscription sign-ups": benchmark_app_subscriptions, "Cost per subscription": benchmark_cost_per_sub}
            benchmark_value = benchmark_values.get(metric)
            
            if benchmark_value is not None:
                fig.add_trace(go.Scatter(
                    x=chart_df["Label"],
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
                    x=chart_df["Label"],
                    y=[benchmark_value_category] * len(chart_df),
                    mode="lines",
                    name=f"Category Benchmark",
                    line=dict(color="purple", width=4, dash="dashdot"),
                    hovertemplate=f"<b>Category Benchmark {metric}</b><br>Value: {hover_y_template}<extra></extra>"
                ))
    

        
    
    st.plotly_chart(fig, use_container_width=True)

    # Creative images under chart - single row aligned under corresponding bars
    
    # Get image sizing preferences from session state or use defaults
    use_manual_size = st.session_state.get("manual_image_size", False)
    image_width = st.session_state.get("image_width_slider", 300)
    
    # Use actual number of creatives being displayed (not slider value)
    actual_creatives_shown = len(chart_df)
    
    # Handle edge case where no creatives are shown
    if actual_creatives_shown == 0:
        st.write("*No creatives to display*")
    else:
        # Use adaptive layout based on actual number of creatives to maximize image size
        if actual_creatives_shown == 1:
            # Special case for single creative - use single column
            cols = st.columns(1, gap="medium")
        elif actual_creatives_shown <= 3:
            # For 2-3 creatives: Use full width with larger images
            cols = st.columns(actual_creatives_shown, gap="medium")
        elif actual_creatives_shown <= 6:
            # For 4-6 creatives: Balanced layout with good image size
            cols = st.columns(actual_creatives_shown, gap="small")
        else:
            # For 7+ creatives: Compact layout
            cols = st.columns(actual_creatives_shown, gap="small")
        
        # Display images in the created columns
        for i, (_, r) in enumerate(chart_df.iterrows()):
            with cols[i]:
                img = _find_image_for_row(r, image_dict)
                cap = get_display_name(r.get("Group_Key") or "")
                cap = str(cap).replace("<br>", " ")
                
                # Wrap caption text for better display
                import textwrap
                width = 40 if actual_creatives_shown == 1 else 25
                cap = "\n".join(textwrap.wrap(cap, width=width)) if cap else ""
                
                if img:
                    # Display image with manual or adaptive sizing
                    if use_manual_size:
                        # Manual size control: all images same width
                        st.image(img, width=image_width)
                    else:
                        # Adaptive sizing based on number of creatives
                        if actual_creatives_shown <= 3:
                            # For few images, use larger width setting to maximize space usage
                            st.image(img, use_container_width=True, width=None)
                        else:
                            st.image(img, use_container_width=True)
                    # Display caption with larger font
                    st.markdown(f"<p style='text-align: center; font-size: 16px;'>{cap}</p>", unsafe_allow_html=True)
                else:
                    st.markdown(f"<p style='text-align: center; font-size: 16px;'><strong>{cap}</strong></p>", unsafe_allow_html=True)
                    st.write("*No image available*")
    


    # ==============================
    # 3. GRAPH DESIGN OPTIONS
    # ==============================
    st.markdown("---")
    st.markdown("### 🎨 GRAPH DESIGN OPTIONS")
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
                "Select color", 
                value=bar_color,
                help="Click the colored box to open the color picker",
                key="temp_bar_color_picker"
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
    col1, col2, col3 = st.columns([1, 1, 1])
    
    with col1:
        use_manual_size = st.checkbox(
            "Manual Image Size Control",
            value=False,
            key="manual_image_size",
            help="Override automatic sizing and set a fixed size for all images"
        )
    
    with col2:
        if use_manual_size:
            image_width = st.slider(
                "Image Width (pixels)",
                min_value=100,
                max_value=800,
                value=300,
                step=25,
                key="image_width_slider",
                help="Set the width for all images in pixels"
            )
        else:
            image_width = None
    
    with col3:
        if use_manual_size:
            st.write(f"All images: **{image_width}px** wide")

    # Tip for users about automatic updates
    if num_to_show_new != num_to_show or bar_width_new != bar_width or bar_color_new != bar_color or use_manual_size:
        st.info("💡 **Tip:** The chart and images above will update automatically as you adjust these settings. Scroll up to see the changes!")

    # ==============================
    # AD SIZE PERFORMANCE CHART
    # ==============================
    if has_size_col and size_col:
        st.markdown("---")
        st.subheader("📊 AD SIZE PERFORMANCE")
        st.markdown("Compare performance across different ad sizes.")
        
        # Dedicated filters for size analysis
        st.markdown("**Size Analysis Filters**")
        col1, col2, col3 = st.columns([2.0, 0.9, 1.1])
        
        with col1:
            # Order filter for size analysis
            size_selected_orders_display = st.multiselect(
                "Order",
                options=order_options,
                default=["All Orders"],
                key="size_order_filter",
                help="Filter by order name or campaign ID for size analysis"
            )
            
            # Extract actual order names
            size_selected_orders = []
            for display_label in size_selected_orders_display:
                if display_label == "All Orders":
                    size_selected_orders.append("All Orders")
                elif " (ID: " in display_label:
                    order_name = display_label.split(" (ID: ")[0]
                    size_selected_orders.append(order_name)
                else:
                    size_selected_orders.append(display_label)
        
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
                st.session_state.size_metric_filter = "CTR"
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
        size_agg = size_filtered_data.groupby(size_col).agg({
            "Impressions": "sum",
            "Click-throughs": "sum",
            "DPV": "sum",
            "Purchases": "sum"
        }).reset_index()
        
        # Calculate metrics
        size_agg["CTR"] = (size_agg["Click-throughs"] / size_agg["Impressions"]).fillna(0)
        size_agg["DPVR"] = (size_agg["DPV"] / size_agg["Impressions"]).fillna(0)
        size_agg["Purchase_Rate"] = (size_agg["Purchases"] / size_agg["Impressions"]).fillna(0)
        
        # Add ROAS if available
        if "Sales_USD" in size_filtered_data.columns and "Total_Cost" in size_filtered_data.columns:
            size_roas_agg = size_filtered_data.groupby(size_col).agg({
                "Sales_USD": "sum",
                "Total_Cost": "sum"
            }).reset_index()
            size_agg = size_agg.merge(size_roas_agg, on=size_col, how="left")
            size_agg["Promoted_ROAS"] = (size_agg["Sales_USD"] / size_agg["Total_Cost"]).fillna(0)
        
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
            size_agg["Total_ROAS"] = (size_agg["Total_Sales_USD"] / size_agg["Total_Cost"]).fillna(0)
        
        # Add Total DPVR and Total Purchase Rate if available
        if "Total_DPV" in size_filtered_data.columns:
            size_total_dpv_agg = size_filtered_data.groupby(size_col).agg({"Total_DPV": "sum"}).reset_index()
            size_agg = size_agg.merge(size_total_dpv_agg, on=size_col, how="left")
            size_agg["Total_DPVR"] = (size_agg["Total_DPV"] / size_agg["Impressions"]).fillna(0)
        
        if "Total_Purchases" in size_filtered_data.columns:
            size_total_purch_agg = size_filtered_data.groupby(size_col).agg({"Total_Purchases": "sum"}).reset_index()
            size_agg = size_agg.merge(size_total_purch_agg, on=size_col, how="left")
            size_agg["Total_Purchase_Rate"] = (size_agg["Total_Purchases"] / size_agg["Impressions"]).fillna(0)
        
        # Sort by selected metric for size analysis
        if size_metric in size_agg.columns:
            size_agg = size_agg.sort_values(by=size_metric, ascending=False)
        
        # Create size performance chart
        if not size_agg.empty and size_metric in size_agg.columns:
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
            size_display["CTR"] = (size_display["CTR"] * 100).map("{:.4f}%".format)
            size_display["DPVR"] = (size_display["DPVR"] * 100).map("{:.4f}%".format)
            size_display["Purchase_Rate"] = (size_display["Purchase_Rate"] * 100).map("{:.4f}%".format)
            # Format numbers with commas
            size_display["Impressions"] = size_display["Impressions"].map("{:,.0f}".format)
            size_display["Click-throughs"] = size_display["Click-throughs"].map("{:,.0f}".format)
            size_display["DPV"] = size_display["DPV"].map("{:,.0f}".format)
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

    # ==============================
    # ORDER PERFORMANCE CHART
    # ==============================
    if "Order_ID" in processed.columns:
        st.markdown("---")
        st.subheader("📈 ORDER PERFORMANCE")
        st.markdown("Compare performance across different orders/campaigns.")
        
        # Dedicated filters for order analysis
        st.markdown("**Order Analysis Filters**")
        col1, col2 = st.columns([2.1, 0.9])
        
        with col1:
            # Order filter for order analysis - select which orders to include
            order_analysis_selected_orders_display = st.multiselect(
                "Orders to Compare",
                options=order_options,
                default=["All Orders"],  # Default to all orders
                key="order_analysis_order_filter",
                help="Select which orders to include in the comparison"
            )
            
            # Extract actual order names
            order_analysis_selected_orders = []
            for display_label in order_analysis_selected_orders_display:
                if display_label == "All Orders":
                    order_analysis_selected_orders.append("All Orders")
                elif " (ID: " in display_label:
                    order_name = display_label.split(" (ID: ")[0]
                    order_analysis_selected_orders.append(order_name)
                else:
                    order_analysis_selected_orders.append(display_label)
        
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
                st.session_state.order_metric_filter = "CTR"
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
        order_agg = order_filtered_data.groupby("Order_ID").agg({
            "Impressions": "sum",
            "Click-throughs": "sum",
            "DPV": "sum",
            "Purchases": "sum"
        }).reset_index()
        
        # Calculate metrics
        order_agg["CTR"] = (order_agg["Click-throughs"] / order_agg["Impressions"]).fillna(0)
        order_agg["DPVR"] = (order_agg["DPV"] / order_agg["Impressions"]).fillna(0)
        order_agg["Purchase_Rate"] = (order_agg["Purchases"] / order_agg["Impressions"]).fillna(0)
        
        # Add ROAS if available
        if "Sales_USD" in order_filtered_data.columns and "Total_Cost" in order_filtered_data.columns:
            order_roas_agg = order_filtered_data.groupby("Order_ID").agg({
                "Sales_USD": "sum",
                "Total_Cost": "sum"
            }).reset_index()
            order_agg = order_agg.merge(order_roas_agg, on="Order_ID", how="left")
            order_agg["Promoted_ROAS"] = (order_agg["Sales_USD"] / order_agg["Total_Cost"]).fillna(0)
        
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
            order_agg["Total_ROAS"] = (order_agg["Total_Sales_USD"] / order_agg["Total_Cost"]).fillna(0)
        
        # Add Total DPVR and Total Purchase Rate if available
        if "Total_DPV" in order_filtered_data.columns:
            order_total_dpv_agg = order_filtered_data.groupby("Order_ID").agg({"Total_DPV": "sum"}).reset_index()
            order_agg = order_agg.merge(order_total_dpv_agg, on="Order_ID", how="left")
            order_agg["Total_DPVR"] = (order_agg["Total_DPV"] / order_agg["Impressions"]).fillna(0)
        
        if "Total_Purchases" in order_filtered_data.columns:
            order_total_purch_agg = order_filtered_data.groupby("Order_ID").agg({"Total_Purchases": "sum"}).reset_index()
            order_agg = order_agg.merge(order_total_purch_agg, on="Order_ID", how="left")
            order_agg["Total_Purchase_Rate"] = (order_agg["Total_Purchases"] / order_agg["Impressions"]).fillna(0)
        
        # Remove any potential duplicates and sort by selected metric
        order_agg = order_agg.drop_duplicates(subset=['Order_ID']).reset_index(drop=True)
        
        if order_metric in order_agg.columns:
            order_agg = order_agg.sort_values(by=order_metric, ascending=False).reset_index(drop=True)
        
        # Create order performance chart
        if not order_agg.empty and order_metric in order_agg.columns:
            # Truncate long order names for display
            order_agg["Order_Display"] = order_agg["Order_ID"].apply(lambda x: x[:50] + "..." if len(str(x)) > 50 else str(x))
            
            # If truncation created duplicates, make display names unique by adding suffixes
            duplicate_count = order_agg.duplicated(subset=['Order_Display']).sum()
            if duplicate_count > 0:
                # Add numeric suffix to duplicates to make them unique
                display_counts = {}
                unique_displays = []
                for display in order_agg['Order_Display']:
                    if display in display_counts:
                        display_counts[display] += 1
                        unique_displays.append(f"{display} ({display_counts[display]})")
                    else:
                        display_counts[display] = 1
                        unique_displays.append(display)
                order_agg['Order_Display'] = unique_displays
            
            # Format text based on metric type
            if order_metric in ["CTR", "DPVR", "Purchase_Rate", "Total_DPVR", "Total_Purchase_Rate"]:
                text_template = "%{y:.4f}"
            else:
                text_template = "%{y:.2f}"
            
            # Create figure with go.Bar for explicit control
            fig_order = go.Figure()
            fig_order.add_trace(go.Bar(
                x=order_agg["Order_Display"],
                y=order_agg[order_metric],
                text=order_agg[order_metric].round(4 if order_metric in ["CTR", "DPVR", "Purchase_Rate", "Total_DPVR", "Total_Purchase_Rate"] else 2),
                texttemplate=text_template,
                textposition="outside",
                marker=dict(color=bar_color),
                hovertemplate="<b>%{x}</b><br>" + metric_labels.get(order_metric, order_metric) + ": " + text_template + "<extra></extra>",
                name=""
            ))
            
            fig_order.update_layout(
                title="",
                xaxis_title="Order / Campaign",
                yaxis_title=metric_labels.get(order_metric, order_metric),
                xaxis_tickangle=45,
                showlegend=False,
                margin=dict(b=150, t=40),
                height=400
            )
            
            st.plotly_chart(fig_order, use_container_width=True)
            
            # Show order summary table
            st.markdown("**Order Performance Summary**")
            order_display = order_agg.copy()
            # Format percentages (multiply by 100 for display)
            order_display["CTR"] = (order_display["CTR"] * 100).map("{:.4f}%".format)
            order_display["DPVR"] = (order_display["DPVR"] * 100).map("{:.4f}%".format)
            order_display["Purchase_Rate"] = (order_display["Purchase_Rate"] * 100).map("{:.4f}%".format)
            # Format numbers with commas
            order_display["Impressions"] = order_display["Impressions"].map("{:,.0f}".format)
            order_display["Click-throughs"] = order_display["Click-throughs"].map("{:,.0f}".format)
            order_display["DPV"] = order_display["DPV"].map("{:,.0f}".format)
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



    # Notepad
    # ==============================
    st.markdown("---")
    st.subheader("NOTEPAD")
    
    # AI Creative Analysis Section
    ai_analysis_enabled = st.checkbox(
        "🤖 AI Creative Analysis",
        value=False,
        help="Get AI-powered analysis of creative design elements"
    )
    
    if ai_analysis_enabled:
        # Create dropdown for creative selection
        creative_options = []
        if not chart_df.empty:
            creative_options = [f"{row['Group_Key']}" for _, row in chart_df.iterrows()]
        
        if creative_options:
            selected_creative = st.selectbox(
                "Select Creative for AI Analysis:",
                options=creative_options,
                key="ai_analysis_creative"
            )
            
            # Find the selected creative's data and image
            selected_row = chart_df[chart_df['Group_Key'] == selected_creative].iloc[0]
            selected_image = _find_image_for_row(selected_row, image_dict)
            
            col1, col2 = st.columns([1, 2])
            
            with col1:
                if selected_image:
                    st.image(selected_image, caption=get_display_name(selected_creative), use_container_width=True)
                else:
                    st.write("*No image available for analysis*")
            
            with col2:
                if selected_image and st.button("🔍 Analyze Creative", key="analyze_btn"):
                    with st.spinner("Analyzing creative design elements..."):
                        # AI Analysis (simulated for now - can be replaced with actual AI service)
                        analysis = f"""
**AI Creative Analysis for: {selected_creative}**

**Visual Complexity:** {'Simple & Clean' if 'simple' in selected_creative.lower() else 'Detailed & Busy'}

**Color Palette:** {'Bright & Vibrant' if any(word in selected_creative.lower() for word in ['bright', 'colorful', 'vibrant']) else 'Neutral & Subdued'}

**Imagery Focus:** {'Product-Focused' if any(word in selected_creative.lower() for word in ['product', 'item', 'bottle', 'package']) else 'Lifestyle-Oriented'}

**Text Density:** {'Minimal Text' if len(selected_creative) < 20 else 'Text-Heavy'}

**Design Style:** {'Modern & Minimalist' if any(word in selected_creative.lower() for word in ['clean', 'simple', 'minimal']) else 'Traditional & Detailed'}

**Recommendations:**
• Consider A/B testing against simpler/more complex variations
• Evaluate color contrast for better visibility
• Test product vs lifestyle imagery approaches
• Optimize text-to-visual ratio for target audience

*Note: Analysis based on creative naming patterns and visual assessment. For deeper insights, consider professional creative testing.*
                        """
                    
                    st.markdown(analysis)
                    
                    # Add to notepad option
                    if st.button("📝 Add Analysis to Notepad", key="add_to_notes"):
                        if 'user_notes' not in st.session_state:
                            st.session_state.user_notes = ""
                        st.session_state.user_notes += f"\n\n{analysis}"
                        st.success("✅ Analysis added to notepad!")
        else:
            st.info("No creatives available for analysis. Please ensure images are uploaded and chart data is available.")
    
    # Regular notepad section
    default_prompt = (
        "Compare high vs low performers:\n"
        "- Color palette\n"
        "- Layout\n"
        "- Copy\n"
        "- CTA placement\n"
        "- ASIN prominence"
    )
    if 'user_notes' not in st.session_state:
        st.session_state.user_notes = default_prompt
    user_notes = st.text_area("Jot down observations...", value=st.session_state.user_notes, height=200, key="notes")
    st.session_state.user_notes = user_notes
    st.download_button("Download Notes", user_notes, "creative_insights.txt", "text/plain")

    # ==============================
    # Full Table
    # ==============================
    st.subheader(f"ALL RESULTS (n={total_creatives})")
    
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
    
    disp_cols = ["Creative Identifier", "Full Creative Name", "Impressions", "Click-throughs",
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

    # Add editable creative identifier functionality
    st.markdown("**💡 Tip:** Click on any Creative Identifier below to edit it. Changes will automatically update the chart, filters, and image captions.")
    
    # Create editable interface for creative identifiers
    st.markdown("**Edit Creative Identifiers:**")
    col_count = min(3, len(table_df))
    if col_count > 0:
        cols = st.columns(col_count)
        
        for idx, (_, row) in enumerate(table_df.iterrows()):
            if row["Creative Identifier"] == "📊 TOTALS":  # Skip totals row
                continue
                
            with cols[idx % col_count]:
                original_name = row["Creative Identifier"]
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
                    st.rerun()
    

    
    # Update the Creative Identifier column with edited names
    table_df["Creative Identifier"] = table_df["Creative Identifier"].apply(
        lambda x: get_display_name(x) if x != "📊 TOTALS" else x
    )

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
        "Full Creative Name": f"All {total_creatives} Creatives",
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
    
    st.dataframe(styled, use_container_width=True)

    # CSV download (use original column names)
    csv_data = sorted_df.to_csv(index=False)
    st.download_button("Download Full Results CSV", csv_data, "creative_analytics.csv", "text/csv")

# ==============================
# User Feedback Section
# ==============================
st.markdown("---")
st.markdown("### 📢 Submit Feedback on Slack")

# Slack invitation highlight box
st.markdown(
    """
    <div style="background-color: #E6F2FF; 
                border-left: 6px solid #0066CC;
                color: #003366; 
                padding: 20px 30px; 
                font-size: 26px;
                font-weight: bold;
                margin: 3px 0;
                max-width: 700px;">
        💬 JOIN <i>#</i>CCM-CREATIVE-ANALYSIS-TOOL ON SLACK
    </div>
    """,
    unsafe_allow_html=True
)

st.markdown("Your feedback helps us understand the tool's impact and make it even better!")

# ==============================
# Footer
# ==============================
st.markdown("---")
st.caption("Slack Ericka Sawhney @esawhney for feedback or questions")
