# TripShift AI

**Travel disruption and autonomous replanning agent** for TECHNOVA '26, Track 2: AI Agent Challenges at PCE, Nagpur.

> One change can affect the entire journey. TripShift traces those dependencies, proposes the smallest feasible recovery, checks every proposal against explicit rules, and explains what still needs a human decision.

## Project status

**Planning / API exploration.** The current `agent.py` and `app.py` are intentionally small prototypes used to test model providers, tool calling, and Streamlit. They do **not** yet implement the travel product described below. The travel engine, scenarios, recovery plans, and finished interface are roadmap items. Do not present README features as already working during a demo.

This project uses simulated itinerary, flight, and hotel data for the competition prototype. It does not check live availability, make bookings, or send messages.

## The challenge

An itinerary is a network of commitments. A delayed flight may leave too little time for a transfer, close a hotel check-in window, and make a meeting unreachable. Generating a fresh itinerary misses the important question: **which commitments became impossible, why, and what is the least disruptive valid repair?**

The submitted agent must demonstrate a multi-step workflow with tool use and decisions. Seven named responsibilities from the problem statement are implemented as **roles and tools**, not necessarily seven independent language models:

| Role | Responsibility |
| --- | --- |
| Itinerary | Read the journey and identify affected items |
| Flight | Apply the disruption and inspect replacement options |
| Dependency | Propagate timing changes through explicit constraints |
| Hotel | Check arrival windows and alternatives |
| Schedule | Check meetings, activities, preparation, and travel time |
| Replanning | Compare candidates and repair rejected plans |
| Communication | Draft messages for people affected by the chosen plan |

## Product contract

Given a structured journey and a disruption, TripShift should:

1. Show the original itinerary and the precise changed event.
2. Recompute downstream times and classify each item as **unaffected**, **at risk**, or **broken**. Each label must include the governing rule and remaining slack or violation.
3. Find two or three recovery candidates when the scenario data permits. Include the option that changes the fewest commitments.
4. Validate each candidate before recommending it. Reject broken connections, overlaps, closed check-in windows, invalid meeting arrival times, and other hard-constraint violations.
5. Compare valid candidates by arrival delay, extra cost, number of changed items, priority commitments preserved, and resilience.
6. Draft relevant stakeholder messages for user review. Applying a plan and sending messages require explicit human confirmation in any future connected version.
7. Report **no feasible plan** with specific blockers when the available data cannot support one.

A validation badge means **valid against the current scenario snapshot and stated assumptions**. It does not imply a live seat, room, or reservation is confirmed.

## Standout feature: Recovery Ladder

A recovery plan includes a **checked fallback and an activation trigger**. Example: “Choose replacement flight A; if that flight becomes unavailable, use flight B and move the client meeting by 30 minutes.” The agent validates both branches before showing them, then demonstrates a second injected disruption by switching branches and recalculating the dependency chain.

The ladder exposes its assumptions. If the fallback also fails, TripShift stops with the blocking constraints instead of inventing availability or claiming a guarantee. This is the intended meaning of a robust recovery, not a promise that external travel systems cannot fail.

## How the agent should work

```text
Disruption input
    ↓
Parse and normalize event → inspect itinerary → calculate dependency impact
    ↓
Search scenario alternatives → build candidate plans → deterministic validation
    ↓                                         ↑
Rank valid plans ← repair rejected candidates ┘
    ↓
Prepare Recovery Ladder → explain changes → draft messages for review
```

The language model interprets the request, chooses tools, weighs valid trade-offs, and writes explanations. Typed Python code owns time arithmetic, dependency propagation, feasibility checks, and scoring. A plan may be shown as a recommendation only after validation.

### Planned data model

- **Itinerary item:** stable ID, kind (flight, transfer, hotel, meeting, activity), local start/end, IANA timezone, location, status, flexibility, priority, cost, and data source.
- **Dependency:** source item, target item, rule type, minimum buffer or deadline, hard/soft status, and explanation.
- **Disruption:** item ID, changed field, old/new values, observation time, and source.
- **Recovery plan:** proposed changes, cost and delay deltas, affected commitments, validation report, assumptions, and fallback trigger.
- **Validation report:** pass/fail for every hard rule, remaining slack, unresolved unknowns, and a reproducible reason for each result.

Times should be stored in timezone-aware form and displayed in local time. A graph edge only means an item *may* be affected; the engine must recompute slack to decide whether it is actually at risk or broken. Missing duration, policy, or availability data must appear as **unknown**, never silently become a valid assumption.

## Interface direction

The app should feel like a compact travel operations desk: **near-black canvas, one restrained neon mint accent, crisp typography, generous spacing, and visible causal relationships**. Risk colors communicate status; they are not decoration.

```text
TripShift        Journey: Mumbai → Nagpur            Scenario data
─────────────────────────────────────────────────────────────────────
Disruption: flight delayed 3h 30m               [Analyze impact]

Journey timeline       Impact and dependency path     Recovery plans
Flight → Transfer      Broken hotel check-in          A  Fastest
       → Hotel         At-risk client meeting         B  Fewest changes
       → Meeting       Rule + remaining slack         Cost · delay · proof
                                                      Fallback trigger
─────────────────────────────────────────────────────────────────────
Messages to review                       Agent action log
```

**Visual tokens:** canvas `#090B0D`, surface `#111619`, primary text `#F3F6F5`, muted text `#95A5A3`, border `#26332F`, accent `#78F5C6`. Use amber and red sparingly for risk and broken states. Keep icons simple and avoid large gradients, permanent glows, and decorative particle effects.

**Motion:** cards and controls should feel responsive and tactile through opacity/transform transitions. Use `cubic-bezier(0.22, 1, 0.36, 1)` for 260–320 ms panel entrances, `cubic-bezier(0.2, 0.8, 0.2, 1)` for 120–160 ms hover/press feedback, and `cubic-bezier(0.4, 0, 0.2, 1)` for 200–240 ms state changes. Animate a dependency path once when its status changes; do not run continuous motion. Support keyboard focus, high contrast, and `prefers-reduced-motion`. On narrower screens, stack the three work areas while keeping the disruption and selected plan easy to reach.

**Implementation direction:** retain Python for the agent and constraint engine. Build the first competition interface in Streamlit with focused CSS/custom components for the timeline, plan cards, and motion. If Streamlit's rerun model prevents the desired interaction quality, the UI can later move to a dedicated frontend without replacing the core engine.

## Build roadmap

| Phase | Deliverable | Done when |
| --- | --- | --- |
| 1. Core journey | Typed itinerary and scenario fixtures | A seeded trip and delay load reproducibly |
| 2. Dependency engine | Propagation, slack, and validation | Every affected item has a rule-backed status; impossible plans fail |
| 3. Agent workflow | Travel-specific tools and bounded repair loop | The agent calls tools, revises rejected candidates, and reports blockers |
| 4. Recovery Ladder | Ranked plans plus tested fallback trigger | A second disruption activates a revalidated branch |
| 5. Interface and communication | Dark dashboard, comparisons, drafts, action log | Judges can follow cause → repair → proof without reading raw tool output |
| 6. Demo hardening | Tests, setup instructions, offline fixture mode | The demo survives provider failure and the impossible-case scenario |

**Competition priority:** complete phases 1–2 and one end-to-end valid recovery before expanding the interface. Then add ranked choices, the Recovery Ladder, and presentation polish. Live APIs and real bookings are outside the competition MVP.

## Demo scenarios and checks

1. **Delay cascade:** a delayed flight breaks a transfer buffer, closes hotel check-in, and threatens a meeting. Show the exact rule and slack at each step, then compare repairs.
2. **Second shock:** remove the preferred replacement flight. Show the Recovery Ladder trigger, fallback validation, and changed communication drafts.
3. **Impossible case:** no available candidate satisfies hard constraints. Show the blockers and what a human must resolve.

Core checks should cover midnight and timezone crossings, tight transfer buffers, overlapping meetings, hotel policies, missing data, repeated disruption events, candidate validation, and provider outage. Use deterministic fixture data so the jury can replay the same result.

## Current skeleton and local exploration

The existing files are exploratory, not the final architecture:

- `agent.py`: generic OpenAI-compatible tool-calling loop with Groq, Gemini, and optional Ollama configuration.
- `app.py`: simple Streamlit interface for the generic loop.
- `test_keys.py` and `list_gemini.py`: provider diagnostics.

The current loop exposes a calculator, web search, and text-file writer. These are **not** travel availability or booking tools. The current default provider chain also does not include Ollama; offline operation must be tested and configured before it is advertised as working. Provider failover currently restarts a task, so future state-changing tools must avoid duplicate actions.

To explore the skeleton, use a local virtual environment with the dependencies imported by these files (`openai`, `python-dotenv`, `ddgs`, and `streamlit`), set provider credentials in `.env`, then run `python agent.py "your goal"` or `streamlit run app.py`. This runs the **generic test agent**, not TripShift. A pinned `requirements.txt`, `.env.example`, and reproducible project setup are planned deliverables. Never commit `.env` or API keys.

## Failure boundaries

- All flight and hotel options in the MVP are simulated and labeled as such.
- External information and model text cannot override validator rules.
- No recommendation is labeled valid when a required constraint is unresolved.
- A model outage falls back to a deterministic scenario explanation or an explicit unavailable state; it must not fabricate a plan.
- The user reviews changes and messages. The prototype does not make bookings or contact stakeholders.
- The interface shows an action log of observable tool calls and results, not supposed access to the model's private reasoning.

## Event and ownership notes

Track 2 permits and encourages AI tooling, but the team must be able to explain the implementation, prompt design, workflow, and failure boundaries. The event's general integrity rules prohibit presenting third-party work as one's own. Credit the origin of any reused skeleton or code, and follow additional instructions announced by the organizers. The Track 1 rule to push a GitHub commit every 20 minutes is not stated as a Track 2 requirement.
