# AI-Enabled Project & Delivery Management

**A 20-hour practitioner program for experienced Project and Delivery Managers**
Five half-days · 4–4.5 hours each · online, recorded · hands-on throughout

Prepared by GenAI People (Jerry Kurian) for Gynosis Information Technology Pvt. Ltd. · client: UST

---

## 1. Program summary

Generative AI has moved from "a chatbot that drafts my status report" to agents
that plan, design, implement, review and test software on their own. The job of
the Project and Delivery Manager is changing with it: less time collecting
status, more time deciding at gates; less time chasing risk, more time reading
forecasts that were produced from live delivery data.

This program teaches both halves of that shift:

1. **Using AI in project management** — Generative AI, predictive analytics and
   automation across planning, forecasting, risk, reporting and stakeholder
   communication, with the tools PMs already run (Jira / Azure DevOps / GitHub,
   Teams / Slack, Excel / Power BI, Copilot / ChatGPT / Claude).
2. **Managing AI-driven delivery** — how to govern a delivery pipeline in which
   agents do most of the work and humans hold the gates. The running case for
   this is the **Software Factory**, an open-source agent-driven delivery
   pipeline built by GenAI People: a plain GitHub issue goes in; a specced,
   planned, designed, implemented, reviewed, tested and released change comes
   out — with human approval gates and no ability for an agent to put anything
   on `main`.

Every module has a lab. Days 1–3 use each participant's own tooling plus a
sandbox GitHub organisation; Days 4–5 run a real epic through the Software
Factory with participants in the approver seats. The capstone is a full
AI-enabled delivery plan for a case-study release, presented and critiqued.

### Why the Software Factory is the running case

The client's stated outcomes — predictability, faster reporting, lower risk
exposure, automation, better governance, readiness for AI-driven initiatives —
are exactly what a factory-style pipeline forces you to design for:

| Factory concept | What a PM learns from it |
|---|---|
| **GitHub is the state machine** — issues, sub-issues and `factory:*` labels encode where every piece of work is | Reporting becomes a query, not a meeting. Flow metrics come for free |
| **OpenSpec is the content** — proposal, WHEN/THEN scenarios, design, task list live in the repo; issues carry state plus a link, never spec content | One source of truth for *what* is being built; the drift that kills most projects is designed out |
| **Ten roles, five gates** — scrum → intake → planner → architect → dispatch → implementer → reviewer → qa → release → ops, with humans at G0 (release scope), G1 (spec), G2 (design), GS (staging) and G3 (production) | The PM's job is redesigned around decisions, not coordination. Which gates can never be delegated (GS, G3) and which can (G0) is an explicit governance choice |
| **Release gating** — a milestone *is* the release; a Scrum Master agent posts scope, sequencing, risks and a GO/NO-GO before anything starts | AI-assisted release planning, done on the whole set of requirements rather than one at a time |
| **Guardrails are controls, not instructions** — a hook blocks agent pushes to `main`, a deny list removes merge tools, a detector opens an incident if anything slips through | Governance for AI systems is enforced in the toolchain, not written in a policy document |
| **Model routing** — spend model quality where errors compound (spec, design, review), economise where volume lives (implementation, QA) | Cost and quality management for AI-driven work |
| **Every run ends by saying what is expected of the next actor**; `factory:blocked` is how an agent asks a human | Stakeholder communication and escalation designed into the workflow |
| **The Factory Console** — an attention queue ("what needs me, and why"), decision log, and "Ask the Factory" cited Q&A over an epic's own artifacts | What an AI-era PMO dashboard looks like: a lens over the system of record, never a second source of truth |

---

## 2. Target audience and prerequisites

- Career Grade 4–6 Project / Delivery Managers, 12–18 years total experience,
  5–6 years in project or delivery management.
- Comfortable with an agile or hybrid delivery lifecycle, a work-tracking tool
  (Jira / Azure DevOps / GitHub Projects) and spreadsheets.
- No coding required. Labs use browser-based tools, Excel and guided scripts;
  the code-facing labs on Days 4–5 are done through GitHub's web UI and the
  Factory Console.

## 3. Learning objectives

By the end of the program participants will be able to:

1. Apply Generative AI to charters, WBS, estimates, risk registers, status
   reports and stakeholder communications with reliable prompting patterns and
   an explicit review step.
2. Build a probabilistic delivery forecast (Monte Carlo on throughput and cycle
   time) and use AI to surface, classify and mitigate risk from live delivery
   data.
3. Automate recurring reporting and communication from the system of record
   (issues, PRs, CI, calendars) into Teams / Slack / email with an LLM in the
   loop.
4. Select and integrate modern PM, collaboration and monitoring tools, and read
   flow and DORA metrics from them.
5. Explain and operate an agent-driven delivery pipeline: roles, states, gates,
   guardrails, model routing and release gating — and decide which gates a
   human must hold.
6. Plan and govern a Gen AI project: non-determinism, evaluation, cost and
   token budgets, data privacy, hallucination risk, responsible-AI controls.
7. Produce an AI-enabled delivery plan for a real release and defend it.

## 4. Program structure — five half-days

| Day | Theme | Client ToC modules covered | Hours |
|---|---|---|---|
| 1 | Generative AI for the project manager: foundations, forecasting and risk | Introduction to Generative AI in PM · AI-Driven Project Forecasting and Risk Management · Hands-On Exercise | 4 |
| 2 | AI for project automation and reporting | Using AI for Project Automation and Reporting · Hands-On Exercise | 4 |
| 3 | Technology and tools for modern project management | Overview of Modern PM Tools · Integrating Collaboration and Communication Tools · Advanced Techniques for Project Monitoring · Hands-On Exercise: Tool Integration | 4 |
| 4 | Managing AI-driven delivery: the Software Factory operating model | The Future of Project Management · Best Practices for Project Delivery in Tech Projects · Practical Guide to Managing Gen AI Projects | 4 |
| 5 | Capstone, governance and certification | Capstone Project & Case Study Discussion · Course Conclusion and Certification | 4 |

Each day: 3 × ~50-minute teaching-and-demo blocks, 1 × 60–75-minute lab, two
10-minute breaks, and a 10-minute close with a "what I will use on Monday"
round.

---

## 5. Detailed outline

### Day 1 — Generative AI for the project manager (4 h)

**1.1 Introduction to Generative AI in project management (60 min)**
- How LLMs work at the level a PM needs: tokens, context, temperature,
  hallucination, why the same prompt gives different answers.
- The three levels of AI in delivery: **assistant** (drafts for you),
  **copilot** (works in your tools), **agent** (does the work, you approve).
- Where AI fits in the PM lifecycle — initiation, planning, execution,
  monitoring, closure — and where it does not.
- Prompting patterns for PMs: role + context + artifact + constraints + format;
  few-shot with your own past documents; "critique then rewrite"; asking for
  the questions before the answer.
- Demo: charter, WBS, RACI and an estimate range from a one-page brief, with
  the model asked to list its assumptions first.
- *Factory tie-in:* the Intake Analyst role — an agent that turns a raw request
  into WHEN/THEN acceptance scenarios and **stops and asks** (applies
  `factory:blocked`) rather than inventing requirements. Why "ask before you
  assume" is the most valuable prompt rule in delivery.

**1.2 AI-driven project forecasting and risk management (75 min)**
- Predictive analytics on delivery data: throughput, cycle time, WIP, ageing;
  why story points forecast worse than counts.
- Monte Carlo simulation for "when will it be done" and "how much by that
  date", in Excel and in a guided Python notebook.
- Using an LLM on top of the numbers: explaining a forecast to a sponsor,
  generating scenarios, stress-testing assumptions.
- AI-assisted risk management: mining risk from tickets, retros, incident logs
  and meeting transcripts; classifying by exposure; pre-mortems; automated
  risk-register upkeep.
- Early-warning signals from the system of record: blocked ageing, review
  queue depth, re-open rate, scope churn.
- *Factory tie-in:* the Scrum Master role reads a whole milestone and posts
  scope, sequencing, risks and a GO / NO-GO verdict before a single agent
  starts — AI release planning on the set, not the item. Which of those risk
  categories (duplicate, oversized, under-specified, mis-sequenced) map onto
  your own portfolio.

**1.3 Hands-on exercise (75 min)**
- Lab 1A — From brief to plan: participants take a supplied product brief,
  produce charter, WBS, RACI and risk register with an LLM, then run a
  structured review pass. Deliverable: a marked-up plan with the AI's
  assumptions and the PM's corrections side by side.
- Lab 1B — Forecast: with a supplied throughput dataset (and optionally their
  own exported Jira / ADO data) build a Monte Carlo forecast, produce the P50 /
  P85 dates, and have the LLM draft the sponsor explanation.
- Close: what changed in the plan once you asked the model for its questions
  first.

### Day 2 — AI for project automation and reporting (4 h)

**2.1 Using AI for project automation (60 min)**
- The automation stack a PM can own: triggers (webhooks, schedules), workflow
  tools (Power Automate, n8n, Zapier, GitHub Actions), an LLM step, a
  destination (Teams, Slack, email, Confluence, SharePoint).
- Candidate processes: intake triage, RAID log upkeep, action-item extraction
  from meetings, dependency reminders, change-request summaries, escalation
  routing.
- Human-in-the-loop design: what the automation may do alone, what it must
  draft for approval, what it must never touch. Idempotency and audit.
- *Factory tie-in:* the label state machine — exactly one `factory:*` state per
  issue, labels trigger agents, agent comments carry a marker so they never
  self-trigger. Every run ends by saying what is expected of the next actor.
  What that teaches about designing any workflow automation.

**2.2 AI-driven reporting and stakeholder communication (60 min)**
- Reporting from the system of record instead of from people: issues, PRs, CI,
  deployments, calendars as inputs; the LLM as narrator, not as source.
- Report anatomy by audience: sponsor, steering committee, team, client.
  Tone, length, what to leave out. Generating three versions from one dataset.
- Meeting intelligence: transcripts to decisions, actions and risks; keeping the
  decision log current automatically.
- Guarding against confident nonsense: citations back to the source object,
  "as-of" timestamps, and a review step that is cheaper than the mistake.
- *Factory tie-in:* the Factory Console — a **lens** over GitHub, never a second
  source of truth. The attention queue ("what needs me, and why"), the
  as-proposed ⇄ as-approved artifact diff, the decision log posted as ordinary
  GitHub comments with hidden markers, and "Ask the Factory": cited Q&A that
  answers only from an epic's own artifacts.

**2.3 Hands-on exercise (90 min)**
- Lab 2A — Automated weekly status: from a sandbox repo (or the participant's
  own tracker export), build a pipeline that pulls open issues, PRs, blocked
  items and deployments, has an LLM write a sponsor-grade status and a
  team-grade status, and posts both to a Teams / Slack channel. No code beyond
  a guided template.
- Lab 2B — Meeting to decisions: transcript in, decision log + action list +
  new risks out, each line citing its timestamp.
- Close: which of your current reports could disappear next month.

### Day 3 — Technology and tools for modern project management (4 h)

**3.1 Overview of modern project management tools (50 min)**
- The landscape and where the AI is: Jira (Atlassian Intelligence, Rovo),
  Azure DevOps + Copilot, GitHub Projects + Copilot, Asana AI, Linear, Monday,
  ClickUp Brain, Notion AI, Microsoft Planner / Project + Copilot.
- Choosing by the delivery model, not the feature list: where the system of
  record should live, what must be integrated versus what merely coexists.
- Spec-driven tooling: OpenSpec, ADRs, design docs as reviewable artifacts.
- *Factory tie-in:* why the factory uses plain GitHub objects (milestones,
  issues, sub-issues, labels, PRs) as its whole state and OpenSpec change
  folders as its content — vendor-neutral, auditable, and every stage
  resumable. How the same shape ports to Copilot or another agent runner.

**3.2 Integrating collaboration and communication tools (50 min)**
- Integration primitives a PM should understand: webhooks, APIs, connectors,
  bots, and the Model Context Protocol (MCP) that lets an AI assistant talk to
  your tools.
- Teams / Slack as the notification surface; email as the record; the chat
  assistant as the query interface. Avoiding notification debt.
- Identity and permissions: every automated action should run as *someone*,
  and approvals should be recorded in the tool that owns the decision.
- *Factory tie-in:* the control path — a GitHub event → a ~20-line caller
  stub → a router that reads the event and the current label → a role runs →
  a label moves and a comment is posted. Approvers are named in a config
  file; the pipeline assigns and @-mentions them, so GitHub's own
  notification machinery does the work.

**3.3 Advanced techniques for project monitoring (50 min)**
- Flow metrics (throughput, cycle time, WIP, flow efficiency) and DORA
  (deployment frequency, lead time, change-failure rate, MTTR) — reading them
  together.
- Dashboards that answer questions: Power BI / Looker / Grafana over the
  tracker and the CI system; anomaly and trend detection with AI.
- Real-time versus periodic monitoring; alert fatigue; what an "attention
  queue" looks like versus a dashboard.
- *Factory tie-in:* the `factory:in-progress` marker and per-state timing as
  live cycle-time data; the Ops role's health, smoke and soak checks; the
  `factory:incident` state as the post-deploy feedback loop; the Factory Ops
  view (queue depth, workers, workspaces).

**3.4 Hands-on exercise: tool integration (90 min)**
- Lab 3 — Wire it up: in the sandbox GitHub organisation, connect a repository
  to Teams / Slack, add an LLM summarisation step on issue and PR events, and
  build a small flow-metrics dashboard from the label history (cycle time by
  stage, WIP by state, blocked ageing). Optional stretch: expose the tracker
  to an AI assistant through MCP and ask it delivery questions.
- Close: the one integration you would add to your current project first.

### Day 4 — Managing AI-driven delivery: the Software Factory operating model (4 h)

**4.1 The future of project management (45 min)**
- From managing people to managing people *and* agents: what gets automated
  (coordination, status, first-draft artifacts, code) and what does not
  (scope, trade-offs, gates, relationships, accountability).
- The PM as gatekeeper and governor: decision latency becomes the constraint;
  the pipeline waits on a human, not the other way round.
- Skills that appreciate: writing unambiguous requirements, reading a design,
  judging a test report, saying no at a gate.
- The organisation around it: approver lists, coordination repos, estates of
  many repositories under one set of conventions.

**4.2 Best practices for project delivery in tech projects (60 min)**
- Spec-driven delivery: a change is a proposal + acceptance scenarios + design
  + task list, each reviewed before the next is written.
- Small batches: tasks of at most half a day, one PR each, ordered so every
  intermediate merge is releasable (schema → service → consumer).
- Staging first, always: nothing reaches `main` that was not assembled and
  proven on an integration branch; dependency-ordered merges; promotion PRs
  that carry the staging evidence.
- Independent review: a reviewer that never shares the implementer's context
  (and, in the factory, is a different model so blind spots differ).
- Guardrails as controls, not instructions: a hook that blocks the push, a
  deny list that removes the merge tool, a detector that files an incident.
- Release gating and the Expedite / Fast-Track trade-offs: all the ceremony
  and none of the pauses, versus none of the ceremony for changes too small
  to deserve it.
- *Factory walkthrough:* the ten roles, the state labels, and the five gates —
  G0 release, G1 spec, G2 design, GS staging, G3 production — and why only GS
  and G3 are structural (the moments something leaves the factory's own
  branches).

**4.3 Practical guide to managing Gen AI projects (60 min)**
- What is different: non-deterministic outputs, evaluation instead of
  pass/fail testing, prompt and model drift, cost measured in tokens, data
  privacy in prompts and outputs, vendor and model dependency.
- The Gen AI project lifecycle: use-case triage → data and access → prototype
  → evaluation set → guardrails → pilot → production monitoring → model
  routing and cost management.
- Estimating and forecasting Gen AI work: where the uncertainty actually lives
  (evaluation loops, integration, change management), and how to plan for it.
- Responsible AI for delivery managers: transparency, human oversight,
  auditability, the EU AI Act and Indian DPDP Act in one page each, what the
  client's own AI policy will require.
- *Factory tie-in:* model routing — spend model quality where errors compound
  (spec, design, review), economise where volume lives (implementation, QA),
  probe and degrade gracefully when a tier is unavailable. What a run costs
  and how to budget an estate.

**4.4 Hands-on exercise: run an epic through the factory (75 min)**
- Lab 4 — In a prepared sandbox estate, teams file a requirement against a
  milestone, comment `Plan release` and read the Scrum Master's plan, open
  gate G0, review the Intake Analyst's proposal and WHEN/THEN scenarios at G1
  (and deliberately send one back with questions), approve the plan and design
  at G2, watch implementation → review → test run unattended, open GS, and see
  what G3 asks of a human. Participants take turns as release-scope approver,
  spec approver, design approver and tester.
- Close: which of your current sign-offs are gates, and which are merely
  waiting.

### Day 5 — Capstone, governance and certification (4 h)

**5.1 Case study discussion (45 min)**
- The original four-repository deployment (FastAPI backend, React frontend,
  Python sales service, NestJS messaging server): what the pipeline does, what
  each role produces, what it cost, what broke and what the gates caught.
- A second case: the same pipeline shape ported to another agent runner —
  what was vendor-neutral (state, content, gates, approvers) and what was not
  (agent definition and launch).
- Discussion: which parts of this apply to a services engagement with a client
  PMO, a fixed-price project, a regulated environment.

**5.2 Capstone project (120 min, teams of 3–4)**
- Brief: a release of 6–8 requirements for a case-study product (an insurance
  policy-servicing application is supplied; teams may substitute a sanitised
  release of their own).
- Deliverables, all produced with AI and reviewed by the team:
  1. Release plan — scope table, sequencing, risks, what to drop, GO / NO-GO
     (Scrum Master format).
  2. Probabilistic forecast — P50 / P85 completion with assumptions.
  3. Risk register with AI-mined risks, exposure, owners, early-warning
     signals.
  4. Automation and reporting plan — which reports and rituals are automated,
     from which sources, with what human review.
  5. Governance design — which gates exist, who holds them, which are
     delegated to an agent, what guardrails are controls.
  6. Sponsor-grade one-page status and a steering-committee narrative,
     generated from the plan.
- Presentations (10 minutes per team) with structured peer and trainer
  critique against the program's outcome measures.

**5.3 Course conclusion and certification (45 min)**
- Program recap against the six business outcomes.
- Personal 30-60-90 day adoption plan: one report to automate, one forecast to
  run, one gate to redesign, one Gen AI project to govern.
- Assessment: capstone score (60%) + short scenario-based quiz (40%);
  certificate of completion issued on passing.
- Resources: the Software Factory handbook and case studies (open source,
  MIT), prompt library, forecast templates, automation templates, reading list.

---

## 6. Mapping to the client's expected business outcomes

| Expected business outcome | Where it is built | Evidence at the end of the program |
|---|---|---|
| Improved project delivery predictability | Day 1 (forecasting), Day 4 (small batches, staging first, release gating) | A P50 / P85 forecast on real or supplied data; a release plan with sequencing |
| Faster and more accurate project reporting | Day 2 (reporting from the system of record), Day 3 (monitoring) | A working automated status report posted to Teams / Slack |
| Reduced project risk exposure through AI-driven forecasting | Day 1 (risk mining, early-warning signals), Day 4 (independent review, gates) | AI-mined risk register with exposure and signals |
| Increased productivity through workflow automation | Day 2 (automation), Day 3 (integration), Day 4 (agents doing the work) | Automated workflow built in the lab; an epic run end-to-end by agents |
| Better resource utilisation and governance | Day 3 (flow metrics), Day 4 (gates, approvers, guardrails, model routing) | Governance design in the capstone |
| Enhanced readiness to manage AI-driven business initiatives | Day 4 (managing Gen AI projects), Day 5 (capstone) | Capstone delivery plan and 30-60-90 plan |

## 7. Optional additional topics (beyond the initial curriculum)

The client indicated openness to further topics. Any of these can be added as
a 60–90 minute block or a sixth half-day:

- Agile estimation and planning with AI (story splitting, backlog grooming,
  sprint planning assistants).
- Vendor and contract management for AI-delivered work: acceptance criteria
  when an agent wrote the code, IP and licensing of generated artifacts.
- Change management and adoption: bringing a team onto an agent-driven
  pipeline; role redesign for BAs, testers and tech leads.
- Portfolio and PMO-level AI: cross-project forecasting, capacity planning,
  and multi-repository estates with one set of conventions.
- Agentic AI deep-dive: multi-agent orchestration patterns (event-driven
  routers versus graph engines), MCP, evaluating agent runs.
- Building the client's own factory: a half-day workshop that factory-enables
  one of the client's sandbox repositories and runs a first epic.

## 8. Delivery format and logistics

| Item | Detail |
|---|---|
| Mode | Online, instructor-led, recorded (recording provided to the client) |
| Duration | 20 hours: 5 half-days × 4 hours (4.5 with extended labs) |
| Batch size | Recommended 12–20 participants; capstone in teams of 3–4 |
| Materials | Slide deck, lab guides, prompt library, forecast and automation templates, sandbox GitHub organisation, the Software Factory handbook and case studies |
| Assessment | Capstone (60%) + scenario quiz (40%); certificate of completion |
| Language | English |

## 9. Lab setup

**Per participant (hardware)**
- Laptop with 8 GB RAM or more, modern browser (Chrome / Edge), stable internet,
  microphone and camera. No GPU required; nothing runs locally that needs one.

**Per participant (software and accounts)**
- A GitHub account (free) — added to the training sandbox organisation.
- Access to a Generative AI assistant: Claude (claude.ai or Claude Code),
  ChatGPT, or Microsoft Copilot. The client's own enterprise assistant is
  preferred if available, so that labs respect the client's data policy.
- Microsoft Excel (or Google Sheets) for the forecasting labs.
- Microsoft Teams or Slack — a sandbox channel the trainer can post into.
- Optional for the stretch labs: VS Code, Node.js 20+, Python 3.11+.

**Provided by the trainer**
- The sandbox GitHub organisation with the Software Factory installed on a
  case-study repository, approver lists configured for the batch, and the
  Factory Console deployed for participants.
- LLM API credits for the factory runs on Days 4–5 (agent runs are billed to
  the trainer's key; the client pays nothing beyond the per-pax lab fee).
- Datasets, prompt library, lab guides and templates.

**Lab cost per participant** covers the sandbox environment, the factory's
agent-run credits for the labs and capstone, and the participant's AI-assistant
usage where the client does not supply its own. Exact figure per the
commercial proposal.

## 10. Regenerating the deck

The slide deck in this folder is generated from `build-deck.js` with
`pptxgenjs` (icons via `react-icons` + `sharp`):

```bash
npm install pptxgenjs react-icons react react-dom sharp   # once, anywhere on NODE_PATH
node build-deck.js
```

Files:

| File | What it is |
|---|---|
| `README.md` | This outline |
| `AI-Enabled-Project-Delivery-Management.pptx` | The program deck (37 slides) |
| `AI-Enabled-Project-Delivery-Management.pdf` | PDF export of the deck |
| `build-deck.js` | Deck generator |
| `response-to-gynosis.md` | Draft reply to the vendor's questionnaire |
