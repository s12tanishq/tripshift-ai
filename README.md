# TripShift AI

A travel disruption and autonomous replanning prototype for TECHNOVA '26, Track 2 at PCE, Nagpur.

**Current status:** a model-driven competition prototype with an optional India-localized travel search. Gemini or Groq calls local itinerary, dependency, validation, provider-evidence, and communication tools. The main journey and selectable recovery plans remain simulated. SerpApi searches Google Flights and Hotels for India-localized, timestamped, indicative results when a key is configured. The app does not book travel or send messages.

## What works now

- Loads a five-step journey: flight, airport transfer, hotel check-in, client meeting, and team dinner.
- Applies a numeric flight delay and recalculates downstream timing through explicit dependency rules.
- Interprets IANA timezones and checks offsets, including daylight-saving transitions and trips across local timezones.
- Explains the causal path, remaining slack, and hard-rule violation for each affected commitment.
- Enforces earliest/latest hotel windows and minimum/maximum connection gaps where supplied.
- Can search Indian domestic flights and Nagpur hotels in INR, preserve search timestamps, and check a returned flight's schedule against the journey graph.
- Checks four candidate actions, including keeping the current journey, two replacement flights, and a late check-in/meeting change.
- Scores feasible plans transparently by extra cost, arrival delay, and explicit edits. The model weighs the checked trade-offs and chooses a plan; the tool layer rejects invalid choices.
- Maintains a Recovery Ladder: a model-selected plan plus a distinct validated fallback when available. A second-shock mode removes one replacement flight and forces a fresh model run and validation.
- Drafts driver, hotel, and meeting updates for human review only.
- Shows actual model tool calls in an observable action log and an honest no-feasible-plan result.
- Shows a specific next step for missing keys, rejected keys, quota, network failures, empty searches, and old travel results. A failed provider call never becomes a fake recommendation.
- Saves and opens demo setups as small JSON files containing only the entered controls. Changing inputs or refreshing travel evidence clears the previous analysis.
- Runs from a dark, responsive Streamlit dashboard with restrained mint accents, tactile hover/press feedback, cubic-bezier transitions, and reduced-motion support.

The model interprets the disruption, chooses which tools to call, and selects a checked recovery and fallback. When provider evidence has been searched, the model reads it through a separate tool. The local rules engine owns time arithmetic and hard constraints. Provider offers are **not** mapped to the simulated selectable plans: a displayed price or seat may change, rebooking cost is unknown, and a hotel result cannot confirm late check-in at an existing booking. If neither model provider completes the workflow, the app shows an error; it does not substitute a scripted recommendation.

## Run it

```bash
cd /Users/tanishqpachghare/Documents/TECHNOVA/agent-kit
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
test -f .env || cp .env.example .env
# Add a GEMINI_API_KEY or GROQ_API_KEY to .env
# Optional: add SERPAPI_API_KEY for India travel searches
streamlit run app.py
```

The project already has a local `venv`, so on this machine `venv/bin/streamlit run app.py` should work without reinstalling. Streamlit prints the local URL, usually `http://127.0.0.1:8501`. A model call happens only when you press **Analyze journey**. Auto mode tries Gemini first, then Groq if Gemini fails. You can choose either provider directly in the app. **Search India travel** starts a separate SerpApi search; if you then analyze the journey, the model reads that snapshot.

For travel search, create a [SerpApi account](https://serpapi.com/pricing) and set `SERPAPI_API_KEY=...` in `.env`. Its published free tier currently lists 250 searches per month; a flight and hotel check use two successful searches. The adapter requests Google Flights and Hotels with `gl=in` and `currency=INR`. This is **indicative search data**, not direct airline or hotel inventory. A live check on 1 October 2026 returned BOM–NAG flights and Nagpur hotels; actual results and prices can change. Three flight schedules fit the journey only if airport pickup moves, so they remain conditional until the driver confirms. Without the key, both searches show **unknown** and the simulated/model-driven demo still works. Keep keys out of chat and submission archives.

For a later commercial India integration, [TripJack](https://training.tripjack.com/nav/api) offers flights and hotels through one API, but its published flow includes an agreement, testing, certification, and onboarding; obtaining partner access is outside this competition prototype.

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

Run the automated checks:

```bash
venv/bin/python -m unittest discover -s tests -v
```

## Demo in four moves

1. **Delay cascade:** the 210-minute delay moves the transfer and hotel arrival. Hotel check-in misses its latest start by 30 minutes; the fixed client meeting needs 60 more minutes of travel and preparation. The timeline and impact panel show the full dependency path.
2. **Recovery Ladder:** the model compares checked alternatives and picks a primary and fallback. Switch the scenario mode to “Second shock” and analyze again. One replacement flight becomes unavailable; the model must choose among the remaining valid plans.
3. **Impossible case:** mark all replacement or exception options unavailable. Every candidate is blocked, and the app reports why instead of presenting an invented recovery.
4. **Provider evidence (optional):** press **Search India travel**. The separate panel shows observed time, indicative state, INR price, search timestamp, and the itinerary-rule result for flight timings. Analyze again to let the model inspect this evidence. If the search fails, use its displayed next step.

Open **Save or open a demo setup** to download the current controls as `tripshift-setup.json` or restore a saved file. The file excludes API keys, provider search results, and model output. It works across devices and does not write shared state to the server. Loaded setups require a fresh analysis and, if desired, a fresh travel search.

The journey and selectable recovery plans in the first three modes are simulated. Search results are separate indicative evidence; live fare, seat, and room availability must be rechecked before any purchase. A green validation badge means valid **against the stated timing rules**; it does not confirm a real seat, room, or stakeholder agreement.

## System design

```text
Disruption input
  → Gemini or Groq model calls local tools
  → read itinerary and record delay
  → trace dependencies and recompute slack
  → inspect optional India travel search evidence
  → inspect and validate simulated scenario options
  → model selects a valid plan and fallback
  → prepare messages for review
```

| Component | File | Responsibility |
| --- | --- | --- |
| Scenario fixture | `data/nagpur_demo.json` | Journey, rules, disruption, and simulated options |
| Deterministic core | `tripshift/core.py` | Time calculations, graph order, propagation, validation, ranking |
| Provider adapter | `tripshift/inventory.py` | Typed India travel search results, source times, retry guidance, flight schedule checks |
| Saved setups | `tripshift/scenario_io.py` | Versioned input-only JSON export/import and validation |
| Agent workflow | `tripshift/agent.py` | Provider calls, tool loop, guarded decision, fallback, draft preparation |
| Dashboard | `app.py` | Timeline, impact proof, plans, messages, action log, saved setups |
| UI settings | `.streamlit/config.toml` | Dark theme, local-only development server, 1 MB setup upload limit |
| CLI | `agent.py` | Repeatable terminal demo |
| Checks | `tests/` | Cascade, tool dispatch, selection guard, fallback, timezones, provider parsing, and unknown states |

The seven roles in the problem statement are responsibilities within this workflow, not seven separate language-model processes. The model makes genuine API tool calls and chooses the recovery. The deterministic core owns all time arithmetic. Each dependency has a source, target, minimum buffer, optional maximum gap, and reason. A graph connection alone does not make an item broken: the engine recomputes arrival times and slack before assigning a status. Fixed commitments remain fixed; movable ones shift only as needed. The validator rejects late check-in, meeting conflicts, connection gaps, unavailable options, and malformed journeys.

The fixture declares `Asia/Kolkata` and uses ISO timestamps with explicit offsets. Imported scenarios may declare a default `timezone`; an item may override it with `timezone`, `start_timezone`, or `end_timezone`. The parser checks that an explicit offset matches the named zone. For a local timestamp without an offset, it accepts an unambiguous time and rejects nonexistent or ambiguous daylight-saving times. Durations, delays, and dependency gaps are measured as elapsed time, then converted back to each event's local timezone for display.

Items may define `earliest_start`, `latest_start`, and `latest_end`. Dependencies may define `max_gap_minutes` in addition to `min_gap_minutes`. The Nagpur fixture now uses a hotel arrival window and a 30–90 minute landing-to-pickup window. These are checks against supplied scenario rules, not confirmations from a hotel or driver.

### Provider evidence

The fixture includes a BOM → NAG one-way query for 15 October 2026 and a one-night Nagpur hotel search. The adapter calls only SerpApi search endpoints, with India localization and INR. It records observation time, provider creation time when returned, and the search ID. It distinguishes `offers_found`, `no_results`, and `unknown`: an empty query does not prove there is no availability elsewhere, while a missing key, failed request, or unparseable response remains unknown. Returned flight times are parsed as `Asia/Kolkata` for this **Indian domestic** demo route and checked against the same dependency engine. An early flight is also checked with an explicitly moved airport pickup; a passing result is labeled **conditional** until the driver confirms that change. Hotel results must include coordinates within the fixture's radius and a total INR rate. Search results have no guaranteed expiry time; prices can change immediately, so the UI asks users to recheck. Neither flight nor hotel results become selectable simulated plans or prove a booking, seat, late check-in exception, or final rebooking cost.

### Status language

- **Unaffected:** known rules still have comfortable slack.
- **At risk:** an event changed, a dependency upstream is broken, or the spare buffer is 15 minutes or less.
- **Broken:** a hard deadline or timing rule is violated.
- **Valid plan:** every hard rule in the fixture passes and required simulated options are available.

The “Edits” figure counts **explicit plan changes**. Automatically propagated arrival shifts appear separately in the selected-plan proof.

## Interface direction

The UI uses a near-black canvas (`#090B0D`), low-contrast charcoal surfaces, mint (`#78F5C6`) for actions and valid states, and amber/red only for risk and failure. It favors a clear three-part workspace: journey timeline, dependency diagnosis, and recovery options. The action log and messages sit below the decision area.

Motion is brief and functional: 260–320 ms panel entry with `cubic-bezier(.22,1,.36,1)`, 120–160 ms hover/press feedback with `cubic-bezier(.2,.8,.2,1)`, and a reduced-motion override. Buttons have 44 px touch targets and keyboard controls show a visible mint focus ring. At 600 px and below, timeline times wrap beneath each event; the layout was checked in the browser at 390 px and 320 px with no horizontal overflow. No perpetual neon effects or background animation are used.

## Delivery roadmap

| Phase | State | Next acceptance target |
| --- | --- | --- |
| 1. Working agent prototype | Complete | Model tool calls, dependency proof, guarded choice, fallback, and dashboard |
| 2. Constraint engine hardening | Complete | IANA timezone validation, daylight-saving-safe elapsed time, hotel windows, connection bounds, and edge-case tests |
| 3. Provider data adapters | Complete; live search verified | Search India-localized flight/hotel results, preserve source times and unknown states, and check direct or conditional flight schedules against the graph |
| 4. Product reliability and UI | Complete | Actionable provider errors, portable saved setups, stale-analysis clearing, keyboard focus, and 320/390 px checks |
| 5. Competition handoff | Planned | Demo rehearsal, failure-case walkthrough, clean submission and attribution |
| 6. Real-world execution | Future | Authenticated holds or bookings and stakeholder messages, each behind human approval |

The competition demo currently needs a working model key and network access. Later integrations can replace simulated sources without replacing the constraint engine.

## Failure boundaries and trust

- No real bookings, payments, or stakeholder messages occur.
- Unknown external availability is not treated as confirmed. A missing key, provider error, or old search result gets a specific retry instruction.
- Travel search results are labeled indicative; no result is treated as a booked seat or room.
- Hotel search cannot verify a late check-in exception on the existing reservation.
- No plan that fails a hard rule is shown as a recommendation.
- The agent action log contains observable steps and results, not purported private model reasoning.
- If all options fail, the result names the blockers and asks for a human decision.
- Saved setup files include the entered disruption text; review that text before sharing a file. They never contain keys, live search evidence, or model results.
- The development server binds to `127.0.0.1` by default; override that setting explicitly for a deployment.
- `.env` is ignored by Git and read when analysis starts. The selected provider receives the entered disruption and simulated journey details. Diagnostic scripts from the original API test skeleton remain separate.

Track 2 requires genuine agentic behavior and an explainable technical defense. The team's implementation, rule choices, and failure boundaries should be understandable to every presenter. Credit any reused code according to the event's integrity rules. The Track 1 rule about GitHub commits every 20 minutes is not stated as a Track 2 rule.
