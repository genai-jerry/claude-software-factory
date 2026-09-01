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
    pulls: opts.pulls || [],          // [{number, head:{ref}, base:{ref}, state}]
    branches: opts.branches || [],    // branch names that exist on the remote
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
      pulls: {
        // PRs: opts.pulls = [{number, head:{ref}, base:{ref}, state}]
        list: async (p) => ({ data: (state.pulls || []).filter(pr =>
          (pr.state || 'open') === (p.state || 'open') &&
          (!p.head || `o:${pr.head.ref}` === p.head)) }),
        merge: async (p) => {
          const pr = (state.pulls || []).find(x => x.number === p.pull_number);
          if (pr) { pr.state = 'merged'; pr.merged_base = pr.base.ref; }
          state.log.push(`merge PR #${p.pull_number} -> ${pr ? pr.base.ref : '?'}`);
          return {};
        },
        update: async (p) => {
          const pr = (state.pulls || []).find(x => x.number === p.pull_number);
          if (pr && p.base) pr.base = { ref: p.base };
          state.log.push(`retarget PR #${p.pull_number} base=${p.base}`);
          return {};
        },
      },
      repos: {
        // Branches: opts.branches = ['main', 'factory/epic-5', ...]
        getBranch: async (p) => {
          if (!(state.branches || []).includes(p.branch)) {
            const e = new Error('not found'); e.status = 404; throw e;
          }
          return { data: { name: p.branch, commit: { sha: 'sha-' + p.branch } } };
        },
      },
      git: {
        createRef: async (p) => {
          (state.branches ||= []).push(p.ref.replace('refs/heads/', ''));
          state.log.push(`create-branch ${p.ref} @ ${p.sha}`);
          return {};
        },
      },
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
    // factory:fast-track bypasses the release queue AND the pipeline: it goes
    // straight to the fast lane, which implements it and opens a PR.
    const w = makeWorld({ files: filesGated,
      issues: { 5: { number: 5, title: 'Typo', labels: [{ name: 'factory:fast-track' }], user: { type: 'User' }, milestone: null } } });
    const out = await run(routeSrc, { world: w, context: ctx('issues', { action: 'opened', issue: w.state.issues[5] }) });
    check('not parked', !w.state.issues[5].labels.some(l => l.name === 'factory:backlog'), w.state.log);
    check('routes to the fast lane', out.role === 'fasttrack', out);
    check('no intake label', !w.state.issues[5].labels.some(l => l.name === 'factory:intake'), w.state.log);

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
  console.log('\n14b. factory:fast-track applied — the fast lane implements it');
  {
    const ms = { number: 7, title: 'v0.4', html_url: 'u' };
    const w = makeWorld({ files: filesGated, issues: {
      5: { number: 5, title: 'Rename a page title', labels: [{ name: 'factory:backlog' }, { name: 'factory:fast-track' }], user: { type: 'User' }, milestone: ms },
    } });
    const out = await run(routeSrc, { world: w, context: ctx('issues', {
      action: 'labeled', issue: w.state.issues[5],
      label: { name: 'factory:fast-track' }, sender: { login: 'genai-jerry' } }) });
    check('role=fasttrack', out.role === 'fasttrack', out);
    check('issues=["5"]', out.issues === '["5"]', out);
    check('leaves the release queue', !w.state.issues[5].labels.some(l => l.name === 'factory:backlog'), w.state.log);

    // Re-labelling after a PR exists must not open a second one.
    const w2 = makeWorld({ files: filesGated, issues: {
      5: { number: 5, title: 'Rename a page title', labels: [{ name: 'factory:fast-track' }], user: { type: 'User' }, milestone: null },
    }, comments: { 5: [{ body: 'Opened #40.\n\n<!-- factory-fast-track-done -->\n<!-- factory-agent -->' }] } });
    const out2 = await run(routeSrc, { world: w2, context: ctx('issues', {
      action: 'labeled', issue: w2.state.issues[5],
      label: { name: 'factory:fast-track' }, sender: { login: 'genai-jerry' } }) });
    check('already has a PR -> no second run', out2.role === 'none', out2);

    // An issue the pipeline has already invested in is not hijacked.
    const w3 = makeWorld({ files: filesGated, issues: {
      5: { number: 5, title: 'Big thing', labels: [{ name: 'factory:spec-ready' }, { name: 'factory:fast-track' }], user: { type: 'User' }, milestone: null },
    } });
    const out3 = await run(routeSrc, { world: w3, context: ctx('issues', {
      action: 'labeled', issue: w3.state.issues[5],
      label: { name: 'factory:fast-track' }, sender: { login: 'genai-jerry' } }) });
    check('in-flight issue not hijacked', out3.role === 'none', out3);
    check('and it says why', (w3.state.comments[5] || []).some(c => /does not take over/.test(c.body)), w3.state.log);
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

  // --------------------------------------------------------------- scenario 16
  console.log('\n16. factory:in-progress is a marker, not a state — routing ignores it');
  {
    // The agent jobs put it on an issue for the length of a run. Every
    // factory:* test in the router therefore has to look straight through it,
    // or a run would change the routing of the issue it is running on.
    const IP = { name: 'factory:in-progress' };

    // (a) the label event the marker itself raises (only with a PAT) routes nowhere
    const w = makeWorld({ files: filesGated, issues: {
      5: { number: 5, title: 'Add renewals', labels: [{ name: 'factory:intake' }, IP], user: { type: 'User' } },
    } });
    const out = await run(routeSrc, { world: w, context: ctx('issues', {
      action: 'labeled', issue: w.state.issues[5],
      label: { name: 'factory:in-progress' }, sender: { login: 'github-actions' } }) });
    check('marker label event -> role=none', out.role === 'none', out);
    check('and it changes nothing',
      !w.state.log.some(l => !l.startsWith('info:')) && !(w.state.comments[5] || []).length, w.state.log);

    // (b) still "not started": milestoned into an approved release enters intake
    const ms = { number: 7, title: 'v0.4', html_url: 'u' };
    const w2 = makeWorld({ files: filesGated, issues: {
      1: { number: 1, title: 'release(7): v0.4', labels: [{ name: 'factory:release' }, { name: 'factory:release-approved' }], user: { type: 'Bot' }, milestone: ms },
      5: { number: 5, title: 'Late addition', labels: [{ name: 'factory:backlog' }, IP], user: { type: 'User' }, milestone: ms },
    } });
    const out2 = await run(routeSrc, { world: w2, context: ctx('issues',
      { action: 'milestoned', issue: w2.state.issues[5], milestone: ms }) });
    check('marked issue still counts as not started', out2.role === 'intake', out2);

    // (c) the fast lane does not read it as work already in flight
    const w3 = makeWorld({ files: filesGated, issues: {
      5: { number: 5, title: 'Rename a page title', labels: [{ name: 'factory:intake' }, IP, { name: 'factory:fast-track' }], user: { type: 'User' } },
    } });
    const out3 = await run(routeSrc, { world: w3, context: ctx('issues', {
      action: 'labeled', issue: w3.state.issues[5],
      label: { name: 'factory:fast-track' }, sender: { login: 'boss' } }) });
    check('fast lane not blocked by the marker', out3.role === 'fasttrack', out3);

    // (d) a blocked issue with nothing but the marker beside it still resumes
    const w4 = makeWorld({ files: filesOpen, issues: {
      5: { number: 5, title: 'Epic', labels: [{ name: 'factory:blocked' }, IP], user: { type: 'User' } },
    } });
    const out4 = await run(routeSrc, { world: w4, context: ctx('issue_comment', {
      action: 'created', issue: w4.state.issues[5],
      comment: { body: 'here is the answer', user: { login: 'boss', type: 'User' }, author_association: 'OWNER' } }) });
    check('blocked resume -> intake', out4.role === 'intake', out4);

    // (e) the explanatory replies report the state, not the marker
    const w5 = makeWorld({ files: filesOpen, issues: {
      5: { number: 5, title: 'Epic', labels: [{ name: 'factory:planned' }, IP], user: { type: 'User' } },
    } });
    await run(routeSrc, { world: w5, context: ctx('issue_comment', {
      action: 'created', issue: w5.state.issues[5],
      comment: { body: 'Approved', user: { login: 'boss', type: 'User' }, author_association: 'OWNER' } }) });
    const reply = (w5.state.comments[5] || [])[0];
    check('reply names the state only', !!reply &&
      reply.body.includes('**factory:planned**') && !reply.body.includes('**factory:planned, factory:in-progress**'),
      reply && reply.body);

    // (f) a release batch still releases an issue that a run is marking
    const w6 = makeWorld({ files: filesGated, issues: {
      1: { number: 1, title: 'release(7): v0.4', labels: [{ name: 'factory:release' }, { name: 'factory:release-approved' }], user: { type: 'Bot' }, milestone: ms },
      5: { number: 5, title: 'Add renewals', labels: [{ name: 'factory:backlog' }, IP], user: { type: 'User' }, milestone: ms },
    } });
    const out6 = await run(relSrc, { world: w6, context: { ...ctx('x', {}), __env: { RELEASE_ISSUE: '1' } } });
    check('release batch includes the marked issue', out6.issues === '["5"]', out6);
  }

  // --------------------------------------------------------------- scenario 17
  console.log('\n17. every agent job marks its issue in progress and clears it whatever happens');
  {
    // The marker is only honest if it comes off on failure, on a no-op-guard
    // failure and on a timeout — i.e. from an always() step that is the last
    // one in the job. Assert it on the YAML rather than trusting the review.
    const MARK = /issues\/\$ISSUE\/labels/;
    const CLEAR = /-X DELETE[\s\S]*labels\/factory%3Ain-progress/;
    for (const [name, job] of Object.entries(doc.jobs)) {
      const steps = job.steps || [];
      if (!steps.some(s => /claude-code-action|claude -p /.test(`${s.uses || ''}${s.run || ''}`))) continue;
      const mark = steps.find(s => MARK.test(s.run || ''));
      const clear = steps[steps.length - 1];
      check(`${name} marks the issue in progress`, !!mark, steps.map(s => s.name));
      check(`${name} clears the marker in its last step`, CLEAR.test(clear.run || ''), clear.name);
      check(`${name} clears it under always()`, /\balways\s*\(\s*\)/.test(String(clear.if || '')), clear.if);
      // A cosmetic label must never be able to fail a run that otherwise worked.
      check(`${name} never fails on the marker`,
        mark.continue_on_error === true || mark['continue-on-error'] === true, mark);
    }
  }

  // --------------------------------------------------------------- scenario 18
  console.log('\n18. the factory may act on events it raised itself');
  {
    // The factory files its own issues on a human's behalf (a fast-track fix
    // split out of the issue a role was working on, a release tracker), so the
    // triggering actor is its App. claude-code-action refuses a non-human actor
    // unless it is in allowed_bots, and an omitted input is not a softer
    // setting — it is a hard failure before the prompt is read, which stranded
    // the request on a red run. The router is what decides whether an event is
    // worth a run; this only stops the actor check from overriding it.
    const input = (doc.on || doc[true]).workflow_call.inputs.allowed_bots;
    check('the workflow takes an allowed_bots input', !!input, Object.keys((doc.on || doc[true]).workflow_call.inputs));
    check('it defaults to the factory App alone, not to every bot',
      input && input.default === 'claude', input && input.default);
    for (const [name, job] of Object.entries(doc.jobs)) {
      for (const step of job.steps || []) {
        if (!/claude-code-action/.test(step.uses || '')) continue;
        check(`${name} passes allowed_bots to ${step.name}`,
          (step.with || {}).allowed_bots === '${{ inputs.allowed_bots }}',
          (step.with || {}).allowed_bots);
      }
    }
  }

  // --------------------------------------------------------------- scenario 19
  console.log('\n19. the repo profile — drafted, re-run, and drift-checked');
  {
    // Filed with the label: one API call files the issue and starts the
    // Profiler. Labels set at creation emit no `labeled` event of their own,
    // so routing this on `opened` is what makes the single call work.
    const w = makeWorld({ files: filesOpen,
      issues: { 7: { number: 7, title: 'Factory: repo profile', labels: [{ name: 'factory:profile' }],
                     user: { type: 'User' }, milestone: null } } });
    const out = await run(routeSrc, { world: w, context: ctx('issues', { action: 'opened', issue: w.state.issues[7] }) });
    check('role=profiler', out.role === 'profiler', out);
    check('never enters intake', !w.state.issues[7].labels.some(l => l.name === 'factory:intake'), w.state.log);

    // Re-applying the label is how a redraft is asked for.
    const w2 = makeWorld({ files: filesOpen,
      issues: { 7: { number: 7, title: 'Factory: repo profile', labels: [{ name: 'factory:profile' }],
                     user: { type: 'User' }, milestone: null } } });
    const out2 = await run(routeSrc, { world: w2, context: ctx('issues',
      { action: 'labeled', issue: w2.state.issues[7], label: { name: 'factory:profile' }, sender: { login: 'dev' } }) });
    check('re-applying the label re-runs it', out2.role === 'profiler', out2);

    // Drift: a manifest changed on the default branch. The push carries no
    // issue, so the router finds or files the singleton profile issue — the
    // agent job's matrix would be empty otherwise and the role would drop.
    const w3 = makeWorld({ files: filesOpen, issues: {} });
    const out3 = await run(routeSrc, { world: w3, context: ctx('push',
      { ref: 'refs/heads/main', repository: { default_branch: 'main' } }) });
    check('role=profiler', out3.role === 'profiler', out3);
    check('files the profile issue to run against', out3.issues === '["1"]', { out: out3, log: w3.state.log });
    check('labels it factory:profile', (w3.state.created[0] || {}).labels.some(l => l.name === 'factory:profile'),
      w3.state.created);

    // ...and reuses it next time rather than filing a second.
    const out4 = await run(routeSrc, { world: w3, context: ctx('push',
      { ref: 'refs/heads/main', repository: { default_branch: 'main' } }) });
    check('reuses the same issue', out4.issues === '["1"]', out4);
    check('filed exactly one', w3.state.created.length === 1, w3.state.created.map(i => i.number));

    // A push to any other branch is not the code the roles check out.
    const w5 = makeWorld({ files: filesOpen, issues: {} });
    const out5 = await run(routeSrc, { world: w5, context: ctx('push',
      { ref: 'refs/heads/feature-x', repository: { default_branch: 'main' } }) });
    check('non-default branch routes nowhere', out5.role === 'none', out5);
    check('and files nothing', w5.state.created.length === 0, w5.state.created);
  }

  // --------------------------------------------------------------- scenario 20
  console.log('\n20. epic-branch policy (§6b) — gate merges land on factory/epic-<n>');
  {
    const filesEpics = { ...filesOpen,
      '.github/factory-branches.json': JSON.stringify({ staging: 'staging', required: true, auto_create: true, epics: true }) };
    const approvedBy = (i) => ({ action: 'created', issue: i,
      repository: { default_branch: 'main' },
      comment: { body: 'Approved', user: { login: 'boss', type: 'User' }, author_association: 'OWNER' } });

    // G1 with epics:true is the adoption point: a spec PR still based on the
    // default branch gets the epic branch created and its base retargeted
    // before the squash merge.
    const w = makeWorld({ files: filesEpics, branches: ['main'],
      pulls: [{ number: 9, head: { ref: 'factory/5-spec' }, base: { ref: 'main' } }],
      issues: { 5: { number: 5, title: 'Epic', labels: [{ name: 'factory:spec-ready' }], user: { type: 'User' } } } });
    const out = await run(routeSrc, { world: w, context: ctx('issue_comment', approvedBy(w.state.issues[5])) });
    check('G1 -> planner', out.role === 'planner', out);
    check('epic branch created', w.state.branches.includes('factory/epic-5'), w.state.log);
    check('spec PR retargeted + merged into the epic branch',
      w.state.pulls[0].state === 'merged' && w.state.pulls[0].merged_base === 'factory/epic-5', w.state.log);

    // A spec PR already based on the epic branch (intake did its job) merges
    // as-is — no retarget, no duplicate branch creation.
    const w2 = makeWorld({ files: filesEpics, branches: ['main', 'factory/epic-5'],
      pulls: [{ number: 9, head: { ref: 'factory/5-spec' }, base: { ref: 'factory/epic-5' } }],
      issues: { 5: { number: 5, title: 'Epic', labels: [{ name: 'factory:spec-ready' }], user: { type: 'User' } } } });
    await run(routeSrc, { world: w2, context: ctx('issue_comment', approvedBy(w2.state.issues[5])) });
    check('already-targeted spec PR merges without a retarget',
      w2.state.pulls[0].merged_base === 'factory/epic-5' && !w2.state.log.some(l => l.startsWith('retarget')), w2.state.log);

    // G2 on an epic whose spec merged to the default branch (no epic branch
    // yet) adopts it too: the branch is cut from the default branch, which
    // carries that merged spec, and the design PR is retargeted onto it. No
    // task PR can have merged yet — tasks are dispatched only after G2.
    const w3 = makeWorld({ files: filesEpics, branches: ['main'],
      pulls: [{ number: 9, head: { ref: 'factory/5-design' }, base: { ref: 'main' } }],
      issues: { 5: { number: 5, title: 'Epic', labels: [{ name: 'factory:design-ready' }], user: { type: 'User' } } } });
    const out3 = await run(routeSrc, { world: w3, context: ctx('issue_comment', approvedBy(w3.state.issues[5])) });
    check('G2 -> dispatch', out3.role === 'dispatch', out3);
    check('G2 adopts an epic whose spec merged to the default branch',
      w3.state.pulls[0].merged_base === 'factory/epic-5' && w3.state.branches.includes('factory/epic-5'), w3.state.log);

    // The gate is also reachable by a human merging the document PR
    // themselves, which leaves nothing open to retarget. Adoption used to
    // hang off that PR, so this route silently condemned the epic to legacy
    // routing and every task PR it later opened went to the integration
    // branch instead of the epic branch.
    const w3b = makeWorld({ files: filesEpics, branches: ['main'], pulls: [],
      issues: { 5: { number: 5, title: 'Epic', labels: [{ name: 'factory:spec-ready' }], user: { type: 'User' } } } });
    const out3b = await run(routeSrc, { world: w3b, context: ctx('issue_comment', approvedBy(w3b.state.issues[5])) });
    check('a hand-merged gate document still adopts the epic',
      out3b.role === 'planner' && w3b.state.branches.includes('factory/epic-5'), w3b.state.log);

    // G2 on an adopted epic (epic branch exists): a design PR aimed at main is
    // retargeted onto the epic branch before merging.
    const w4 = makeWorld({ files: filesEpics, branches: ['main', 'factory/epic-5'],
      pulls: [{ number: 9, head: { ref: 'factory/5-design' }, base: { ref: 'main' } }],
      issues: { 5: { number: 5, title: 'Epic', labels: [{ name: 'factory:design-ready' }], user: { type: 'User' } } } });
    await run(routeSrc, { world: w4, context: ctx('issue_comment', approvedBy(w4.state.issues[5])) });
    check('design PR follows the existing epic branch',
      w4.state.pulls[0].merged_base === 'factory/epic-5', w4.state.log);

    // Rollback: epics:false retargets an epic-branch-based document PR back to
    // the default branch before merging.
    const w5 = makeWorld({ files: filesOpen, branches: ['main', 'factory/epic-5'],
      pulls: [{ number: 9, head: { ref: 'factory/5-spec' }, base: { ref: 'factory/epic-5' } }],
      issues: { 5: { number: 5, title: 'Epic', labels: [{ name: 'factory:spec-ready' }], user: { type: 'User' } } } });
    await run(routeSrc, { world: w5, context: ctx('issue_comment', approvedBy(w5.state.issues[5])) });
    check('epics:false retargets back to the default branch',
      w5.state.pulls[0].merged_base === 'main', w5.state.log);

    // ...and cuts no epic branch of its own at a gate.
    const w5b = makeWorld({ files: filesOpen, branches: ['main'],
      pulls: [{ number: 9, head: { ref: 'factory/5-design' }, base: { ref: 'main' } }],
      issues: { 5: { number: 5, title: 'Epic', labels: [{ name: 'factory:design-ready' }], user: { type: 'User' } } } });
    await run(routeSrc, { world: w5b, context: ctx('issue_comment', approvedBy(w5b.state.issues[5])) });
    check('epics:false creates no epic branch at a gate',
      !w5b.state.branches.includes('factory/epic-5') && w5b.state.pulls[0].merged_base === 'main', w5b.state.log);

    // Legacy estates (no policy file at all) are byte-for-byte unaffected.
    const w6 = makeWorld({ files: filesOpen, branches: ['main'],
      pulls: [{ number: 9, head: { ref: 'factory/5-spec' }, base: { ref: 'main' } }],
      issues: { 5: { number: 5, title: 'Epic', labels: [{ name: 'factory:spec-ready' }], user: { type: 'User' } } } });
    await run(routeSrc, { world: w6, context: ctx('issue_comment', approvedBy(w6.state.issues[5])) });
    check('no policy file: spec merges to main, nothing retargeted, no branch created',
      w6.state.pulls[0].merged_base === 'main' && w6.state.branches.length === 1, w6.state.log);

    // factory:on-epic is release-managed: an Approved comment there explains
    // itself and routes nothing.
    const w7 = makeWorld({ files: filesEpics, issues: {
      5: { number: 5, title: 'Epic', labels: [{ name: 'factory:on-epic' }], user: { type: 'User' } } } });
    const out7 = await run(routeSrc, { world: w7, context: ctx('issue_comment', approvedBy(w7.state.issues[5])) });
    check('Approved on factory:on-epic routes nothing and explains',
      out7.role === 'none' && (w7.state.comments[5] || []).some(c => c.body.includes('epic branch')), w7.state.log);
  }

  // --------------------------------------------------------------- scenario 21
  console.log('\n21. a cross-repo epic (FACTORY.md §7) — the dispatcher has to run over there');
  {
    // The task lives here; the epic lives in another repo and the body says so.
    // Looking #250 up here found nothing (or an unrelated issue with that
    // number), so the tasks this one unblocks were never released.
    const task = { number: 198, title: 'task(250): contact column',
                   body: 'Part of o/backend#250\n\nChange folder: ...',
                   labels: [], user: { type: 'User' }, state: 'closed' };
    const w = makeWorld({ files: filesOpen, issues: { 198: task } });
    const out = await run(routeSrc, { world: w, context: ctx('issues', { action: 'closed', issue: task }) });
    check('nothing routed in this repo', out.role === 'none', out);
    const said = (w.state.comments[198] || [])[0] || { body: '' };
    check('says the epic is elsewhere', said.body.includes('o/backend#250'), w.state.log);
    check('names the control to use over there',
      said.body.includes('role: `dispatch`, issue `250`'), w.state.log);
    check('and says why it could not do it itself',
      said.body.includes('FACTORY_CROSS_REPO_TOKEN'), w.state.log);

    // The same-repo case is untouched: no comment, dispatch here.
    const w2 = makeWorld({ files: filesOpen, issues: {
      5: { number: 5, title: 'Epic', labels: [{ name: 'factory:design-approved' }], user: { type: 'User' } },
      8: { number: 8, title: 'task(5): step one', body: 'Part of o/r#5',
           labels: [], user: { type: 'User' }, state: 'closed' } } });
    const out2 = await run(routeSrc, { world: w2, context: ctx('issues', { action: 'closed', issue: w2.state.issues[8] }) });
    check('a marker naming this repo dispatches here',
      out2.role === 'dispatch' && out2.issue === '5', out2);
    check('and says nothing', (w2.state.comments[8] || []).length === 0, w2.state.log);
  }

  // --------------------------------------------------------------- scenario 22
  console.log('\n22. expedite (FACTORY.md §4a) — one auto-advance map, not three copies of one');
  {
    // The map has to exist twice in this workflow: the route job decides what
    // an expedited issue does the moment the marker lands, and expedite-chain
    // decides it again after each role finishes. They are different jobs and
    // cannot share a scope, so the only thing standing between them and drift
    // is this check. The Python engine has one copy (router.EXPEDITE_MAP) and
    // is pinned by the conformance fixtures below.
    const mapOf = (src, where) => {
      const m = /const EXPEDITE_MAP = \{([\s\S]*?)\};/.exec(src);
      check(`${where} declares EXPEDITE_MAP`, !!m, where);
      if (!m) return null;
      const out = {};
      for (const line of m[1].split('\n')) {
        const kv = /'([^']+)':\s*'([^']+)'/.exec(line);
        if (kv) out[kv[1]] = kv[2];
      }
      return out;
    };
    const chainJob = doc.jobs['expedite-chain'];
    check('the workflow has an expedite-chain job', !!chainJob, Object.keys(doc.jobs));
    const chainSrc = ((chainJob.steps || []).find(s => (s.with || {}).script) || { with: {} }).with.script || '';
    const routeMap = mapOf(routeSrc, 'the route job');
    const chainMap = mapOf(chainSrc, 'the expedite-chain job');
    check('both copies of the auto-advance map agree',
      JSON.stringify(routeMap) === JSON.stringify(chainMap), { routeMap, chainMap });
    // The two gates expedite must never open. A row here would be a silent
    // licence to ship: GS puts an epic on staging, G3 puts it in production.
    for (const forbidden of ['factory:epic-ready', 'factory:in-staging', 'factory:deployed',
                             'factory:backlog', 'factory:intake']) {
      check(`the map never advances ${forbidden}`,
        routeMap && routeMap[forbidden] === undefined, routeMap);
    }
    // Re-dispatch is the only way this engine can chain, and it needs the PAT.
    check('expedite-chain reads the cross-repo token',
      /CROSS_TOKEN/.test(JSON.stringify(chainJob)), 'no CROSS_TOKEN in expedite-chain');
    check('expedite-chain says so on the issue when the token is missing',
      /factory-expedite-no-token/.test(chainSrc), 'no say-once marker');
    check('expedite-chain only runs after a successful agent job',
      /needs\.agent\.result == 'success'/.test(String(chainJob.if || '')), chainJob.if);
    // architect-chain must survive intact: replacing its in-run chaining with
    // a dispatch would make plain planner→architect need the PAT too.
    check('planner → architect still chains in-run, PAT or no PAT',
      !!doc.jobs['architect-chain'], Object.keys(doc.jobs));
  }

  // ------------------------------------------------------------------ fixtures
  // The JSON conformance fixtures are the canonical routing decision table,
  // shared with the orchestrator's Python router (orchestrator/conformance/).
  // Everything above pins workflow-specific mechanics (YAML job conditions,
  // marker steps); the fixtures pin the routing decisions any engine must
  // reproduce. Both run here so a routing change cannot land without the
  // fixture set moving with it.
  await runFixtures();

  console.log(failures ? `\n${failures} FAILURE(S)` : '\nall scenarios pass');
  process.exit(failures ? 1 : 0);
})();

function fixtureWorld(fx) {
  const CONFIG_PATHS = {
    release: '.github/factory-release.json',
    approvers: '.github/factory-approvers.json',
    orchestrator: '.github/factory-orchestrator.json',
    branches: '.github/factory-branches.json',
  };
  const files = {};
  for (const [key, p] of Object.entries(CONFIG_PATHS)) {
    const v = (fx.config || {})[key];
    if (v === undefined) continue;
    files[p] = v === 'invalid-json' ? '{not json' : JSON.stringify(v);
  }
  const milestones = {};
  for (const m of (fx.repo || {}).milestones || []) {
    milestones[m.number] = { number: m.number, title: m.title, html_url: m.htmlUrl || 'u' };
  }
  const msObj = (n) => (n == null ? null
    : milestones[n] || (milestones[n] = { number: n, title: `ms${n}`, html_url: 'u' }));
  const issues = {}, comments = {};
  for (const i of (fx.repo || {}).issues || []) {
    issues[i.number] = {
      number: i.number,
      title: i.title,
      body: i.body || '',
      labels: (i.labels || []).map(name => ({ name })),
      user: { type: i.authorType || 'User' },
      state: i.state || 'open',
      milestone: msObj(i.milestone),
      pull_request: i.isPullRequest ? {} : undefined,
    };
    if (i.comments && i.comments.length) comments[i.number] = i.comments.map(c => ({ body: c.body }));
  }
  return { world: makeWorld({ files, issues, comments }), msObj };
}

function fixtureContext(fx, world, msObj) {
  const ev = fx.event;
  const iss = (n) => world.state.issues[n];
  if (ev.name === 'issues') {
    const payload = { action: ev.action, issue: iss(ev.issue) };
    if (ev.label !== undefined) payload.label = { name: ev.label };
    if (ev.sender !== undefined) {
      payload.sender = { login: ev.sender, type: ev.senderType || 'User' };
    }
    if (ev.milestone !== undefined) payload.milestone = msObj(ev.milestone);
    return ctx('issues', payload);
  }
  if (ev.name === 'issue_comment') {
    return ctx('issue_comment', {
      action: ev.action,
      issue: iss(ev.issue),
      comment: {
        body: ev.comment.body,
        user: { login: ev.comment.login, type: ev.comment.authorType || 'User' },
        author_association: ev.comment.authorAssociation || 'NONE',
      },
    });
  }
  if (ev.name === 'milestone') return ctx('milestone', { action: ev.action, milestone: msObj(ev.milestone) });
  if (ev.name === 'push') return ctx('push', { ref: ev.ref, repository: { default_branch: ev.defaultBranch } });
  if (ev.name === 'workflow_dispatch') return ctx('workflow_dispatch', {}, { DISPATCH_ROLE: ev.role, DISPATCH_ISSUE: ev.issue });
  throw new Error(`unknown event ${ev.name}`);
}

function assertExpect(name, fx, expect, world, outputs, baseline, chainOut) {
  const L = (n) => (world.state.issues[n] ? world.state.issues[n].labels.map(l => l.name || l) : []);
  if (expect.role !== undefined) check(`${name}: role=${expect.role}`, outputs.role === expect.role, outputs);
  if (expect.issues !== undefined) {
    check(`${name}: issues=${JSON.stringify(expect.issues)}`, outputs.issues === JSON.stringify(expect.issues), outputs);
  }
  if (expect.releaseIssue !== undefined) {
    check(`${name}: releaseIssue=${JSON.stringify(expect.releaseIssue)}`,
      String(outputs.release_issue || '') === expect.releaseIssue, outputs);
  }
  for (const [n, want] of Object.entries(expect.labels || {})) {
    for (const l of want.has || []) check(`${name}: #${n} has ${l}`, L(Number(n)).includes(l), L(Number(n)));
    for (const l of want.not || []) check(`${name}: #${n} not ${l}`, !L(Number(n)).includes(l), L(Number(n)));
  }
  for (const [n, want] of Object.entries(expect.comments || {})) {
    const before = baseline[n] || 0;
    const fresh = (world.state.comments[n] || []).slice(before);
    if (want.count !== undefined) check(`${name}: #${n} ${want.count} new comment(s)`, fresh.length === want.count, fresh.map(c => c.body.slice(0, 60)));
    if (want.countAtLeast !== undefined) check(`${name}: #${n} >=${want.countAtLeast} new comment(s)`, fresh.length >= want.countAtLeast, fresh.length);
    for (const s of want.contains || []) {
      check(`${name}: #${n} comment contains ${JSON.stringify(s.slice(0, 40))}`,
        fresh.some(c => c.body.includes(s)), fresh.map(c => c.body.slice(0, 80)));
    }
    for (const s of want.notContains || []) {
      check(`${name}: #${n} comment omits ${JSON.stringify(s.slice(0, 40))}`,
        !fresh.some(c => c.body.includes(s)), fresh.map(c => c.body.slice(0, 80)));
    }
  }
  if (expect.createdCount !== undefined) {
    check(`${name}: created ${expect.createdCount} issue(s)`, world.state.created.length === expect.createdCount,
      world.state.created.map(i => i.title));
  }
  (expect.createdIssues || []).forEach((want, idx) => {
    const got = world.state.created[idx];
    check(`${name}: created[${idx}] exists`, !!got, world.state.created.map(i => i.title));
    if (!got) return;
    if (want.titlePattern) check(`${name}: created[${idx}] title ~ ${want.titlePattern}`, new RegExp(want.titlePattern).test(got.title), got.title);
    for (const l of want.labels || []) check(`${name}: created[${idx}] labelled ${l}`, got.labels.some(x => (x.name || x) === l), got.labels);
    for (const s of want.bodyContains || []) check(`${name}: created[${idx}] body has ${JSON.stringify(s.slice(0, 40))}`, (got.body || '').includes(s), got.body);
  });
  if (expect.chainIssues !== undefined) {
    check(`${name}: chain issues=${JSON.stringify(expect.chainIssues)}`,
      chainOut && chainOut.issues === JSON.stringify(expect.chainIssues), chainOut);
  }
  if (expect.chainCount !== undefined) {
    check(`${name}: chain count=${expect.chainCount}`, chainOut && chainOut.count === expect.chainCount, chainOut);
  }
}

async function runFixtures() {
  const dir = path.join(__dirname, '..', 'orchestrator', 'conformance', 'fixtures');
  if (!fs.existsSync(dir)) { console.log('\n(no conformance fixtures directory - skipping)'); return; }
  const names = fs.readdirSync(dir).filter(f => f.endsWith('.json')).sort();
  console.log(`\n--- conformance fixtures (${names.length}) ---`);
  for (const file of names) {
    const fx = JSON.parse(fs.readFileSync(path.join(dir, file), 'utf8'));
    const { world, msObj } = fixtureWorld(fx);
    const baseline = {};
    for (const [n, cs] of Object.entries(world.state.comments)) baseline[n] = cs.length;
    const context = fixtureContext(fx, world, msObj);
    const outputs = await run(routeSrc, { world, context });
    let chainOut = null;
    if (fx.chain === 'release') {
      const rel = String(outputs.release_issue || (fx.expect || {}).releaseIssue || '');
      chainOut = await run(relSrc, { world, context: { ...ctx('x', {}), __env: { RELEASE_ISSUE: rel } } });
    }
    assertExpect(fx.name, fx, fx.expect || {}, world, outputs, baseline, chainOut);
    if (fx.repeatEvent) {
      const baseline2 = {};
      for (const [n, cs] of Object.entries(world.state.comments)) baseline2[n] = cs.length;
      const context2 = fixtureContext(fx, world, msObj);
      const outputs2 = await run(routeSrc, { world, context: context2 });
      let chainOut2 = null;
      if (fx.chain === 'release') {
        const rel = String(outputs2.release_issue || (fx.expect || {}).releaseIssue || '');
        chainOut2 = await run(relSrc, { world, context: { ...ctx('x', {}), __env: { RELEASE_ISSUE: rel } } });
      }
      assertExpect(`${fx.name} (2nd)`, fx, fx.expectSecond || {}, world, outputs2, baseline2, chainOut2);
    }
  }
}
