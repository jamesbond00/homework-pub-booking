"""Ex5 tools. Four tools the agent uses to research an Edinburgh booking.

Each tool:
  1. Reads its fixture from sample_data/ (DO NOT modify the fixtures).
  2. Logs its arguments and output into _TOOL_CALL_LOG (see integrity.py).
  3. Returns a ToolResult with success=True/False, output=dict, summary=str.

The grader checks for:
  * Correct parallel_safe flags (reads True, generate_flyer False).
  * Every tool's results appear in _TOOL_CALL_LOG.
  * Tools fail gracefully on missing fixtures or bad inputs (ToolError,
    not RuntimeError).
"""

from __future__ import annotations

import html
import json
from pathlib import Path

from sovereign_agent.session.directory import Session
from sovereign_agent.tools.registry import ToolError, ToolRegistry, ToolResult, _RegisteredTool

from starter.edinburgh_research.integrity import record_tool_call

_SAMPLE_DATA = Path(__file__).parent / "sample_data"
_AREA_STOPWORDS = {
    "edinburgh",
    "near",
    "station",
    "st",
    "area",
    "pub",
    "pubs",
}


def _load_fixture(name: str) -> object:
    path = _SAMPLE_DATA / name
    if not path.exists():
        raise ToolError(
            "SA_TOOL_DEPENDENCY_MISSING",
            f"Required fixture is missing: {path}",
            context={"path": str(path)},
        )
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _invalid_result(tool_name: str, arguments: dict, message: str, **context: object) -> ToolResult:
    output = {"error": message, **context}
    record_tool_call(tool_name, arguments, output)
    return ToolResult(
        success=False,
        output=output,
        summary=f"{tool_name}: {message}",
        error=ToolError("SA_TOOL_INVALID_INPUT", message, context=context),
    )


def _area_tokens(value: object) -> set[str]:
    normalized = (
        str(value)
        .casefold()
        .replace(",", " ")
        .replace("-", " ")
        .replace("_", " ")
    )
    return {
        token
        for token in normalized.split()
        if token and token not in _AREA_STOPWORDS
    }


def _area_matches(query: str, venue_area: object) -> bool:
    query_normalized = query.casefold()
    area_normalized = str(venue_area).casefold()
    if query_normalized in area_normalized or area_normalized in query_normalized:
        return True

    query_tokens = _area_tokens(query)
    area_tokens = _area_tokens(venue_area)
    return bool(query_tokens and area_tokens and query_tokens & area_tokens)


# ---------------------------------------------------------------------------
# TODO 1 — venue_search
# ---------------------------------------------------------------------------
def venue_search(near: str, party_size: int, budget_max_gbp: int = 1000) -> ToolResult:
    """Search for Edinburgh venues near <near> that can seat the party.

    Reads sample_data/venues.json. Filters by:
      * open_now == True
      * area contains <near> (case-insensitive substring match)
      * seats_available_evening >= party_size
      * hire_fee_gbp + min_spend_gbp <= budget_max_gbp

    Returns a ToolResult with:
      output: {"near": ..., "party_size": ..., "results": [<venue dicts>], "count": int}
      summary: "venue_search(<near>, party=<N>): <count> result(s)"

    MUST call record_tool_call(...) before returning so the integrity
    check can see what data was produced.
    """
    arguments = {
        "near": near,
        "party_size": party_size,
        "budget_max_gbp": budget_max_gbp,
    }
    if party_size <= 0:
        return _invalid_result("venue_search", arguments, "party_size must be positive")
    if budget_max_gbp < 0:
        return _invalid_result("venue_search", arguments, "budget_max_gbp must be non-negative")

    venues = _load_fixture("venues.json")
    if not isinstance(venues, list):
        return _invalid_result("venue_search", arguments, "venues fixture must contain a list")

    results = [
        venue
        for venue in venues
        if isinstance(venue, dict)
        and venue.get("open_now") is True
        and _area_matches(near, venue.get("area", ""))
        and int(venue.get("seats_available_evening", 0)) >= party_size
        and int(venue.get("hire_fee_gbp", 0)) + int(venue.get("min_spend_gbp", 0)) <= budget_max_gbp
    ]
    output = {
        "near": near,
        "party_size": party_size,
        "budget_max_gbp": budget_max_gbp,
        "results": results,
        "count": len(results),
    }
    record_tool_call("venue_search", arguments, output)
    return ToolResult(
        success=True,
        output=output,
        summary=f"venue_search({near}, party={party_size}): {len(results)} result(s)",
    )


# ---------------------------------------------------------------------------
# TODO 2 — get_weather
# ---------------------------------------------------------------------------
def get_weather(city: str, date: str) -> ToolResult:
    """Look up the scripted weather for <city> on <date> (YYYY-MM-DD).

    Reads sample_data/weather.json. Returns:
      output: {"city": str, "date": str, "condition": str, "temperature_c": int, ...}
      summary: "get_weather(<city>, <date>): <condition>, <temp>C"

    If the city or date is not in the fixture, return success=False with
    a clear ToolError (SA_TOOL_INVALID_INPUT). Do NOT raise.

    MUST call record_tool_call(...) before returning.
    """
    arguments = {"city": city, "date": date}
    weather = _load_fixture("weather.json")
    if not isinstance(weather, dict):
        return _invalid_result("get_weather", arguments, "weather fixture must contain an object")

    city_key = city.casefold()
    if city_key not in weather or not isinstance(weather[city_key], dict):
        return _invalid_result("get_weather", arguments, f"no weather data for city {city!r}")
    if date not in weather[city_key]:
        return _invalid_result(
            "get_weather",
            arguments,
            f"no weather data for {city_key} on {date}",
            city=city_key,
            date=date,
        )

    day = weather[city_key][date]
    if not isinstance(day, dict):
        return _invalid_result("get_weather", arguments, "weather entry must contain an object")

    output = {"city": city_key, "date": date, **day}
    record_tool_call("get_weather", arguments, output)
    return ToolResult(
        success=True,
        output=output,
        summary=(
            f"get_weather({city_key}, {date}): {output['condition']}, {output['temperature_c']}C"
        ),
    )


# ---------------------------------------------------------------------------
# TODO 3 — calculate_cost
# ---------------------------------------------------------------------------
def calculate_cost(
    venue_id: str,
    party_size: int,
    duration_hours: int,
    catering_tier: str = "bar_snacks",
) -> ToolResult:
    """Compute the total cost for a booking.

    Formula:
      base_per_head = base_rates_gbp_per_head[catering_tier]
      venue_mult    = venue_modifiers[venue_id]
      subtotal      = base_per_head * venue_mult * party_size * max(1, duration_hours)
      service       = subtotal * service_charge_percent / 100
      total         = subtotal + service + <venue's hire_fee_gbp + min_spend_gbp>
      deposit_rule  = per deposit_policy thresholds

    Returns:
      output: {
        "venue_id": str,
        "party_size": int,
        "duration_hours": int,
        "catering_tier": str,
        "subtotal_gbp": int,
        "service_gbp": int,
        "total_gbp": int,
        "deposit_required_gbp": int,
      }
      summary: "calculate_cost(<venue>, <party>): total £<N>, deposit £<M>"

    MUST call record_tool_call(...) before returning.
    """
    arguments = {
        "venue_id": venue_id,
        "party_size": party_size,
        "duration_hours": duration_hours,
        "catering_tier": catering_tier,
    }
    if party_size <= 0:
        return _invalid_result("calculate_cost", arguments, "party_size must be positive")
    if duration_hours <= 0:
        return _invalid_result("calculate_cost", arguments, "duration_hours must be positive")

    catering = _load_fixture("catering.json")
    venues = _load_fixture("venues.json")
    if not isinstance(catering, dict) or not isinstance(venues, list):
        return _invalid_result("calculate_cost", arguments, "fixtures have invalid structure")

    base_rates = catering.get("base_rates_gbp_per_head", {})
    modifiers = catering.get("venue_modifiers", {})
    if not isinstance(base_rates, dict) or catering_tier not in base_rates:
        return _invalid_result(
            "calculate_cost",
            arguments,
            f"unknown catering_tier {catering_tier!r}",
        )
    if not isinstance(modifiers, dict) or venue_id not in modifiers:
        return _invalid_result("calculate_cost", arguments, f"unknown venue_id {venue_id!r}")

    venue = next((v for v in venues if isinstance(v, dict) and v.get("id") == venue_id), None)
    if venue is None:
        return _invalid_result(
            "calculate_cost",
            arguments,
            f"venue_id {venue_id!r} is missing from venues fixture",
        )

    base_per_head = float(base_rates[catering_tier])
    venue_mult = float(modifiers[venue_id])
    hours = max(1, duration_hours)
    subtotal = round(base_per_head * venue_mult * party_size * hours)
    service = round(subtotal * float(catering.get("service_charge_percent", 0)) / 100)
    venue_minimum = int(venue.get("hire_fee_gbp", 0)) + int(venue.get("min_spend_gbp", 0))
    total = subtotal + service + venue_minimum
    if total < 300:
        deposit = 0
    elif total <= 1000:
        deposit = round(total * 0.20)
    else:
        deposit = round(total * 0.30)

    output = {
        "venue_id": venue_id,
        "party_size": party_size,
        "duration_hours": duration_hours,
        "catering_tier": catering_tier,
        "subtotal_gbp": subtotal,
        "service_gbp": service,
        "venue_minimum_gbp": venue_minimum,
        "total_gbp": total,
        "deposit_required_gbp": deposit,
    }
    record_tool_call("calculate_cost", arguments, output)
    return ToolResult(
        success=True,
        output=output,
        summary=f"calculate_cost({venue_id}, party={party_size}): total £{total}, deposit £{deposit}",
    )


# ---------------------------------------------------------------------------
# TODO 4 — generate_flyer
# ---------------------------------------------------------------------------
def generate_flyer(session: Session, event_details: dict) -> ToolResult:
    """Produce an HTML flyer and write it to workspace/flyer.html.

    event_details is expected to contain at least:
      venue_name, venue_address, date, time, party_size, condition,
      temperature_c, total_gbp, deposit_required_gbp

    Write a self-contained HTML flyer (inline CSS, no external assets). Tag every key fact with data-testid="<n>" so the integrity check can parse it.

    Write a formatted HTML flyer with an H1 title, the event
    facts, a weather summary, and the cost breakdown.

    Returns:
      output: {"path": "workspace/flyer.html", "bytes_written": int}
      summary: "generate_flyer: wrote <path> (<N> chars)"

    MUST call record_tool_call(...) before returning — the integrity
    check compares the flyer's contents against earlier tool outputs.

    IMPORTANT: this tool MUST be registered with parallel_safe=False
    because it writes a file.
    """
    arguments = {"event_details": event_details}
    required = [
        "venue_name",
        "venue_address",
        "date",
        "time",
        "party_size",
        "condition",
        "temperature_c",
        "total_gbp",
        "deposit_required_gbp",
    ]
    missing = [key for key in required if key not in event_details]
    if missing:
        return _invalid_result(
            "generate_flyer",
            arguments,
            "event_details missing required fields",
            missing=missing,
        )

    def esc(key: str) -> str:
        return html.escape(str(event_details[key]))

    total = int(event_details["total_gbp"])
    deposit = int(event_details["deposit_required_gbp"])
    condition = str(event_details["condition"]).replace("_", " ")
    flyer = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{esc("venue_name")} Event Flyer</title>
  <style>
    body {{
      margin: 0;
      font-family: Arial, sans-serif;
      color: #202124;
      background: #f5f1e8;
    }}
    main {{
      max-width: 720px;
      margin: 40px auto;
      padding: 32px;
      background: #ffffff;
      border: 1px solid #d8d0c0;
      border-radius: 8px;
    }}
    h1 {{ margin-top: 0; font-size: 32px; }}
    dl {{ display: grid; grid-template-columns: 180px 1fr; gap: 12px 20px; }}
    dt {{ font-weight: 700; }}
    dd {{ margin: 0; }}
  </style>
</head>
<body>
  <main>
    <h1>Pub Night at <span data-testid="venue_name">{esc("venue_name")}</span></h1>
    <dl>
      <dt>Address</dt><dd data-testid="venue_address">{esc("venue_address")}</dd>
      <dt>Date</dt><dd data-testid="date">{esc("date")}</dd>
      <dt>Time</dt><dd data-testid="time">{esc("time")}</dd>
      <dt>Party size</dt><dd data-testid="party_size">{esc("party_size")}</dd>
      <dt>Weather</dt><dd><span data-testid="condition">{html.escape(condition)}</span>, <span data-testid="temperature_c">{esc("temperature_c")}C</span></dd>
      <dt>Total cost</dt><dd data-testid="total_gbp">£{total}</dd>
      <dt>Deposit required</dt><dd data-testid="deposit_required_gbp">£{deposit}</dd>
    </dl>
  </main>
</body>
</html>
"""
    path = session.workspace_dir / "flyer.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(flyer, encoding="utf-8")
    output = {"path": "workspace/flyer.html", "bytes_written": len(flyer.encode("utf-8"))}
    record_tool_call("generate_flyer", arguments, output)
    return ToolResult(
        success=True,
        output=output,
        summary=f"generate_flyer: wrote workspace/flyer.html ({len(flyer)} chars)",
    )


# ---------------------------------------------------------------------------
# Registry builder — DO NOT MODIFY the name, signature, or registration calls.
# The grader imports and calls this to pick up your tools.
# ---------------------------------------------------------------------------
def build_tool_registry(session: Session) -> ToolRegistry:
    """Build a session-scoped tool registry with all four Ex5 tools plus
    the sovereign-agent builtins (read_file, write_file, list_files,
    handoff_to_structured, complete_task).

    DO NOT change the tool names — the tests and grader call them by name.
    """
    from sovereign_agent.tools.builtin import make_builtin_registry

    reg = make_builtin_registry(session)

    # venue_search
    reg.register(
        _RegisteredTool(
            name="venue_search",
            description="Search Edinburgh venues by area, party size, and max budget.",
            fn=venue_search,
            parameters_schema={
                "type": "object",
                "properties": {
                    "near": {"type": "string"},
                    "party_size": {"type": "integer"},
                    "budget_max_gbp": {"type": "integer", "default": 1000},
                },
                "required": ["near", "party_size"],
            },
            returns_schema={"type": "object"},
            is_async=False,
            parallel_safe=True,  # read-only
            examples=[
                {
                    "input": {"near": "Haymarket", "party_size": 6, "budget_max_gbp": 800},
                    "output": {"count": 1, "results": [{"id": "haymarket_tap"}]},
                }
            ],
        )
    )

    # get_weather
    reg.register(
        _RegisteredTool(
            name="get_weather",
            description="Get scripted weather for a city on a YYYY-MM-DD date.",
            fn=get_weather,
            parameters_schema={
                "type": "object",
                "properties": {
                    "city": {"type": "string"},
                    "date": {"type": "string"},
                },
                "required": ["city", "date"],
            },
            returns_schema={"type": "object"},
            is_async=False,
            parallel_safe=True,  # read-only
            examples=[
                {
                    "input": {"city": "Edinburgh", "date": "2026-04-25"},
                    "output": {"condition": "cloudy", "temperature_c": 12},
                }
            ],
        )
    )

    # calculate_cost
    reg.register(
        _RegisteredTool(
            name="calculate_cost",
            description="Compute total cost and deposit for a booking.",
            fn=calculate_cost,
            parameters_schema={
                "type": "object",
                "properties": {
                    "venue_id": {"type": "string"},
                    "party_size": {"type": "integer"},
                    "duration_hours": {"type": "integer"},
                    "catering_tier": {
                        "type": "string",
                        "enum": ["drinks_only", "bar_snacks", "sit_down_meal", "three_course_meal"],
                        "default": "bar_snacks",
                    },
                },
                "required": ["venue_id", "party_size", "duration_hours"],
            },
            returns_schema={"type": "object"},
            is_async=False,
            parallel_safe=True,  # pure compute, no shared state
            examples=[
                {
                    "input": {
                        "venue_id": "haymarket_tap",
                        "party_size": 6,
                        "duration_hours": 3,
                    },
                    "output": {"total_gbp": 556, "deposit_required_gbp": 111},
                }
            ],
        )
    )

    # generate_flyer — parallel_safe=False because it writes a file
    def _flyer_adapter(event_details: dict) -> ToolResult:
        return generate_flyer(session, event_details)

    reg.register(
        _RegisteredTool(
            name="generate_flyer",
            description="Write an HTML flyer for the event to workspace/flyer.html.",
            fn=_flyer_adapter,
            parameters_schema={
                "type": "object",
                "properties": {"event_details": {"type": "object"}},
                "required": ["event_details"],
            },
            returns_schema={"type": "object"},
            is_async=False,
            parallel_safe=False,  # writes a file — MUST be False
            examples=[
                {
                    "input": {
                        "event_details": {
                            "venue_name": "Haymarket Tap",
                            "date": "2026-04-25",
                            "party_size": 6,
                        }
                    },
                    "output": {"path": "workspace/flyer.html"},
                }
            ],
        )
    )

    return reg


__all__ = [
    "build_tool_registry",
    "venue_search",
    "get_weather",
    "calculate_cost",
    "generate_flyer",
]
