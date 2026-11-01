// Comment lint tests: node scripts/test-comment-lint.js (no dependencies).
// Exits non-zero on the first failure.
'use strict';
const assert = require('assert');
const { lint, summarize, guessKind } = require('./comment-lint');

const GOOD = `**Test plan ready: 14 test cases.**
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
    const body = '**You need to:** nothing. ' + 'word '.repeat(170);
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
  'the frame lines and the headline are not content sentences'() {
    const r = lint(GOOD, 'summary');
    // GOOD has two bullets, a Next line, a Links line, a headline and a You need to line.
    assert.strictEqual(r.sentences, 2, `counted ${r.sentences}`);
  },
  'too many sentences, a high grade and long sentences are each reported'() {
    const many = '**You need to:** nothing.\n' + Array.from({ length: 10 }, (_, i) => `- The lead gets message number ${i} today.`).join('\n');
    assert.ok(lint(many, 'summary').problems.some(p => p.includes('sentences in the visible part')));
    const dense = '**You need to:** nothing.\nThe reconciliation infrastructure deduplicates asynchronous notification propagation. Idempotency guarantees eliminate duplicate conversational initialization.';
    const d = lint(dense, 'summary');
    assert.ok(d.grade > 8, `grade ${d.grade}`);
    assert.ok(d.problems.some(p => p.includes('reads at grade')));
    const plain = '**You need to:** nothing.\nThe lead moves the call. The calendar sends the new time. The CRM sends it again. The code sees one move.';
    const p = lint(plain, 'summary');
    assert.ok(p.grade !== null && p.grade <= 8, `grade ${p.grade}`);
    assert.ok(!p.problems.some(x => x.includes('reads at grade')));
    const long = '**You need to:** nothing.\n' + Array.from({ length: 3 }, () => 'the lead and the calendar and the crm and the code all take part in this one long sentence that goes on and on.').join('\n');
    assert.ok(lint(long, 'summary').problems.some(x => x.includes('sentences average')));
  },
  'a block without its questions is reported; with them it passes'() {
    const head = '**Round 2 blocked: the loader deletes nothing.**\n**You need to:** decide below.\n';
    assert.ok(lint(head, 'blocked').problems.some(p => p.includes('Questions for you')));
    const withQ = head + '**Questions for you:**\n1. Allow one more round on this task?\n';
    assert.ok(!lint(withQ, 'blocked').problems.some(p => p.includes('Questions for you')));
    assert.ok(!lint('**You need to:** nothing.', 'summary').problems.some(p => p.includes('Questions for you')));
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
  'numbers where a name belongs are reported; the Links line is exempt'() {
    const r = lint('**You need to:** nothing.\n- The aggregation task (#62) waits on beacon-api#61.\n```mermaid\nT1[x]\n```\nLinks: #62 · #61', 'summary');
    assert.deepStrictEqual(r.number_refs, ['#62', 'beacon-api#61']);
    assert.ok(r.problems.some(p => p.includes('numbers where a name belongs')));
    assert.deepStrictEqual(lint('**You need to:** nothing.\n- ST-4 waits on the aggregation task.\nLinks: #62', 'summary').number_refs, []);
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
  'a comment asking for nothing is a summary even if it says approve'() {
    assert.strictEqual(guessKind('**Test plan ready.**\n**You need to:** nothing now. You approve the plan with the design.'), 'summary');
    assert.strictEqual(guessKind('**Spec ready.**\n**You need to:** approve the spec.'), 'ready');
  },
  'the Factory details fold has its own cap'() {
    const fold = n => `**You need to:** nothing.\n\n<details><summary>Factory details</summary>\n${'word '.repeat(n)}\n</details>`;
    assert.deepStrictEqual(lint(fold(100), 'summary').problems, []);
    const r = lint(fold(101), 'summary');
    assert.strictEqual(r.details_words, 101);
    assert.ok(r.problems.some(p => /Factory details is 101 words/.test(p)), r.problems.join('; '));
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
