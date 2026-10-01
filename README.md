# TripShift AI

A travel disruption and autonomous replanning prototype for TECHNOVA '26, Track 2 at PCE, Nagpur.

**Current status:** a model-driven competition prototype for a user-entered, single-flight journey and its connected commitments. Enter an origin and destination airport, flight, pickup, hotel check-in, meeting, and activity; then test how a delay affects the whole chain. Gemini or Groq calls local itinerary, dependency, validation, provider-evidence, and communication tools. Optional SerpApi searches return timestamped, indicative flights for the selected airport pair and hotels in the destination city. A prefilled Mumbai → Nagpur journey is available for a repeatable demo. The app does not book travel or send messages.

## What works now

- Builds a journey from user-entered origin/destination airport codes, city names, IANA time zones, flight times, pickup, hotel deadline, meeting, and activity. **Demo journey** provides a prefilled example; both modes use the same dependency validator.
- Applies a numeric flight delay and recalculates downstream timing through explicit dependency rules.
- Interprets IANA timezones and checks offsets, including daylight-saving transitions and trips across local timezones.
- Explains the causal path, remaining slack, and hard-rule violation for each affected commitment.
- Enforces earliest/latest hotel windows and minimum/maximum connection gaps where supplied.
- Can search flights for the selected IATA airport pair and destination-city hotels in INR, preserve search timestamps, and check returned flight schedules in the entered time zones. City-level hotel proximity remains unverified without hotel coordinates.
- Checks four candidate actions for either journey. User-entered journey alternatives are explicitly **illustrative**: prices and availability are unknown until checked with a supplier and stakeholders.
- Compares candidates by timing, known cost where available, and explicit edits. The model weighs the checked trade-offs and chooses a plan; the tool layer rejects options that fail hard timing rules. An unknown custom-route price is never presented as a real ₹0 fare.
- Maintains a Recovery Ladder: a model-selected plan plus a distinct validated fallback when available. A second-shock mode removes one replacement flight and forces a fresh model run and validation.
- Drafts driver, hotel, and meeting updates for human review only.
- Shows actual model tool calls in an observable action log and an honest no-feasible-plan result.
- Shows a specific next step for missing keys, rejected keys, quota, network failures, empty searches, and old travel results. A failed provider call never becomes a fake recommendation.
- Saves and opens setups as small JSON files containing entered controls and, when selected, the custom journey. Changing inputs or refreshing travel evidence clears the previous analysis.
- Runs from a dark, responsive Streamlit dashboard with a muted sage accent, tactile hover/press feedback, cubic-bezier transitions, and reduced-motion support.

The model interprets the disruption, chooses which tools to call, and selects a timing-checked recovery and fallback. When provider evidence has been searched, the model reads it through a separate tool. The local rules engine owns time arithmetic and hard constraints. Provider offers are **not** mapped to the illustrative selectable plans: a displayed price or seat may change, rebooking cost is unknown, and a hotel result cannot confirm late check-in at an existing booking. If neither model provider completes the workflow, the app shows an error; it does not substitute a scripted recommendation.

## Run it

```bash
cd agent-kit
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
test -f .env || cp .env.example .env
# Add a GEMINI_API_KEY or GROQ_API_KEY to .env
# Optional: add SERPAPI_API_KEY for India travel searches
streamlit run app.py
```

Streamlit prints a local URL, usually `http://127.0.0.1:8501`. Select **My journey** to enter your own airport pair and commitments, or select **Demo journey** for the prefilled example. A model call happens only when you press **Analyze journey**. Auto mode tries Gemini first, then Groq if Gemini fails. You can choose either provider directly in the app. **Search live travel** starts a separate SerpApi search for the selected route; if you then analyze the journey, the model reads that snapshot.

For travel search, create a [SerpApi account](https://serpapi.com/pricing) and set `SERPAPI_API_KEY=...` in `.env`. A flight-and-hotel check makes two searches. The adapter requests Google Flights and Hotels with `gl=in` and `currency=INR`. Airport codes, dates, city, and time zones come from the selected journey. This is **indicative search data**, not direct airline or hotel inventory; coverage and results depend on the entered route and date. A flight schedule may fit only if pickup moves, and that driver change remains conditional until confirmed. Without a search key, both searches show **unknown**, while model-driven analysis of the entered schedule can still run. Keep keys out of chat and submission archives.

For a later commercial India integration, [TripJack](https://training.tripjack.com/nav/api) offers flights and hotels through one API, but its published flow includes an agreement, testing, certification, and onboarding; obtaining partner access is outside this competition prototype.

The defaults are `gemini-3.5-flash-lite` and `openai/gpt-oss-120b`; set `GEMINI_MODEL` or `GROQ_MODEL` in `.env` to change them. Model access and rate limits depend on your provider account. The existing `.env` is local and ignored by Git; never include it in a submission archive.

CLI commands for the included prefilled scenario (the dashboard supports user-entered journeys):

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

## Build and analyze a journey

Select **My journey** near the top of the dashboard. Open **Build your journey** and enter both airport codes and city names, an IANA time zone for each city, the original flight departure and arrival, airport pickup, hotel check-in and deadline, meeting, and activity times. Flight departure is entered in the origin's local time; the arrival and later commitments use the destination's local time. The builder checks that the original journey is possible before accepting it. It assumes a 45-minute airport transfer, a 30-minute hotel check-in, 30–90 minutes from landing to pickup, and short travel/preparation buffers between later events. Airport codes must be three letters; a code's real-world validity and route coverage are established only when a travel provider returns results.

Press **Use this journey**. The route illustration, event strip, disruption analysis, dependency chain, recovery candidates, drafts, and travel search then use the new journey. The editor collapses after saving. Changing routes clears the prior analysis and search snapshot. A user-entered journey is held in the browser session; use **Settings & saved setups → Save setup** to keep a portable copy. Older version 1 demo setup files still load.

Custom recovery candidates are **illustrative timing scenarios**, not found flights or confirmed hotel exceptions. Their price is shown as **Unknown** and they require independent confirmation. The live flight search can look up the entered airport pair and the hotel search queries the destination city. City-level hotel results have unverified proximity to the actual meeting or hotel.

The current builder handles **one flight followed by pickup, hotel check-in, meeting, and activity**. Additional flight legs and arbitrary event types are future work.

## Try the workflow in four moves

1. **Choose a journey:** enter your own route and commitments in **My journey**, or use **Demo journey** for a prefilled case.
2. **Apply a delay:** set the flight delay and press **Analyze journey**. Follow the impact panel from the flight through pickup, hotel, meeting, and activity. It shows changed times, spare buffer, and any broken rule.
3. **Inspect recovery:** compare the timing-checked primary choice and fallback. **Second shock** removes one illustrative replacement option and runs the checks again. **Impossible case** blocks all replacement or exception options so you can see the no-feasible-plan response.
4. **Check provider evidence (optional):** press **Search live travel** for the selected airport pair and destination city. The separate panel shows observation time, indicative state, INR price, and the timing-rule result for flight schedules. Analyze again to let the model inspect this evidence.

For a repeatable judge walkthrough, **Demo journey** uses a simulated Mumbai → Nagpur itinerary with a 210-minute delay. That specific case misses its hotel check-in deadline by 30 minutes and leaves the fixed meeting 60 minutes short of its required travel and preparation buffer. User-entered journeys produce their own results from their entered times and rules.

Open **Settings & saved setups** to download the current controls and custom journey, if selected, as `tripshift-setup.json` or restore a saved file. The file excludes API keys, provider search results, and model output. It works across devices and does not write shared state to the server. Loaded setups require a fresh analysis and, if desired, a fresh travel search.

The included demo journey and its selectable plans are simulated. User-entered journey recovery choices are hypothetical schedule changes. Search results are separate indicative evidence; live fare, seat, and room availability must be rechecked before any purchase. A passing validation badge means a plan fits **the stated timing rules**; it does not confirm a real seat, room, or stakeholder agreement.

## System design

```text
Selected journey + disruption input
  → Gemini or Groq model calls local tools
  → read itinerary and record delay
  → trace dependencies and recompute slack
  → inspect optional India travel search evidence
  → inspect and validate recovery candidates
  → model selects a valid plan and fallback
  → prepare messages for review
```

| Component | File | Responsibility |
| --- | --- | --- |
| Included demo | `data/nagpur_demo.json` | Repeatable example journey and simulated recovery choices |
| Journey builder | `tripshift/builder.py` | Validate user-entered route and commitments, generate dependency graph and illustrative recovery choices |
| Deterministic core | `tripshift/core.py` | Time calculations, graph order, propagation, validation, ranking |
| Provider adapter | `tripshift/inventory.py` | Typed India travel search results, source times, retry guidance, flight schedule checks |
| Saved setups | `tripshift/scenario_io.py` | Versioned input-only JSON export/import and validation |
| Agent workflow | `tripshift/agent.py` | Provider calls, tool loop, guarded decision, fallback, draft preparation |
| Dashboard | `app.py` | Timeline, impact proof, plans, messages, action log, saved setups |
| UI settings | `.streamlit/config.toml` | Dark theme, local-only development server, 1 MB setup upload limit |
| CLI | `agent.py` | Repeatable terminal demo |
| Checks | `tests/` | Cascade, tool dispatch, selection guard, fallback, timezones, provider parsing, and unknown states |

The seven roles in the problem statement are responsibilities within this workflow, not seven separate language-model processes. The model makes genuine API tool calls and chooses the recovery. The deterministic core owns all time arithmetic. Each dependency has a source, target, minimum buffer, optional maximum gap, and reason. A graph connection alone does not make an item broken: the engine recomputes arrival times and slack before assigning a status. Fixed commitments remain fixed; movable ones shift only as needed. The validator rejects late check-in, meeting conflicts, connection gaps, unavailable options, and malformed journeys.

The journey builder accepts an IANA time zone for each airport and validates local times. The included demo uses `Asia/Kolkata` and ISO timestamps with explicit offsets. Imported scenarios may declare a default `timezone`; an item may override it with `timezone`, `start_timezone`, or `end_timezone`. The parser checks that an explicit offset matches the named zone. For a local timestamp without an offset, it accepts an unambiguous time and rejects nonexistent or ambiguous daylight-saving times. Durations, delays, and dependency gaps are measured as elapsed time, then converted back to each event's local timezone for display.

Items may define `earliest_start`, `latest_start`, and `latest_end`. Dependencies may define `max_gap_minutes` in addition to `min_gap_minutes`. Both the builder and included demo apply a hotel deadline and a 30–90 minute landing-to-pickup window. These are checks against supplied scenario rules, not confirmations from a hotel or driver.

### Provider evidence

The selected journey supplies its origin and destination airport codes, travel date, destination city, and time zones. The adapter calls SerpApi search endpoints with India localization and INR. It records observation time, provider creation time when returned, and the search ID. It distinguishes `offers_found`, `no_results`, and `unknown`: an empty query does not prove there is no availability elsewhere, while a missing key, failed request, or unparseable response remains unknown.

Returned flight times are parsed in the selected origin and destination IANA time zones and checked against the same dependency engine. A flight that works only after moving airport pickup is labelled **conditional** until the driver confirms that change. Where hotel coordinates are supplied, the adapter can check the configured radius. User-entered journeys currently search by destination city, so hotel proximity is unverified. Search results have no guaranteed expiry time; prices can change immediately, so the UI asks users to recheck. Neither flights nor hotels returned by the provider become selectable recovery plans or prove a booking, seat, late check-in exception, or final rebooking cost.

### Status language

- **Unaffected:** known rules still have comfortable slack.
- **At risk:** an event changed, a dependency upstream is broken, or the spare buffer is 15 minutes or less.
- **Broken:** a hard deadline or timing rule is violated.
- **Valid plan / timing fits:** every hard timing rule passes. For a custom journey, availability and price of illustrative options still need confirmation.

The “Edits” figure counts **explicit plan changes**. Automatically propagated arrival shifts appear separately in the selected-plan proof.

## Interface direction

The UI includes a compact Demo journey / My journey switch and a collapsible builder that leaves the main dashboard uncluttered. It uses a near-black canvas (`#0C0E10`), charcoal surfaces, and one muted sage accent (`#A8BDB1`). A consistent system sans-serif font, quieter borders, and a narrower content area keep the workspace readable. The recommended recovery appears first; alternatives expand on demand. Journey, Travel search, Messages, and Activity have separate tabs. Model/scenario controls and portable setups sit inside **Settings & saved setups**. Status labels and distinct marker shapes keep risk readable without relying on multiple bright colours.

Motion is brief and functional: 300–350 ms panel entry with `cubic-bezier(.22,1,.36,1)`, 160–200 ms hover/press feedback with `cubic-bezier(.2,.8,.2,1)`, and a reduced-motion override. Buttons have 44 px touch targets and keyboard controls show a visible sage focus ring. At 600 px and below, timeline times wrap beneath each event; the layout was checked in the browser at 390 px and 320 px with no horizontal overflow. The header illustrates the selected route with a finite line-draw and arrival animation. The original itinerary uses a compact icon-based stage preview. Muted surface gradients and a fine accent edge distinguish the recommendation. Motion stops after the introduction and respects reduced-motion preferences; no perpetual neon effects are used.

## Delivery roadmap

| Phase | State | Next acceptance target |
| --- | --- | --- |
| 1. Working agent prototype | Complete | Model tool calls, dependency proof, guarded choice, fallback, and dashboard |
| 2. Constraint engine hardening | Complete | IANA timezone validation, daylight-saving-safe elapsed time, hotel windows, connection bounds, and edge-case tests |
| 3. Provider data adapters | Complete; live search verified | Search India-localized flight/hotel results, preserve source times and unknown states, and check direct or conditional flight schedules against the graph |
| 4. Product reliability and UI | Complete | User-entered routes, actionable provider errors, portable saved setups, stale-analysis clearing, keyboard focus, and 320/390 px checks |
| 5. Competition handoff | Planned | Demo rehearsal, failure-case walkthrough, clean submission and attribution |
| 6. Real-world execution | Future | Authenticated holds or bookings and stakeholder messages, each behind human approval |

Model analysis currently needs a working Gemini or Groq key and network access. Travel search additionally needs a SerpApi key. Later integrations can replace simulated sources without replacing the constraint engine.

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
