// Comment lint: does an agent comment follow FACTORY.md §1a (Writing for people)?
//
// Report-only. It scores a comment and never changes or blocks one. Both engines
// can run it — it is plain Node with no dependencies — and the scores are the
// measure of whether the writing rules work.
//
//   node scripts/comment-lint.js < comment.md            one comment, JSON out
//   node scripts/comment-lint.js --json < comments.json  [{body, kind?}, ...] → per-comment + summary
//
// What it checks, on the visible part only (`<details>`, code blocks, HTML
// comments and link targets are removed first):
//   - words against the budget for the comment's kind (§1a table)
//   - sentences longer than 25 words
//   - a "You need to:" line, where the kind calls for one
//   - factory-internal terms in the prose (they belong in Factory details)
'use strict';

const BUDGETS = { started: 25, ready: 120, blocked: 80, summary: 150 };
const NEEDS_ACTION = new Set(['ready', 'blocked', 'summary']);
const SENTENCE_LIMIT = 25;
// The fold is for audit, not for the analysis. Without a cap it became the
// place the explanation went (550 words under an 80-word notice).
const DETAILS_LIMIT = 100;

// Mechanics a reader should not need. Gate codes alone are allowed only beside
// their plain name, which the rule below checks separately.
const INTERNAL_TERMS = [
  /\bfactory:[a-z-]+/g,
  /\bmode:\s*gate\b/g,
  /\bepics:\s*(?:true|false)\b/g,
  /\bschema\b/gi,
  /\bchange folder\b/gi,
  /\bthe profile\b/gi,
  /\bre-?dispatch\w*/gi,
  /\bchain(?:ed)? run\b/gi,
];
const GATES = {
  G0: 'release approval', G1: 'spec approval', G2: 'design approval',
  GS: 'release to staging', G3: 'production release',
};

function visibleText(body) {
  return String(body || '')
    .replace(/<details>[\s\S]*?<\/details>/gi, ' ')
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/<!--[\s\S]*?-->/g, ' ')
    .replace(/<sub>[\s\S]*?<\/sub>/gi, ' ')
    .replace(/!?\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/https?:\/\/\S+/g, 'link');
}

function detailsWords(body) {
  let n = 0;
  for (const m of String(body || '').matchAll(/<details>([\s\S]*?)<\/details>/gi)) {
    n += words(m[1].replace(/<summary>[\s\S]*?<\/summary>/i, ' ').replace(/```[\s\S]*?```/g, m2 => m2)).length;
  }
  return n;
}

function words(text) {
  return text.split(/\s+/).filter(w => /[\p{L}\p{N}]/u.test(w));
}

function sentences(text) {
  // Join hard-wrapped lines back into their paragraph or list item first; then
  // a new item, a heading or a blank line ends a sentence as surely as a full stop.
  const unwrapped = text.replace(/\n(?![ \t]*(?:[-*]|\d+\.|#|\||\n))[ \t]*/g, ' ');
  return unwrapped
    .split(/\n+|(?<=[.!?])\s+/)
    .map(s => s.replace(/^\s*(?:[-*]|\d+\.)\s+(?:\[[ x]\]\s*)?/, '').trim())
    .filter(Boolean);
}

function guessKind(body) {
  const text = visibleText(body).trim();
  if (/^▶/.test(text) || (/is running/i.test(text) && words(text).length <= 40)) return 'started';
  if (/\b(blocked|failed|could not|cannot)\b/i.test(text.split('\n')[0])) return 'blocked';
  // "You need to: nothing" asks for no work, so it is a summary however many
  // times the text says "approve" or "review".
  if (/you need to:?\*{0,2}\s*nothing/i.test(text)) return 'summary';
  if (/\b(waiting on you|approve|review)\b/i.test(text)) return 'ready';
  return 'summary';
}

function lint(body, kind) {
  kind = kind || guessKind(body);
  const text = visibleText(body);
  const count = words(text).length;
  const budget = BUDGETS[kind] ?? BUDGETS.summary;
  const long = sentences(text)
    .map(s => ({ sentence: s, words: words(s).length }))
    .filter(s => s.words > SENTENCE_LIMIT);
  const terms = new Set();
  for (const re of INTERNAL_TERMS) for (const m of text.matchAll(re)) terms.add(m[0]);
  for (const [code, name] of Object.entries(GATES)) {
    const re = new RegExp(`\\b${code}\\b`);
    if (re.test(text) && !text.toLowerCase().includes(name)) terms.add(`${code} without "${name}"`);
  }
  const hasAction = /\*{0,2}you need to:?\*{0,2}/i.test(text);
  const folded = detailsWords(body);
  const problems = [];
  if (count > budget) problems.push(`over budget: ${count} words, ${kind} allows ${budget}`);
  if (long.length) problems.push(`${long.length} sentence(s) over ${SENTENCE_LIMIT} words`);
  if (NEEDS_ACTION.has(kind) && !hasAction) problems.push('no "You need to:" line');
  if (terms.size) problems.push(`internal terms: ${[...terms].join(', ')}`);
  if (folded > DETAILS_LIMIT) problems.push(`Factory details is ${folded} words, over its ${DETAILS_LIMIT}-word cap`);
  return {
    kind, words: count, budget, over_budget: count > budget, details_words: folded,
    long_sentences: long, has_action: hasAction,
    internal_terms: [...terms], ok: problems.length === 0, problems,
  };
}

function summarize(results) {
  const ws = results.map(r => r.words).sort((a, b) => a - b);
  const at = p => (ws.length ? ws[Math.min(ws.length - 1, Math.floor(ws.length * p))] : 0);
  return {
    comments: results.length,
    ok: results.filter(r => r.ok).length,
    words_p50: at(0.5), words_p90: at(0.9), words_max: ws[ws.length - 1] || 0,
    over_budget: results.filter(r => r.over_budget).length,
  };
}

module.exports = { lint, summarize, visibleText, guessKind, BUDGETS };

if (require.main === module) {
  const input = require('fs').readFileSync(0, 'utf8');
  if (process.argv.includes('--json')) {
    const results = JSON.parse(input).map(c => lint(c.body, c.kind));
    process.stdout.write(JSON.stringify({ summary: summarize(results), results }, null, 2) + '\n');
  } else {
    process.stdout.write(JSON.stringify(lint(input), null, 2) + '\n');
  }
}
