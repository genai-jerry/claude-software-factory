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
//   - the visible sentences: more than eight is over §1a's "six or fewer"
//   - readability: Flesch-Kincaid grade over 8, or sentences averaging over
//     20 words (§1a Length) — a measure of word and sentence length only; it
//     cannot see a stand-in noun, which rule 14 is for
//   - words against a backstop cap for the comment's kind
//   - sentences longer than 25 words
//   - a "You need to:" line, where the kind calls for one
//   - factory-internal terms in the prose (they belong in Factory details)
//   - issue, PR or task numbers in the prose (§1a rule 11: name the task; the
//     numbers go on the Links line, which is exempt)
'use strict';

// Backstop caps, not targets: §1a measures length in sentences and grade.
const BUDGETS = { started: 25, ready: 160, blocked: 160, summary: 220 };
const NEEDS_ACTION = new Set(['ready', 'blocked', 'summary']);
const SENTENCE_LIMIT = 25;
// §1a Length: six sentences or fewer; the lint allows eight before it says so.
const SENTENCES_LIMIT = 8;
const GRADE_LIMIT = 8;
const AVG_WORDS_LIMIT = 20;
// The lines §1a does not count as sentences: the frame around the content.
const FRAME_LINE = /^\s*\*{0,2}(?:you need to|next|links|questions? for you):?/i;
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
// A number where a name belongs: `#62`, `beacon-api#62`, a Mermaid `T1[`
// box id. Case ids (`ST-4`) carry no `#` and are allowed.
const NUMBER_REFS = /(?:\b[\w.-]+(?:\/[\w.-]+)?)?#\d+\b|\bT\d+\[/g;

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

// The sentences a person reads as content: not the frame lines, not the
// headline, not a bare fragment.
function contentSentences(text) {
  const lines = text.split('\n').filter(l => !FRAME_LINE.test(l));
  const first = lines.findIndex(l => l.trim());
  // The headline is the first bold line; it frames the comment and is not counted.
  if (first >= 0 && /^\s*\*\*.*\*\*\s*$/.test(lines[first])) lines.splice(first, 1);
  return sentences(lines.join('\n')).filter(s => words(s).length >= 3);
}
function syllables(word) {
  const w = word.toLowerCase().replace(/[^a-z]/g, '');
  if (!w) return 0;
  let n = (w.match(/[aeiouy]+/g) || []).length;
  if (w.endsWith('e') && !w.endsWith('le') && n > 1) n -= 1;
  return Math.max(1, n);
}
// Flesch-Kincaid grade over the content sentences; null when there is too
// little text to measure (under two sentences).
function readingGrade(ss) {
  if (ss.length < 2) return null;
  const ws = ss.flatMap(s => words(s));
  if (!ws.length) return null;
  const syl = ws.reduce((n, w) => n + syllables(w), 0);
  return Math.round((0.39 * ws.length / ss.length + 11.8 * syl / ws.length - 15.59) * 10) / 10;
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
  const numbers = new Set();
  for (const line of text.split('\n')) {
    if (/^\s*\*{0,2}links:?\*{0,2}/i.test(line)) continue;
    for (const m of line.matchAll(NUMBER_REFS)) numbers.add(m[0]);
  }
  const content = contentSentences(text);
  const grade = readingGrade(content);
  const avgWords = content.length ? Math.round(content.reduce((n, s) => n + words(s).length, 0) / content.length * 10) / 10 : 0;
  const hasAction = /\*{0,2}you need to:?\*{0,2}/i.test(text);
  // A block ends with the questions a person answers (§1a rule 13).
  const hasQuestions = /^\s*\*{0,2}questions? for you:?\*{0,2}/im.test(text);
  const folded = detailsWords(body);
  const problems = [];
  if (count > budget) problems.push(`over budget: ${count} words, ${kind} allows ${budget}`);
  if (kind !== 'started' && content.length > SENTENCES_LIMIT) problems.push(`${content.length} sentences in the visible part; aim for six`);
  if (grade !== null && grade > GRADE_LIMIT) problems.push(`reads at grade ${grade}; aim for ${GRADE_LIMIT} or lower (shorter words, shorter sentences)`);
  if (content.length >= 2 && avgWords > AVG_WORDS_LIMIT) problems.push(`sentences average ${avgWords} words; aim for ${AVG_WORDS_LIMIT} or fewer`);
  if (long.length) problems.push(`${long.length} sentence(s) over ${SENTENCE_LIMIT} words`);
  if (NEEDS_ACTION.has(kind) && !hasAction) problems.push('no "You need to:" line');
  if (kind === 'blocked' && !hasQuestions) problems.push('blocked without a "Questions for you:" list');
  if (terms.size) problems.push(`internal terms: ${[...terms].join(', ')}`);
  if (numbers.size) problems.push(`numbers where a name belongs: ${[...numbers].join(', ')} (name the task; numbers go on the Links line)`);
  if (folded > DETAILS_LIMIT) problems.push(`Factory details is ${folded} words, over its ${DETAILS_LIMIT}-word cap`);
  return {
    kind, words: count, budget, over_budget: count > budget, details_words: folded,
    sentences: content.length, grade, avg_sentence_words: avgWords,
    long_sentences: long, has_action: hasAction, has_questions: hasQuestions,
    internal_terms: [...terms], number_refs: [...numbers], ok: problems.length === 0, problems,
  };
}

function summarize(results) {
  const ws = results.map(r => r.words).sort((a, b) => a - b);
  const gs = results.map(r => r.grade).filter(g => g !== null).sort((a, b) => a - b);
  const at = (arr, p) => (arr.length ? arr[Math.min(arr.length - 1, Math.floor(arr.length * p))] : 0);
  return {
    comments: results.length,
    ok: results.filter(r => r.ok).length,
    words_p50: at(ws, 0.5), words_p90: at(ws, 0.9), words_max: ws[ws.length - 1] || 0,
    over_budget: results.filter(r => r.over_budget).length,
    grade_p50: at(gs, 0.5), grade_p90: at(gs, 0.9),
    over_grade: results.filter(r => r.grade !== null && r.grade > GRADE_LIMIT).length,
    over_sentences: results.filter(r => r.kind !== 'started' && r.sentences > SENTENCES_LIMIT).length,
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
