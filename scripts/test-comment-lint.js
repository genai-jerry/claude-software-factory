// Comment lint tests: node scripts/test-comment-lint.js (no dependencies).
// Exits non-zero on the first failure.
'use strict';
const assert = require('assert');
const { lint, summarize, guessKind } = require('./comment-lint');

const GOOD = `**Test plan ready for #34: 14 test cases.**
**You need to:** nothing now. You approve the plan with the design at design approval (G2).
- ST-1 to ST-9: status words from a real Google Sheet reach Beacon.
- ST-14 is the riskiest: Beacon's own write must not come back.
Next: the Architect writes the design on the same branch.
Links: [test plan](https://github.com/o/r/blob/x/test-plan.md) · #44–#57

<details><summary>Factory details</summary>
Pushed to factory/34-design; the epic stays at factory:planned; schema is spec-driven, so the
files were written directly. This text is long and full of internal terms on purpose.
</details>

<!-- factory-agent -->`;

const cases = {
  'a comment in the §1a shape passes, whatever its Factory details hold'() {
    const r = lint(GOOD, 'summary');
    assert.deepStrictEqual(r.problems, []);
    assert.ok(r.words < 80, `counted ${r.words} words`);
  },
  'over budget is reported against the kind'() {
    const body = '**You need to:** nothing. ' + 'word '.repeat(130);
    assert.ok(lint(body, 'ready').over_budget);
    assert.ok(!lint(body, 'summary').over_budget);
  },
  'a hard-wrapped long sentence is one sentence'() {
    const body = '**You need to:** nothing.\n\nThis sentence is wrapped across\nseveral lines the way agents\nwrite markdown and it keeps\ngoing well past the twenty five\nword limit for descriptions in this handbook today.';
    assert.strictEqual(lint(body, 'summary').long_sentences.length, 1);
  },
  'list items are separate sentences'() {
    const items = Array.from({ length: 6 }, (_, i) => `- item ${i} has a few short words`).join('\n');
    assert.strictEqual(lint(`**You need to:** nothing.\n${items}`, 'summary').long_sentences.length, 0);
  },
  'a missing action line is reported where the kind needs one'() {
    assert.ok(lint('Tests pass.', 'ready').problems.some(p => p.includes('You need to')));
    assert.ok(!lint('▶ The intake is running.', 'started').problems.some(p => p.includes('You need to')));
  },
  'internal terms in the prose are reported; a gate code needs its plain name'() {
    const r = lint('**You need to:** approve at G2. The epic moves to factory:design-ready with epics: true.', 'ready');
    assert.ok(r.internal_terms.includes('factory:design-ready'));
    assert.ok(r.internal_terms.includes('epics: true'));
    assert.ok(r.internal_terms.some(t => t.startsWith('G2 without')));
    assert.ok(!lint('**You need to:** approve at design approval (G2).', 'ready')
      .internal_terms.some(t => t.startsWith('G2')));
  },
  'code blocks and link targets do not count'() {
    const r = lint('**You need to:** run it.\n```\n' + 'x '.repeat(200) + '\n```\n[a](https://example.com/' + 'y'.repeat(300) + ')', 'ready');
    assert.ok(r.words < 10, `counted ${r.words}`);
  },
  'kind is guessed from the text'() {
    assert.strictEqual(guessKind('▶ The **planner** is running — [watch](https://x).'), 'started');
    assert.strictEqual(guessKind('**Blocked: no test command in the profile.**'), 'blocked');
    assert.strictEqual(guessKind('@a — **Gate G1 (spec approval)** is waiting on you.'), 'ready');
  },
  'summary gives percentiles'() {
    const s = summarize([10, 20, 30, 40, 1000].map(n => lint('w '.repeat(n), 'summary')));
    assert.strictEqual(s.comments, 5);
    assert.strictEqual(s.words_max, 1000);
    assert.strictEqual(s.words_p50, 30);
  },
};

let failed = 0;
for (const [name, fn] of Object.entries(cases)) {
  try { fn(); console.log(`ok   ${name}`); }
  catch (e) { failed++; console.log(`FAIL ${name}\n     ${e.message}`); }
}
process.exit(failed ? 1 : 0);
