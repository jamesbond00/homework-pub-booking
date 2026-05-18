# Ex5 Implementation Notes

These notes document the Ex5 Edinburgh research implementation so the code is easier to revisit later.

## Goal

Ex5 implements the loop-half research scenario. The agent researches a pub near Haymarket, checks weather, calculates booking cost, writes an HTML flyer, then verifies that concrete facts in the flyer came from tool outputs rather than LLM invention.

The important files are:

- `tools.py`: four scenario tools plus the tool registry.
- `integrity.py`: shared tool-call log and dataflow verification.
- `run.py`: runnable loop-half scenario using scripted fake LLM by default.
- `sample_data/*.json`: deterministic fixture data used by the tools.

## Tool Result Pattern

Every Ex5 tool follows the same contract:

1. Validate inputs.
2. Read deterministic fixture data when needed.
3. Build a plain `dict` output.
4. Call `record_tool_call(tool_name, arguments, output)`.
5. Return `ToolResult(success=..., output=..., summary=...)`.

This pattern matters because the executor expects `ToolResult`, while the dataflow checker only knows what facts are legitimate if the tool records its output in `_TOOL_CALL_LOG`.

Invalid user/tool inputs return `success=False` with `ToolError("SA_TOOL_INVALID_INPUT", ...)`. Missing fixture files raise `ToolError("SA_TOOL_DEPENDENCY_MISSING", ...)` because that is an environment/setup failure, not a normal user input problem.

## `venue_search`

`venue_search(near, party_size, budget_max_gbp)` reads `sample_data/venues.json`.

It filters venues by:

- `open_now == True`
- `area` matches the requested `near` text, case-insensitive, with common location words such as `station`, `near`, and `Edinburgh` ignored for token matching
- `seats_available_evening >= party_size`
- `hire_fee_gbp + min_spend_gbp <= budget_max_gbp`

The returned output includes the original query, matching venue dicts, and `count`.

Why: the planner/executor needs a deterministic list of candidate pubs, and the integrity checker later needs exact venue values such as `Haymarket Tap` to appear in the tool log. The looser area matching is there because real LLMs may call the tool with natural phrases like `Haymarket station` even though the fixture stores the area as `Haymarket`.

## `get_weather`

`get_weather(city, date)` reads `sample_data/weather.json`.

The city key is normalized with `casefold()`, so `Edinburgh` and `edinburgh` both resolve to the fixture key. Missing city/date values return a failed `ToolResult` instead of raising.

Why: weather is a concrete flyer fact. The final condition and temperature must trace back to this tool output.

## `calculate_cost`

`calculate_cost(venue_id, party_size, duration_hours, catering_tier)` reads both:

- `sample_data/catering.json`
- `sample_data/venues.json`

The formula implemented is:

```text
subtotal = base_rate_per_head * venue_modifier * party_size * max(1, duration_hours)
service = subtotal * service_charge_percent / 100
venue_minimum = hire_fee_gbp + min_spend_gbp
total = subtotal + service + venue_minimum
```

Deposit logic:

- total under 300 GBP: no deposit
- total from 300 to 1000 GBP: 20 percent deposit
- total over 1000 GBP: 30 percent deposit

Values are rounded to integer GBP.

Why: the final flyer can contain money values, and the integrity checker must be able to reject prices that were never computed by a tool.

## `generate_flyer`

`generate_flyer(session, event_details)` writes `workspace/flyer.html` inside the session directory.

Expected `event_details` keys:

- `venue_name`
- `venue_address`
- `date`
- `time`
- `party_size`
- `condition`
- `temperature_c`
- `total_gbp`
- `deposit_required_gbp`

The generated flyer is self-contained HTML with inline CSS. Every key fact is tagged with a `data-testid`, for example:

```html
<span data-testid="venue_name">Haymarket Tap</span>
<dd data-testid="total_gbp">£556</dd>
```

Why: writing the flyer is the actual artifact Ex5 is graded on. The `data-testid` tags make facts easy to identify and audit.

Important registry detail: `generate_flyer` is registered with `parallel_safe=False` because it writes a file. The read-only tools stay `parallel_safe=True`.

## Integrity Log

`integrity.py` defines `_TOOL_CALL_LOG`, a process-local list of `ToolCallRecord` objects.

Each record stores:

- `tool_name`
- `arguments`
- `output`
- `timestamp`

The log is cleared before a real scenario run in `run.py` so preflight/probe tool calls do not pollute the actual dataflow check.

Why: the integrity checker does not trust the LLM's final text. It trusts only values that came from recorded tool calls.

## `verify_dataflow`

`verify_dataflow(flyer_content)` extracts concrete facts from flyer text and checks each one against `_TOOL_CALL_LOG`.

Currently extracted facts include:

- money values like `£556`
- temperatures like `12C`
- weather conditions like `cloudy`
- explicit venue labels like `Venue: Haymarket Tap`
- generated flyer heading text like `Pub Night at Haymarket Tap`
- labelled total values like `Total: Castle Royal Grand Inn`
- weather-line phrases like `Weather: scorching 35C`

Why this extra extraction exists: the grader plants fabrications beyond money values. It checks that fake venue names and fake weather phrases are rejected too.

The helper `fact_appears_in_log` recursively scans nested dict/list tool outputs and arguments. It normalizes common display differences such as `£556` versus `556`, and `12C` versus `12`.

Weather phrases use `weather_phrase_appears_in_log`, which verifies the condition and temperature against `get_weather` outputs specifically.

## Scenario Runner

`run.py` uses:

- `DefaultPlanner`
- `DefaultExecutor`
- `LoopHalf`
- the Ex5 tool registry

Default mode uses `FakeLLMClient`, so `make ex5` is offline and deterministic. `--real` switches to `OpenAICompatibleClient` with config from the environment.

After the loop finishes, `run.py`:

1. Checks `workspace/flyer.html` exists.
2. Reads flyer content.
3. Calls `verify_dataflow(flyer_content)`.
4. Exits non-zero if integrity fails.

Why: this makes dataflow integrity part of the runnable scenario, not a separate optional test.

## Useful Verification Commands

Run the scenario:

```bash
uv run python -m starter.edinburgh_research.run
```

Run the grader dataflow probe:

```bash
uv run python -m grader.dataflow_probe
```

Run lint on the edited files:

```bash
uv run ruff check starter/edinburgh_research/tools.py starter/edinburgh_research/integrity.py
```

Run public Ex5 tests:

```bash
uv run pytest tests/public/test_ex5_scaffold.py -v
```

At the time these notes were written, the direct scenario, ruff check, and dataflow probe passed. Local pytest crashed during startup with a segmentation fault in pytest capture before running test assertions.

## Things To Remember

- Do not remove `record_tool_call` from any tool; missing log entries lose integrity coverage.
- Do not mark `generate_flyer` as parallel-safe; it writes `workspace/flyer.html`.
- `generate_flyer` logs only its own write result, so flyer facts must come from earlier tool outputs or its `event_details` arguments.
- If changing flyer text, make sure `verify_dataflow` still extracts the same concrete facts.
- If changing fixture values or formulas, re-run the scenario and dataflow probe.
