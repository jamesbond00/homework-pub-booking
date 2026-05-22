# Ex6 — Rasa structured half

## Your answer

The RasaStructuredHalf subclass overrides run() to POST a booking
intent to Rasa's REST webhook and interpret the response. Input
payload flows: loop half produces raw booking data → StructuredHalf
calls normalise_booking_payload (via validator.py) to produce a
Rasa-shaped message with canonical types → urllib POST to Rasa →
parse response text or custom payloads for a committed or rejected
booking.

For offline mode we spawn a stdlib http.server thread that mimics the
Rasa webhook and applies the same party-size and deposit rules as the
custom action. This lets `make ex6` validate the HTTP contract without
requiring a Rasa license.

Three design choices worth noting: (1) we raise ValidationFailed in
normalise_booking_payload and catch it in run() rather than letting
it propagate; the StructuredHalf contract demands a HalfResult. (2)
Network errors return success=False with SA_EXT_SERVICE_UNAVAILABLE
— the caller decides whether to retry. (3) The stable sender_id is a
hash of (venue+date+time) so the Rasa tracker is consistent across
retries within one session.

Real mode was verified on 2026-05-19 with `make ex6-real`. The probe
confirmed Rasa on `localhost:5005` and the action server on
`localhost:5055`, with Rasa reporting version 3.16.4. The run created
session `sess_6c53cba2997c` at
`sovereign-agent/examples/ex6-rasa-half/sess_6c53cba2997c`
and completed successfully:

```text
Structured half outcome: complete
summary: booking confirmed by rasa (ref=BK-7D401E9E)
```

The booking that reached Rasa was normalised to `haymarket_tap`,
`2026-04-25`, `19:30`, party size `6`, and deposit `200`. Rasa returned
the confirmation text `Booking confirmed. Reference: BK-7D401E9E.`

## Citations

- starter/rasa_half/validator.py — normalise_booking_payload + helpers
- starter/rasa_half/structured_half.py — RasaStructuredHalf.run + mock server
- rasa_project/actions/actions.py — ActionValidateBooking policy rules
- rasa_project/data/flows.yml — confirm_booking flow and compatibility flows
- Session sess_6c53cba2997c — successful real Rasa run on 2026-05-19
