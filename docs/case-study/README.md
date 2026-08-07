# Case study: the original deployment

These three documents describe the factory as first built and run across a
four-repository estate (a FastAPI backend, a React frontend, a Python sales
service and a NestJS messaging server). They are kept verbatim because the
concrete detail is the point — a worked example beats an abstract one.

Read them for *why* the design is shaped this way. Read `FACTORY.md` at the
repo root for what the factory actually does today; where the two disagree,
FACTORY.md wins.

| Document | Covers |
|---|---|
| `01-factory-overview.md` | Architecture, workflow, configuration files, guardrails |
| `02-factory-skills.md` | The nine role prompts and the OpenSpec skills, and what each does |
| `03-factory-on-copilot.md` | Porting the same pipeline shape onto GitHub Copilot |

One thing has changed since these were written: the factory no longer lives
copied into each repo. It is a plugin plus reusable workflows (FACTORY.md §10).
