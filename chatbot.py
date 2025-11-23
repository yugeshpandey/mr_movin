import re
from typing import Optional, Tuple, Literal, List

from recommender import (
    filter_by_budget,
    cheapest_metros,
    most_expensive_metros,
    best_rent_growth,
    compare_metros,
    available_states,
)

# -----------------------
#  Helpers: parsing & intent
# -----------------------

_US_STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
}


def _parse_budget(text: str) -> Optional[float]:
    """Extract a numeric monthly budget from text."""
    cleaned = text.replace(",", "").replace("$", " ")
    nums = re.findall(r"(\d+\.?\d*)", cleaned)
    if not nums:
        return None
    for n in nums:
        try:
            value = float(n)
        except ValueError:
            continue
        if 300 <= value <= 20000:
            return value
    try:
        return float(nums[0])
    except ValueError:
        return None


def _parse_state(text: str) -> Optional[str]:
    """
    Try to pull a US state code from the text (2-letter code).

    Rules:
    - Prefer explicit patterns like 'in CA', 'in tx' (case-insensitive).
    - Then look for 2-letter tokens that are ALL CAPS in the *original* text,
      e.g. 'Portland, ME'. This avoids treating 'me' in 'show me' as Maine.
    """
    # 1) Explicit "in XX" pattern
    match = re.search(r"\bin\s+([A-Za-z]{2})\b", text, flags=re.IGNORECASE)
    if match:
        code = match.group(1).upper()
        if code in _US_STATES:
            return code

    # 2) Standalone 2-letter tokens that are all caps in original text
    for token in re.findall(r"\b([A-Za-z]{2})\b", text):
        if token.isupper():
            code = token.upper()
            if code in _US_STATES:
                return code

    return None


def _parse_compare_request(text: str) -> Optional[Tuple[str, str]]:
    """Rough parsing of 'compare X and Y' type requests."""
    if "compare" not in text.lower():
        return None
    parts = re.split(r"\band\b", text, flags=re.IGNORECASE)
    if len(parts) < 2:
        return None
    a = re.sub(r"^compare", "", parts[-2], flags=re.IGNORECASE).strip(",. ")
    b = parts[-1].strip(",. ")
    return (a, b) if a and b else None


def _is_cheapest_request(text: str) -> bool:
    t = text.lower()
    return any(
        kw in t
        for kw in [
            "cheapest",
            "low cost",
            "least expensive",
            "most affordable",
            "affordable metros",
        ]
    )


def _is_most_expensive_request(text: str) -> bool:
    t = text.lower()
    return any(
        kw in t for kw in ["most expensive", "high cost", "priciest", "top expensive"]
    )


def _parse_growth_intent(
    text: str,
) -> Optional[Tuple[Literal["3y", "5y"], Literal["up", "down"]]]:
    """
    Detect if the user is asking about up-and-coming or declining markets.
    """
    t = text.lower()
    if any(kw in t for kw in ["up-and-coming", "up and coming", "rising", "growing"]):
        direction = "up"
    elif any(kw in t for kw in ["declining", "falling", "going down", "cooling"]):
        direction = "down"
    else:
        return None
    if "5 year" in t or "five year" in t or "5-year" in t:
        horizon = "5y"
    else:
        horizon = "3y"
    return horizon, direction


def _is_greeting(text: str) -> bool:
    t = text.lower().strip()
    greetings = [
        "hi",
        "hello",
        "hey",
        "yo",
        "hi there",
        "good morning",
        "good evening",
    ]
    return t in greetings or t.startswith(("hi ", "hello ", "hey "))


def _is_relocation_related(text: str) -> bool:
    """
    Heuristic: is this message about rent / relocation / metros?
    """
    t = text.lower()
    keywords = [
        "rent",
        "rental",
        "apartment",
        "flat",
        "housing",
        "move",
        "moving",
        "relocate",
        "relocation",
        "city",
        "metro",
        "neighborhood",
        "budget",
        "cheapest",
        "affordable",
        "expensive",
        "compare",
        "cost of living",
        "up-and-coming",
        "up and coming",
        "declining",
    ]
    return any(kw in t for kw in keywords)


def _fallback_help_message() -> str:
    examples = [
        "I have a $2,500 monthly rent budget and want an apartment in California.",
        "Show me some of the cheapest metros in the US.",
        "Compare Seattle, WA and Austin, TX.",
        "What are some up-and-coming rental markets over the last 3 years?",
        "Find metros under $1,800 per month in TX.",
    ]
    lines = [
        "I'm here to help with apartment hunting, rent levels, and relocation decisions based on rental data. 😊",
        "",
        "Here are some example questions to try:",
    ]
    lines += [f"- {ex}" for ex in examples]
    lines.append(
        "\nIf you ask about a rent budget, a city or state, or compare metros, "
        "I’ll give you data-driven recommendations."
    )
    return "\n".join(lines)


def _state_not_in_data_message(state: str, states_in_data: List[str]) -> str:
    """
    Build a friendly message when the user asks for a state that
    doesn't exist in the dataset.
    """
    lines = [
        f"I couldn't find any rental data for the state '{state}' in this dataset.",
        "",
    ]
    if states_in_data:
        lines.append("Here are some states I *do* have data for:")
        lines += [f"- {s}" for s in sorted(states_in_data)]
        lines.append(
            "\nYou can ask about one of these states (e.g. '$2500 in CA'), "
            "or leave out the state entirely to see results across the whole country."
        )
    else:
        lines.append(
            "It looks like there are no state-level entries in the current dataset."
        )
    return "\n".join(lines)


# -----------------------
#  MAIN CHAT FUNCTION
# -----------------------

def chat(message: str, history: Optional[List[dict]] = None) -> str:
    """
    Core chat function — returns a plain string (no LLM polishing).
    """
    message = (message or "").strip()

    # 1) Empty → greeting
    if not message:
        return (
            "Hi there! 👋 I'm your Apartment Relocation Assistant.\n\n"
            "Tell me your monthly rent budget and a place you're interested in, "
            "or ask me to compare two metros like 'Compare Seattle and Austin'."
        )

    # 2) User greeting → friendly greeting
    if _is_greeting(message):
        return (
            "Hello! 👋 I'm here to help you explore US metros using rental data.\n\n"
            "Tell me your rent budget, ask for the cheapest metros, or ask me to compare cities!"
        )

    # 3) Off-topic → fallback (NO LLM)
    if not _is_relocation_related(message):
        return _fallback_help_message()

    # 4) Parse state once and validate against the dataset
    state = _parse_state(message)
    if state:
        try:
            raw_states = available_states() or []
            states_in_data = {
                str(s).strip().upper() for s in raw_states if str(s).strip()
            }
        except Exception:
            states_in_data = set()

        if states_in_data and state not in states_in_data:
            # Valid US state code, but not present in the dataset
            return _state_not_in_data_message(state, sorted(states_in_data))

    # --- From here on, use `state` in all branches ---

    # Compare
    pair = _parse_compare_request(message)
    if pair:
        metro_a, metro_b = pair
        results = compare_metros(metro_a, metro_b)
        info_a, info_b = results["a"], results["b"]

        if not info_a and not info_b:
            return (
                f"I couldn’t find either '{metro_a}' or '{metro_b}' in the dataset. "
                "Try using full metro names like 'Seattle, WA'."
            )

        if not info_a or not info_b:
            missing = metro_a if not info_a else metro_b
            return (
                f"I found one metro but not '{missing}'. "
                "Try using the format 'City, ST' (e.g. 'Austin, TX')."
            )

        def fmt(meta):
            name = meta.get("RegionName", "(unknown)")
            st = meta.get("State", "")
            current = meta.get("Current_Rent", None)
            r3 = meta.get("rent_3yr_pct_change", None)
            r5 = meta.get("rent_5yr_pct_change", None)
            parts = []
            if current is not None:
                parts.append(f"~${current:,.0f} avg monthly rent")
            if r3 is not None:
                parts.append(f"{r3:+.1f}% over 3 years")
            if r5 is not None:
                parts.append(f"{r5:+.1f}% over 5 years")
            joined = "; ".join(parts) if parts else "no data"
            return f"{name} ({st}) — {joined}"

        text_a, text_b = fmt(info_a), fmt(info_b)
        diff = (info_b.get("Current_Rent") or 0) - (info_a.get("Current_Rent") or 0)
        more = "more" if diff > 0 else "less"
        diff_abs = abs(diff)

        result = (
            "Here's a comparison based on current rents:\n\n"
            f"- {text_a}\n"
            f"- {text_b}\n\n"
        )
        if diff_abs > 0:
            result += (
                f"{info_b['RegionName']} is about ${diff_abs:,.0f} {more} "
                f"expensive per month."
            )
        else:
            result += "Both metros have similar rent levels in this dataset."

        return result

    # Growth (up-and-coming or declining)
    growth = _parse_growth_intent(message)
    if growth:
        horizon, direction = growth
        df = best_rent_growth(limit=10, horizon=horizon, direction=direction, state=state)

        if df.empty:
            return "I couldn't find metros matching that growth pattern in the dataset."

        desc = "up-and-coming" if direction == "up" else "declining"
        horizon_desc = "5 years" if horizon == "5y" else "3 years"
        col = "rent_5yr_pct_change" if horizon == "5y" else "rent_3yr_pct_change"

        lines = [f"Here are some {desc} metros over the last {horizon_desc}:\n"]
        for _, row in df.iterrows():
            name = row["RegionName"]
            st = row.get("State", "")
            pct = row[col]
            current = row.get("Current_Rent", None)
            if current is not None:
                lines.append(
                    f"- {name} ({st}) — ~${current:,.0f} now, {pct:+.1f}% change"
                )
            else:
                lines.append(f"- {name} ({st}) — {pct:+.1f}% change")

        if state:
            lines.append(f"\n(Filtered to {state}.)")

        return "\n".join(lines)

    # Cheapest
    if _is_cheapest_request(message):
        df = cheapest_metros(limit=10, state=state)

        if df.empty:
            return "I couldn't find any metros in the dataset for that request."

        lines = ["Here are some of the cheapest metros by current average rent:\n"]
        for _, row in df.iterrows():
            lines.append(
                f"- {row['RegionName']} ({row.get('State','')}) — "
                f"~${row['Current_Rent']:,.0f} per month"
            )

        if state:
            lines.append(f"\n(Filtered to {state}.)")

        return "\n".join(lines)

    # Most expensive
    if _is_most_expensive_request(message):
        df = most_expensive_metros(limit=10, state=state)

        if df.empty:
            return "I couldn't find any metros in the dataset for that request."

        lines = ["Here are some of the most expensive metros by current average rent:\n"]
        for _, row in df.iterrows():
            lines.append(
                f"- {row['RegionName']} ({row.get('State','')}) — "
                f"~${row['Current_Rent']:,.0f} per month"
            )

        if state:
            lines.append(f"\n(Filtered to {state}.)")

        return "\n".join(lines)

    # Budget-based (default path)
    budget = _parse_budget(message)

    if budget is None:
        df = cheapest_metros(limit=10, state=state)
        if df.empty:
            return (
                "I couldn't find any metros in the dataset. "
                "Try asking about the cheapest metros or providing a rent budget."
            )

        lines = [
            "I didn’t see a clear budget, so here are some of the cheaper metros by current rent:\n"
        ]
        for _, row in df.iterrows():
            lines.append(
                f"- {row['RegionName']} ({row.get('State','')}) — "
                f"~${row['Current_Rent']:,.0f} per month"
            )

        lines.append(
            "\nTell me your rent budget (e.g. '$2500 in CA') and I’ll filter results further."
        )

        return "\n".join(lines)

    df = filter_by_budget(budget, state=state)
    if df.empty:
        return (
            f"I couldn’t find metros with average rent under about ${budget:,.0f}. "
            "Try increasing your budget or omitting the state filter."
        )

    df = df.head(10)

    if state:
        head = (
            f"Here are metros in {state} with average monthly rent roughly "
            f"under your budget of ~${budget:,.0f}:\n"
        )
    else:
        head = (
            f"Here are metros with average monthly rent roughly under your "
            f"budget of ~${budget:,.0f}:\n"
        )

    lines = [head]
    for _, row in df.iterrows():
        lines.append(
            f"- {row['RegionName']} ({row.get('State','')}) — "
            f"~${row['Current_Rent']:,.0f} per month, trend: {row.get('trend_label','unknown')}"
        )

    lines.append(
        "\nYou can also ask about trends or compare specific metros."
    )

    return "\n".join(lines)
