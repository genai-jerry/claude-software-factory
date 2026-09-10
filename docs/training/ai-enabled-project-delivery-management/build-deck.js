// Builds AI-Enabled-Project-Delivery-Management.pptx
// Run: node build-deck.js
const pptxgen = require("pptxgenjs");

let icons = null;
try {
  const R = require("react");
  const RDS = require("react-dom/server");
  const Fi = require("react-icons/fi");
  const sharp = require("sharp");
  icons = { R, RDS, Fi, sharp };
} catch (e) {
  console.warn("icons unavailable:", e.message);
}

// ---------- palette (from the factory's own diagrams) ----------
const C = {
  teal: "0B6E6B",
  tealDark: "0A3B39",
  ink: "0F1A1C",
  slate: "3A464B",
  grey: "9FADB1",
  mist: "DFEDEC",
  soft: "F4F6F6",
  white: "FFFFFF",
  orange: "B24A17",
  orangeSoft: "FAEDE4",
  red: "A33526",
  redSoft: "F5E6E3",
};
const HFONT = "Cambria";
const BFONT = "Calibri";

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE"; // 13.33 x 7.5
pres.author = "GenAI People";
pres.title = "AI-Enabled Project & Delivery Management";

const W = 13.33;
let slideNo = 0;

// ---------- icon helper ----------
const iconCache = {};
async function icon(name, color = C.teal) {
  if (!icons) return null;
  const key = name + color;
  if (iconCache[key]) return iconCache[key];
  const Cmp = icons.Fi[name];
  if (!Cmp) return null;
  const svg = icons.RDS.renderToStaticMarkup(
    icons.R.createElement(Cmp, { color: "#" + color, size: 256, strokeWidth: 1.75 })
  );
  const buf = await icons.sharp(Buffer.from(svg)).png().toBuffer();
  const data = "image/png;base64," + buf.toString("base64");
  iconCache[key] = data;
  return data;
}

// ---------- primitives ----------
function footer(slide, dark) {
  slideNo++;
  if (slideNo === 1) return;
  slide.addText("AI-Enabled Project & Delivery Management  ·  GenAI People", {
    x: 0.6, y: 7.02, w: 8, h: 0.3, fontFace: BFONT, fontSize: 9,
    color: dark ? C.grey : C.grey, isTextBox: true, margin: 0,
  });
  slide.addText(String(slideNo), {
    x: 12.13, y: 7.02, w: 0.6, h: 0.3, fontFace: BFONT, fontSize: 9, align: "right",
    color: C.grey, isTextBox: true, margin: 0,
  });
}

function header(slide, title, kicker, opts = {}) {
  const dark = !!opts.dark;
  if (kicker) {
    slide.addText(kicker.toUpperCase(), {
      x: 0.6, y: 0.38, w: 12, h: 0.3, fontFace: BFONT, fontSize: 11, bold: true,
      color: dark ? C.mist : C.orange, charSpacing: 2, isTextBox: true, margin: 0,
    });
  }
  slide.addText(title, {
    x: 0.6, y: kicker ? 0.66 : 0.45, w: 12.1, h: 0.85, fontFace: HFONT, fontSize: 30, bold: true,
    color: dark ? C.white : C.ink, isTextBox: true, margin: 0, valign: "middle",
  });
}

function chip(slide, text, x, y, opts = {}) {
  const w = opts.w || Math.max(0.9, text.length * 0.085 + 0.35);
  const h = opts.h || 0.32;
  slide.addShape(pres.ShapeType.roundRect, {
    x, y, w, h, fill: { color: opts.fill || C.mist }, line: { color: opts.line || opts.fill || C.mist, width: 0.5 },
    rectRadius: 0.16,
  });
  slide.addText(text, {
    x, y, w, h, fontFace: opts.mono ? "Courier New" : BFONT, fontSize: opts.fontSize || 10.5, bold: true,
    color: opts.color || C.tealDark, align: "center", valign: "middle", isTextBox: true, margin: 0,
  });
  return w;
}

function card(slide, x, y, w, h, opts = {}) {
  slide.addShape(pres.ShapeType.roundRect, {
    x, y, w, h, fill: { color: opts.fill || C.soft }, line: { color: opts.fill || C.soft, width: 0 }, rectRadius: 0.12,
    shadow: opts.shadow ? { type: "outer", color: "000000", blur: 6, offset: 2, angle: 90, opacity: 0.12 } : undefined,
  });
  let ty = y + 0.18;
  if (opts.title) {
    slide.addText(opts.title, {
      x: x + 0.22, y: ty, w: w - 0.44, h: opts.titleH || 0.4, fontFace: HFONT, fontSize: opts.titleSize || 15, bold: true,
      color: opts.titleColor || C.teal, isTextBox: true, margin: 0, valign: "top",
    });
    ty += (opts.titleH || 0.4) + 0.05;
  }
  if (opts.body) {
    const body = Array.isArray(opts.body) && typeof opts.body[0] === "string"
      ? opts.body.map((t, i, a) => ({ text: t, options: { bullet: { indent: 12 }, breakLine: i < a.length - 1, paraSpaceAfter: 4 } }))
      : opts.body;
    slide.addText(body, {
      x: x + 0.22, y: ty, w: w - 0.44, h: y + h - ty - 0.15, fontFace: BFONT, fontSize: opts.bodySize || 11.5,
      color: opts.bodyColor || C.slate, isTextBox: true, margin: 0, valign: "top",
    });
  }
}

function bullets(slide, items, x, y, w, h, opts = {}) {
  const arr = items.map((t, i) => {
    if (typeof t === "object" && t.head) {
      return [
        { text: t.head + "  ", options: { bold: true, color: opts.headColor || C.ink, bullet: { indent: 14 }, paraSpaceAfter: opts.gap || 6 } },
        { text: t.text, options: { breakLine: i < items.length - 1, paraSpaceAfter: opts.gap || 6 } },
      ];
    }
    return { text: t, options: { bullet: { indent: 14 }, breakLine: i < items.length - 1, paraSpaceAfter: opts.gap || 6 } };
  }).flat();
  slide.addText(arr, {
    x, y, w, h, fontFace: BFONT, fontSize: opts.fontSize || 13, color: opts.color || C.slate,
    isTextBox: true, margin: 0, valign: "top",
  });
}

function stat(slide, x, y, w, big, label, opts = {}) {
  slide.addText(big, {
    x, y, w, h: 0.9, fontFace: HFONT, fontSize: opts.size || 44, bold: true, color: opts.color || C.teal,
    isTextBox: true, margin: 0, align: opts.align || "left", valign: "bottom",
  });
  slide.addText(label, {
    x, y: y + 0.92, w, h: 0.5, fontFace: BFONT, fontSize: 11.5, color: opts.labelColor || C.slate,
    isTextBox: true, margin: 0, align: opts.align || "left", valign: "top",
  });
}

function arrowRight(slide, x, y, w = 0.3, color = C.grey) {
  slide.addShape(pres.ShapeType.rightArrow, { x, y, w, h: 0.22, fill: { color }, line: { color, width: 0 } });
}

async function iconCircle(slide, name, x, y, d = 0.6, opts = {}) {
  slide.addShape(pres.ShapeType.ellipse, {
    x, y, w: d, h: d, fill: { color: opts.fill || C.mist }, line: { color: opts.fill || C.mist, width: 0 },
  });
  const data = await icon(name, opts.color || C.teal);
  if (data) slide.addImage({ data, x: x + d * 0.24, y: y + d * 0.24, w: d * 0.52, h: d * 0.52 });
}

// Agenda slide: time blocks
function agenda(slide, day, theme, blocks, tocModules) {
  header(slide, `Day ${day} — ${theme}`, `Day ${day} agenda · 4 hours` + (tocModules.kicker ? ` · ${tocModules.kicker}` : ""));
  // left: timeline
  let y = 1.75;
  const rowH = 0.62;
  blocks.forEach((b, i) => {
    const isLab = /lab|hands-on/i.test(b.title);
    slide.addText(b.time, {
      x: 0.6, y, w: 1.15, h: rowH, fontFace: BFONT, fontSize: 11, bold: true, color: C.grey,
      isTextBox: true, margin: 0, valign: "middle",
    });
    slide.addShape(pres.ShapeType.roundRect, {
      x: 1.8, y: y + 0.06, w: 6.5, h: rowH - 0.12, fill: { color: isLab ? C.orangeSoft : C.soft },
      line: { color: isLab ? C.orangeSoft : C.soft, width: 0 }, rectRadius: 0.1,
    });
    slide.addText([
      { text: b.title, options: { bold: true, color: isLab ? C.orange : C.ink, fontSize: 12.5 } },
      { text: b.sub ? "   " + b.sub : "", options: { color: C.slate, fontSize: 11 } },
    ], {
      x: 1.98, y: y + 0.06, w: 6.2, h: rowH - 0.12, fontFace: BFONT, isTextBox: true, margin: 0, valign: "middle",
    });
    y += rowH + 0.04;
  });
  // right: ToC coverage + factory thread
  card(slide, 8.7, 1.75, 4.05, 2.2, {
    title: "Client ToC modules covered", titleSize: 13,
    body: tocModules.covered, bodySize: 11,
  });
  card(slide, 8.7, 4.15, 4.05, 2.55, {
    title: "Software Factory thread", titleSize: 13, fill: C.mist, titleColor: C.tealDark,
    body: tocModules.factory, bodySize: 11, bodyColor: C.tealDark,
  });
}

// Lab slide
async function labSlide(slide, day, title, labs, deliverable, closing) {
  header(slide, title, `Day ${day} · hands-on exercise`);
  let x = 0.6;
  const w = labs.length === 1 ? 8.0 : (8.1 - 0.3 * (labs.length - 1)) / labs.length;
  for (const l of labs) {
    card(slide, x, 1.75, w, 3.1, { title: l.title, titleH: 0.62, body: l.steps, bodySize: 12, shadow: true, fill: C.white });
    x += w + 0.3;
  }
  slide.addShape(pres.ShapeType.roundRect, { x: 0.6, y: 5.1, w: 8.1, h: 1.25, fill: { color: C.orangeSoft }, line: { color: C.orangeSoft, width: 0 }, rectRadius: 0.12 });
  await iconCircle(slide, "FiFlag", 0.8, 5.32, 0.5, { fill: C.white, color: C.orange });
  slide.addText([
    { text: "Deliverable  ", options: { bold: true, color: C.orange } },
    { text: deliverable, options: { color: C.slate } },
  ], { x: 1.45, y: 5.2, w: 7.1, h: 1.05, fontFace: BFONT, fontSize: 12.5, isTextBox: true, margin: 0, valign: "middle" });

  slide.addShape(pres.ShapeType.roundRect, { x: 9.0, y: 1.75, w: 3.75, h: 4.6, fill: { color: C.ink }, line: { color: C.ink, width: 0 }, rectRadius: 0.12 });
  await iconCircle(slide, "FiMessageCircle", 9.3, 2.0, 0.55, { fill: C.teal, color: C.white });
  slide.addText("Closing round", { x: 9.3, y: 2.7, w: 3.2, h: 0.4, fontFace: HFONT, fontSize: 15, bold: true, color: C.white, isTextBox: true, margin: 0 });
  slide.addText(closing, { x: 9.3, y: 3.15, w: 3.2, h: 3.4, fontFace: BFONT, fontSize: 12.5, color: C.mist, isTextBox: true, margin: 0, valign: "top", italic: true });
}

(async () => {
  // =====================================================================
  // 1. Title
  // =====================================================================
  {
    const s = pres.addSlide();
    s.background = { color: C.ink };
    s.addShape(pres.ShapeType.ellipse, { x: 8.9, y: -1.6, w: 6.5, h: 6.5, fill: { color: C.tealDark }, line: { color: C.tealDark, width: 0 } });
    s.addShape(pres.ShapeType.ellipse, { x: 10.4, y: 0.2, w: 3.6, h: 3.6, fill: { color: C.teal }, line: { color: C.teal, width: 0 } });
    chip(s, "factory:intake", 10.9, 1.7, { fill: C.white, color: C.tealDark, mono: true, fontSize: 10 });
    chip(s, "factory:spec-ready", 9.5, 2.35, { fill: C.mist, color: C.tealDark, mono: true, fontSize: 10 });
    chip(s, "factory:deployed", 10.6, 3.0, { fill: C.orangeSoft, color: C.orange, mono: true, fontSize: 10 });
    s.addText("CORPORATE TRAINING PROGRAM  ·  20 HOURS  ·  5 HALF-DAYS", {
      x: 0.7, y: 1.6, w: 8, h: 0.35, fontFace: BFONT, fontSize: 12, bold: true, color: C.mist, charSpacing: 2, isTextBox: true, margin: 0,
    });
    s.addText("AI-Enabled Project & Delivery Management", {
      x: 0.7, y: 2.0, w: 8.6, h: 1.9, fontFace: HFONT, fontSize: 46, bold: true, color: C.white, isTextBox: true, margin: 0, valign: "middle",
    });
    s.addText("Generative AI, predictive analytics and automation for experienced Project and Delivery Managers — with the Software Factory, an agent-driven delivery pipeline, as the running case.", {
      x: 0.7, y: 4.0, w: 8.2, h: 1.1, fontFace: BFONT, fontSize: 16, color: C.mist, isTextBox: true, margin: 0, valign: "top",
    });
    s.addText([
      { text: "GenAI People", options: { bold: true, color: C.white } },
      { text: "  ·  Jerry Kurian  ·  genaipeople.com", options: { color: C.grey } },
    ], { x: 0.7, y: 6.3, w: 8, h: 0.4, fontFace: BFONT, fontSize: 13, isTextBox: true, margin: 0 });
    s.addText("Prepared for Gynosis Information Technology Pvt. Ltd. · Client: UST", {
      x: 0.7, y: 6.7, w: 8, h: 0.35, fontFace: BFONT, fontSize: 11, color: C.grey, isTextBox: true, margin: 0,
    });
    footer(s, true);
    s.addNotes("Opening: this program is built for PMs who already run delivery well and need to run it with AI — both using AI in their own work and governing delivery where agents do most of the work.");
  }

  // =====================================================================
  // 2. The shift
  // =====================================================================
  {
    const s = pres.addSlide();
    header(s, "The Project Manager's job is changing — twice", "Why this program");
    bullets(s, [
      { head: "First shift: AI in the PM's own work.", text: "Charters, estimates, risk registers, status reports and stakeholder updates are now drafted in minutes. The skill moves from writing to reviewing." },
      { head: "Second shift: AI doing the delivery.", text: "Agents now spec, plan, design, implement, review and test. The PM stops coordinating hand-offs and starts holding gates." },
      { head: "What does not change.", text: "Scope, trade-offs, accountability, relationships, and the decision to ship. These get more valuable, not less." },
      { head: "The program teaches both halves,", text: "with hands-on labs every day and a real agent-driven pipeline on Days 4 and 5." },
    ], 0.6, 1.8, 6.6, 4.9, { fontSize: 14, gap: 12 });

    // right: three levels
    const levels = [
      ["FiEdit3", "Assistant", "Drafts for you. You paste context in, you copy the output out. Day 1.", C.soft, C.teal],
      ["FiCpu", "Copilot", "Works inside your tools — tracker, chat, spreadsheet, IDE. Days 2 and 3.", C.mist, C.teal],
      ["FiGitMerge", "Agent", "Does the work end to end. You approve at gates. Days 4 and 5.", C.ink, C.white],
    ];
    let y = 1.8;
    for (const [ic, t, d, fill, col] of levels) {
      s.addShape(pres.ShapeType.roundRect, { x: 7.7, y, w: 5.05, h: 1.45, fill: { color: fill }, line: { color: fill, width: 0 }, rectRadius: 0.12 });
      await iconCircle(s, ic, 7.9, y + 0.4, 0.65, { fill: fill === C.ink ? C.teal : C.white, color: fill === C.ink ? C.white : C.teal });
      s.addText(t, { x: 8.75, y: y + 0.2, w: 3.8, h: 0.4, fontFace: HFONT, fontSize: 16, bold: true, color: col, isTextBox: true, margin: 0 });
      s.addText(d, { x: 8.75, y: y + 0.6, w: 3.85, h: 0.75, fontFace: BFONT, fontSize: 11.5, color: fill === C.ink ? C.mist : C.slate, isTextBox: true, margin: 0, valign: "top" });
      y += 1.62;
    }
    footer(s);
  }

  // =====================================================================
  // 3. Program at a glance
  // =====================================================================
  {
    const s = pres.addSlide();
    header(s, "Five half-days, one running case", "Program at a glance");
    const days = [
      ["1", "GenAI for the PM", "Foundations · forecasting · risk", ["Intro to GenAI in PM", "Forecasting & risk", "Lab: plan + forecast"]],
      ["2", "Automation & reporting", "Workflows · status · comms", ["AI automation", "AI reporting", "Lab: automated status"]],
      ["3", "Tools & integration", "Landscape · integration · monitoring", ["Modern PM tools", "Collaboration tools", "Monitoring", "Lab: tool integration"]],
      ["4", "AI-driven delivery", "The Software Factory operating model", ["Future of PM", "Delivery best practices", "Managing Gen AI projects", "Lab: run an epic"]],
      ["5", "Capstone & certification", "Case study · capstone · 30-60-90", ["Case study", "Capstone (teams)", "Conclusion & certificate"]],
    ];
    let x = 0.6;
    const w = 2.32;
    for (const [n, t, sub, items] of days) {
      const isFactory = n === "4";
      s.addShape(pres.ShapeType.roundRect, { x, y: 1.8, w, h: 4.15, fill: { color: isFactory ? C.ink : C.soft }, line: { color: isFactory ? C.ink : C.soft, width: 0 }, rectRadius: 0.12 });
      s.addText(n, { x: x + 0.2, y: 1.9, w: 1, h: 0.8, fontFace: HFONT, fontSize: 40, bold: true, color: isFactory ? C.white : C.teal, isTextBox: true, margin: 0 });
      s.addText("4 h", { x: x + w - 0.8, y: 2.0, w: 0.6, h: 0.3, fontFace: BFONT, fontSize: 11, bold: true, color: C.grey, isTextBox: true, margin: 0, align: "right" });
      s.addText(t, { x: x + 0.2, y: 2.75, w: w - 0.4, h: 0.6, fontFace: HFONT, fontSize: 15, bold: true, color: isFactory ? C.white : C.ink, isTextBox: true, margin: 0, valign: "top" });
      s.addText(sub, { x: x + 0.2, y: 3.35, w: w - 0.4, h: 0.5, fontFace: BFONT, fontSize: 10.5, italic: true, color: isFactory ? C.mist : C.grey, isTextBox: true, margin: 0, valign: "top" });
      s.addText(items.map((it, i) => ({ text: it, options: { bullet: { indent: 10 }, breakLine: i < items.length - 1, paraSpaceAfter: 4 } })), {
        x: x + 0.2, y: 3.9, w: w - 0.35, h: 1.95, fontFace: BFONT, fontSize: 11, color: isFactory ? C.mist : C.slate, isTextBox: true, margin: 0, valign: "top",
      });
      x += w + 0.16;
    }
    s.addText([
      { text: "Every day: ", options: { bold: true, color: C.ink } },
      { text: "three 50-minute teaching-and-demo blocks, one 60–90-minute lab, a closing round. ", options: { color: C.slate } },
      { text: "Every module ", options: { bold: true, color: C.ink } },
      { text: "ties back to the Software Factory so the concepts are seen running, not just described.", options: { color: C.slate } },
    ], { x: 0.6, y: 6.15, w: 12.1, h: 0.7, fontFace: BFONT, fontSize: 12.5, isTextBox: true, margin: 0, valign: "middle" });
    footer(s);
  }

  // =====================================================================
  // 4. Audience + how we teach
  // =====================================================================
  {
    const s = pres.addSlide();
    header(s, "Built for senior delivery practitioners", "Audience and format");
    stat(s, 0.6, 1.7, 2.6, "20 h", "five half-days of 4–4.5 hours, online, recorded");
    stat(s, 3.4, 1.7, 2.6, "8", "hands-on labs, one every half-day or more");
    stat(s, 6.2, 1.7, 2.6, "1", "capstone: a full AI-enabled delivery plan, presented");
    stat(s, 9.0, 1.7, 3.6, "12–20", "participants per batch; capstone teams of 3–4");

    card(s, 0.6, 3.7, 5.9, 2.7, {
      title: "Who it is for",
      body: [
        "Career Grade 4–6 Project and Delivery Managers",
        "12–18 years total experience, 5–6 in project / delivery management",
        "Running agile or hybrid delivery with Jira, Azure DevOps or GitHub",
        "No coding required — labs are browser, spreadsheet and guided templates",
      ], bodySize: 13,
    });
    card(s, 6.8, 3.7, 5.95, 2.7, {
      title: "How it is taught", fill: C.mist, titleColor: C.tealDark,
      body: [
        "Concept → live demo → lab on participants' own data or a sandbox",
        "Sandbox GitHub organisation with the Software Factory pre-installed",
        "Participants sit in the approver seats on Days 4–5 and open real gates",
        "Assessment: capstone 60% + scenario quiz 40% → certificate of completion",
      ], bodySize: 13, bodyColor: C.tealDark,
    });
    footer(s);
  }

  // =====================================================================
  // 5. Business outcomes mapping
  // =====================================================================
  {
    const s = pres.addSlide();
    header(s, "Every expected business outcome has a module and a proof", "Business outcomes");
    const rows = [
      ["Improved project delivery predictability", "Day 1 forecasting · Day 4 small batches, staging first, release gating", "P50 / P85 forecast on real data; sequenced release plan"],
      ["Faster and more accurate project reporting", "Day 2 reporting from the system of record · Day 3 monitoring", "A working automated status report posted to Teams / Slack"],
      ["Reduced risk exposure through AI-driven forecasting", "Day 1 risk mining and early-warning signals · Day 4 independent review, gates", "AI-mined risk register with exposure and signals"],
      ["Increased productivity through workflow automation", "Day 2 automation · Day 3 integration · Day 4 agents doing the work", "Automation built in the lab; an epic run end-to-end by agents"],
      ["Better resource utilisation and governance", "Day 3 flow metrics · Day 4 gates, approvers, guardrails, model routing", "Governance design in the capstone"],
      ["Readiness to manage AI-driven business initiatives", "Day 4 managing Gen AI projects · Day 5 capstone", "Capstone delivery plan and personal 30-60-90 plan"],
    ];
    const hdr = ["Expected business outcome", "Where it is built", "Evidence at the end"];
    const tbl = [hdr.map(h => ({ text: h, options: { bold: true, color: C.white, fill: { color: C.teal }, fontSize: 12 } }))];
    rows.forEach((r, i) => tbl.push(r.map((c, j) => ({ text: c, options: { bold: j === 0, color: j === 0 ? C.ink : C.slate, fill: { color: i % 2 ? C.white : C.soft }, fontSize: 11.5 } }))));
    s.addTable(tbl, { x: 0.6, y: 1.75, w: 12.1, colW: [3.6, 4.7, 3.8], fontFace: BFONT, border: { type: "solid", color: C.white, pt: 1 }, rowH: 0.6, valign: "middle", margin: 0.08 });
    footer(s);
  }

  // =====================================================================
  // 6. The running case: Software Factory
  // =====================================================================
  {
    const s = pres.addSlide();
    header(s, "The running case: the Software Factory", "An agent-driven delivery pipeline · open source, MIT");
    s.addText("A plain GitHub issue goes in. A specced, planned, designed, implemented, reviewed, tested and released change comes out — with human approval gates, and no ability for an agent to put anything on main.", {
      x: 0.6, y: 1.65, w: 12.1, h: 0.85, fontFace: HFONT, fontSize: 16, italic: true, color: C.tealDark, isTextBox: true, margin: 0, valign: "top",
    });
    const roles = ["scrum", "intake", "planner", "architect", "dispatch", "implementer", "reviewer", "qa", "release", "ops"];
    const outs = ["release plan", "proposal + specs", "tasks.md", "design.md", "ready tasks", "PR per task", "line review", "tests green", "staging → main", "verify, archive"];
    const cw = 1.16, gap = 0.06; let x = 0.6;
    roles.forEach((r, i) => {
      s.addShape(pres.ShapeType.chevron, { x, y: 2.85, w: cw + 0.1, h: 0.75, fill: { color: i % 2 ? C.teal : C.tealDark }, line: { color: C.white, width: 1 } });
      s.addText(r, { x: x + 0.3, y: 2.85, w: cw - 0.18, h: 0.75, fontFace: BFONT, fontSize: 9, bold: true, color: C.white, align: "center", valign: "middle", isTextBox: true, margin: 0 });
      s.addText(outs[i], { x: x - 0.05, y: 3.65, w: cw + 0.2, h: 0.5, fontFace: BFONT, fontSize: 9.5, color: C.slate, align: "center", isTextBox: true, margin: 0, valign: "top" });
      x += cw + gap;
    });
    // gates
    const gates = [["G0", "release scope", 0.9], ["G1", "spec", 2.4], ["G2", "design", 4.3], ["GS", "to staging", 9.7], ["G3", "to production", 11.2]];
    s.addText("Human gates", { x: 0.6, y: 4.3, w: 3, h: 0.3, fontFace: BFONT, fontSize: 11, bold: true, color: C.orange, isTextBox: true, margin: 0 });
    for (const [g, l, gx] of gates) {
      s.addShape(pres.ShapeType.ellipse, { x: gx, y: 4.65, w: 0.55, h: 0.55, fill: { color: C.orange }, line: { color: C.orange, width: 0 } });
      s.addText(g, { x: gx, y: 4.65, w: 0.55, h: 0.55, fontFace: BFONT, fontSize: 11, bold: true, color: C.white, align: "center", valign: "middle", isTextBox: true, margin: 0 });
      s.addText(l, { x: gx - 0.5, y: 5.22, w: 1.55, h: 0.3, fontFace: BFONT, fontSize: 10, color: C.slate, align: "center", isTextBox: true, margin: 0 });
    }
    s.addText("Everything between the gates runs unattended. Only GS and G3 can never be delegated: they are the moments something leaves the factory's own branches.", {
      x: 5.1, y: 4.3, w: 4.3, h: 1.2, fontFace: BFONT, fontSize: 10.5, color: C.slate, isTextBox: true, margin: 0, valign: "top", italic: true,
    });
    // why it is the case
    card(s, 0.6, 5.7, 12.1, 1.15, {
      fill: C.mist, body: [
        { text: "Why it is the running case: ", options: { bold: true, color: C.tealDark } },
        { text: "the client's six outcomes — predictability, reporting, risk, automation, governance, AI readiness — are exactly what a factory-style pipeline forces you to design for. Participants see every concept of the program running on a real repository, and sit in the approver seats themselves.", options: { color: C.tealDark } },
      ], bodySize: 12,
    });
    footer(s);
    s.addNotes("Built by GenAI People. github.com/genai-jerry/claude-software-factory. Ten roles, five gates. Emphasise: the orchestrator is not an AI — it is a routing job that reads labels. Any human can take over any stage by setting the next label.");
  }

  // =====================================================================
  // 7. Two foundations, one rule
  // =====================================================================
  {
    const s = pres.addSlide();
    header(s, "Two foundations, one rule", "The factory's design principles — and what a PM takes from them");
    const cols = [
      ["FiGitBranch", "GitHub is the state machine", "Milestones are releases; issues, sub-issues and factory:* labels encode where every piece of work is. A label change is what wakes an agent.", "For the PM: reporting becomes a query, not a meeting. Flow metrics come for free. Any human can take over any stage by moving the label."],
      ["FiFileText", "OpenSpec is the content", "What is being built — proposal, WHEN/THEN scenarios, technical design, task checklist — lives in the repo as plain Markdown, versioned with the code.", "For the PM: the artifacts you review at a gate are short documents, not transcripts. Requirements, plan and design are one folder, one history."],
      ["FiLink", "Issues carry state plus a link — never spec content", "Agents read requirements from the change folder, never from the issue body. That is what stops the two sources of truth from drifting.", "For the PM: the single most common cause of delivery failure — the ticket says one thing, the document another — is designed out."],
    ];
    let x = 0.6;
    for (const [ic, t, d, pm] of cols) {
      card(s, x, 1.75, 3.9, 5.0, { fill: C.soft });
      await iconCircle(s, ic, x + 0.25, 1.95, 0.7, { fill: C.white });
      s.addText(t, { x: x + 0.25, y: 2.8, w: 3.4, h: 0.85, fontFace: HFONT, fontSize: 15, bold: true, color: C.ink, isTextBox: true, margin: 0, valign: "top" });
      s.addText(d, { x: x + 0.25, y: 3.65, w: 3.4, h: 1.35, fontFace: BFONT, fontSize: 11.5, color: C.slate, isTextBox: true, margin: 0, valign: "top" });
      s.addShape(pres.ShapeType.roundRect, { x: x + 0.2, y: 5.05, w: 3.5, h: 1.55, fill: { color: C.mist }, line: { color: C.mist, width: 0 }, rectRadius: 0.1 });
      s.addText(pm, { x: x + 0.35, y: 5.12, w: 3.2, h: 1.42, fontFace: BFONT, fontSize: 11, color: C.tealDark, isTextBox: true, margin: 0, valign: "middle" });
      x += 4.1;
    }
    footer(s);
  }

  // =====================================================================
  // DAY 1
  // =====================================================================
  {
    const s = pres.addSlide();
    agenda(s, 1, "Generative AI for the project manager", [
      { time: "0:00 – 1:00", title: "Introduction to Generative AI in PM", sub: "LLMs for PMs · assistant / copilot / agent · prompting patterns" },
      { time: "1:00 – 1:10", title: "Break" },
      { time: "1:10 – 2:25", title: "AI-driven forecasting and risk management", sub: "Throughput, Monte Carlo, risk mining, early-warning signals" },
      { time: "2:25 – 2:35", title: "Break" },
      { time: "2:35 – 3:50", title: "Hands-on: from brief to plan; forecast", sub: "Lab 1A charter / WBS / risks · Lab 1B Monte Carlo" },
      { time: "3:50 – 4:00", title: "Closing round" },
    ], {
      covered: ["Introduction to Generative AI in Project Management", "AI-Driven Project Forecasting and Risk Management", "Hands-On Exercise"],
      factory: ["The Intake Analyst: an agent that stops and asks (factory:blocked) instead of inventing requirements", "The Scrum Master: release scope, sequencing, risks and a GO / NO-GO on the whole milestone before anything starts"],
    });
    footer(s);
  }

  // Day 1 — where GenAI fits
  {
    const s = pres.addSlide();
    header(s, "Where Generative AI fits in the PM lifecycle", "Day 1 · module 1.1 · and where it does not");
    const phases = [
      ["Initiate", ["Charter and business case drafts", "Stakeholder map", "Assumption and question lists"], "Assistant"],
      ["Plan", ["WBS, RACI, schedule skeleton", "Estimate ranges with rationale", "Requirements → acceptance scenarios"], "Assistant → Agent"],
      ["Execute", ["Meeting → decisions and actions", "Change-request summaries", "Agents implementing tasks"], "Copilot → Agent"],
      ["Monitor", ["Status from the system of record", "Forecasts and risk signals", "Attention queue: what needs me"], "Copilot"],
      ["Close", ["Lessons learned from the record", "Archive specs, decisions", "Benefits tracking narrative"], "Assistant"],
    ];
    let x = 0.6;
    for (const [p, items, lvl] of phases) {
      s.addShape(pres.ShapeType.chevron, { x, y: 1.75, w: 2.45, h: 0.6, fill: { color: C.teal }, line: { color: C.white, width: 1 } });
      s.addText(p, { x: x + 0.15, y: 1.75, w: 2.1, h: 0.6, fontFace: BFONT, fontSize: 13, bold: true, color: C.white, align: "center", valign: "middle", isTextBox: true, margin: 0 });
      card(s, x, 2.45, 2.3, 2.7, { fill: C.soft, body: items, bodySize: 11.5 });
      chip(s, lvl, x, 5.25, { w: 2.3, fill: C.mist, fontSize: 10 });
      x += 2.45;
    }
    s.addShape(pres.ShapeType.roundRect, { x: 0.6, y: 5.8, w: 12.1, h: 1.0, fill: { color: C.ink }, line: { color: C.ink, width: 0 }, rectRadius: 0.12 });
    s.addText([
      { text: "Where it does not fit: ", options: { bold: true, color: C.white } },
      { text: "deciding scope, negotiating trade-offs, owning the relationship, and saying yes or no at a gate. The prompting rule that matters most in delivery: ask the model for its questions and assumptions before its answer.", options: { color: C.mist } },
    ], { x: 0.85, y: 5.85, w: 11.6, h: 0.9, fontFace: BFONT, fontSize: 12.5, isTextBox: true, margin: 0, valign: "middle" });
    footer(s);
  }

  // Day 1 — forecasting
  {
    const s = pres.addSlide();
    header(s, "Forecasting: from a date to a probability", "Day 1 · module 1.2 · predictive analytics");
    // native chart: Monte Carlo completion-week distribution
    const weeks = ["W8", "W9", "W10", "W11", "W12", "W13", "W14", "W15", "W16"];
    const probs = [2, 7, 15, 22, 21, 15, 10, 5, 3];
    s.addChart(pres.ChartType.bar, [{ name: "Simulations reaching done (%)", labels: weeks, values: probs }], {
      x: 0.6, y: 1.7, w: 7.2, h: 4.2, barDir: "col",
      chartColors: [C.teal], showTitle: true, title: "Monte Carlo — 10,000 runs on 12 weeks of throughput", titleFontSize: 12, titleColor: C.slate, titleFontFace: BFONT,
      showValue: true, dataLabelPosition: "outEnd", dataLabelFontSize: 9, dataLabelColor: C.slate, dataLabelFontFace: BFONT,
      catAxisLabelColor: C.slate, valAxisLabelColor: C.grey, catAxisLabelFontSize: 10, valAxisLabelFontSize: 9,
      valGridLine: { color: "E3E8EA", size: 0.5 }, catGridLine: { style: "none" }, showLegend: false, valAxisMaxVal: 25,
      catAxisLabelFontFace: BFONT, valAxisLabelFontFace: BFONT,
    });
    chip(s, "P50 · week 12", 1.0, 6.05, { fill: C.mist });
    chip(s, "P85 · week 14", 2.7, 6.05, { fill: C.orangeSoft, color: C.orange });
    s.addText("A sponsor asked for week 11. The honest answer is 24% — and the model can say why.", { x: 4.5, y: 6.0, w: 3.4, h: 0.6, fontFace: BFONT, fontSize: 10.5, italic: true, color: C.slate, isTextBox: true, margin: 0, valign: "middle" });

    bullets(s, [
      { head: "Count things, not points.", text: "Throughput and cycle time forecast better than estimates, and need no re-estimation." },
      { head: "Simulate, then explain.", text: "Monte Carlo in Excel or a guided notebook gives P50 / P85; the LLM turns it into the sponsor conversation." },
      { head: "Stress-test the inputs.", text: "Ask the model for the scenarios that would move the P85 by two weeks — scope churn, WIP, blocked ageing." },
      { head: "Factory tie-in.", text: "Because every stage is a label with a timestamp, the factory produces per-stage cycle-time data by itself. Forecasting an epic is a query." },
    ], 8.2, 1.7, 4.55, 5.0, { fontSize: 12, gap: 10 });
    footer(s);
    s.addNotes("Chart values are illustrative. In the lab, participants use a supplied 12-week throughput dataset or their own Jira/ADO export.");
  }

  // Day 1 — risk + scrum master
  {
    const s = pres.addSlide();
    header(s, "AI-driven risk management: mine it, classify it, watch for it", "Day 1 · module 1.2 · risk");
    card(s, 0.6, 1.75, 5.7, 5.0, {
      title: "Three moves", titleH: 0.45,
      body: [
        { text: "Mine. ", options: { bold: true, color: C.ink } }, { text: "Risks hide in tickets, retros, incident logs and meeting transcripts. An LLM reads all of it and proposes a register with sources cited.", options: { breakLine: true, paraSpaceAfter: 14 } },
        { text: "Classify. ", options: { bold: true, color: C.ink } }, { text: "Probability × impact is still the model; the AI drafts, the PM decides. Pre-mortems generate the risks nobody wants to say aloud.", options: { breakLine: true, paraSpaceAfter: 14 } },
        { text: "Watch. ", options: { bold: true, color: C.ink } }, { text: "Early-warning signals from the system of record: blocked ageing, review-queue depth, re-open rate, scope churn, cycle-time drift. Automate the watch; escalate on threshold.", options: { breakLine: true, paraSpaceAfter: 14 } },
        { text: "Factory tie-in. ", options: { bold: true, color: C.tealDark } }, { text: "The Scrum Master (right) does the first two moves on a whole release before anything starts; the state labels give you the third for free.", options: {} },
      ], bodySize: 13,
    });
    // mock release plan
    s.addShape(pres.ShapeType.roundRect, { x: 6.6, y: 1.75, w: 6.15, h: 5.0, fill: { color: C.white }, line: { color: C.mist, width: 1.5 }, rectRadius: 0.12, shadow: { type: "outer", color: "000000", blur: 6, offset: 2, angle: 90, opacity: 0.1 } });
    chip(s, "factory:release-ready", 6.85, 1.95, { mono: true, fontSize: 10 });
    s.addText("Release plan — release(3): Policy servicing Q4", { x: 6.85, y: 2.35, w: 5.7, h: 0.35, fontFace: HFONT, fontSize: 13, bold: true, color: C.ink, isTextBox: true, margin: 0 });
    s.addText("Posted by the Scrum Master role after reading every issue in the milestone", { x: 6.85, y: 2.68, w: 5.7, h: 0.3, fontFace: BFONT, fontSize: 9.5, italic: true, color: C.grey, isTextBox: true, margin: 0 });
    const plan = [
      ["#41", "Renewal reminders via WhatsApp", "1", "—"],
      ["#42", "Premium recalculation API", "2", "schema first"],
      ["#43", "Agent dashboard", "3", "depends on #42"],
      ["#44", "Bulk import", "—", "oversized: split"],
      ["#45", "Fix date format", "—", "fast-track"],
    ];
    const tbl = [["Issue", "Intent", "Seq", "Concern"].map(h => ({ text: h, options: { bold: true, color: C.white, fill: { color: C.teal }, fontSize: 9.5 } }))];
    plan.forEach((r, i) => tbl.push(r.map((c, j) => ({ text: c, options: { fontSize: 9.5, color: j === 3 && c !== "—" ? C.orange : C.slate, bold: j === 3 && c !== "—", fill: { color: i % 2 ? C.white : C.soft } } }))));
    s.addTable(tbl, { x: 6.85, y: 3.05, w: 5.65, colW: [0.6, 2.5, 0.55, 2.0], fontFace: BFONT, border: { type: "solid", color: C.white, pt: 1 }, rowH: 0.3, margin: 0.04, valign: "middle" });
    s.addText([
      { text: "Risks  ", options: { bold: true, color: C.ink } },
      { text: "1. #42 has no owner for the rate table (ask: actuarial). 2. #43 and an in-flight change overlap on the dashboard module.\n", options: { color: C.slate } },
      { text: "Verdict  ", options: { bold: true, color: C.ink } },
      { text: "GO once #44 is split and #45 leaves the milestone.", options: { color: C.tealDark, bold: true } },
    ], { x: 6.85, y: 5.0, w: 5.65, h: 1.15, fontFace: BFONT, fontSize: 10.5, isTextBox: true, margin: 0, valign: "top" });
    s.addText("AI release planning on the set, not the item: duplicates, sequencing, size and under-specification are caught before a single agent starts. Gate G0 is the human's — or, by config, the agent's own GO.", { x: 6.85, y: 6.15, w: 5.65, h: 0.55, fontFace: BFONT, fontSize: 9.5, italic: true, color: C.grey, isTextBox: true, margin: 0, valign: "top" });
    footer(s);
  }

  // Day 1 lab
  {
    const s = pres.addSlide();
    await labSlide(s, 1, "Lab 1: from brief to plan, then from data to a date", [
      { title: "1A · Brief → charter, WBS, RACI, risks", steps: ["Take the supplied one-page product brief", "Ask the model for its questions and assumptions first", "Generate charter, WBS, RACI and a risk register", "Run a structured review pass: what is wrong, what is missing, what is invented", "Mark up corrections side by side with the AI draft"] },
      { title: "1B · Throughput → P50 / P85", steps: ["Load the 12-week throughput dataset (or your own tracker export)", "Build the Monte Carlo in Excel or the guided notebook", "Read the P50 and P85 dates; try a WIP-limit scenario", "Have the LLM draft the sponsor explanation and the two scenarios that move the date"] },
    ], "A marked-up AI-drafted plan with the PM's corrections, and a probabilistic forecast with a sponsor-ready explanation.",
      "What changed in the plan once you asked the model for its questions first?\n\nWhich date would you have committed to before today, and which will you commit to now?");
    footer(s);
  }

  // =====================================================================
  // DAY 2
  // =====================================================================
  {
    const s = pres.addSlide();
    agenda(s, 2, "AI for project automation and reporting", [
      { time: "0:00 – 1:00", title: "Using AI for project automation", sub: "Triggers, workflow tools, the LLM step, human-in-the-loop design" },
      { time: "1:00 – 1:10", title: "Break" },
      { time: "1:10 – 2:10", title: "AI-driven reporting and stakeholder communication", sub: "Reports from the system of record · meeting intelligence · citations" },
      { time: "2:10 – 2:20", title: "Break" },
      { time: "2:20 – 3:50", title: "Hands-on: automated status; meeting to decisions", sub: "Lab 2A weekly status to Teams / Slack · Lab 2B decision log" },
      { time: "3:50 – 4:00", title: "Closing round" },
    ], {
      covered: ["Using AI for Project Automation and Reporting", "Hands-On Exercise"],
      factory: ["The label state machine: one state per issue, labels trigger agents, agent comments never self-trigger", "Every run ends by saying what is expected of the next actor", "The Factory Console: a lens, never a second source of truth — attention queue, decision log, cited Q&A"],
    });
    footer(s);
  }

  // Day 2 — automation stack
  {
    const s = pres.addSlide();
    header(s, "The automation stack a PM can own", "Day 2 · module 2.1");
    const steps = [
      ["FiZap", "Trigger", "Webhook, schedule, label change, new message"],
      ["FiRepeat", "Workflow", "Power Automate, n8n, Zapier, GitHub Actions"],
      ["FiCpu", "LLM step", "Summarise, classify, draft, extract, route"],
      ["FiSend", "Destination", "Teams, Slack, email, Confluence, the tracker"],
      ["FiUserCheck", "Human review", "Approve, edit, or let it through by policy"],
    ];
    let x = 0.6;
    for (let i = 0; i < steps.length; i++) {
      const [ic, t, d] = steps[i];
      card(s, x, 1.75, 2.15, 2.2, { fill: i === 4 ? C.orangeSoft : C.soft });
      await iconCircle(s, ic, x + 0.2, 1.95, 0.6, { fill: C.white, color: i === 4 ? C.orange : C.teal });
      s.addText(t, { x: x + 0.2, y: 2.65, w: 1.8, h: 0.35, fontFace: HFONT, fontSize: 14, bold: true, color: i === 4 ? C.orange : C.ink, isTextBox: true, margin: 0 });
      s.addText(d, { x: x + 0.2, y: 3.0, w: 1.8, h: 0.9, fontFace: BFONT, fontSize: 11, color: C.slate, isTextBox: true, margin: 0, valign: "top" });
      if (i < 4) arrowRight(s, x + 2.18, 2.75, 0.3);
      x += 2.45;
    }
    // three columns of policy
    const pol = [
      ["May do alone", ["Post a status draft to a channel", "Label and route new intake", "Remind owners of ageing items", "Extract actions from a transcript"], C.mist, C.tealDark],
      ["Must draft for approval", ["Client-facing communications", "Scope or date changes", "Escalations to a sponsor", "Anything that names a person's performance"], C.soft, C.ink],
      ["Must never touch", ["Merging to production", "Approving a gate on a human's behalf", "Deleting records", "Sending data outside the client's policy"], C.redSoft, C.red],
    ];
    x = 0.6;
    for (const [t, items, fill, col] of pol) {
      card(s, x, 4.25, 3.9, 2.5, { title: t, titleColor: col, fill, body: items, bodySize: 11.5, bodyColor: fill === C.redSoft ? C.red : C.slate });
      x += 4.1;
    }
    footer(s);
    s.addNotes("Factory tie-in: the factory's own rule set is exactly this table. Agents label, comment and open PRs; they may never merge to main, and a hook enforces it rather than a prompt.");
  }

  // Day 2 — reporting from the system of record / state machine
  {
    const s = pres.addSlide();
    header(s, "Report from the system of record, not from people", "Day 2 · module 2.2 · the label state machine as data");
    const states = ["backlog", "intake", "spec-ready", "spec-approved", "planned", "design-ready", "design-approved", "ready", "in-review", "in-test", "ready-to-ship", "in-staging", "deployed"];
    let x = 0.6, y = 1.8;
    states.forEach((st, i) => {
      const gate = ["spec-ready", "design-ready", "in-staging", "backlog"].includes(st);
      const w = chip(s, "factory:" + st, x, y, { mono: true, fontSize: 9.5, fill: gate ? C.orangeSoft : C.mist, color: gate ? C.orange : C.tealDark });
      x += w + 0.32;
      if (i < states.length - 1) {
        if (x + 1.6 > 12.7) { x = 0.6; y += 0.55; } else { arrowRight(s, x - 0.28, y + 0.05, 0.2, C.grey); }
      }
    });
    s.addText("Exactly one state label per issue. Orange states wait on a human. Every transition has a timestamp, an actor and a comment — so status, cycle time, WIP and blocked ageing are queries.", {
      x: 0.6, y: 3.3, w: 12.1, h: 0.4, fontFace: BFONT, fontSize: 11, italic: true, color: C.slate, isTextBox: true, margin: 0,
    });
    const cols = [
      ["Inputs", ["Issues, sub-issues, labels, milestones", "Pull requests and reviews", "CI runs and deployments", "Calendar and meeting transcripts", "Never: a status meeting"]],
      ["The LLM is the narrator, not the source", ["One dataset, three audiences: sponsor, steering committee, team", "Each claim cites the object it came from", "As-of timestamps on every number", "A review step that costs less than the mistake"]],
      ["Meeting intelligence", ["Transcript → decisions, actions, new risks", "Decision log kept current automatically", "In the factory: decisions are posted as ordinary GitHub comments with hidden markers — readable anywhere, indexed by the Console"]],
    ];
    x = 0.6;
    for (const [t, items] of cols) {
      card(s, x, 3.85, 3.9, 2.95, { title: t, titleH: 0.6, titleSize: 13.5, body: items, bodySize: 11.5 });
      x += 4.1;
    }
    footer(s);
  }

  // Day 2 — Factory Console attention queue
  {
    const s = pres.addSlide();
    header(s, "What an AI-era PMO dashboard looks like: the attention queue", "Day 2 · module 2.2 · the Factory Console");
    s.addText("\"What needs me, and why\" — a lens over GitHub, never a second source of truth. Drop its tables, replay the events, and it is whole again.", {
      x: 0.6, y: 1.65, w: 12.1, h: 0.5, fontFace: HFONT, fontSize: 14, italic: true, color: C.tealDark, isTextBox: true, margin: 0,
    });
    // mock queue
    s.addShape(pres.ShapeType.roundRect, { x: 0.6, y: 2.3, w: 7.3, h: 4.45, fill: { color: C.white }, line: { color: C.mist, width: 1.5 }, rectRadius: 0.12, shadow: { type: "outer", color: "000000", blur: 6, offset: 2, angle: 90, opacity: 0.1 } });
    s.addText("Attention queue · 4 items", { x: 0.85, y: 2.45, w: 4, h: 0.35, fontFace: HFONT, fontSize: 13, bold: true, color: C.ink, isTextBox: true, margin: 0 });
    const q = [
      ["G1", "#42 Premium recalculation API — spec PR ready", "Why you: spec approver · Waiting 2 days · 2 open questions the analyst could not answer", C.orange],
      ["G2", "#41 Renewal reminders — design + tasks PR ready", "Why you: design approver · Changed since you looked: migration plan added", C.orange],
      ["!", "#43 Agent dashboard — factory:blocked", "Why you: epic owner · Implementer asks: which auth scope does the widget use?", C.red],
      ["GS", "#38 Claims export — epic assembled and green", "Why you: staging approver · 6 tasks merged in order, system tests 5/5 passed", C.teal],
    ];
    let y = 2.9;
    for (const [g, t, why, col] of q) {
      s.addShape(pres.ShapeType.roundRect, { x: 0.85, y, w: 6.8, h: 0.85, fill: { color: C.soft }, line: { color: C.soft, width: 0 }, rectRadius: 0.08 });
      s.addShape(pres.ShapeType.ellipse, { x: 1.0, y: y + 0.2, w: 0.45, h: 0.45, fill: { color: col }, line: { color: col, width: 0 } });
      s.addText(g, { x: 1.0, y: y + 0.2, w: 0.45, h: 0.45, fontFace: BFONT, fontSize: 10, bold: true, color: C.white, align: "center", valign: "middle", isTextBox: true, margin: 0 });
      s.addText([{ text: t, options: { bold: true, color: C.ink, fontSize: 11, breakLine: true } }, { text: why, options: { color: C.slate, fontSize: 9.5 } }], {
        x: 1.6, y: y + 0.08, w: 5.95, h: 0.72, fontFace: BFONT, isTextBox: true, margin: 0, valign: "middle",
      });
      y += 0.95;
    }
    bullets(s, [
      { head: "Attention, not activity.", text: "The queue lists decisions waiting on you, each with the reason it is yours and how long it has waited." },
      { head: "What changed since you looked.", text: "As-proposed ⇄ as-approved diffs of the spec and design, so a re-review is minutes." },
      { head: "Decision log.", text: "Every gate approval is a recorded decision; every recorded decision is searchable." },
      { head: "Ask the Factory.", text: "Cited Q&A that answers only from the epic's own artifacts, threads, PRs and runs — with a token budget per organisation." },
      { head: "Lesson for any dashboard:", text: "show the person what needs them, cite the source object, and never become the place the truth lives." },
    ], 8.2, 2.3, 4.55, 4.5, { fontSize: 11.5, gap: 8 });
    footer(s);
  }

  // Day 2 lab
  {
    const s = pres.addSlide();
    await labSlide(s, 2, "Lab 2: a status report nobody has to write", [
      { title: "2A · Automated weekly status", steps: ["Connect the sandbox repo (or your tracker export) to the workflow tool", "Pull open issues, PRs, blocked items and deployments", "LLM step: sponsor-grade and team-grade versions from the same data, every claim cited", "Post both to a Teams / Slack channel; add a human-review branch for the sponsor version"] },
      { title: "2B · Meeting → decisions", steps: ["Take a supplied 40-minute transcript", "Extract decisions, actions and new risks, each with a timestamp", "Post the decisions as structured comments on the epic", "Compare with the human minutes: what did each miss?"] },
    ], "A working automated status pipeline posting to a channel, and a decision log generated from a transcript with citations.",
      "Which of your current reports could disappear next month?\n\nWhat would you need to trust before the sponsor version goes out unreviewed?");
    footer(s);
  }

  // =====================================================================
  // DAY 3
  // =====================================================================
  {
    const s = pres.addSlide();
    agenda(s, 3, "Technology and tools for modern project management", [
      { time: "0:00 – 0:50", title: "Overview of modern PM tools", sub: "Jira, ADO, GitHub, Asana, Linear, Notion, MS Project — and where the AI is" },
      { time: "0:50 – 1:40", title: "Integrating collaboration and communication tools", sub: "Webhooks, APIs, bots, MCP · identity and permissions" },
      { time: "1:40 – 1:50", title: "Break" },
      { time: "1:50 – 2:40", title: "Advanced techniques for project monitoring", sub: "Flow metrics, DORA, dashboards, anomaly detection, attention vs alerts" },
      { time: "2:40 – 2:50", title: "Break" },
      { time: "2:50 – 4:00", title: "Hands-on: tool integration", sub: "Lab 3: repo → chat → LLM summary → flow dashboard" },
    ], {
      covered: ["Overview of Modern Project Management Tools", "Integrating Collaboration and Communication Tools", "Advanced Techniques for Project Monitoring", "Hands-On Exercise: Tool Integration"],
      factory: ["Plain GitHub objects as the whole state; OpenSpec folders as the content — vendor-neutral and resumable", "The control path: event → caller stub → router → role → label moves", "Approvers named in config; GitHub's own notifications do the work"],
    });
    footer(s);
  }

  // Day 3 — tools landscape
  {
    const s = pres.addSlide();
    header(s, "The tool landscape — choose by delivery model, not feature list", "Day 3 · module 3.1");
    const cats = [
      ["FiLayers", "Work tracking", "Jira + Atlassian Intelligence / Rovo · Azure DevOps + Copilot · GitHub Projects + Copilot · Linear · Asana AI · Monday · ClickUp Brain"],
      ["FiBookOpen", "Knowledge and specs", "Confluence · Notion AI · SharePoint + Copilot · OpenSpec change folders · ADRs and design docs as reviewable artifacts"],
      ["FiMessageSquare", "Collaboration", "Microsoft Teams + Copilot · Slack AI · meeting recorders (Teams, Zoom, Fireflies, Otter) · email as the record"],
      ["FiBarChart2", "Monitoring and BI", "Power BI · Looker · Grafana · Jira dashboards · DORA tooling (LinearB, Jellyfish, DX) · the Factory Console"],
      ["FiCpu", "AI assistants and agents", "ChatGPT · Claude · Microsoft Copilot · Claude Code · GitHub Copilot coding agent · Cursor · orchestration (GitHub Actions, LangGraph)"],
      ["FiTool", "Automation", "Power Automate · n8n · Zapier · GitHub Actions · Model Context Protocol (MCP) servers that expose tools to assistants"],
    ];
    let x = 0.6, y = 1.75;
    for (let i = 0; i < cats.length; i++) {
      const [ic, t, d] = cats[i];
      card(s, x, y, 3.9, 2.05, { fill: C.soft });
      await iconCircle(s, ic, x + 0.2, y + 0.2, 0.55, { fill: C.white });
      s.addText(t, { x: x + 0.9, y: y + 0.25, w: 2.9, h: 0.45, fontFace: HFONT, fontSize: 14, bold: true, color: C.ink, isTextBox: true, margin: 0, valign: "middle" });
      s.addText(d, { x: x + 0.2, y: y + 0.85, w: 3.5, h: 1.1, fontFace: BFONT, fontSize: 10.5, color: C.slate, isTextBox: true, margin: 0, valign: "top" });
      x += 4.1;
      if (i === 2) { x = 0.6; y += 2.25; }
    }
    s.addText("Three questions before any tool: where does the system of record live, what must be integrated versus merely coexist, and who is the identity every automated action runs as?", {
      x: 0.6, y: 6.3, w: 12.1, h: 0.5, fontFace: BFONT, fontSize: 12, italic: true, color: C.tealDark, isTextBox: true, margin: 0, valign: "middle",
    });
    footer(s);
  }

  // Day 3 — integration control path
  {
    const s = pres.addSlide();
    header(s, "How an event becomes an action: the control path", "Day 3 · module 3.2 · integration primitives, seen in the factory");
    const path = [
      ["GitHub event", "issue opened · label applied · comment 'Approved' · PR merged", C.soft, C.ink],
      ["Caller stub", "~20 lines in the repo: triggers and a version pin, no logic", C.soft, C.ink],
      ["Router", "Reads the event and the current label; names a role or replies why nothing ran", C.mist, C.tealDark],
      ["Role runs", "One agent, one issue, a model chosen per stage", C.teal, C.white],
      ["Visible trace", "Label moved, comment posted, next actor @-mentioned. No silent green runs", C.ink, C.white],
    ];
    let x = 0.6;
    for (let i = 0; i < path.length; i++) {
      const [t, d, fill, col] = path[i];
      s.addShape(pres.ShapeType.roundRect, { x, y: 1.75, w: 2.2, h: 1.9, fill: { color: fill }, line: { color: fill, width: 0 }, rectRadius: 0.12 });
      s.addText(t, { x: x + 0.18, y: 1.85, w: 1.85, h: 0.45, fontFace: HFONT, fontSize: 13.5, bold: true, color: col, isTextBox: true, margin: 0, valign: "middle" });
      s.addText(d, { x: x + 0.18, y: 2.3, w: 1.85, h: 1.25, fontFace: BFONT, fontSize: 10.5, color: fill === C.teal || fill === C.ink ? C.mist : C.slate, isTextBox: true, margin: 0, valign: "top" });
      if (i < 4) arrowRight(s, x + 2.22, 2.6, 0.26);
      x += 2.48;
    }
    const cols = [
      ["Primitives every PM should know", ["Webhook: the tool calls you when something happens", "API: you ask the tool", "Bot: an identity that acts in chat", "MCP: a standard way to give an AI assistant tools — your tracker, your docs, your calendar"]],
      ["Identity and permissions", ["Every automated action runs as someone", "Approvals are recorded in the tool that owns the decision", "In the factory, the Console posts approvals under the user's own GitHub identity — it adds zero new enforcement paths", "Approvers are a config file; the pipeline assigns and @-mentions them"]],
      ["Avoiding notification debt", ["Teams / Slack for attention, email for the record, the assistant for questions", "One channel per project, one thread per epic", "Digest what is informational; interrupt only for decisions", "Say, on the object, what is expected of the next actor"]],
    ];
    x = 0.6;
    for (const [t, items] of cols) {
      card(s, x, 3.95, 3.9, 2.85, { title: t, titleSize: 13, body: items, bodySize: 11 });
      x += 4.1;
    }
    footer(s);
  }

  // Day 3 — monitoring metrics
  {
    const s = pres.addSlide();
    header(s, "Monitoring that answers questions: flow metrics and DORA", "Day 3 · module 3.3");
    const stages = ["intake", "spec gate", "plan+design", "design gate", "implement", "review", "test", "staging gate", "prod gate"];
    const days = [0.3, 2.1, 0.4, 1.6, 1.2, 0.5, 0.6, 1.9, 0.8];
    s.addChart(pres.ChartType.bar, [{ name: "Median days in stage", labels: stages, values: days }], {
      x: 0.6, y: 1.7, w: 7.4, h: 4.1, barDir: "bar",
      chartColors: [C.teal], showTitle: true, title: "Cycle time by stage — one epic, from the label history (days)", titleFontSize: 12, titleColor: C.slate, titleFontFace: BFONT,
      showValue: true, dataLabelPosition: "outEnd", dataLabelFontSize: 9, dataLabelColor: C.slate, dataLabelFontFace: BFONT,
      catAxisLabelColor: C.slate, valAxisLabelColor: C.grey, catAxisLabelFontSize: 10, valAxisLabelFontSize: 9,
      valGridLine: { color: "E3E8EA", size: 0.5 }, catGridLine: { style: "none" }, showLegend: false, valAxisMaxVal: 2.5, dataLabelFormatCode: "0.0", valAxisLabelFormatCode: "0.0",
      catAxisLabelFontFace: BFONT, valAxisLabelFontFace: BFONT, catAxisOrientation: "maxMin",
    });
    s.addText("Where did the 9.4 days go? 6.4 of them were humans at gates. The agents took 3.0. Decision latency is the new constraint.", {
      x: 0.8, y: 5.9, w: 7.0, h: 0.75, fontFace: BFONT, fontSize: 11.5, italic: true, color: C.orange, isTextBox: true, margin: 0, valign: "middle",
    });
    card(s, 8.3, 1.7, 4.45, 2.4, { title: "Flow metrics", titleSize: 13.5, body: ["Throughput · cycle time · WIP · flow efficiency · ageing", "Read together: rising WIP with flat throughput is the earliest warning you get"], bodySize: 11.5 });
    card(s, 8.3, 4.25, 4.45, 2.5, { title: "DORA", titleSize: 13.5, fill: C.mist, titleColor: C.tealDark, bodyColor: C.tealDark, body: ["Deployment frequency · lead time · change-failure rate · time to restore", "In the factory: factory:deployed and factory:incident are the two labels that make these a query; the Ops role's smoke and soak checks feed them"], bodySize: 11.5 });
    footer(s);
    s.addNotes("Chart values are illustrative. Point: AI monitoring is anomaly and trend detection on top of these, and an attention queue instead of an alert firehose.");
  }

  // Day 3 lab
  {
    const s = pres.addSlide();
    await labSlide(s, 3, "Lab 3: wire the tools together", [
      { title: "Repo → chat → LLM → dashboard", steps: ["In the sandbox GitHub organisation, connect a repository to a Teams / Slack channel", "Add an LLM summarisation step on issue and PR events (what changed, who is waiting, why)", "Build a small flow-metrics dashboard from the label history: cycle time by stage, WIP by state, blocked ageing", "Stretch: expose the tracker to an AI assistant through MCP and ask it delivery questions in plain English", "Stretch: add an anomaly rule — alert when blocked ageing exceeds two days"] },
    ], "A live integration from the system of record to the team's chat, with an LLM in the loop, and a dashboard that reads from the same events.",
      "Which one integration would you add to your current project first?\n\nWhat did the LLM summary get wrong, and what would you give it to fix that?");
    footer(s);
  }

  // =====================================================================
  // DAY 4
  // =====================================================================
  {
    const s = pres.addSlide();
    agenda(s, 4, "Managing AI-driven delivery", [
      { time: "0:00 – 0:45", title: "The future of project management", sub: "Managing people and agents · the PM as gatekeeper · skills that appreciate" },
      { time: "0:45 – 1:45", title: "Best practices for project delivery in tech projects", sub: "Spec-driven · small batches · staging first · independent review · guardrails as controls" },
      { time: "1:45 – 1:55", title: "Break" },
      { time: "1:55 – 2:55", title: "Practical guide to managing Gen AI projects", sub: "Non-determinism, evaluation, cost, privacy, responsible AI, model routing" },
      { time: "2:55 – 3:05", title: "Break" },
      { time: "3:05 – 4:20", title: "Hands-on: run an epic through the factory", sub: "Lab 4: file it, plan the release, open G0 → G1 → G2 → GS, see what G3 asks" },
    ], {
      covered: ["The Future of Project Management", "Best Practices for Project Delivery in Tech Projects", "Practical Guide to Managing Gen AI Projects"],
      kicker: "the Software Factory operating model",
      factory: ["This is the day the factory is the subject, not the example", "Ten roles, the state machine, five gates — and why only GS and G3 are structural", "Guardrails: a hook, a deny list, a detector", "Model routing: spend quality where errors compound"],
    });
    footer(s);
  }

  // Day 4 — future of PM
  {
    const s = pres.addSlide();
    header(s, "From managing people to managing people and agents", "Day 4 · module 4.1 · the future of project management");
    card(s, 0.6, 1.75, 5.9, 3.2, {
      title: "What gets automated", body: ["Coordination and hand-offs between stages", "Status collection and first-draft reporting", "First-draft artifacts: specs, plans, designs, test plans", "Implementation, review and testing of well-specified work", "Release assembly: dependency-ordered merges, staging checks"], bodySize: 12.5,
    });
    card(s, 6.8, 1.75, 5.95, 3.2, {
      title: "What stays human — and appreciates", fill: C.mist, titleColor: C.tealDark, bodyColor: C.tealDark,
      body: ["Scope, priorities and trade-offs", "Writing an unambiguous requirement", "Reading a design and a test report well enough to say no", "Opening the gates that put code on staging and in production", "Relationships, escalation, accountability"], bodySize: 12.5,
    });
    s.addShape(pres.ShapeType.roundRect, { x: 0.6, y: 5.15, w: 12.15, h: 1.6, fill: { color: C.ink }, line: { color: C.ink, width: 0 }, rectRadius: 0.12 });
    await iconCircle(s, "FiClock", 0.85, 5.6, 0.7, { fill: C.teal, color: C.white });
    s.addText([
      { text: "The pipeline waits on a human, not the other way round. ", options: { bold: true, color: C.white } },
      { text: "When agents take minutes and approvals take days, decision latency becomes the delivery constraint. The PM's operating rhythm changes from weekly status to daily gates — and the PMO's dashboard changes from activity to attention.", options: { color: C.mist } },
    ], { x: 1.75, y: 5.25, w: 10.8, h: 1.4, fontFace: BFONT, fontSize: 12.5, isTextBox: true, margin: 0, valign: "middle" });
    footer(s);
  }

  // Day 4 — roles and gates
  {
    const s = pres.addSlide();
    header(s, "Ten roles, five gates: the factory pipeline in one picture", "Day 4 · module 4.2");
    const rows = [
      ["0", "Release", "scrum", "Release plan for one milestone: scope, sequencing, risks, GO / NO-GO", "G0", "release scope approver — or the agent's own GO"],
      ["1", "Intake", "intake", "proposal.md + WHEN/THEN scenarios, opened as a PR; stops and asks if ambiguous", "G1", "spec approver reviews the PR, comments 'Approved'"],
      ["2", "Plan", "planner", "tasks.md — ≤ ~10 tasks of ≤ half a day, one PR each, mirrored into sub-issues", "", ""],
      ["3", "Design", "architect", "design.md per repo: contracts, migrations, failure modes; reads the actual code first", "G2", "design approver — plan and design are one approval"],
      ["4", "Dispatch", "dispatch", "Marks tasks whose dependencies are merged as ready; no judgement, pure coordination", "", ""],
      ["5", "Implement", "implementer", "Branch, tests, draft PR — exactly one task per session", "", ""],
      ["6", "Review", "reviewer", "Independent session, different model; approve or send back", "", ""],
      ["7", "Test", "qa", "Scenario → test mapping, suites green, test report on the PR", "", ""],
      ["8", "Deploy", "release", "Dependency-ordered merges onto the epic branch, then integration, then promotion PRs", "GS", "staging approver: 'Approved' on the assembled epic"],
      ["9", "Verify", "ops", "Health and smoke checks, soak, archive the change, close the issue", "G3", "a human presses Merge on the promotion PR — never an agent"],
    ];
    const tbl = [["#", "Stage", "Role", "Produces", "Gate", "Who opens it"].map(h => ({ text: h, options: { bold: true, color: C.white, fill: { color: C.teal }, fontSize: 10.5 } }))];
    rows.forEach((r, i) => tbl.push(r.map((c, j) => {
      const o = { fontSize: 10, color: C.slate, fill: { color: i % 2 ? C.white : C.soft } };
      if (j === 2) { o.fontFace = "Courier New"; o.color = C.tealDark; o.bold = true; }
      if (j === 4 && c) { o.bold = true; o.color = C.white; o.fill = { color: C.orange }; o.align = "center"; }
      if (j === 5 && c) { o.color = C.orange; }
      if (j === 1) { o.bold = true; o.color = C.ink; }
      return { text: c, options: o };
    })));
    s.addTable(tbl, { x: 0.6, y: 1.7, w: 12.1, colW: [0.4, 1.1, 1.3, 5.3, 0.6, 3.4], fontFace: BFONT, border: { type: "solid", color: C.white, pt: 1 }, rowH: 0.42, margin: 0.05, valign: "middle" });
    s.addText("Beside the stages: a fast lane (factory:fast-track) for changes too small for the ceremony, and expedite (factory:expedite) for all of the ceremony and none of the pauses — which still stops at GS.", {
      x: 0.6, y: 6.4, w: 12.1, h: 0.45, fontFace: BFONT, fontSize: 10.5, italic: true, color: C.slate, isTextBox: true, margin: 0, valign: "middle",
    });
    footer(s);
  }

  // Day 4 — best practices
  {
    const s = pres.addSlide();
    header(s, "Delivery best practices, as the factory enforces them", "Day 4 · module 4.2 · best practices for project delivery in tech projects");
    const bp = [
      ["FiFileText", "Spec-driven delivery", "A change is a proposal, acceptance scenarios, a design and a task list — each reviewed before the next is written."],
      ["FiGrid", "Small batches", "Tasks of at most half a day, one PR each, ordered so every intermediate merge is releasable: schema → service → consumer."],
      ["FiLayers", "Staging first, always", "Nothing reaches main that was not assembled and proven on an integration branch. Promotion PRs carry the staging evidence."],
      ["FiEye", "Independent review", "A reviewer that never shares the implementer's context — in the factory, a different model, so the blind spots differ."],
      ["FiShield", "Guardrails as controls", "A hook blocks the push, a deny list removes the merge tool, a detector files an incident. Not a policy document."],
      ["FiPackage", "Release gating", "A milestone is the release. Nothing starts until the whole set has been read, sequenced and approved — once."],
    ];
    let x = 0.6, y = 1.75;
    for (let i = 0; i < bp.length; i++) {
      const [ic, t, d] = bp[i];
      card(s, x, y, 3.9, 2.35, { fill: i % 2 ? C.mist : C.soft });
      await iconCircle(s, ic, x + 0.2, y + 0.2, 0.55, { fill: C.white });
      s.addText(t, { x: x + 0.9, y: y + 0.25, w: 2.9, h: 0.45, fontFace: HFONT, fontSize: 14, bold: true, color: C.ink, isTextBox: true, margin: 0, valign: "middle" });
      s.addText(d, { x: x + 0.2, y: y + 0.85, w: 3.5, h: 1.4, fontFace: BFONT, fontSize: 11, color: i % 2 ? C.tealDark : C.slate, isTextBox: true, margin: 0, valign: "top" });
      x += 4.1;
      if (i === 2) { x = 0.6; y += 2.55; }
    }
    footer(s);
  }

  // Day 4 — guardrails
  {
    const s = pres.addSlide();
    header(s, "Governance you can prove: controls, not instructions", "Day 4 · module 4.2 · guardrails");
    const layers = [
      ["1", "Prevent", "A pre-tool-use hook blocks any agent git push to main or master — every refspec form, force pushes, deletes. Tested like code.", C.tealDark],
      ["2", "Remove", "A permission deny list removes the PR-merge tools from every agent session. Humans merge in the GitHub UI; that click is gate G3.", C.teal],
      ["3", "Detect", "A detection workflow opens a factory:incident issue if a commit ever lands on main without a pull request, or by a PR that did not come from staging.", C.orange],
    ];
    let y = 1.75;
    for (const [n, t, d, col] of layers) {
      s.addShape(pres.ShapeType.roundRect, { x: 0.6, y, w: 7.4, h: 1.35, fill: { color: C.soft }, line: { color: C.soft, width: 0 }, rectRadius: 0.12 });
      s.addShape(pres.ShapeType.ellipse, { x: 0.85, y: y + 0.32, w: 0.7, h: 0.7, fill: { color: col }, line: { color: col, width: 0 } });
      s.addText(n, { x: 0.85, y: y + 0.32, w: 0.7, h: 0.7, fontFace: HFONT, fontSize: 20, bold: true, color: C.white, align: "center", valign: "middle", isTextBox: true, margin: 0 });
      s.addText(t, { x: 1.8, y: y + 0.15, w: 5.9, h: 0.4, fontFace: HFONT, fontSize: 15, bold: true, color: C.ink, isTextBox: true, margin: 0 });
      s.addText(d, { x: 1.8, y: y + 0.55, w: 5.9, h: 0.75, fontFace: BFONT, fontSize: 11, color: C.slate, isTextBox: true, margin: 0, valign: "top" });
      y += 1.55;
    }
    s.addShape(pres.ShapeType.roundRect, { x: 0.6, y: 6.4, w: 7.4, h: 0.45, fill: { color: C.orangeSoft }, line: { color: C.orangeSoft, width: 0 }, rectRadius: 0.1 });
    s.addText("Plus: agent comments carry a marker so they never trigger themselves; a gate flip is checked against the approver list no matter who sends it.", { x: 0.8, y: 6.4, w: 7.1, h: 0.45, fontFace: BFONT, fontSize: 10, color: C.orange, isTextBox: true, margin: 0, valign: "middle" });

    s.addShape(pres.ShapeType.roundRect, { x: 8.3, y: 1.75, w: 4.45, h: 5.1, fill: { color: C.ink }, line: { color: C.ink, width: 0 }, rectRadius: 0.12 });
    s.addText("What a PM takes from this", { x: 8.55, y: 1.95, w: 4.0, h: 0.4, fontFace: HFONT, fontSize: 15, bold: true, color: C.white, isTextBox: true, margin: 0 });
    bullets(s, [
      "A rule an AI system 'should follow' is a wish. A rule the toolchain enforces is a control.",
      "Ask of every AI initiative: what can it not do, and how do we know?",
      "Detection is the third layer, not the first — and it must page a person.",
      "Approver lists, gate evidence and decision logs are the audit trail regulators will ask for.",
      "The same three layers apply to a chatbot, an automation, or a coding agent.",
    ], 8.55, 2.5, 4.0, 4.2, { fontSize: 11.5, color: C.mist, gap: 9 });
    footer(s);
  }

  // Day 4 — managing Gen AI projects
  {
    const s = pres.addSlide();
    header(s, "Managing Gen AI projects: what is actually different", "Day 4 · module 4.3 · practical guide");
    const diffs = [
      ["Non-deterministic output", "The same input gives different answers. Pass / fail testing becomes evaluation on a curated set with a threshold."],
      ["Evaluation is the schedule", "Most of the time goes into the eval loop, integration and change management — not the model."],
      ["Cost is tokens", "Budget per run, per stage, per organisation. Route cheap models to volume, strong models to judgement."],
      ["Drift", "Prompts, models and data all move. Version them; re-run the evals on every change."],
      ["Data in the prompt", "Privacy and confidentiality apply to what goes in and what comes out. Client policy decides the assistant."],
      ["Vendor dependency", "Keep state and content vendor-neutral; only the execution layer should be tied to one model provider."],
    ];
    let x = 0.6, y = 1.75;
    for (let i = 0; i < diffs.length; i++) {
      const [t, d] = diffs[i];
      card(s, x, y, 3.9, 1.5, { fill: C.soft, title: t, titleSize: 13, titleH: 0.35, body: d, bodySize: 10.5 });
      x += 4.1;
      if (i === 2) { x = 0.6; y += 1.65; }
    }
    // lifecycle
    const lc = ["Use-case triage", "Data & access", "Prototype", "Evaluation set", "Guardrails", "Pilot", "Monitor & route"];
    x = 0.6;
    const cw = 1.62;
    s.addText("The Gen AI project lifecycle", { x: 0.6, y: 5.15, w: 6, h: 0.3, fontFace: BFONT, fontSize: 11, bold: true, color: C.orange, isTextBox: true, margin: 0 });
    lc.forEach((t, i) => {
      s.addShape(pres.ShapeType.chevron, { x, y: 5.5, w: cw + 0.1, h: 0.6, fill: { color: i % 2 ? C.teal : C.tealDark }, line: { color: C.white, width: 1 } });
      s.addText(t, { x: x + 0.15, y: 5.5, w: cw - 0.2, h: 0.6, fontFace: BFONT, fontSize: 10, bold: true, color: C.white, align: "center", valign: "middle", isTextBox: true, margin: 0 });
      x += cw + 0.13;
    });
    s.addText("Responsible AI in one line each: transparency (say what the AI did), human oversight (a person holds the gate), auditability (the decision log), lawfulness (EU AI Act risk tiers, India's DPDP Act, the client's own AI policy).", {
      x: 0.6, y: 6.2, w: 12.1, h: 0.6, fontFace: BFONT, fontSize: 11, italic: true, color: C.slate, isTextBox: true, margin: 0, valign: "middle",
    });
    footer(s);
  }

  // Day 4 — model routing
  {
    const s = pres.addSlide();
    header(s, "Model routing: spend quality where errors compound", "Day 4 · module 4.3 · cost and quality management for AI work");
    const rows = [
      ["scrum · intake · planner · architect · reviewer", "Fable 5 → Opus 5 → Sonnet 5", "A wrong release scope, spec, plan or design — or a missed review defect — multiplies downstream. The model delta is cheap by comparison."],
      ["implementer · qa · release", "Opus 5 → Sonnet 5", "Strong coding and testing on the volume stages, guard-railed by the merged design and the spec scenarios."],
      ["dispatch · ops", "Haiku 4.5 → Sonnet 5", "Mechanical coordination and checks. Fast and cheap; nothing here needs judgement."],
    ];
    const tbl = [["Stages", "Preference chain", "Why"].map(h => ({ text: h, options: { bold: true, color: C.white, fill: { color: C.teal }, fontSize: 12 } }))];
    rows.forEach((r, i) => tbl.push(r.map((c, j) => ({ text: c, options: { fontSize: 11.5, bold: j < 2, color: j === 0 ? C.ink : j === 1 ? C.tealDark : C.slate, fontFace: j === 1 ? "Courier New" : BFONT, fill: { color: i % 2 ? C.white : C.soft } } }))));
    s.addTable(tbl, { x: 0.6, y: 1.75, w: 12.1, colW: [3.6, 3.0, 5.5], fontFace: BFONT, border: { type: "solid", color: C.white, pt: 1 }, rowH: [0.4, 0.75, 0.75, 0.75], margin: 0.08, valign: "middle" });
    const cols = [
      ["FiSliders", "Preference chains, not a single model", "Before launching, the pipeline probes each model with a one-token ping and uses the first the credential can reach. A plan or tier gap degrades gracefully instead of failing the run."],
      ["FiDollarSign", "Budgeting an estate", "Cost per role per run × runs per epic × epics per release. The Console holds a token budget per organisation for its Q&A. Ask the same of any AI vendor: what does one unit of work cost?"],
      ["FiRefreshCw", "The PM's version of this", "Use the strong model for the artifacts people will sign off on; the fast one for the drafts, summaries and reminders. Review where the error would compound."],
    ];
    let x = 0.6;
    for (const [ic, t, d] of cols) {
      card(s, x, 4.75, 3.9, 2.0, { fill: C.mist });
      await iconCircle(s, ic, x + 0.2, 4.92, 0.5, { fill: C.white });
      s.addText(t, { x: x + 0.85, y: 4.92, w: 2.95, h: 0.5, fontFace: HFONT, fontSize: 12.5, bold: true, color: C.tealDark, isTextBox: true, margin: 0, valign: "middle" });
      s.addText(d, { x: x + 0.2, y: 5.5, w: 3.5, h: 1.2, fontFace: BFONT, fontSize: 10.5, color: C.tealDark, isTextBox: true, margin: 0, valign: "top" });
      x += 4.1;
    }
    footer(s);
  }

  // Day 4 lab
  {
    const s = pres.addSlide();
    header(s, "Lab 4: run an epic through the factory — in the approver seats", "Day 4 · hands-on exercise · 75 minutes");
    const steps = [
      ["File", "A requirement against a milestone in the sandbox estate. It parks in factory:backlog."],
      ["Plan release", "Comment it on the tracker. Read the Scrum Master's scope, order, risks and verdict."],
      ["G0", "Comment 'Approved'. Every backlog issue in the milestone enters intake at once."],
      ["G1", "Review the proposal and WHEN/THEN scenarios. Send one back with questions — see factory:blocked work."],
      ["G2", "Read tasks.md and design.md in one PR. Approve. The Dispatcher releases the unblocked tasks."],
      ["Watch", "Implement → review → test run unattended. Read the review and the test report as they land."],
      ["GS", "The epic is assembled and green. Approve; the Release Manager carries it to staging and verifies."],
      ["G3", "See what the promotion PR asks of a human, and why no agent can press that button."],
    ];
    let x = 0.6, y = 1.75;
    for (let i = 0; i < steps.length; i++) {
      const [t, d] = steps[i];
      const gate = /^G/.test(t);
      s.addShape(pres.ShapeType.roundRect, { x, y, w: 2.85, h: 1.95, fill: { color: gate ? C.orangeSoft : C.soft }, line: { color: gate ? C.orangeSoft : C.soft, width: 0 }, rectRadius: 0.12 });
      s.addShape(pres.ShapeType.ellipse, { x: x + 0.2, y: y + 0.2, w: 0.5, h: 0.5, fill: { color: gate ? C.orange : C.teal }, line: { color: gate ? C.orange : C.teal, width: 0 } });
      s.addText(String(i + 1), { x: x + 0.2, y: y + 0.2, w: 0.5, h: 0.5, fontFace: BFONT, fontSize: 12, bold: true, color: C.white, align: "center", valign: "middle", isTextBox: true, margin: 0 });
      s.addText(t, { x: x + 0.85, y: y + 0.2, w: 1.9, h: 0.5, fontFace: HFONT, fontSize: 14, bold: true, color: gate ? C.orange : C.ink, isTextBox: true, margin: 0, valign: "middle" });
      s.addText(d, { x: x + 0.2, y: y + 0.8, w: 2.5, h: 1.1, fontFace: BFONT, fontSize: 10.5, color: C.slate, isTextBox: true, margin: 0, valign: "top" });
      x += 3.08;
      if (i === 3) { x = 0.6; y += 2.15; }
    }
    s.addShape(pres.ShapeType.roundRect, { x: 0.6, y: 6.15, w: 12.1, h: 0.7, fill: { color: C.ink }, line: { color: C.ink, width: 0 }, rectRadius: 0.12 });
    s.addText([
      { text: "Roles rotate: ", options: { bold: true, color: C.white } },
      { text: "release-scope approver, spec approver, design approver, tester.  ", options: { color: C.mist } },
      { text: "Closing round: ", options: { bold: true, color: C.white } },
      { text: "which of your current sign-offs are gates, and which are merely waiting?", options: { color: C.mist, italic: true } },
    ], { x: 0.85, y: 6.15, w: 11.6, h: 0.7, fontFace: BFONT, fontSize: 12, isTextBox: true, margin: 0, valign: "middle" });
    footer(s);
  }

  // =====================================================================
  // DAY 5
  // =====================================================================
  {
    const s = pres.addSlide();
    agenda(s, 5, "Capstone, governance and certification", [
      { time: "0:00 – 0:45", title: "Case study discussion", sub: "The four-repository estate · porting the pipeline to another runner · what applies to you" },
      { time: "0:45 – 0:55", title: "Break" },
      { time: "0:55 – 2:55", title: "Capstone project (teams of 3–4)", sub: "AI-enabled delivery plan for a case-study release, six deliverables" },
      { time: "2:55 – 3:05", title: "Break" },
      { time: "3:05 – 3:40", title: "Capstone presentations and critique", sub: "10 minutes per team, scored against the outcome measures" },
      { time: "3:40 – 4:15", title: "Course conclusion, 30-60-90 plan, certification", sub: "Recap, scenario quiz, personal adoption plan, certificate" },
    ], {
      covered: ["Capstone Project & Case Study Discussion", "Course Conclusion and Certification"],
      factory: ["The original deployment: four repositories, one pipeline — what it cost, what broke, what the gates caught", "The same shape on GitHub Copilot: what was vendor-neutral and what was not", "The capstone's governance design uses the factory's gate and guardrail vocabulary"],
    });
    footer(s);
  }

  // Day 5 — case study
  {
    const s = pres.addSlide();
    header(s, "Case study: one pipeline, four repositories", "Day 5 · the original deployment");
    const repos = [
      ["lighthouse-backend", "Python 3.12 · FastAPI · MySQL", "Coordination repo — epics filed here"],
      ["lighthouse-ui", "React 19 · Vite · TypeScript", "Frontend implementer"],
      ["lighthouse-sales", "FastAPI · Postgres/pgvector · Celery", "Sales automation implementer"],
      ["lighthouse-whatsapp-server", "NestJS · Prisma · BullMQ", "Messaging implementer"],
    ];
    const tbl = [["Repository", "Stack", "Role in the estate"].map(h => ({ text: h, options: { bold: true, color: C.white, fill: { color: C.teal }, fontSize: 11 } }))];
    repos.forEach((r, i) => tbl.push(r.map((c, j) => ({ text: c, options: { fontSize: 10.5, fontFace: j === 0 ? "Courier New" : BFONT, bold: j === 0, color: j === 0 ? C.tealDark : C.slate, fill: { color: i % 2 ? C.white : C.soft } } }))));
    s.addTable(tbl, { x: 0.6, y: 1.75, w: 6.6, colW: [2.4, 2.3, 1.9], fontFace: BFONT, border: { type: "solid", color: C.white, pt: 1 }, rowH: 0.45, margin: 0.06, valign: "middle" });
    bullets(s, [
      { head: "The problem it solved.", text: "An agent could write good code, but nothing could tell you where a piece of work was, what it was supposed to do, or who had agreed to it." },
      { head: "What each stage cost,", text: "in minutes and in tokens — and where the humans spent their time (mostly at G1, reading specs)." },
      { head: "What broke.", text: "Cross-repo hand-offs without a shared token; runs that finished green having done nothing; sub-issues stranded with no state after a merge." },
      { head: "What the gates caught.", text: "A design that duplicated an existing module; a task ordering that would have shipped a consumer before its schema." },
    ], 0.6, 4.15, 6.6, 2.7, { fontSize: 11.5, gap: 8 });
    card(s, 7.5, 1.75, 5.25, 5.1, {
      title: "Second case: the same shape on GitHub Copilot", titleH: 0.7, titleSize: 14, fill: C.mist, titleColor: C.tealDark, bodyColor: C.tealDark,
      body: [
        "State (issues, labels, milestones, PRs) and content (OpenSpec folders) are vendor-neutral — roughly 70% of the factory did not change",
        "What had to change: how an agent is defined and launched, and how permissions are enforced",
        "Role prompts ported almost verbatim: trigger → mission → numbered steps → guardrails",
        "Discussion for your context: a services engagement with a client PMO, a fixed-price project, a regulated environment — what carries over, what needs a different gate design?",
      ], bodySize: 11.5,
    });
    footer(s);
  }

  // Day 5 — capstone brief
  {
    const s = pres.addSlide();
    header(s, "Capstone: an AI-enabled delivery plan for a real release", "Day 5 · 2 hours in teams of 3–4, then 10-minute presentations");
    s.addText("Brief: a release of 6–8 requirements for a case-study insurance policy-servicing application (teams may substitute a sanitised release of their own). Produce everything with AI; review everything as a team.", {
      x: 0.6, y: 1.65, w: 12.1, h: 0.6, fontFace: BFONT, fontSize: 12.5, color: C.slate, isTextBox: true, margin: 0, valign: "top",
    });
    const dels = [
      ["FiList", "Release plan", "Scope table, sequencing with the dependency that forces it, risks, what to drop, GO / NO-GO — in the Scrum Master's format."],
      ["FiTrendingUp", "Probabilistic forecast", "P50 / P85 completion with the assumptions and the two scenarios that move it."],
      ["FiAlertTriangle", "Risk register", "AI-mined from the requirements and the case history; exposure, owners, early-warning signals."],
      ["FiRepeat", "Automation & reporting plan", "Which reports and rituals are automated, from which sources, with what human review."],
      ["FiShield", "Governance design", "Which gates exist, who holds them, which are delegated to an agent, which guardrails are controls."],
      ["FiFileText", "Stakeholder pack", "A sponsor-grade one-page status and a steering-committee narrative, generated from the plan."],
    ];
    let x = 0.6, y = 2.4;
    for (let i = 0; i < dels.length; i++) {
      const [ic, t, d] = dels[i];
      card(s, x, y, 3.9, 1.85, { fill: C.soft });
      await iconCircle(s, ic, x + 0.2, y + 0.2, 0.5, { fill: C.white });
      s.addText(`${i + 1}. ${t}`, { x: x + 0.85, y: y + 0.2, w: 2.95, h: 0.5, fontFace: HFONT, fontSize: 13, bold: true, color: C.ink, isTextBox: true, margin: 0, valign: "middle" });
      s.addText(d, { x: x + 0.2, y: y + 0.8, w: 3.5, h: 1.0, fontFace: BFONT, fontSize: 10.5, color: C.slate, isTextBox: true, margin: 0, valign: "top" });
      x += 4.1;
      if (i === 2) { x = 0.6; y += 2.05; }
    }
    s.addText("Scored against the six business outcomes: predictability, reporting, risk, automation, governance, AI readiness. Peer critique first, trainer critique second.", {
      x: 0.6, y: 6.45, w: 12.1, h: 0.4, fontFace: BFONT, fontSize: 11, italic: true, color: C.tealDark, isTextBox: true, margin: 0, valign: "middle",
    });
    footer(s);
  }

  // Day 5 — conclusion / 30-60-90 / certification
  {
    const s = pres.addSlide();
    header(s, "Leaving with a plan, not just a certificate", "Day 5 · conclusion and certification");
    const plan = [
      ["30 days", "One report to automate", ["Pick the report that costs the most hours", "Build it from the system of record with an LLM narrator", "Run it in parallel with the manual one for two cycles"], C.soft],
      ["60 days", "One forecast, one gate", ["Replace a committed date with a P50 / P85", "Redesign one sign-off as a real gate with evidence and an approver list", "Put an attention queue in front of the sponsor"], C.mist],
      ["90 days", "One AI-driven initiative", ["Govern a Gen AI project with evals, budgets and guardrails as controls", "Or: factory-enable one sandbox repository and run a first epic", "Report what changed in predictability and reporting time"], C.ink],
    ];
    let x = 0.6;
    for (const [t, sub, items, fill] of plan) {
      const dark = fill === C.ink;
      s.addShape(pres.ShapeType.roundRect, { x, y: 1.75, w: 3.9, h: 3.3, fill: { color: fill }, line: { color: fill, width: 0 }, rectRadius: 0.12 });
      s.addText(t, { x: x + 0.25, y: 1.9, w: 3.4, h: 0.6, fontFace: HFONT, fontSize: 26, bold: true, color: dark ? C.white : C.teal, isTextBox: true, margin: 0 });
      s.addText(sub, { x: x + 0.25, y: 2.5, w: 3.4, h: 0.4, fontFace: BFONT, fontSize: 13, bold: true, color: dark ? C.mist : C.ink, isTextBox: true, margin: 0 });
      s.addText(items.map((it, i) => ({ text: it, options: { bullet: { indent: 10 }, breakLine: i < items.length - 1, paraSpaceAfter: 5 } })), {
        x: x + 0.25, y: 2.95, w: 3.4, h: 2.0, fontFace: BFONT, fontSize: 11, color: dark ? C.mist : C.slate, isTextBox: true, margin: 0, valign: "top",
      });
      x += 4.1;
    }
    card(s, 0.6, 5.25, 5.9, 1.6, { title: "Assessment and certificate", titleSize: 13, body: ["Capstone 60% + scenario-based quiz 40%", "Certificate of completion issued on passing; recording and materials retained by the client"], bodySize: 11.5 });
    card(s, 6.8, 5.25, 5.95, 1.6, { title: "Take-home resources", titleSize: 13, fill: C.mist, titleColor: C.tealDark, bodyColor: C.tealDark, body: ["The Software Factory handbook and case studies (open source, MIT)", "Prompt library, forecast templates, automation templates, reading list"], bodySize: 11.5 });
    footer(s);
  }

  // Lab setup
  {
    const s = pres.addSlide();
    header(s, "Lab setup and system requirements", "Logistics · answers to the lab questions in the request");
    const cols = [
      ["FiMonitor", "Hardware (per participant)", ["Laptop with 8 GB RAM or more", "Chrome or Edge, stable internet", "Microphone and camera", "No GPU; nothing heavy runs locally"]],
      ["FiUser", "Software and accounts", ["GitHub account (free), added to the sandbox organisation", "A Generative AI assistant: Claude, ChatGPT or Microsoft Copilot — the client's enterprise assistant preferred, to respect data policy", "Excel or Google Sheets", "Teams or Slack sandbox channel", "Optional stretch: VS Code, Node.js 20+, Python 3.11+"]],
      ["FiServer", "Provided by the trainer", ["Sandbox GitHub organisation with the Software Factory installed on a case-study repository", "Approver lists configured for the batch", "Factory Console deployed for participants", "LLM API credits for the factory runs on Days 4–5", "Datasets, prompt library, lab guides, templates"]],
    ];
    let x = 0.6;
    for (const [ic, t, items] of cols) {
      card(s, x, 1.75, 3.9, 4.3, { fill: C.soft });
      await iconCircle(s, ic, x + 0.2, 1.95, 0.55, { fill: C.white });
      s.addText(t, { x: x + 0.9, y: 1.95, w: 2.9, h: 0.55, fontFace: HFONT, fontSize: 13.5, bold: true, color: C.ink, isTextBox: true, margin: 0, valign: "middle" });
      s.addText(items.map((it, i) => ({ text: it, options: { bullet: { indent: 10 }, breakLine: i < items.length - 1, paraSpaceAfter: 5 } })), {
        x: x + 0.2, y: 2.65, w: 3.5, h: 3.3, fontFace: BFONT, fontSize: 11, color: C.slate, isTextBox: true, margin: 0, valign: "top",
      });
      x += 4.1;
    }
    s.addShape(pres.ShapeType.roundRect, { x: 0.6, y: 6.2, w: 12.1, h: 0.65, fill: { color: C.mist }, line: { color: C.mist, width: 0 }, rectRadius: 0.1 });
    s.addText([
      { text: "Lab cost per participant ", options: { bold: true, color: C.tealDark } },
      { text: "covers the sandbox environment, the agent-run credits for the labs and capstone, and AI-assistant usage where the client does not supply its own. All required software is available from our side; the client supplies only its own enterprise AI assistant if it prefers one.", options: { color: C.tealDark } },
    ], { x: 0.85, y: 6.2, w: 11.6, h: 0.65, fontFace: BFONT, fontSize: 10.5, isTextBox: true, margin: 0, valign: "middle" });
    footer(s);
  }

  // Delivery logistics + optional topics
  {
    const s = pres.addSlide();
    header(s, "Delivery format, and topics we can add", "Logistics · optional extensions");
    const rows = [
      ["Mode", "Online, instructor-led, recorded — recording provided to the client"],
      ["Duration", "20 hours: 5 half-days × 4 hours (4.5 with extended labs)"],
      ["Batch size", "12–20 participants; capstone in teams of 3–4"],
      ["Materials", "Slide deck, lab guides, prompt library, forecast and automation templates, sandbox estate, the Software Factory handbook"],
      ["Assessment", "Capstone 60% + scenario quiz 40% → certificate of completion"],
      ["Language", "English"],
    ];
    const tbl = rows.map((r, i) => r.map((c, j) => ({ text: c, options: { fontSize: 11.5, bold: j === 0, color: j === 0 ? C.ink : C.slate, fill: { color: i % 2 ? C.white : C.soft } } })));
    s.addTable(tbl, { x: 0.6, y: 1.75, w: 5.9, colW: [1.4, 4.5], fontFace: BFONT, border: { type: "solid", color: C.white, pt: 1 }, rowH: 0.62, margin: 0.08, valign: "middle" });
    card(s, 6.8, 1.75, 5.95, 5.1, {
      title: "Beyond the initial curriculum (60–90 min each, or a sixth half-day)", titleH: 0.7, titleSize: 13.5, fill: C.mist, titleColor: C.tealDark, bodyColor: C.tealDark,
      body: [
        "Agile estimation and planning with AI: story splitting, backlog grooming, sprint-planning assistants",
        "Vendor and contract management for AI-delivered work: acceptance when an agent wrote the code, IP of generated artifacts",
        "Change management and role redesign: BAs, testers and tech leads on an agent-driven pipeline",
        "Portfolio and PMO-level AI: cross-project forecasting, capacity planning, multi-repository estates",
        "Agentic AI deep-dive: event-driven routers versus graph engines, MCP, evaluating agent runs",
        "Build the client's own factory: factory-enable one sandbox repository and run a first epic",
      ], bodySize: 11.5,
    });
    footer(s);
  }

  // Closing
  {
    const s = pres.addSlide();
    s.background = { color: C.ink };
    s.addShape(pres.ShapeType.ellipse, { x: -2.2, y: 3.6, w: 6.5, h: 6.5, fill: { color: C.tealDark }, line: { color: C.tealDark, width: 0 } });
    s.addText("A plain requirement goes in.\nA governed, proven change comes out.\nThe PM holds the gates.", {
      x: 0.7, y: 1.4, w: 11.8, h: 2.6, fontFace: HFONT, fontSize: 36, bold: true, color: C.white, isTextBox: true, margin: 0, valign: "middle",
    });
    s.addText("That is the delivery model this program prepares Project and Delivery Managers to run — and the one they practise, hands-on, for 20 hours.", {
      x: 0.7, y: 4.1, w: 9.5, h: 0.8, fontFace: BFONT, fontSize: 16, color: C.mist, isTextBox: true, margin: 0, valign: "top",
    });
    chip(s, "factory:deployed", 0.7, 5.15, { fill: C.teal, color: C.white, mono: true, fontSize: 11 });
    s.addText([
      { text: "Jerry Kurian  ·  GenAI People\n", options: { bold: true, color: C.white, fontSize: 15 } },
      { text: "jerry@genaipeople.com  ·  genaipeople.com  ·  github.com/genai-jerry/claude-software-factory", options: { color: C.grey, fontSize: 12 } },
    ], { x: 0.7, y: 5.8, w: 11.5, h: 0.9, fontFace: BFONT, isTextBox: true, margin: 0, valign: "top" });
    footer(s, true);
  }

  const out = "AI-Enabled-Project-Delivery-Management.pptx";
  await pres.writeFile({ fileName: out });
  console.log("wrote", out, "slides:", slideNo);
})();
