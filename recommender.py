import os
from typing import Optional, Dict, Literal, List

import pandas as pd

# ---- Configuration ----
_DATA_FILENAME = "new cleaned data.csv"

# Cache for the loaded DataFrame
_DATA_CACHE: Optional[pd.DataFrame] = None


def _get_data_path() -> str:
    """
    Resolve the path to the cleaned rent dataset.

    We first look for the CSV in the same folder as this file.
    If not found, we look for it in a "data" subfolder, and finally
    fall back to the current working directory.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    direct_path = os.path.join(here, _DATA_FILENAME)
    if os.path.exists(direct_path):
        return direct_path

    data_path = os.path.join(here, "data", _DATA_FILENAME)
    if os.path.exists(data_path):
        return data_path

    return _DATA_FILENAME


def _compute_growth_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add growth-related columns to the DataFrame in-place and return it.

    compute:
        - rent_3yr_change / rent_3yr_pct_change (2022 -> Current)
        - rent_5yr_change / rent_5yr_pct_change (2021 -> Current)
        - trend_label: 'rising' / 'flat' / 'falling' based on 3yr % change
    """
    df = df.copy()

    # 3-year: 2022 -> Current
    if {"2022_Avg_Rent", "Current_Rent"}.issubset(df.columns):
        df["rent_3yr_change"] = df["Current_Rent"] - df["2022_Avg_Rent"]
        df["rent_3yr_pct_change"] = (
            (df["rent_3yr_change"] / df["2022_Avg_Rent"]) * 100.0
        )

    # 5-year: 2021 -> Current
    if {"2021_Avg_Rent", "Current_Rent"}.issubset(df.columns):
        df["rent_5yr_change"] = df["Current_Rent"] - df["2021_Avg_Rent"]
        df["rent_5yr_pct_change"] = (
            (df["rent_5yr_change"] / df["2021_Avg_Rent"]) * 100.0
        )

    # Simple trend label from 3-year % change
    def _label_trend(pct: float) -> str:
        if pd.isna(pct):
            return "unknown"
        if pct > 10:
            return "rising"
        if pct < -5:
            return "falling"
        return "flat"

    if "rent_3yr_pct_change" in df.columns:
        df["trend_label"] = df["rent_3yr_pct_change"].apply(_label_trend)
    else:
        df["trend_label"] = "unknown"

    return df


def load_data() -> pd.DataFrame:
    """
    Load the cleaned rent dataset with growth columns, cached in memory.

    Expected CSV columns:
        City, StateName, 2021_Avg_Rent, 2022_Avg_Rent, 2023_Avg_Rent,
        2024_Avg_Rent, 2025_Avg_Rent, Current_Rent

    We normalize these to internal names:
        City      -> RegionName
        StateName -> State
    """
    global _DATA_CACHE
    if _DATA_CACHE is None:
        data_path = _get_data_path()
        df = pd.read_csv(data_path)

        # Normalize column names to internal names
        df = df.rename(
            columns={
                "StateName": "State",
                "City": "RegionName",
            }
        )

        # Ensure numeric columns are floats
        rent_cols = [
            c
            for c in df.columns
            if "Rent" in c or "Avg_Rent" in c or c == "Current_Rent"
        ]
        for col in rent_cols:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        df = _compute_growth_columns(df)
        _DATA_CACHE = df

    return _DATA_CACHE


def filter_by_budget(
    monthly_budget: float,
    state: Optional[str] = None,
    trend: Optional[Literal["rising", "flat", "falling"]] = None,
    include_us_aggregate: bool = False,
) -> pd.DataFrame:
    """
    Filter metros whose Current_Rent is <= monthly_budget.

    Args:
        monthly_budget: User's monthly rent budget in dollars.
        state: Optional state filter (2-letter code, e.g. 'CA').
        trend: Optional trend filter: 'rising', 'flat', or 'falling'.
        include_us_aggregate: whether to include 'United States' aggregate row.

    Returns:
        DataFrame sorted by Current_Rent ascending.
    """
    df = load_data().copy()

    # Filter out United States aggregate row by default
    if not include_us_aggregate and "RegionName" in df.columns:
        df = df[df["RegionName"] != "United States"]

    df = df[df["Current_Rent"].notna()]
    df = df[df["Current_Rent"] <= monthly_budget]

    if state and "State" in df.columns:
        state = state.upper()
        df = df[df["State"].fillna("").str.upper() == state]

    if trend and "trend_label" in df.columns:
        df = df[df["trend_label"] == trend]

    df = df.sort_values("Current_Rent", ascending=True)
    return df


def cheapest_metros(
    limit: int = 10,
    state: Optional[str] = None,
    include_us_aggregate: bool = False,
) -> pd.DataFrame:
    """
    Return the cheapest metros by Current_Rent.
    """
    df = load_data().copy()

    if not include_us_aggregate and "RegionName" in df.columns:
        df = df[df["RegionName"] != "United States"]

    if state and "State" in df.columns:
        state = state.upper()
        df = df[df["State"].fillna("").str.upper() == state]

    df = df[df["Current_Rent"].notna()]
    df = df.sort_values("Current_Rent", ascending=True)

    return df.head(limit)


def most_expensive_metros(
    limit: int = 10,
    state: Optional[str] = None,
    include_us_aggregate: bool = False,
) -> pd.DataFrame:
    """
    Return the most expensive metros by Current_Rent.
    """
    df = load_data().copy()

    if not include_us_aggregate and "RegionName" in df.columns:
        df = df[df["RegionName"] != "United States"]

    if state and "State" in df.columns:
        state = state.upper()
        df = df[df["State"].fillna("").str.upper() == state]

    df = df[df["Current_Rent"].notna()]
    df = df.sort_values("Current_Rent", ascending=False)

    return df.head(limit)


def best_rent_growth(
    limit: int = 10,
    horizon: Literal["3y", "5y"] = "3y",
    direction: Literal["up", "down"] = "up",
    state: Optional[str] = None,
    include_us_aggregate: bool = False,
) -> pd.DataFrame:
    """
    Return metros with the strongest rising or declining rents.

    horizon:
        "3y" → use rent_3yr_pct_change
        "5y" → use rent_5yr_pct_change

    direction:
        "up"   → highest positive growth
        "down" → lowest/most negative growth
    """
    df = load_data().copy()

    if not include_us_aggregate and "RegionName" in df.columns:
        df = df[df["RegionName"] != "United States"]

    if state and "State" in df.columns:
        state = state.upper()
        df = df[df["State"].fillna("").str.upper() == state]

    if horizon == "3y":
        col = "rent_3yr_pct_change"
    else:
        col = "rent_5yr_pct_change"

    if col not in df.columns:
        return df.iloc[0:0].copy()  # empty

    df = df[df[col].notna()]

    ascending = direction == "down"
    df = df.sort_values(col, ascending=ascending)

    return df.head(limit)


def available_states() -> List[str]:
    """
    Return a sorted list of state codes that exist in the dataset.
    """
    df = load_data()
    if "State" not in df.columns:
        return []
    states = (
        df["State"]
        .dropna()
        .astype(str)
        .str.strip()
        .str.upper()
        .unique()
        .tolist()
    )
    states = [s for s in states if s]
    return sorted(states)


def compare_metros(metro_a: str, metro_b: str) -> Dict[str, Optional[Dict]]:
    """
    Compare two metros by name.

    Matching is case-insensitive:
      1. Exact match on RegionName
      2. Fallback to "contains" search on RegionName

    Returns:
        {
          "a": { ... row for metro_a ... } or None,
          "b": { ... row for metro_b ... } or None
        }
    """
    df = load_data()

    def _find(metro: str) -> Optional[Dict]:
        if "RegionName" not in df.columns:
            return None

        # Exact match
        exact = df[df["RegionName"].str.lower() == metro.lower()]
        if not exact.empty:
            return exact.iloc[0].to_dict()

        # Contains
        subset = df[df["RegionName"].str.lower().str.contains(metro.lower())]
        if not subset.empty:
            return subset.iloc[0].to_dict()

        return None

    info_a = _find(metro_a)
    info_b = _find(metro_b)

    return {"a": info_a, "b": info_b}
