# Ex9 — Reflection

## Q1 — Planner handoff decision

### Your answer

In my Ex7 planner-evidence run `sess_be59a03d5b73`, the planner ticket
`tk_7ca3ce0c` produced one subgoal, `sg_confirm`, with description "confirm
the booking under policy rules." The important field is on line 8 of
`raw_output.json`: `assigned_half: "structured"`. The signal that caused the
decision was the phrase "under policy rules." That is no longer open-ended
venue research; it is the strict confirmation step where the structured half
owns the party-size and deposit caps.

I also kept the completed Ex7 round-trip run `sess_5c4866c44934` to show the
same boundary in a full bridge execution. In that run, trace line 5 records
the `handoff_to_structured` call with a complete booking payload. Line 6 then
records `session.state_changed` from `loop` to `structured`, and line 7 records
the reverse transition with `rejection_reason: party_too_large`.

Together, those logs show both parts of the lesson: the planner can label a
policy-confirmation subgoal as structured, and the bridge turns that boundary
into an actual runtime handoff.

### Citation

- `evidence/ex9/ex7_planner_handoff_sessions/sess_be59a03d5b73/logs/tickets/tk_7ca3ce0c/raw_output.json:8`
- `evidence/ex9/ex7_sessions/sess_5c4866c44934/logs/trace.jsonl:5`
- `evidence/ex9/ex7_sessions/sess_5c4866c44934/logs/trace.jsonl:6`
- `evidence/ex9/ex7_sessions/sess_5c4866c44934/logs/trace.jsonl:7`

---

## Q2 — Dataflow integrity catch

### Your answer

For Ex5 I created a reproducible fabrication check under
`evidence/ex9/fabrication_check`. The correct Ex5 evidence run
`sess_6bda3f6c45b3` produced a flyer with Haymarket Tap, cloudy weather, total
cost `£556`, and deposit `£111`. The trace proves those values came from tools:
line 5 records `calculate_cost(haymarket_tap, party=6): total £556, deposit
£111`, and line 6 records `generate_flyer` using `total_gbp: 556` and
`deposit_required_gbp: 111`.

Then I planted a specific bad fact by replacing the verified total cost `£556`
with `£9999` in a copied flyer. A human skim could easily miss this kind of
error because the flyer still looks valid HTML and all the other facts remain
correct. The integrity check did not rely on plausibility. It compared flyer
facts against the values returned by the tool calls in `_TOOL_CALL_LOG`.

The saved result shows the behavior I want the grader to see:
`Fabricated flyer integrity: ok=False; dataflow FAIL: 1 unverified fact(s):
['£9999']`. This is a concrete test case someone else can reproduce: run the
Ex5 tools, generate the flyer, replace one tool-derived price with `£9999`,
then call `verify_dataflow` in the same process.

### Citation

- `evidence/ex9/ex5_sessions/sess_6bda3f6c45b3/logs/trace.jsonl:5`
- `evidence/ex9/ex5_sessions/sess_6bda3f6c45b3/logs/trace.jsonl:6`
- `evidence/ex9/ex5_sessions/sess_6bda3f6c45b3/workspace/flyer.html:36`
- `evidence/ex9/fabrication_check/integrity_result.md`

---

## Q3 — Expected production failure

### Your answer

The first production failure I would expect is a stale handoff file causing the
structured half to process the wrong booking request. For example, a previous
customer's rejected party-size-12 handoff could remain visible in `ipc/`, and
the next booking attempt could accidentally pick up that old payload instead of
the current proposal. In a real pub-booking business, that would be serious:
the agent might reject or confirm a booking using another customer's venue,
party size, or deposit.

The one primitive I would rely on to surface this is IPC atomic rename. The
handoff bridge writes exactly one visible `handoff_to_structured.json` file and
archives the old forward handoff after a rejection. In my Ex7 trace, line 5
shows the first handoff payload, line 7 shows the structured rejection, line 12
shows the retry handoff, and line 14 shows completion. That sequence only stays
safe if a handoff file becomes visible atomically and stale handoffs are removed
or archived before another one appears.

This primitive surfaces the failure because malformed IPC state is observable:
if more than one handoff file is visible, or if a stale file remains after the
bridge changes state, the system can fail closed instead of silently routing the
wrong booking.

### Citation

- `evidence/ex9/ex7_sessions/sess_5c4866c44934/logs/trace.jsonl:5`
- `evidence/ex9/ex7_sessions/sess_5c4866c44934/logs/trace.jsonl:7`
- `evidence/ex9/ex7_sessions/sess_5c4866c44934/logs/trace.jsonl:12`
- `evidence/ex9/ex7_sessions/sess_5c4866c44934/logs/trace.jsonl:14`
