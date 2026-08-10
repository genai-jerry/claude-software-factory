// Router tests.
//
// The route job is the one piece of real logic in this repo, and a wrong branch
// there is invisible until a real issue sits at the wrong label. This extracts
// the route and release-chain github-script bodies straight out of
// .github/workflows/factory-pipeline.yml and runs them against a fake GitHub
// API, so the thing under test is the shipped code, not a copy of it.
//
//   npm install js-yaml && node scripts/test-router.js
//
// Exits non-zero on the first failing expectation set.
const fs = require('fs');
const path = require('path');
let yaml;
try {
  yaml = require('js-yaml');
} catch (e) {
  console.error('This harness needs js-yaml:  npm install js-yaml');
  process.exit(2);
}

const WF = path.join(__dirname, '..', '.github', 'workflows', 'factory-pipeline.yml');
const doc = yaml.load(fs.readFileSync(WF, 'utf8'));
const routeSrc = doc.jobs.route.steps.find(s => s.id === 'route').with.script;
const relSrc = doc.jobs['release-chain'].steps.find(s => s.id === 'release').with.script;

function makeWorld(opts) {
  const state = {
    issues: opts.issues || {},        // number -> {number,title,labels:[],user:{type},milestone,pull_request}
    comments: opts.comments || {},    // number -> [{body}]
    created: [],
    log: [],
    files: opts.files || {},
  };
  const L = n => state.issues[n].labels.map(l => l.name || l);
  const github = {
    paginate: async (fn, params) => (await fn(params)).data,
    rest: {
      issues: {
        listForRepo: async (p) => {
          let all = Object.values(state.issues);
          if (p.labels) all = all.filter(i => L(i.number).includes(p.labels));
          if (p.milestone) all = all.filter(i => i.milestone && String(i.milestone.number) === String(p.milestone));
          if (p.state && p.state !== 'all') all = all.filter(i => (i.state || 'open') === p.state);
          return { data: all };
        },
        get: async (p) => ({ data: state.issues[p.issue_number] }),
        create: async (p) => {
          const n = Math.max(0, ...Object.keys(state.issues).map(Number)) + 1;
          const iss = { number: n, title: p.title, body: p.body, user: { type: 'Bot' },
                        labels: (p.labels || []).map(name => ({ name })),
                        milestone: p.milestone ? { number: p.milestone } : null, state: 'open' };
          state.issues[n] = iss; state.created.push(iss);
          state.log.push(`create #${n} "${p.title}" [${(p.labels || []).join(',')}]`);
          return { data: iss };
        },
        addLabels: async (p) => {
          for (const n of p.labels) if (!L(p.issue_number).includes(n)) state.issues[p.issue_number].labels.push({ name: n });
          state.log.push(`+label #${p.issue_number} ${p.labels.join(',')}`);
        },
        removeLabel: async (p) => {
          const i = state.issues[p.issue_number];
          if (!L(p.issue_number).includes(p.name)) { const e = new Error('not found'); e.status = 404; throw e; }
          i.labels = i.labels.filter(l => (l.name || l) !== p.name);
          state.log.push(`-label #${p.issue_number} ${p.name}`);
        },
        createComment: async (p) => {
          (state.comments[p.issue_number] ||= []).push({ body: p.body });
          state.log.push(`comment #${p.issue_number}: ${p.body.split('\n')[0].slice(0, 70)}`);
        },
        listComments: async (p) => ({ data: state.comments[p.issue_number] || [] }),
        addAssignees: async (p) => { state.log.push(`assign #${p.issue_number} ${p.assignees.join(',')}`); },
      },
      pulls: { list: async () => ({ data: [] }), merge: async () => ({}) },
    },
  };
  const outputs = {};
  const core = {
    info: m => state.log.push(`info: ${m}`),
    setOutput: (k, v) => { outputs[k] = v; },
  };
  return { github, core, outputs, state };
}

async function run(src, { context, world }) {
  const fakeRequire = (m) => {
    if (m === 'fs') return { readFileSync: (p) => {
      if (world.state.files[p] === undefined) { const e = new Error('ENOENT'); throw e; }
      return world.state.files[p];
    } };
    return require(m);
  };
  const fn = new Function('github', 'core', 'context', 'require', 'process',
    `return (async () => { ${src} })()`);
  await fn(world.github, world.core, context, fakeRequire, { env: context.__env || {} });
  return world.outputs;
}

const GATED = JSON.stringify({ gating: 'milestone', approval: 'human',
  auto_create_release_issue: true, exempt_labels: ['factory:fast-track'] });
const APPROVERS = JSON.stringify({ release_scope: ['boss'], spec: ['boss'], design: ['boss'], implementation: ['boss'] });
const filesGated = { '.github/factory-release.json': GATED, '.github/factory-approvers.json': APPROVERS };
const filesOpen = { '.github/factory-approvers.json': APPROVERS };
const ctx = (name, payload, env) => ({ eventName: name, payload,
  repo: { owner: 'o', repo: 'r' }, __env: env || {} });

let failures = 0;
function check(label, cond, extra) {
  console.log(`${cond ? '  ok  ' : ' FAIL '} ${label}${cond ? '' : '  <<< ' + JSON.stringify(extra)}`);
  if (!cond) failures++;
}

(async () => {
  // ---------------------------------------------------------------- scenario 1
  console.log('\n1. gating OFF — issue opened goes straight to intake');
  {
    const w = makeWorld({ files: filesOpen,
      issues: { 5: { number: 5, title: 'Add renewals', labels: [], user: { type: 'User' }, milestone: null } } });
    const out = await run(routeSrc, { world: w, context: ctx('issues', { action: 'opened', issue: w.state.issues[5] }) });
    check('role=intake', out.role === 'intake', out);
    check('issues=["5"]', out.issues === '["5"]', out);
    check('factory:intake applied', w.state.issues[5].labels.some(l => l.name === 'factory:intake'), w.state.log);
  }

  // ---------------------------------------------------------------- scenario 2
  console.log('\n2. gating ON, no milestone — parked in backlog, nothing runs');
  {
    const w = makeWorld({ files: filesGated,
      issues: { 5: { number: 5, title: 'Add renewals', labels: [{ name: 'factory:intake' }], user: { type: 'User' }, milestone: null } } });
    const out = await run(routeSrc, { world: w, context: ctx('issues', { action: 'opened', issue: w.state.issues[5] }) });
    check('role=none', out.role === 'none', out);
    check('backlog applied', w.state.issues[5].labels.some(l => l.name === 'factory:backlog'), w.state.log);
    check('intake removed', !w.state.issues[5].labels.some(l => l.name === 'factory:intake'), w.state.log);
    check('explained', (w.state.comments[5] || []).length === 1, w.state.log);
  }

  // ---------------------------------------------------------------- scenario 3
  console.log('\n3. gating ON, exempt label — never parked in backlog');
  {
    // factory:fast-track is skipped from intake by a pre-existing rule (it takes
    // the normal PR flow), so the point here is that gating does not park it.
    const w = makeWorld({ files: filesGated,
      issues: { 5: { number: 5, title: 'Typo', labels: [{ name: 'factory:fast-track' }], user: { type: 'User' }, milestone: null } } });
    const out = await run(routeSrc, { world: w, context: ctx('issues', { action: 'opened', issue: w.state.issues[5] }) });
    check('not parked', !w.state.issues[5].labels.some(l => l.name === 'factory:backlog'), w.state.log);
    check('no route (fast-track skips intake)', out.role === 'none', out);

    // and a non-factory exempt label does reach intake
    const files = { ...filesGated, '.github/factory-release.json': JSON.stringify({
      gating: 'milestone', approval: 'human', exempt_labels: ['hotfix'] }) };
    const w2 = makeWorld({ files,
      issues: { 5: { number: 5, title: 'Prod down', labels: [{ name: 'hotfix' }], user: { type: 'User' }, milestone: null } } });
    const out2 = await run(routeSrc, { world: w2, context: ctx('issues', { action: 'opened', issue: w2.state.issues[5] }) });
    check('custom exempt label -> intake', out2.role === 'intake', out2);
  }

  // ---------------------------------------------------------------- scenario 4
  console.log('\n4. milestone created — tracker opened');
  {
    const w = makeWorld({ files: filesGated });
    const out = await run(routeSrc, { world: w, context: ctx('milestone',
      { action: 'created', milestone: { number: 7, title: 'v0.4 renewals', html_url: 'u' } }) });
    check('role=none', out.role === 'none', out);
    check('tracker created', w.state.created.length === 1 && w.state.created[0].title === 'release(7): v0.4 renewals', w.state.log);
    check('tracker labels', ['factory:release', 'factory:release-planning']
      .every(n => w.state.created[0].labels.some(l => l.name === n)), w.state.log);
    // Nobody is subscribed to a bot-opened issue, so the tracker has to say who
    // must act and that nothing is running until they do.
    check('tracker cc\'s the G0 approvers', w.state.created[0].body.includes('@boss'), w.state.created[0].body);
    check('tracker says nothing is running', /Nothing is running yet/.test(w.state.created[0].body), w.state.created[0].body);
  }

  // ---------------------------------------------------------------- scenario 5
  console.log('\n5. issue milestoned into an unapproved release — queued, no duplicate tracker');
  {
    const ms = { number: 7, title: 'v0.4', html_url: 'u' };
    const w = makeWorld({ files: filesGated, issues: {
      1: { number: 1, title: 'release(7): v0.4', labels: [{ name: 'factory:release' }, { name: 'factory:release-planning' }], user: { type: 'Bot' }, milestone: ms },
      5: { number: 5, title: 'Add renewals', labels: [{ name: 'factory:intake' }], user: { type: 'User' }, milestone: ms },
    } });
    const out = await run(routeSrc, { world: w, context: ctx('issues', { action: 'milestoned', issue: w.state.issues[5], milestone: ms }) });
    check('role=none', out.role === 'none', out);
    check('no new tracker', w.state.created.length === 0, w.state.log);
    check('backlog applied', w.state.issues[5].labels.some(l => l.name === 'factory:backlog'), w.state.log);
    check('pointed at the tracker', (w.state.comments[5] || []).some(c => c.body.includes('#1')), w.state.log);
  }

  // --------------------------------------------------------------- scenario 5b
  console.log('\n5b. issue filed BEFORE its milestone existed, then milestoned — told what it waits on');
  {
    // The regression: filing first and creating the milestone later left the
    // issue already in factory:backlog, so `milestoned` took the "nothing to
    // do" branch and said nothing at all. Its only guidance stayed the parking
    // comment telling the reader to add a milestone they had just added.
    const ms = { number: 7, title: 'v0.4', html_url: 'u' };
    const w = makeWorld({ files: filesGated, issues: {
      1: { number: 1, title: 'release(7): v0.4', labels: [{ name: 'factory:release' }, { name: 'factory:release-planning' }], user: { type: 'Bot' }, milestone: ms },
      5: { number: 5, title: 'Add renewals', labels: [{ name: 'factory:backlog' }], user: { type: 'User' }, milestone: ms },
    }, comments: { 5: [{ body: 'Parked in `factory:backlog` — this repo runs **release-gated intake**.' }] } });
    const out = await run(routeSrc, { world: w, context: ctx('issues', { action: 'milestoned', issue: w.state.issues[5], milestone: ms }) });
    check('role=none', out.role === 'none', out);
    const notice = (w.state.comments[5] || []).find(c => c.body.includes('factory-queued:1'));
    check('queued notice posted', !!notice, w.state.log);
    check('names the tracker and both commands',
      !!notice && notice.body.includes('#1') && notice.body.includes('Plan release') && notice.body.includes('Approved'),
      notice && notice.body);

    // Re-milestoning the same issue must not repeat it.
    await run(routeSrc, { world: w, context: ctx('issues', { action: 'milestoned', issue: w.state.issues[5], milestone: ms }) });
    check('not repeated', (w.state.comments[5] || []).filter(c => c.body.includes('factory-queued:1')).length === 1, w.state.log);
  }

  // ---------------------------------------------------------------- scenario 6
  console.log('\n6. Plan release comment — scrum, authorised');
  {
    const w = makeWorld({ files: filesGated, issues: {
      1: { number: 1, title: 'release(7): v0.4', labels: [{ name: 'factory:release' }, { name: 'factory:release-planning' }], user: { type: 'Bot' } },
    } });
    const out = await run(routeSrc, { world: w, context: ctx('issue_comment', {
      action: 'created', issue: w.state.issues[1],
      comment: { body: 'Plan release', user: { login: 'boss', type: 'User' }, author_association: 'OWNER' } }) });
    check('role=scrum', out.role === 'scrum', out);
    check('release_issue=1', out.release_issue === '1', out);

    const w2 = makeWorld({ files: filesGated, issues: {
      1: { number: 1, title: 'release(7): v0.4', labels: [{ name: 'factory:release' }, { name: 'factory:release-planning' }], user: { type: 'Bot' } },
    } });
    const out2 = await run(routeSrc, { world: w2, context: ctx('issue_comment', {
      action: 'created', issue: w2.state.issues[1],
      comment: { body: 'Plan release', user: { login: 'randal', type: 'User' }, author_association: 'NONE' } }) });
    check('unauthorised refused', out2.role === 'none' && (w2.state.comments[1] || []).length === 1, w2.state.log);
  }

  // ---------------------------------------------------------------- scenario 7
  console.log('\n7. Approved on a tracker that has no plan yet — explained, nothing runs');
  {
    const w = makeWorld({ files: filesGated, issues: {
      1: { number: 1, title: 'release(7): v0.4', labels: [{ name: 'factory:release' }, { name: 'factory:release-planning' }], user: { type: 'Bot' } },
    } });
    const out = await run(routeSrc, { world: w, context: ctx('issue_comment', {
      action: 'created', issue: w.state.issues[1],
      comment: { body: 'Approved', user: { login: 'boss', type: 'User' }, author_association: 'OWNER' } }) });
    check('role=none', out.role === 'none', out);
    check('explained', (w.state.comments[1] || [])[0].body.includes('Plan release'), w.state.log);
  }

  // ---------------------------------------------------------------- scenario 8
  console.log('\n8. gate G0 via comment, then release-chain fans the milestone out');
  {
    const ms = { number: 7, title: 'v0.4', html_url: 'u' };
    const w = makeWorld({ files: filesGated, issues: {
      1: { number: 1, title: 'release(7): v0.4', labels: [{ name: 'factory:release' }, { name: 'factory:release-ready' }], user: { type: 'Bot' }, milestone: ms },
      5: { number: 5, title: 'Add renewals', labels: [{ name: 'factory:backlog' }], user: { type: 'User' }, milestone: ms },
      6: { number: 6, title: 'Fix lapse email', labels: [{ name: 'factory:backlog' }], user: { type: 'User' }, milestone: ms },
      7: { number: 7, title: 'Older thing', labels: [{ name: 'factory:in-review' }], user: { type: 'User' }, milestone: ms },
      8: { number: 8, title: 'task(5): step one', labels: [], user: { type: 'User' }, milestone: ms },
      9: { number: 9, title: 'Not in this release', labels: [{ name: 'factory:backlog' }], user: { type: 'User' }, milestone: null },
    } });
    const out = await run(routeSrc, { world: w, context: ctx('issue_comment', {
      action: 'created', issue: w.state.issues[1],
      comment: { body: 'Approved', user: { login: 'boss', type: 'User' }, author_association: 'OWNER' } }) });
    check('role=none (no agent yet)', out.role === 'none', out);
    check('release_issue=1', out.release_issue === '1', out);
    check('tracker approved', w.state.issues[1].labels.some(l => l.name === 'factory:release-approved'), w.state.log);

    const out2 = await run(relSrc, { world: w, context: { ...ctx('x', {}), __env: { RELEASE_ISSUE: '1' } } });
    check('count=2', out2.count === '2', out2);
    check('issues=["5","6"]', out2.issues === '["5","6"]', out2);
    check('#5 intake', w.state.issues[5].labels.some(l => l.name === 'factory:intake'), w.state.log);
    check('#5 backlog gone', !w.state.issues[5].labels.some(l => l.name === 'factory:backlog'), w.state.log);
    check('#7 untouched (in flight)', w.state.issues[7].labels.length === 1, w.state.log);
    check('#8 task skipped', w.state.issues[8].labels.length === 0, w.state.log);
    check('#9 other milestone untouched', w.state.issues[9].labels.some(l => l.name === 'factory:backlog'), w.state.log);
    check('receipt posted', (w.state.comments[1] || []).some(c => c.body.includes('factory-release-dispatched')), w.state.log);

    // idempotence: a second run (PAT label event racing the in-run chain)
    const out3 = await run(relSrc, { world: w, context: { ...ctx('x', {}), __env: { RELEASE_ISSUE: '1' } } });
    check('second dispatch is a no-op', out3.count === '0', out3);
  }

  // ---------------------------------------------------------------- scenario 9
  console.log('\n9. issue added to an already-approved release — intake right away');
  {
    const ms = { number: 7, title: 'v0.4', html_url: 'u' };
    const w = makeWorld({ files: filesGated, issues: {
      1: { number: 1, title: 'release(7): v0.4', labels: [{ name: 'factory:release' }, { name: 'factory:release-approved' }], user: { type: 'Bot' }, milestone: ms },
      5: { number: 5, title: 'Late addition', labels: [{ name: 'factory:backlog' }], user: { type: 'User' }, milestone: ms },
    } });
    const out = await run(routeSrc, { world: w, context: ctx('issues', { action: 'milestoned', issue: w.state.issues[5], milestone: ms }) });
    check('role=intake', out.role === 'intake', out);
    check('#5 intake', w.state.issues[5].labels.some(l => l.name === 'factory:intake'), w.state.log);
  }

  // --------------------------------------------------------------- scenario 10
  console.log('\n10. demilestoned before intake — parked again');
  {
    const ms = { number: 7, title: 'v0.4', html_url: 'u' };
    const w = makeWorld({ files: filesGated, issues: {
      5: { number: 5, title: 'Moved out', labels: [{ name: 'factory:intake' }], user: { type: 'User' }, milestone: null },
    } });
    const out = await run(routeSrc, { world: w, context: ctx('issues', { action: 'demilestoned', issue: w.state.issues[5], milestone: ms }) });
    check('role=none', out.role === 'none', out);
    check('backlog applied', w.state.issues[5].labels.some(l => l.name === 'factory:backlog'), w.state.log);
  }

  // --------------------------------------------------------------- scenario 11
  console.log('\n11. demilestoned while in flight — left alone');
  {
    const ms = { number: 7, title: 'v0.4', html_url: 'u' };
    const w = makeWorld({ files: filesGated, issues: {
      5: { number: 5, title: 'In flight', labels: [{ name: 'factory:design-approved' }], user: { type: 'User' }, milestone: null },
    } });
    await run(routeSrc, { world: w, context: ctx('issues', { action: 'demilestoned', issue: w.state.issues[5], milestone: ms }) });
    check('untouched', w.state.issues[5].labels.length === 1 && !(w.state.comments[5] || []).length, w.state.log);
  }

  // --------------------------------------------------------------- scenario 12
  console.log('\n12. existing behaviour still intact (G1 Approved, blocked resume, task close)');
  {
    const w = makeWorld({ files: filesOpen, issues: {
      5: { number: 5, title: 'Epic', labels: [{ name: 'factory:spec-ready' }], user: { type: 'User' } },
    } });
    const out = await run(routeSrc, { world: w, context: ctx('issue_comment', {
      action: 'created', issue: w.state.issues[5],
      comment: { body: 'Approved', user: { login: 'boss', type: 'User' }, author_association: 'OWNER' } }) });
    check('G1 -> planner', out.role === 'planner', out);
    check('label flipped', w.state.issues[5].labels.some(l => l.name === 'factory:spec-approved'), w.state.log);

    const w2 = makeWorld({ files: filesOpen, issues: {
      5: { number: 5, title: 'Epic', labels: [{ name: 'factory:blocked' }, { name: 'factory:intake' }], user: { type: 'User' } },
    } });
    const out2 = await run(routeSrc, { world: w2, context: ctx('issue_comment', {
      action: 'created', issue: w2.state.issues[5],
      comment: { body: 'here is the answer', user: { login: 'boss', type: 'User' }, author_association: 'OWNER' } }) });
    check('blocked resume -> intake', out2.role === 'intake', out2);
    check('blocked cleared', !w2.state.issues[5].labels.some(l => l.name === 'factory:blocked'), w2.state.log);

    const w3 = makeWorld({ files: filesOpen, issues: {
      5: { number: 5, title: 'Epic', labels: [{ name: 'factory:design-approved' }], user: { type: 'User' } },
      8: { number: 8, title: 'task(5): step one', labels: [], user: { type: 'User' } },
    } });
    const out3 = await run(routeSrc, { world: w3, context: ctx('issues', { action: 'closed', issue: w3.state.issues[8] }) });
    check('task close -> dispatch on epic', out3.role === 'dispatch' && out3.issue === '5', out3);

    const w4 = makeWorld({ files: filesOpen, issues: {
      5: { number: 5, title: 'Task', labels: [{ name: 'factory:ready' }], user: { type: 'User' } },
    } });
    const out4 = await run(routeSrc, { world: w4, context: ctx('issue_comment', {
      action: 'created', issue: w4.state.issues[5],
      comment: { body: 'Approved', user: { login: 'boss', type: 'User' }, author_association: 'OWNER' } }) });
    check('ready -> implementer', out4.role === 'implementer', out4);

    const w5 = makeWorld({ files: filesOpen, issues: {
      5: { number: 5, title: 'Epic', labels: [{ name: 'factory:planned' }], user: { type: 'User' } },
    } });
    const out5 = await run(routeSrc, { world: w5, context: ctx('issue_comment', {
      action: 'created', issue: w5.state.issues[5],
      comment: { body: 'Approved', user: { login: 'boss', type: 'User' }, author_association: 'OWNER' } }) });
    check('dead Approved explained', out5.role === 'none' && (w5.state.comments[5] || []).length === 1, w5.state.log);
  }

  // --------------------------------------------------------------- scenario 13
  console.log('\n13. labeled factory:release-approved by hand -> release_issue set');
  {
    const w = makeWorld({ files: filesGated, issues: {
      1: { number: 1, title: 'release(7): v0.4', labels: [{ name: 'factory:release' }, { name: 'factory:release-ready' }, { name: 'factory:release-approved' }], user: { type: 'Bot' } },
    } });
    const out = await run(routeSrc, { world: w, context: ctx('issues', {
      action: 'labeled', issue: w.state.issues[1],
      label: { name: 'factory:release-approved' }, sender: { login: 'boss' } }) });
    check('release_issue=1', out.release_issue === '1', out);
    check('release-ready removed', !w.state.issues[1].labels.some(l => l.name === 'factory:release-ready'), w.state.log);

    const w2 = makeWorld({ files: filesGated, issues: {
      1: { number: 1, title: 'release(7): v0.4', labels: [{ name: 'factory:release' }, { name: 'factory:release-approved' }], user: { type: 'Bot' } },
    } });
    const out2 = await run(routeSrc, { world: w2, context: ctx('issues', {
      action: 'labeled', issue: w2.state.issues[1],
      label: { name: 'factory:release-approved' }, sender: { login: 'randal' } }) });
    check('unauthorised flip reverted', out2.release_issue === '' &&
      !w2.state.issues[1].labels.some(l => l.name === 'factory:release-approved'), w2.state.log);
  }

  // --------------------------------------------------------------- scenario 14
  console.log('\n14. factory:release-ready notifies the G0 approvers');
  {
    const w = makeWorld({ files: filesGated, issues: {
      1: { number: 1, title: 'release(7): v0.4', labels: [{ name: 'factory:release' }, { name: 'factory:release-ready' }], user: { type: 'Bot' } },
    } });
    await run(routeSrc, { world: w, context: ctx('issues', {
      action: 'labeled', issue: w.state.issues[1],
      label: { name: 'factory:release-ready' }, sender: { login: 'scrumbot' } }) });
    check('assigned + mentioned', w.state.log.some(l => l.startsWith('assign #1')) &&
      (w.state.comments[1] || [])[0].body.includes('Gate G0'), w.state.log);
  }

  // --------------------------------------------------------------- scenario 14b
  console.log('\n14b. factory:fast-track — says the silence is deliberate, once');
  {
    // Fast-track dispatches no role and applies no factory:* state, so the
    // issue is visually identical to one the factory forgot about.
    const w = makeWorld({ files: filesGated, issues: {
      5: { number: 5, title: 'Rename a page title', labels: [{ name: 'factory:fast-track' }], user: { type: 'User' }, milestone: null },
    } });
    const out = await run(routeSrc, { world: w, context: ctx('issues', {
      action: 'labeled', issue: w.state.issues[5],
      label: { name: 'factory:fast-track' }, sender: { login: 'genai-jerry' } }) });
    check('role=none', out.role === 'none', out);
    const note = (w.state.comments[5] || []).find(c => c.body.includes('factory-fast-tracked'));
    check('explained', !!note, w.state.log);
    check('says no agent runs, and how to undo', !!note &&
      /no factory agent will run/i.test(note.body) && note.body.includes('Remove `factory:fast-track`'), note && note.body);

    // Label churn must not repeat it.
    await run(routeSrc, { world: w, context: ctx('issues', {
      action: 'labeled', issue: w.state.issues[5],
      label: { name: 'factory:fast-track' }, sender: { login: 'genai-jerry' } }) });
    check('not repeated', (w.state.comments[5] || []).filter(c => c.body.includes('factory-fast-tracked')).length === 1, w.state.log);
  }

  // --------------------------------------------------------------- scenario 14c
  console.log('\n14c. `Plan release` on a requirement issue — answered, not ignored');
  {
    const ms = { number: 7, title: 'v0.4', html_url: 'u' };
    const w = makeWorld({ files: filesGated, issues: {
      1: { number: 1, title: 'release(7): v0.4', labels: [{ name: 'factory:release' }, { name: 'factory:release-planning' }], user: { type: 'Bot' }, milestone: ms },
      5: { number: 5, title: 'Add renewals', labels: [{ name: 'factory:backlog' }], user: { type: 'User' }, milestone: ms },
    } });
    const out = await run(routeSrc, { world: w, context: ctx('issue_comment', {
      action: 'created', issue: w.state.issues[5],
      comment: { body: 'Plan release', user: { login: 'genai-jerry', type: 'User' }, author_association: 'OWNER' } }) });
    check('role=none', out.role === 'none', out);
    const reply = (w.state.comments[5] || [])[0];
    check('replied', !!reply, w.state.log);
    check('points at the tracker', !!reply && reply.body.includes('#1'), reply && reply.body);

    // No milestone at all — still answered, without inventing a tracker.
    const w2 = makeWorld({ files: filesGated, issues: {
      5: { number: 5, title: 'Add renewals', labels: [{ name: 'factory:backlog' }], user: { type: 'User' }, milestone: null },
    } });
    await run(routeSrc, { world: w2, context: ctx('issue_comment', {
      action: 'created', issue: w2.state.issues[5],
      comment: { body: 'Plan release', user: { login: 'genai-jerry', type: 'User' }, author_association: 'OWNER' } }) });
    check('answered with no milestone', (w2.state.comments[5] || []).some(c => /no release to plan/.test(c.body)), w2.state.log);
    check('no tracker invented', w2.state.created.length === 0, w2.state.log);
  }

  // --------------------------------------------------------------- scenario 15
  console.log('\n15. skip propagation — every job downstream of an always() job guards its own status');
  {
    // A skipped job skips everything after it in the needs chain. A job that
    // uses always() runs anyway, but the propagation does not stop there: the
    // next job inherits the skip unless it also carries a status function.
    // release-intake learned this the hard way — a human-approved release moved
    // its issues to factory:intake and then started nothing, because `agent` is
    // skipped on that path. This is invisible in the scenario tests above (they
    // exercise script bodies, not job conditions), so assert it on the YAML.
    const STATUS_FN = /\b(always|success|failure|cancelled)\s*\(\s*\)/;
    const jobs = doc.jobs;
    const ifOf = (j) => String(jobs[j].if || '');
    // Ancestors reachable through needs, transitively.
    const ancestors = (j, seen = new Set()) => {
      const need = jobs[j].needs;
      for (const p of (Array.isArray(need) ? need : need ? [need] : [])) {
        if (seen.has(p)) continue;
        seen.add(p); ancestors(p, seen);
      }
      return seen;
    };
    for (const name of Object.keys(jobs)) {
      const risky = [...ancestors(name)].filter(a => STATUS_FN.test(ifOf(a)));
      if (!risky.length) continue;
      check(`${name} guards its status (downstream of ${risky.join(', ')})`,
        STATUS_FN.test(ifOf(name)), { if: ifOf(name) });
      // always() disables the implicit needs-succeeded check, so a job using it
      // has to assert the results it actually depends on.
      if (/\balways\s*\(\s*\)/.test(ifOf(name))) {
        const need = jobs[name].needs;
        const direct = Array.isArray(need) ? need : need ? [need] : [];
        const asserted = direct.filter(p => ifOf(name).includes(`needs.${p}.result`));
        check(`${name} asserts an upstream result under always()`, asserted.length > 0, { if: ifOf(name) });
      }
    }
  }

  console.log(failures ? `\n${failures} FAILURE(S)` : '\nall scenarios pass');
  process.exit(failures ? 1 : 0);
})();
