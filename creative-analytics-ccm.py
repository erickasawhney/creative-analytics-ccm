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
st.set_page_config(page_title="CREATIVE ANALYTICS TOOL", page_icon="chart_with_upwards_trend", layout="wide")
st.title("CREATIVE ANALYTICS TOOL")
# Show usage as an ordered list so each step is on its own row
st.markdown(
    """
How to use:

1. Download Amazon DSP report (click 'select all' so all columns are included in report)
2. Download creative images (JPGs) and name them by creative identifier (Recommend all same size)
4. Upload the report and images below
5. Select filters
5. Enjoy!
"""
)

# ==============================
# GET CREATIVE IDENTIFIER 
# ==============================
# To get the creative identifier, perform the following steps: 
# for each row in the input file, seperate creative column by underscores
#   get the last two entries
#   group the entries into DCP and creative Identifier
#   if creative identifier is not found, use the DCP as the creative identifier
# aggregate by (creative identifier, end year)
def get_group_key(text):
    txt = str(text or "").strip()
    txt_lower = txt.lower()

    # New behavior per top-of-file comment:
    # - split the creative name on underscores
    # - take the last two entries as [DCP, Creative Identifier]
    # - return the Creative Identifier when present, otherwise fall back to the DCP
    # - if no underscore parts exist or they are empty, fall back to previous heuristics
    if '_' in txt:
        parts = [p.strip() for p in txt.split('_') if p.strip()]
        if parts:
            # Many filenames contain DCP codes and creative identifiers in varying order,
            # for example: '..._fall seasonal_DCP03903799' or '..._DCP03640867_Frozen Breakfast BTS'.
            # Heuristic: remove any token that looks like a DCP (e.g., starts with 'DCP' followed by digits
            # or is a long numeric token), then take the last remaining token as the creative id.
            def _looks_like_dcp(s):
                if not s:
                    return False
                s_low = s.lower()
                if re.search(r"\bdcp\d+\b", s_low):
                    return True
                # numeric-only tokens of length >= 5 are also likely IDs
                if re.fullmatch(r"\d{5,}", s_low):
                    return True
                return False

            # clean trailing punctuation/spaces
            def _clean_token(s):
                if not s:
                    return ""
                s = re.sub(r"[^0-9A-Za-z \-_.]+", "", s)
                s = re.sub(r"[-_.\s]+$", "", s).strip()
                return s

            # Identify and remove DCP-like tokens
            non_dcp_parts = [p for p in parts if not _looks_like_dcp(p)]

            # Prefer last non-DCP token as creative id if available; otherwise fall back to second-last token
            if non_dcp_parts:
                creative_candidate = non_dcp_parts[-1]
            elif len(parts) >= 2:
                creative_candidate = parts[-2]
            else:
                creative_candidate = parts[-1]

            creative_clean = _clean_token(creative_candidate)
            if creative_clean:
                return creative_clean

    # Fallback: try a tokenized heuristic similar to previous behavior
    stop_words = {"image", "static", "class", "sov", "ad", "v1", "v2", "copy", "final", "png", "jpg"}
    words = [w for w in re.split(r"[_.-]+", txt) if w and w.lower() not in stop_words and len(w) > 1]
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

        # Detect Sales USD, Total Sales USD and Total Cost columns for ROAS calculation
        sales_col = find_column(df, ["sales usd", "sales", "revenue", "revenue usd"])
        total_sales_col = find_column(df, ["total sales usd", "total sales", "total_sales", "total_sales_usd"])
        cost_col = find_column(df, ["total cost", "cost", "spend", "media cost"])

        # Detect start/end date columns (common names). Keep as Start_Date / End_Date
        start_col = find_column(df, ["line item start date", "start date", "start_date", "line_item_start_date", "start"])
        end_col = find_column(df, ["line item end date", "end date", "end_date", "line_item_end_date", "end"])

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
        if sales_col:    rename_map[sales_col]    = "Sales_USD"
        if total_sales_col: rename_map[total_sales_col] = "Total_Sales_USD"
        if cost_col:     rename_map[cost_col]     = "Total_Cost"
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

        # Process Sales, Total Sales, DPV, Purchases and Cost columns (keep as float for numeric calcs)
        for col in ["Sales_USD", "Total_Sales_USD", "Total_Cost", "DPV", "Total_DPV", "Purchases", "Total_Purchases"]:
            if col not in df.columns:
                # For counts like DPV/Purchases keep as ints where appropriate later; initialize to 0.0 for safe math
                df[col] = 0.0
            else:
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

        if "Order_ID" in df.columns:
            df["Order_ID"] = df["Order_ID"].astype(str).str.strip()
            df["Order_ID"] = df["Order_ID"].replace({"nan": "", "<NA>": ""}).str.strip()
            df["Order_ID"] = df["Order_ID"].replace({"": None})

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
        "Creative": "first",
    }
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
    # denom uses Impressions (as the app currently uses Impressions for promoted rates)
    denom = grp["Impressions"].replace(0, 1)
    # Promoted (existing) DPVR/Purchase_Rate are already computed above (DPV/Purchases)
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

    grp = grp.rename(columns={"Creative": "Full_Creative_Name"})

    def make_group_key(row):
        cid = row.get("Creative_ID")
        s = row.get("End_Year") or ""
        if cid:
            return f"{cid} | {s}".strip(" | ")
        return f"{s}".strip()

    grp["Group_Key"] = grp.apply(make_group_key, axis=1)

    # Reorder columns to keep compatibility
    base_cols = ["Group_Key", "Creative_ID", "Full_Creative_Name", "Impressions", "Click-throughs", "CTR", "DPV", "DPVR", "Purchases", "Purchase_Rate", "Sales_USD", "Total_Cost"]
    # include End_Year column near the front
    front = ["End_Year"]

    # Ensure financial, ROAS, and total-rate columns are present in order if they exist
    for extra in ["Total_Sales_USD", "Promoted_ROAS", "Total_ROAS", "Total_DPV", "Total_DPVR", "Total_Purchases", "Total_Purchase_Rate"]:
        if extra in grp.columns and extra not in base_cols:
            base_cols.append(extra)

    col_order = front + base_cols
    col_order = [c for c in col_order if c in grp.columns]
    return grp[col_order]

def calculate_order_performance(df):
    """Calculate overall performance metrics for each order"""
    if df is None or df.empty or "Order_ID" not in df.columns:
        return {}
    
    # Filter out rows without Order_ID
    order_df = df[df["Order_ID"].notna() & (df["Order_ID"] != "")].copy()
    if order_df.empty:
        return {}
    
    # Aggregate metrics by Order_ID
    agg_dict = {
        "Impressions": "sum",
        "Click-throughs": "sum", 
        "DPV": "sum",
        "Total_DPV": "sum",
        "Purchases": "sum",
        "Total_Purchases": "sum"
    }
    
    # Add Sales and Cost columns if they exist
    if "Sales_USD" in order_df.columns:
        agg_dict["Sales_USD"] = "sum"
    if "Total_Cost" in order_df.columns:
        agg_dict["Total_Cost"] = "sum"
    if "Total_DP```
