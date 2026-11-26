# Starter issues to file

Eight drafts for the `good first issue` label. Each one is a real gap found by
reading the docs and the code on `main`, and each can be done without
understanding the router. Copy the title and body into a new issue. The
acceptance check is how a reviewer knows the issue is done.

Note for whoever files them: use only the `good first issue` and
`documentation` labels, and no `factory:*` label. A `factory:*` label is how
work is handed to an agent, and these are meant for people.

---

## 1. Setup guide and handbook disagree on how many files a repo holds

**Body**

The docs give four different counts for the files a consuming repo holds:

- `docs/setup-guide.md` step 4 says "Eight files land in the consuming repo".
- Step 6 of the same guide says "the four `.github/*` and
  `.claude/settings.json` files".
- Its "Footprint summary" lists seven files and says "Seven files". It leaves
  out `factory-branches.json` and `factory-testing.json`, which step 4 copies.
- `FACTORY.md` (intro) says "A consuming repo holds ten files", while the
  table in §10 lists twelve, some of them optional.

Pick one way to count (for example "N required, M optional"), and make all
four places agree with the table in FACTORY.md §10.

**Acceptance check**

- The setup guide's step 4, step 6 and footprint summary, and the FACTORY.md
  intro, all give the same numbers.
- Every file in the FACTORY.md §10 table appears in the footprint summary,
  marked required or optional.
- No behaviour, template or workflow file changes.

---

## 2. The docs give three different label counts

**Body**

`scripts/setup-labels.sh` defines 33 `factory:*` labels. The docs say:

- `docs/setup-guide.md` step 1: "the 28 labels listed in FACTORY.md §3".
- `FACTORY.md` §9 step 2: "creates the 32 `factory:*` labels".

Count the labels in the script, check the count against the table in
FACTORY.md §3, and fix the prose. If the §3 table and the script disagree
about which labels exist, say so on the issue instead of guessing.

**Acceptance check**

- Both sentences give the number of labels the script really creates.
- Every label in the script has a row in the FACTORY.md §3 table, and the
  other way round. Any mismatch is listed on the issue.
- `scripts/setup-labels.sh` is not changed.

---

## 3. Finish the Console → Compass rename in the docs

**Body**

The web app was renamed from "Console" to "Compass", but the prose still says
"the Console" in several places:

- `docs/run-locally.md` (the title and about 25 lines)
- `docs/setup-guide.md` ("the Console's worker")
- `FACTORY.md` (three places)
- `CONTRIBUTING.md` ("consuming repos and the Console")
- `orchestrator/README.md`
- `.github/ISSUE_TEMPLATE/config.yml` ("Issues with the Console")

Change the prose to "Compass". Do **not** rename anything a program reads:
environment variables such as `CONSOLE_MASTER_KEY` and `CONSOLE_DATABASE_URL`,
the `<!-- console:thread=… -->` marker, package names such as `@console/web`,
or file paths. `docs/case-study/` is kept as written and is out of scope.

**Acceptance check**

- `grep -rn "Console" --include=*.md .` outside `docs/case-study/`,
  `docs/plan/`, `openspec/` and `wiki/` shows only identifiers a program
  reads.
- No environment variable, marker, package name or path has changed.
- `cd orchestrator && make test` still passes.

---

## 4. Plugin and marketplace descriptions are out of date

**Body**

`.claude-plugin/plugin.json` says "ten agent roles move work between them
behind four approval gates". `.claude-plugin/marketplace.json` says "Ten agent
roles, four approval gates". The repo ships thirteen role prompts in
`commands/`, and FACTORY.md §4 describes five gates: G0, G1, G2, GS and G3.

Update the two `description` fields so they match the README and the
handbook. Leave `version` alone. Maintainers bump it when a release is cut.

**Acceptance check**

- Both descriptions say thirteen roles and do not give a gate count that
  disagrees with FACTORY.md §4.
- `claude plugin validate .` passes.
- Only the two `description` strings changed.

---

## 5. Install steps never copy the requirement issue template

**Body**

FACTORY.md §10 lists `.github/ISSUE_TEMPLATE/factory-requirement.yml` as part
of a consuming repo's footprint and calls it "the intake entry point". §9
step 1 says to copy it from `templates/ISSUE_TEMPLATE/`.

Neither install path does:

- The README's "Install → Steps" block copies the workflow stubs and the
  config files, but not the issue template.
- The table and the `cp` block in `docs/setup-guide.md` step 4 copy
  `factory-bug.yml` but not `factory-requirement.yml`.

Add the copy step to both, with the note from FACTORY.md §9 about editing the
"Affected repositories" checkboxes. While there, add the optional
`.github/factory-orchestrator.json` row to the setup guide's table, since
§10 lists it too.

**Acceptance check**

- Someone who follows only the README steps, or only the setup guide, ends up
  with `.github/ISSUE_TEMPLATE/factory-requirement.yml` in their repo.
- The setup guide's step 4 table has a row for every file in FACTORY.md §10.
- No template file changes.

---

## 6. Add a link check for the Markdown docs

**Body**

Nothing checks the links in the docs. Two README badges pointed at workflow
files that no longer exist (`codeql.yml` here, `ci.yml` in Compass), and
nobody noticed until a manual read.

Add a small workflow that checks links in `*.md` on pull requests that touch
Markdown. Relative links and `#anchor` links must resolve. External links
should warn, not fail, so a third-party outage does not block a PR. Use a
maintained action or script. Keep the workflow's `permissions:` to
`contents: read`.

Read `.github/REPOSITORY_SETTINGS.md` first: the check must not be made a
required status check, because it only runs when Markdown changes.

**Acceptance check**

- A PR that adds a broken relative link to any `.md` file fails the check.
- A PR that touches no Markdown does not run it.
- The check passes on `main` as it stands, or the PR fixes what it finds.
- The workflow declares `permissions: contents: read` and nothing more.

---

## 7. Say how to run the protected-branch hook's tests

**Body**

The README says "The hook is tested; see FACTORY.md §8a". §8a describes what
the hook blocks, but not the tests. CONTRIBUTING.md says to test `hooks/` by
"feed it `git push` payloads by hand".

The tests exist: `orchestrator/tests/test_branch_guard.py` exercises
`hooks/protect-branches.py`. Point the docs at them:

- In CONTRIBUTING.md's layout table, give the command that runs the hook
  tests.
- In FACTORY.md §8a, add one sentence naming the test file.
- Add a three-line example of feeding the hook one payload by hand, for
  people who want to see it refuse a push.

**Acceptance check**

- A new contributor can run the hook's tests from the CONTRIBUTING.md table
  with one command, and the command works on a fresh checkout after
  `make install`.
- The by-hand example prints a refusal for a push to `main`.
- `hooks/protect-branches.py` is not changed.

---

## 8. CONTRIBUTING.md leaves out the comment lint and `tools/`

**Body**

Two parts of the repo are missing from CONTRIBUTING.md:

- `scripts/comment-lint.js` and its test `scripts/test-comment-lint.js`. The
  *Routing conformance* workflow runs `node scripts/test-comment-lint.js`,
  but the "Development setup" block and the PR template do not mention it, so
  a contributor can break it without knowing it exists.
- `tools/log-reader/`, the read-only log tool for Compass. It is not in the
  "Repository layout" table.

Add both to the layout table with how to test each, and add the comment-lint
test to the "Development setup" commands.

**Acceptance check**

- The layout table has a row for `scripts/comment-lint.js` and one for
  `tools/log-reader/`, each with a test command or "no tests yet".
- Running every command in "Development setup" on a fresh checkout runs
  every check the *Routing conformance* workflow runs.
- Only CONTRIBUTING.md changes. The PR template is a maintainer's call.
