# Ex6 Implementation Plan — Rasa Structured Half

## Objective

Ex6 replaces a minimal in-process structured half with a Rasa-backed structured half. The loop side proposes a booking as a Python dict, the structured half normalises it, sends it to Rasa over HTTP, and turns Rasa's response back into a `HalfResult`.

The structured half should make deterministic booking decisions for:

- valid booking: party size <= 8 and deposit <= GBP 300
- rejected booking: party size > 8
- rejected booking: deposit > GBP 300
- malformed booking: missing or invalid required fields
- service failure: Rasa unavailable, timeout, HTTP error, or invalid JSON

## Files In Scope

### Python structured half

`starter/rasa_half/structured_half.py`

Responsibilities:

- define `RasaStructuredHalf`
- expose a valid `discover()` schema
- implement `run(session, input_payload)`
- POST normalised booking data to Rasa's REST webhook
- translate Rasa responses into `HalfResult`
- fail closed by returning `next_action="escalate"` on validation or service errors

### Python validator

`starter/rasa_half/validator.py`

Responsibilities:

- implement `normalise_booking_payload(raw)`
- canonicalise venue IDs
- normalise dates
- parse time into 24-hour `HH:MM`
- parse party size into an integer
- parse deposit into integer GBP
- raise `ValidationFailed` for unsalvageable input

### Rasa flow

`rasa_project/data/flows.yml`

Responsibilities:

- define the flow triggered by `/confirm_booking`
- run `action_validate_booking`
- branch to rejection if validation fails
- branch to confirmation if validation passes

### Rasa custom action

`rasa_project/actions/actions.py`

Responsibilities:

- implement `ActionValidateBooking`
- read `tracker.latest_message.metadata.booking`
- populate Rasa slots from metadata
- reject party sizes over 8
- reject deposits over GBP 300
- create a deterministic booking reference for successful bookings

### Scenario runner

`starter/rasa_half/run.py`

Responsibilities:

- run Ex6 against the mock server with `make ex6`
- run Ex6 against a real Rasa server with `make ex6-real`
- optionally auto-spawn Rasa in `make ex6-auto`

## Data Contract

### Input from loop half

The structured half receives:

```python
{
    "data": {
        "action": "confirm_booking",
        "venue_id": "Haymarket Tap",
        "date": "25th April 2026",
        "time": "7:30pm",
        "party_size": "6",
        "deposit": "GBP 200",
        "duration_hours": 3,
        "catering_tier": "bar_snacks",
    }
}
```

Only `data` is required at the `RasaStructuredHalf.run()` boundary. Inside `data`, the required booking fields are:

- `venue_id`
- `date`
- `time`
- `party_size`

`deposit` should default to `0` if omitted.

### Normalised Rasa message

`normalise_booking_payload()` should produce:

```python
{
    "sender": "homework-<stable_hash>",
    "message": "/confirm_booking",
    "metadata": {
        "booking": {
            "venue_id": "haymarket_tap",
            "date": "2026-04-25",
            "time": "19:30",
            "party_size": 6,
            "deposit_gbp": 200,
            "duration_hours": 3,
            "catering_tier": "bar_snacks",
        }
    },
}
```

The `sender` should be stable for the same venue/date/time combination. That gives Rasa a consistent tracker across retries without relying on a random ID.

### HTTP request to Rasa

`RasaStructuredHalf.run()` should POST this JSON body to:

```text
http://localhost:5005/webhooks/rest/webhook
```

Expected request shape:

```json
{
  "sender": "homework-abc12345",
  "message": "/confirm_booking",
  "metadata": {
    "booking": {
      "venue_id": "haymarket_tap",
      "date": "2026-04-25",
      "time": "19:30",
      "party_size": 6,
      "deposit_gbp": 200,
      "duration_hours": 3,
      "catering_tier": "bar_snacks"
    }
  }
}
```

## Control Flow

1. `run()` receives `input_payload`.
2. It extracts `input_payload["data"]`.
3. It calls `normalise_booking_payload(data)`.
4. If normalisation fails, return:

   ```python
   HalfResult(
       success=False,
       output={"error": "...", "raw": data},
       summary="normalisation failed: ...",
       next_action="escalate",
   )
   ```

5. It sends the normalised message to Rasa's REST webhook.
6. If Rasa is unavailable, times out, returns HTTP error, or returns non-JSON, return `success=False` and `next_action="escalate"`.
7. If Rasa returns a confirmation message or custom payload with `action == "committed"`, return:

   ```python
   HalfResult(
       success=True,
       output={
           "committed": True,
           "booking": booking,
           "booking_reference": booking_reference,
           "rasa_response": messages,
       },
       summary="booking confirmed by rasa ...",
       next_action="complete",
   )
   ```

8. If Rasa returns a rejection message or custom payload with `action == "rejected"`, return:

   ```python
   HalfResult(
       success=False,
       output={
           "rejected": True,
           "reason": rejection_reason,
           "booking": booking,
           "rasa_response": messages,
       },
       summary="rasa rejected: ...",
       next_action="escalate",
   )
   ```

9. If the response is valid JSON but does not clearly confirm or reject, return `success=False` and `next_action="escalate"`.

## Validator Details

### Venue ID

Convert venue names into stable IDs:

- `"Haymarket Tap"` -> `"haymarket_tap"`
- `"haymarket_tap"` -> `"haymarket_tap"`
- `"The Royal Oak!"` -> `"the_royal_oak"`

Implementation:

- strip whitespace
- lowercase
- replace whitespace and hyphens with `_`
- remove unsupported punctuation

### Date

Support at least:

- ISO date: `"2026-04-25"` -> `"2026-04-25"`
- text date: `"25th April 2026"` -> `"2026-04-25"`
- text date without year: `"25th April"` -> default homework year, `"2026-04-25"`

For homework determinism, avoid using the system date for tests. If supporting `"today"` or `"tomorrow"`, map them to fixed scenario dates rather than current wall-clock time.

### Time

Support:

- `"19:30"` -> `"19:30"`
- `"1930"` -> `"19:30"`
- `"7:30pm"` -> `"19:30"`
- `"7.30pm"` -> `"19:30"`
- `"7pm"` -> `"19:00"`
- `"noon"` -> `"12:00"`
- `"midnight"` -> `"00:00"`

Reject impossible times.

### Party Size

Support:

- `6` -> `6`
- `"6"` -> `6`
- `"6 people"` -> `6`

Reject:

- `0`
- negative values
- non-numeric values

### Deposit

Support:

- `"GBP 200"` -> `200`
- `"200 GBP"` -> `200`
- `"£200"` -> `200`
- `200` -> `200`
- `200.0` -> `200`

Reject negative values and non-numeric strings.

## Rasa Action Details

`ActionValidateBooking` should read booking data from:

```python
tracker.latest_message["metadata"]["booking"]
```

Then it should set slots for downstream flow responses:

- `venue_id`
- `date`
- `time`
- `party_size`
- `deposit_gbp`

Validation order:

1. Check required fields.
2. Cast `party_size` and `deposit_gbp` into numbers.
3. Reject `party_size > 8` with `validation_error = "party_too_large"`.
4. Reject `deposit_gbp > 300` with `validation_error = "deposit_too_high"`.
5. On success, clear `validation_error` and set `booking_reference`.

The booking reference should be deterministic, for example a hash of:

```text
venue_id|date|time|party_size
```

## Rasa Flow Details

The minimal required flow is:

```yaml
flows:
  confirm_booking:
    description: Confirm a pub booking after validating policy.
    steps:
      - id: validate
        action: action_validate_booking
        next:
          - if: "slots.validation_error is not null"
            then: rejected
          - else: confirmed
      - id: rejected
        action: utter_booking_rejected
        next: END
      - id: confirmed
        action: utter_booking_confirmed
        next: END
```

This keeps Rasa responsible for policy and dialogue output, while Python remains responsible for orchestration and HTTP error handling.

## Error Handling Rules

`RasaStructuredHalf.run()` should never let expected operational failures crash the scenario.

Return `success=False` and `next_action="escalate"` for:

- missing `input_payload["data"]`
- validator failure
- Rasa connection refused
- Rasa timeout
- Rasa HTTP error
- non-JSON Rasa response
- Rasa response that is neither confirmed nor rejected

Use `error_code = "SA_EXT_SERVICE_UNAVAILABLE"` for connection and HTTP availability failures.

Use `error_code = "SA_EXT_TIMEOUT"` for timeout failures.

## Verification Plan

### Unit/public tests

Run:

```bash
pytest tests/public/test_ex6_scaffold.py
```

These verify:

- `RasaStructuredHalf` subclasses `StructuredHalf`
- `discover()` returns a valid schema
- currency parsing
- time parsing
- venue ID canonicalisation
- party-size validation
- booking payload normalisation

### Mock integration

Run:

```bash
make ex6
```

Expected result:

- the mock Rasa webhook starts locally
- the structured half posts a normalised booking
- the result is successful
- `next_action` is `complete`

### Real Rasa integration

Start the real services using the documented three-terminal flow:

```bash
make ex6-help
```

Then run:

```bash
make ex6-real
```

Expected result:

- Rasa receives `/confirm_booking`
- `ActionValidateBooking` reads `metadata.booking`
- valid bookings are confirmed
- oversize parties and high deposits are rejected with a reason

### Submission check

Run:

```bash
make test
```

For a narrower check:

```bash
uv run python grader/check_submit.py --only ex6
```

## Acceptance Criteria

Ex6 is complete when:

- `normalise_booking_payload()` returns Rasa-ready metadata with at least three required normalisations
- valid booking data produces `HalfResult(success=True, next_action="complete")`
- party size over 8 produces `HalfResult(success=False, next_action="escalate")`
- deposit over GBP 300 produces `HalfResult(success=False, next_action="escalate")`
- HTTP/service failures are represented as structured failures rather than crashes
- `make ex6` passes in mock mode
- `make ex6-real` works when Rasa and the action server are running

## Real Mode Run Result

Observed successful real-mode run:

- Date: 2026-05-19
- Command: `make ex6-real`
- Rasa server probe: `http://localhost:5005` returned HTTP 200
- Rasa version: `3.16.4`
- Action server probe: `http://localhost:5055` returned HTTP 200
- Session ID: `sess_6c53cba2997c`
- Session path: `/Users/alex/Library/Application Support/sovereign-agent/examples/ex6-rasa-half/sess_6c53cba2997c`
- Outcome: `complete`
- Booking reference: `BK-7D401E9E`

Observed output summary:

```text
Structured half outcome: complete
summary: booking confirmed by rasa (ref=BK-7D401E9E)
```

The confirmed booking was normalised before being sent to Rasa:

```python
{
    "venue_id": "haymarket_tap",
    "date": "2026-04-25",
    "time": "19:30",
    "party_size": 6,
    "deposit_gbp": 200,
    "duration_hours": 3,
    "catering_tier": "bar_snacks",
}
```

This verifies the live path across all three processes:

```text
RasaStructuredHalf -> Rasa REST webhook (:5005) -> action server (:5055)
```

## Notes For Ex7

Ex7 depends on Ex6 rejection behavior. The bridge needs a structured rejection reason so it can build a reverse handoff back to the loop half.

For that reason, Ex6 rejection outputs should include:

```python
{
    "rejected": True,
    "reason": "party_too_large",
    "booking": {...},
    "rasa_response": [...]
}
```

This gives Ex7 enough context to retry with a different venue or booking proposal.
