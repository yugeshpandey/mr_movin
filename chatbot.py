import re
from typing import Optional, Tuple, Literal, List

from recommender import (
    filter_by_budget,
    cheapest_metros,
    most_expensive_metros,
    best_rent_growth,
    compare_metros,
)
from llm_helpers import polish_response


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
    cleaned = text.replace(",", "").replace("$", " ")
    nums = re.findall(r"(\d+\.?\d*)", cleaned)
    if not nums:
        return None
    for n in nums:
        try: value = float(n)
        except: continue
        if 300 <= value <= 20000:
            return value
    try: return float(nums[0])
    except: return None


def _parse_state(text: str) -> Optional[str]:
    t = text.upper()
    possible = re.findall(r"\b([A-Z]{2})\b", t)
    for code in possible:
        if code in _US_STATES:
            return code
    match = re.search(r"\bin\s+([A-Za-z]{2})\b", text, flags=re.IGNORECASE)
    if match:
        code = match.group(1).upper()
        if code in _US_STATES:
            return code
    return None


def _parse_compare_request(text: str) -> Optional[Tuple[str, str]]:
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
    return any(kw in t for kw in
        ["cheapest", "low cost", "least expensive", "most affordable", "affordable metros"]
    )


def _is_most_expensive_request(text: str) -> bool:
    t = text.lower()
    return any(kw in t for kw in
        ["most expensive", "high cost", "priciest", "top expensive"]
    )


def _parse_growth_intent(text: str):
    t = text.lower()
    if any(kw in t for kw in ["up-and-coming", "up and coming", "rising", "growing"]):
        direction = "up"
    elif any(kw in t for kw in ["declining", "falling", "going down", "cooling"]):
        direction = "down"
    else:
        return None

    horizon = "5y" if any(kw in t for kw in ["5 year", "five year", "5-year"]) else "3y"
    return horizon, direction


def _is_greeting(text: str) -> bool:
    """Detect simple greetings."""
    t = text.lower().strip()
    greetings = ["hi", "hello", "hey", "yo", "hi there", "good morning", "good evening"]
    return t in greetings or t.startswith(("hi ", "hello ", "hey "))


def _is_relocation_related(text: str) -> bool:
    t = text.lower()
    keywords = [
        "rent","rental","apartment","flat","housing","move","relocate","relocation",
        "city","metro","neighborhood","budget","cheapest","affordable","expensive",
        "compare","cost of living","up-and-coming","up and coming","declining",
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


# -----------------------
#  MAIN CHAT FUNCTION
# -----------------------

def chat(message: str, history: Optional[List[dict]] = None) -> str:
    message = (message or "").strip()

    # 1) Empty → greeting
    if not message:
        raw = (
            "Hi there! 👋 I'm your Apartment Relocation Assistant.\n\n"
            "Tell me your monthly rent budget and a place you're interested in, "
            "or ask me to compare two metros like 'Compare Seattle and Austin'."
        )
        try: return polish_response(raw, message)
        except: return raw

    # 2) User greeting → friendly greeting
    if _is_greeting(message):
        raw = (
            "Hello! 👋 I'm here to help you explore US metros using rental data.\n\n"
            "Tell me your rent budget, ask for the cheapest metros, or ask me to compare cities!"
        )
        try: return polish_response(raw, message)
        except: return raw

    # 3) Off-topic → fallback (NO LLM)
    if not _is_relocation_related(message):
        return _fallback_help_message()

    # --- All your routing logic below (unchanged) ---

    # Compare
    pair = _parse_compare_request(message)
    if pair:
        metro_a, metro_b = pair
        results = compare_metros(metro_a, metro_b)
        info_a, info_b = results["a"], results["b"]

        if not info_a and not info_b:
            raw = f"I couldn’t find either '{metro_a}' or '{metro_b}' in the dataset."
            try: return polish_response(raw, message)
            except: return raw

        if not info_a or not info_b:
            missing = metro_a if not info_a else metro_b
            raw = f"I found one metro but not '{missing}'. Try using 'City, ST'."
            try: return polish_response(raw, message)
            except: return raw

        def fmt(meta):
            name = meta.get("RegionName","(unknown)")
            state = meta.get("State","")
            current = meta.get("Current_Rent",None)
            r3 = meta.get("rent_3yr_pct_change",None)
            r5 = meta.get("rent_5yr_pct_change",None)
            parts=[]
            if current: parts.append(f"~${current:,.0f} avg monthly rent")
            if r3: parts.append(f"{r3:+.1f}% over 3 years")
            if r5: parts.append(f"{r5:+.1f}% over 5 years")
            joined="; ".join(parts) if parts else "no data"
            return f"{name} ({state}) — {joined}"

        text_a, text_b = fmt(info_a), fmt(info_b)
        diff = (info_b.get("Current_Rent") or 0) - (info_a.get("Current_Rent") or 0)
        more = "more" if diff > 0 else "less"
        diff_abs = abs(diff)

        raw = (
            "Here's a comparison based on current rents:\n\n"
            f"- {text_a}\n"
            f"- {text_b}\n\n"
        )
        if diff_abs > 0:
            raw += f"{info_b['RegionName']} is about ${diff_abs:,.0f} {more} expensive per month."
        else:
            raw += "Both metros have similar rent levels."

        try: return polish_response(raw, message)
        except: return raw

    # Growth
    growth = _parse_growth_intent(message)
    if growth:
        horizon, direction = growth
        state = _parse_state(message)
        df = best_rent_growth(limit=10, horizon=horizon, direction=direction, state=state)

        if df.empty:
            raw = "I couldn't find metros matching that growth pattern."
            try: return polish_response(raw, message)
            except: return raw

        desc = "up-and-coming" if direction == "up" else "declining"
        horizon_desc = "5 years" if horizon == "5y" else "3 years"
        col = "rent_5yr_pct_change" if horizon=="5y" else "rent_3yr_pct_change"

        lines=[f"Here are some {desc} metros over the last {horizon_desc}:\n"]
        for _,row in df.iterrows():
            name=row["RegionName"]
            st=row.get("State","")
            pct=row[col]
            current=row.get("Current_Rent",None)
            if current:
                lines.append(f"- {name} ({st}) — ~${current:,.0f}, {pct:+.1f}% change")
            else:
                lines.append(f"- {name} ({st}) — {pct:+.1f}% change")

        if state:
            lines.append(f"\n(Filtered to {state}.)")

        raw="\n".join(lines)
        try: return polish_response(raw, message)
        except: return raw

    # Cheapest
    if _is_cheapest_request(message):
        state=_parse_state(message)
        df=cheapest_metros(limit=10,state=state)

        if df.empty:
            raw="I couldn't find metros for that request."
            try: return polish_response(raw,message)
            except: return raw

        lines=["Here are some of the cheapest metros:\n"]
        for _,row in df.iterrows():
            lines.append(f"- {row['RegionName']} ({row.get('State','')}) — ~${row['Current_Rent']:,.0f}")

        if state:
            lines.append(f"\n(Filtered to {state}.)")

        raw="\n".join(lines)
        try: return polish_response(raw,message)
        except: return raw

    # Most expensive
    if _is_most_expensive_request(message):
        state=_parse_state(message)
        df=most_expensive_metros(limit=10,state=state)

        if df.empty:
            raw="I couldn't find metros for that request."
            try: return polish_response(raw,message)
            except: return raw

        lines=["Here are some of the most expensive metros:\n"]
        for _,row in df.iterrows():
            lines.append(f"- {row['RegionName']} ({row.get('State','')}) — ~${row['Current_Rent']:,.0f}")

        if state:
            lines.append(f"\n(Filtered to {state}.)")

        raw="\n".join(lines)
        try: return polish_response(raw,message)
        except: return raw

    # Budget-based
    budget=_parse_budget(message)
    state=_parse_state(message)

    if budget is None:
        df=cheapest_metros(limit=10,state=state)
        if df.empty:
            raw="I couldn't find metros in the dataset."
            try: return polish_response(raw,message)
            except: return raw

        lines=["I didn’t see a clear budget, so here are some cheap metros:\n"]
        for _,row in df.iterrows():
            lines.append(f"- {row['RegionName']} ({row.get('State','')}) — ~${row['Current_Rent']:,.0f}")

        lines.append(
            "\nTell me your rent budget (e.g. '$2500 in CA') and I’ll filter results further."
        )

        raw="\n".join(lines)
        try: return polish_response(raw,message)
        except: return raw

    df=filter_by_budget(budget,state)
    if df.empty:
        raw=f"I couldn’t find metros below ~${budget:,.0f}."
        try: return polish_response(raw,message)
        except: return raw

    df=df.head(10)

    if state:
        head=f"Here are metros in {state} under ~${budget:,.0f}:\n"
    else:
        head=f"Here are metros under ~${budget:,.0f}:\n"

    lines=[head]
    for _,row in df.iterrows():
        lines.append(
            f"- {row['RegionName']} ({row.get('State','')}) — ~${row['Current_Rent']:,.0f}, trend: {row.get('trend_label','unknown')}"
        )

    lines.append("\nYou can also ask about trends or compare specific metros.")

    raw="\n".join(lines)
    try: return polish_response(raw,message)
    except: return raw
