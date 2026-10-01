# TripShift AI

A travel disruption and autonomous replanning prototype for TECHNOVA '26, Track 2 at PCE, Nagpur.

**Current status:** a model-driven competition prototype with an optional Duffel provider search. Gemini or Groq calls local itinerary, dependency, validation, provider-evidence, and communication tools. The main journey and selectable recovery plans remain simulated. Duffel flight and hotel searches provide separate, timestamped evidence when a token is configured. The app does not book travel or send messages.

## What works now

- Loads a five-step journey: flight, airport transfer, hotel check-in, client meeting, and team dinner.
- Applies a numeric flight delay and recalculates downstream timing through explicit dependency rules.
- Interprets IANA timezones and checks offsets, including daylight-saving transitions and trips across local timezones.
- Explains the causal path, remaining slack, and hard-rule violation for each affected commitment.
- Enforces earliest/latest hotel windows and minimum/maximum connection gaps where supplied.
- Can search Duffel for flight and hotel offers, label test versus live data, show offer expiry, and check a returned flight's schedule against the journey graph.
- Checks four candidate actions, including keeping the current journey, two replacement flights, and a late check-in/meeting change.
- Scores feasible plans transparently by extra cost, arrival delay, and explicit edits. The model weighs the checked trade-offs and chooses a plan; the tool layer rejects invalid choices.
- Maintains a Recovery Ladder: a model-selected plan plus a distinct validated fallback when available. A second-shock mode removes one replacement flight and forces a fresh model run and validation.
- Drafts driver, hotel, and meeting updates for human review only.
- Shows actual model tool calls in an observable action log and an honest no-feasible-plan result.
- Runs from a dark, responsive Streamlit dashboard with restrained mint accents, tactile hover/press feedback, cubic-bezier transitions, and reduced-motion support.

The model interprets the disruption, chooses which tools to call, and selects a checked recovery and fallback. When provider evidence has been searched, the model reads it through a separate tool. The local rules engine owns time arithmetic and hard constraints. Provider offers are **not** mapped to the simulated selectable plans: a fare may expire, its currency and rebooking cost may differ, and a hotel room result cannot confirm late check-in at an existing booking. If neither model provider completes the workflow, the app shows an error; it does not substitute a scripted recommendation.

## Run it

```bash
cd /Users/tanishqpachghare/Documents/TECHNOVA/agent-kit
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Add a GEMINI_API_KEY or GROQ_API_KEY to .env
# Optional: add DUFFEL_ACCESS_TOKEN for provider flight/hotel searches
streamlit run app.py
```

The project already has a local `venv`, so on this machine `venv/bin/streamlit run app.py` should work without reinstalling. Streamlit prints the local URL, usually `http://localhost:8501`. A model call happens only when you press **Analyze journey**. Auto mode tries Gemini first, then Groq if Gemini fails. You can choose either provider directly in the app. **Check provider offers** starts a separate Duffel search; if you then analyze the journey, the model reads that snapshot.

For provider testing, create a [Duffel developer test token](https://duffel.com/docs/api/overview/test-mode) and place it in `.env` as `DUFFEL_ACCESS_TOKEN=...`. Duffel Stays requires [separate account access](https://duffel.com/docs/guides/getting-started-with-stays). If that access is missing, hotel evidence shows **unknown** while flight search can still work. A test token returns sandbox data that may have unrealistic schedules and prices; the interface labels it as test mode. Do not paste keys into chat or include `.env` in an archive.

The defaults are `gemini-3.5-flash-lite` and `openai/gpt-oss-120b`; set `GEMINI_MODEL` or `GROQ_MODEL` in `.env` to change them. Model access and rate limits depend on your provider account. The existing `.env` is local and ignored by Git; never include it in a submission archive.

CLI demo:

```bash
venv/bin/python agent.py --delay 210
venv/bin/python agent.py --delay 210 --second-shock
venv/bin/python agent.py --delay 210 --impossible
venv/bin/python agent.py --delay 0
venv/bin/python agent.py "Our flight is delayed by three and a half hours" --provider gemini
venv/bin/python agent.py --inventory-only --delay 210
venv/bin/python agent.py --delay 210 --search-offers
```

Run the deterministic checks:

```bash
venv/bin/python -m unittest discover -s tests -v
```

## Demo in four moves

1. **Delay cascade:** the 210-minute delay moves the transfer and hotel arrival. Hotel check-in misses its latest start by 30 minutes; the fixed client meeting needs 60 more minutes of travel and preparation. The timeline and impact panel show the full dependency path.
2. **Recovery Ladder:** the model compares checked alternatives and picks a primary and fallback. Switch the scenario mode to “Second shock” and analyze again. One replacement flight becomes unavailable; the model must choose among the remaining valid plans.
3. **Impossible case:** mark all replacement or exception options unavailable. Every candidate is blocked, and the app reports why instead of presenting an invented recovery.
4. **Provider evidence (optional):** press **Check provider offers**. The separate panel shows observed time, test/live mode, fare or rate, expiry, and the itinerary-rule result for flight timings. Analyze again to let the model inspect this evidence.

The journey and selectable recovery plans in the first three modes are simulated. Provider search results are separate evidence, and test-mode offers are sandbox data. A green validation badge means valid **against the stated timing rules**; it does not confirm a real seat, room, or stakeholder agreement.

## System design

```text
Disruption input
  → Gemini or Groq model calls local tools
  → read itinerary and record delay
  → trace dependencies and recompute slack
  → inspect optional Duffel search evidence
  → inspect and validate simulated scenario options
  → model selects a valid plan and fallback
  → prepare messages for review
```

| Component | File | Responsibility |
| --- | --- | --- |
| Scenario fixture | `data/nagpur_demo.json` | Journey, rules, disruption, and simulated options |
| Deterministic core | `tripshift/core.py` | Time calculations, graph order, propagation, validation, ranking |
| Provider adapter | `tripshift/inventory.py` | Typed Duffel flights/hotels, source times, unknown states, flight schedule checks |
| Agent workflow | `tripshift/agent.py` | Provider calls, tool loop, guarded decision, fallback, draft preparation |
| Dashboard | `app.py` | Timeline, impact proof, plans, messages, action log |
| CLI | `agent.py` | Repeatable terminal demo |
| Checks | `tests/` | Cascade, tool dispatch, selection guard, fallback, timezones, provider parsing, and unknown states |

The seven roles in the problem statement are responsibilities within this workflow, not seven separate language-model processes. The model makes genuine API tool calls and chooses the recovery. The deterministic core owns all time arithmetic. Each dependency has a source, target, minimum buffer, optional maximum gap, and reason. A graph connection alone does not make an item broken: the engine recomputes arrival times and slack before assigning a status. Fixed commitments remain fixed; movable ones shift only as needed. The validator rejects late check-in, meeting conflicts, connection gaps, unavailable options, and malformed journeys.

The fixture declares `Asia/Kolkata` and uses ISO timestamps with explicit offsets. Imported scenarios may declare a default `timezone`; an item may override it with `timezone`, `start_timezone`, or `end_timezone`. The parser checks that an explicit offset matches the named zone. For a local timestamp without an offset, it accepts an unambiguous time and rejects nonexistent or ambiguous daylight-saving times. Durations, delays, and dependency gaps are measured as elapsed time, then converted back to each event's local timezone for display.

Items may define `earliest_start`, `latest_start`, and `latest_end`. Dependencies may define `max_gap_minutes` in addition to `min_gap_minutes`. The Nagpur fixture now uses a hotel arrival window and a 30–90 minute landing-to-pickup window. These are checks against supplied scenario rules, not confirmations from a hotel or driver.

### Provider evidence

The fixture includes a BOM → NAG flight query for 15 October 2026 and a one-night hotel search around the Nagpur city centre. The Duffel adapter calls only search endpoints. It records when the response was observed and, when provided, the provider's creation time. It distinguishes `offers_found`, `no_results`, and `unknown`: an empty search does not prove there is no availability elsewhere, while a token or network failure stays unknown. A flight offer is checked as a possible schedule against the same dependency engine, but is not ranked by the simulated INR cost score or selectable as a plan. Expired and malformed offers are withheld from usable evidence. Hotel results show accommodation rates only and do not imply acceptance of a late check-in at the existing hotel.

### Status language

- **Unaffected:** known rules still have comfortable slack.
- **At risk:** an event changed, a dependency upstream is broken, or the spare buffer is 15 minutes or less.
- **Broken:** a hard deadline or timing rule is violated.
- **Valid plan:** every hard rule in the fixture passes and required simulated options are available.

The “Edits” figure counts **explicit plan changes**. Automatically propagated arrival shifts appear separately in the selected-plan proof.

## Interface direction

The UI uses a near-black canvas (`#090B0D`), low-contrast charcoal surfaces, mint (`#78F5C6`) for actions and valid states, and amber/red only for risk and failure. It favors a clear three-part workspace: journey timeline, dependency diagnosis, and recovery options. The action log and messages sit below the decision area.

Motion is brief and functional: 260–320 ms panel entry with `cubic-bezier(.22,1,.36,1)`, 120–160 ms hover/press feedback with `cubic-bezier(.2,.8,.2,1)`, and a reduced-motion override. Streamlit stacks the columns on narrow screens. No perpetual neon effects or background animation are used.

## Delivery roadmap

| Phase | State | Next acceptance target |
| --- | --- | --- |
| 1. Working agent prototype | Complete | Model tool calls, dependency proof, guarded choice, fallback, and dashboard |
| 2. Constraint engine hardening | Complete | IANA timezone validation, daylight-saving-safe elapsed time, hotel windows, connection bounds, and edge-case tests |
| 3. Provider data adapters | Implemented; account verification pending | Search Duffel flight/hotel offers, preserve source times and unknown states, and check flight schedules against the graph |
| 4. Product reliability and UI | Planned | Provider retry guidance, saved scenarios, accessibility and device checks |
| 5. Competition handoff | Planned | Demo rehearsal, failure-case walkthrough, clean submission and attribution |
| 6. Real-world execution | Future | Authenticated holds or bookings and stakeholder messages, each behind human approval |

The competition demo currently needs a working model key and network access. Later integrations can replace simulated sources without replacing the constraint engine.

## Failure boundaries and trust

- No real bookings, payments, or stakeholder messages occur.
- Unknown external availability is not treated as confirmed.
- Provider test-mode offers are labeled as sandbox data; no offer is treated as a booked seat or room.
- Hotel search cannot verify a late check-in exception on the existing reservation.
- No plan that fails a hard rule is shown as a recommendation.
- The agent action log contains observable steps and results, not purported private model reasoning.
- If all options fail, the result names the blockers and asks for a human decision.
- `.env` is ignored by Git and read when analysis starts. The selected provider receives the entered disruption and simulated journey details. Diagnostic scripts from the original API test skeleton remain separate.

Track 2 requires genuine agentic behavior and an explainable technical defense. The team's implementation, rule choices, and failure boundaries should be understandable to every presenter. Credit any reused code according to the event's integrity rules. The Track 1 rule about GitHub commits every 20 minutes is not stated as a Track 2 rule.
