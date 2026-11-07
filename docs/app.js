/* PLStats front end. All numbers come from data/stats.json, produced by run_pipeline.py. */
"use strict";

const LB = 0.45359237;
const LIFTS = ["Squat", "Bench", "Deadlift"];
const SCORE_NAMES = ["Dots", "Wilks", "IPF GL", "N-Score"];
let S = null;            // stats.json (analysis of the default group)
let C = null;            // data for the comparison group currently selected
const cohortCache = {};
const V = () => encodeURIComponent(S.meta.snapshot || "");   // cache key: data files change with each snapshot
let last = null;         // last computed result
let cmpMode = "class";
let distFormula = "N-Score";

/* ------------------------------------------------------------ formulas */
const WILKS = {
  M: [-216.0475144, 16.2606339, -0.002388645, -0.00113732, 7.01863e-06, -1.291e-08],
  F: [594.31747775582, -27.23842536447, 0.82112226871, -0.00930733913, 4.731582e-05, -9.054e-08],
};
const WILKS_BW = { M: [40, 201.9], F: [26.51, 154.53] };
const DOTS = {
  M: [-307.75076, 24.0900756, -0.1918759221, 0.0007391293, -0.000001093],
  F: [-57.96288, 13.6175032, -0.1126655495, 0.0005158568, -0.0000010706],
};
const DOTS_BW = { M: [40, 210], F: [40, 150] };
const GL = { M: [1199.72839, 1025.18162, 0.00921], F: [610.32796, 1045.59282, 0.03048] };

const clamp = (x, [lo, hi]) => Math.min(hi, Math.max(lo, x));
const poly = (c, x) => c.reduce((s, ci, i) => s + ci * x ** i, 0);
const formulas = {
  "Wilks": (t, bw, s) => t * 500 / poly(WILKS[s], clamp(bw, WILKS_BW[s])),
  "Dots": (t, bw, s) => t * 500 / poly(DOTS[s], clamp(bw, DOTS_BW[s])),
  // Like OpenPowerlifting: not defined below 35 kg, never negative.
  "IPF GL": (t, bw, s) => { if (bw < 35) return NaN; const [a, b, c] = GL[s]; return t * Math.max(0, 100 / (a - b * Math.exp(-c * bw))); },
  "N-Score": (t, bw, s) => {
    const p = S.scoring.params;
    return t / (p[s].A * bw ** p[s].b) * p.scale;
  },
};

/* ------------------------------------------------------------ helpers */
const $ = (sel, el = document) => el.querySelector(sel);
const fmt = (x, d = 0) => Number(x).toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });
const pctTxt = (p) => !Number.isFinite(p) ? "—" : p >= 99.5 ? "top 0.5%" : p < 0.5 ? "<1st" : ordinal(Math.round(p));
function ordinal(n) { const s = ["th", "st", "nd", "rd"], v = n % 100; return n + (s[(v - 20) % 10] || s[v] || s[0]); }
const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();

const esc = (s) => String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

/** centred log-ratio of three shares: ln(share) minus the mean of the three logs */
const clr = (p) => { const l = p.map(Math.log), m = (l[0] + l[1] + l[2]) / 3; return l.map(v => v - m); };
/** position of a lift profile (three shares) on a group's PCA map */
function project(shares, pc) {
  const z = clr(shares);
  return [0, 1].map(k => z.reduce((s, v, i) => s + (v - pc.center[i]) * pc.components[k][i], 0));
}

/** percentile (0-100) of value v given quantiles qs at evenly spaced probabilities */
function pctOf(qs, v) {
  if (!qs || !Number.isFinite(v)) return NaN;      // empty group, or a score that isn't defined
  const n = qs.length - 1;
  if (v <= qs[0]) return 0;
  if (v >= qs[n]) return 100;
  let i = 0;
  while (qs[i + 1] <= v) i++;
  const f = qs[i + 1] > qs[i] ? (v - qs[i]) / (qs[i + 1] - qs[i]) : 0;
  return (i + f) / n * 100;
}

function weightClass(bw, sex) {
  const cls = S.meta.weight_classes[sex];
  for (const c of cls) if (bw <= c) return String(c);
  return cls[cls.length - 1] + "+";
}

function regPredict(bw, sex, age, year, r = S.regression) {
  const st = r.std;
  const zbw = (Math.log(bw) - st.lbw_mean) / st.lbw_sd;
  const za = (age - st.age_mean) / st.age_sd;
  const zy = (year - st.year_mean) / st.year_sd;
  const m = sex === "M" ? 1 : 0;
  const x = [1, zbw, m, zbw * m, za, za * za, zy];
  return x.reduce((s, xi, i) => s + xi * r.beta[i], 0);   // ln(total)
}

function layout(extra = {}) {
  const text = css("--text"), muted = css("--muted"), line = css("--line");
  return Object.assign({
    paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)",
    font: { family: "Inter, sans-serif", color: text, size: 13 },
    margin: { l: 56, r: 16, t: 16, b: 50 },
    xaxis: { gridcolor: line, zerolinecolor: muted, linecolor: line },
    yaxis: { gridcolor: line, zerolinecolor: muted, linecolor: line },
    legend: { orientation: "h", y: -0.2 },
    hoverlabel: { font: { family: "Inter, sans-serif" } },
  }, extra);
}
const PCONF = { displayModeBar: false, responsive: true };

function heat(grid, dy) {
  const nx = grid.counts[0].length, ny = grid.counts.length;
  const x = Array.from({ length: nx }, (_, i) => grid.x0 + grid.dx * (i + 0.5));
  const y = Array.from({ length: ny }, (_, i) => (grid.y0 ?? grid.x0) + (dy ?? grid.dy ?? grid.dx) * (i + 0.5));
  const z = grid.counts.map(r => r.map(c => c > 0 ? Math.log10(c) : null));
  return { x, y, z, counts: grid.counts };
}

/* ------------------------------------------------------------ calculator */
function readForm() {
  const f = new FormData($("#lifter"));
  const unit = f.get("unit"), k = unit === "lb" ? LB : 1;
  const num = (n) => parseFloat(f.get(n));
  return {
    sex: f.get("sex"), unit,
    bw: num("bw") * k, age: num("age"),
    squat: num("squat") * k, bench: num("bench") * k, deadlift: num("deadlift") * k,
  };
}
const show = (kg, unit, d = 1) => unit === "lb" ? `${fmt(kg / LB, 0)} lb` : `${fmt(kg, kg % 1 ? d : 0)} kg`;

function compute(inp) {
  const { sex, bw } = inp;
  const total = inp.squat + inp.bench + inp.deadlift;
  const P = C.percentiles[sex], R = C.regression;
  const cls = weightClass(bw, sex);
  const scores = Object.fromEntries(SCORE_NAMES.map(n => {
    const v = formulas[n](total, bw, sex);
    return [n, { v, p: pctOf(P.scores[n], v), n: (P.scores_n || {})[n] || 0 }];
  }));
  const ranks = (group) => {
    const g = P.classes[group] || { n: 0 };
    return { n: g.n, squat: pctOf(g.squat, inp.squat), bench: pctOf(g.bench, inp.bench),
      deadlift: pctOf(g.deadlift, inp.deadlift), total: pctOf(g.total, total) };
  };
  const hasAge = Number.isFinite(inp.age);
  let reg = null;
  if (R) {                                          // null when the group is too small to fit the model
    const age = hasAge ? inp.age : R.std.age_mean;
    const year = +S.meta.data_to.slice(0, 4);
    const lnPred = regPredict(bw, sex, age, year, R);
    const rq = R.resid_quantiles;
    reg = { expected: Math.exp(lnPred) * R.smear, lo: Math.exp(lnPred + rq[20]) * R.smear,
      hi: Math.exp(lnPred + rq[180]) * R.smear, pct: pctOf(rq, Math.log(total) - lnPred), hasAge, age, n: R.n_lifters };
  }
  const shares = [inp.squat, inp.bench, inp.deadlift].map(v => v / total);
  const pc = C.pca[sex];
  return {
    inp, total, cls, scores, rank: { class: ranks(cls), All: ranks("All") }, reg,
    shares, z: pc ? shares.map((v, i) => (v - pc.mean[i]) / pc.sd[i]) : [0, 0, 0], pcs: pc ? project(shares, pc) : null,
  };
}

function profileLabel(z) {
  const i = z.indexOf(Math.max(...z));
  if (z[i] < 0.5) return { text: "Balanced lifter", lift: null };
  if (z[i] < 1.5) return { text: `Leans ${LIFTS[i].toLowerCase()}`, lift: i };
  return { text: `${LIFTS[i]} specialist`, lift: i };
}

function render(r) {
  last = r;
  const { inp } = r, u = inp.unit, sexName = inp.sex === "M" ? "men" : "women";
  $("#results").hidden = false;
  $("#r-total").textContent = show(r.total, u);
  $("#r-class").textContent = `${inp.sex === "M" ? "Men's" : "Women's"} ${r.cls} kg class · ${show(inp.bw, u)} bodyweight`;
  const top = 100 - r.scores["N-Score"].p, rc = r.rank.class;
  $("#r-headline").innerHTML = (Number.isFinite(rc.total)
    ? `Your total beats <b>${fmt(rc.total)}%</b> of the ${fmt(rc.n)} ${sexName} in the ${r.cls}&nbsp;kg class, and `
    : `There are no ${sexName} in the ${r.cls}&nbsp;kg class in this group, but `) +
    `your bodyweight-adjusted N-Score puts you in the <b>${top < 1 ? "top 1%" : "top " + fmt(Math.max(1, top)) + "%"}</b> ` +
    `of ${fmt(r.scores["N-Score"].n)} ${cohortDesc(sexName)}. <span class="hint">Everyone is compared at their best.</span>`;

  $("#r-scores").innerHTML = SCORE_NAMES.map(n => {
    const s = r.scores[n], ok = Number.isFinite(s.v);
    const fit = S.meta.nscore_fit;
    const note = n === "N-Score" && fit ? `<div class="hint">version ${fit.id}, ${fit.fit_date}</div>`
      : !ok ? `<div class="hint">not given under 35 kg</div>` : "";
    return `<div class="tile${n === "N-Score" ? " ours" : ""}"><div class="name">${n}${n === "N-Score" ? " · PLStats" : ""}</div>
      <div class="val">${ok ? fmt(s.v, n === "IPF GL" ? 1 : 0) : "—"}</div>
      <div class="pct">${ok ? `${pctTxt(s.p)} percentile` : "no percentile"}</div><div class="meter"><div style="width:${ok && Number.isFinite(s.p) ? s.p : 0}%"></div></div>${note}</div>`;
  }).join("");

  renderRanks();

  const e = r.reg;
  if (!e) $("#r-expected").innerHTML = `<p class="hint">There aren't enough lifters in this group for an estimate. Try a wider group.</p>`;
  else {
    const diff = (r.total / e.expected - 1) * 100;
    $("#r-expected").innerHTML = `<div class="expect"><div class="sub">Expected total for a ${e.hasAge ? fmt(e.age) + "-year-old" : "typical-age"}
      ${inp.sex === "M" ? "man" : "woman"} at ${show(inp.bw, u)}</div>
      <div class="big">${show(e.expected, u, 0)}</div>
      <div class="sub">80% of lifters like you have a best total between ${show(e.lo, u, 0)} and ${show(e.hi, u, 0)}</div></div>
    <div class="callout">You're <b>${fmt(Math.abs(diff))}% ${diff >= 0 ? "above" : "below"}</b> expected, which beats
      <b>${fmt(e.pct)}%</b> of lifters once bodyweight, sex${e.hasAge ? " and age are" : " are"} taken into account.
      ${e.hasAge ? "" : "<br><span class='hint'>Add your age for a sharper estimate.</span>"}</div>`;
  }

  const pc = C.pca[inp.sex], lab = profileLabel(r.z);
  if (!pc) { $("#r-profile").innerHTML = `<p class="hint">There aren't enough lifters in this group to show a profile.</p>`; renderDist(); return; }
  const colors = [css("--squat"), css("--bench"), css("--dead")];
  $("#r-profile").innerHTML = LIFTS.map((l, i) => {
    const max = 0.6;
    return `<div class="prof-row"><span class="l">${l}</span>
      <div class="bar"><div style="width:${r.shares[i] / max * 100}%;background:${colors[i]}"></div>
        <span class="avg" style="left:${pc.mean[i] / max * 100}%" title="Average"></span></div>
      <span class="v">${fmt(r.shares[i] * 100, 1)}% <span class="hint">avg ${fmt(pc.mean[i] * 100, 1)}%</span></span></div>`;
  }).join("") + `<span class="badge" style="${lab.lift !== null ? `color:${colors[lab.lift]}` : ""}">${lab.text}</span>
    <p class="hint" style="margin-top:8px">The tick on each bar is the average for ${sexName}. If one lift is well above average (more than 1.5 standard deviations), you count as a specialist.</p>`;

  drawProfileMap();
  renderDist();
  try { localStorage.setItem("plstats", JSON.stringify(Object.fromEntries(new FormData($("#lifter"))))); } catch (_) {}
}

let profileView = "2d";
function drawProfileMap() {
  const r = last, other = C.key !== S.cohorts.default;
  $("#profile-cap").innerHTML = profileView === "3d"
    ? `Height is each lifter's Dots, so you can see profile and strength together. Drag to turn, scroll or pinch to zoom.
       Shows a sample of US drug-tested raw lifters${other ? " (the 3-D view always uses this group)" : ""}.`
    : "Lifters placed by how their total splits between the three lifts. Darker means more lifters. You're the star.";
  Plotly.purge("ch-profile");
  profileView === "3d" ? profile3d("ch-profile", r.inp.sex, r) : profileMap("ch-profile", r.inp.sex, r, C.pca[r.inp.sex]);
}

function renderRanks() {
  const r = last; if (!r) return;
  const g = r.rank[cmpMode], label = cmpMode === "class" ? `the ${r.cls} kg class` : "all weight classes";
  const rows = [["Squat", g.squat, "--squat"], ["Bench", g.bench, "--bench"], ["Deadlift", g.deadlift, "--dead"], ["Total", g.total, "--accent"]];
  $("#r-ranks").innerHTML = rows.map(([l, p, c]) => `<div class="rank"><span class="l">${l}</span>
      <div class="bar"><div style="width:${Math.max(p, 1)}%;background:var(${c})"></div></div><span class="v">${pctTxt(p)}</span></div>`).join("") +
    `<p class="hint">${g.n ? `Compared with ${fmt(g.n)} ${r.inp.sex === "M" ? "men" : "women"} in ${label}, each at their best.`
      : `No ${r.inp.sex === "M" ? "men" : "women"} in ${label} in this group.`}</p>`;
}

function renderDist() {
  const r = last; if (!r) return;
  const sex = r.inp.sex, h = C.hist[distFormula], e = S.scoring.hist[distFormula].edges;
  const mid = e.slice(0, -1).map((v, i) => (v + e[i + 1]) / 2);
  const traces = ["M", "F"].filter(s => h[s]).map(s => ({
    x: mid, y: h[s], type: "scatter", mode: "lines", fill: "tozeroy", line: { shape: "hvh", width: 2, color: css(s === "M" ? "--men" : "--women") },
    name: s === "M" ? "Men" : "Women", opacity: s === sex ? 1 : 0.45, hovertemplate: "%{x:.0f}<extra></extra>",
  }));
  const v = r.scores[distFormula].v, ok = Number.isFinite(v);
  Plotly.react("ch-dist", traces, layout({
    xaxis: { title: `${distFormula} (each lifter's best)`, gridcolor: css("--line") }, yaxis: { title: "Share of lifters", showticklabels: false, gridcolor: css("--line") },
    shapes: ok ? [{ type: "line", x0: v, x1: v, yref: "paper", y0: 0, y1: 1, line: { color: css("--text"), width: 2, dash: "dot" } }] : [],
    annotations: ok ? [{ x: v, yref: "paper", y: 1, text: `You: ${fmt(v, distFormula === "IPF GL" ? 1 : 0)}`, showarrow: false, yanchor: "bottom", font: { size: 13 } }] : [],
    margin: { l: 40, r: 16, t: 24, b: 70 },
  }), PCONF);
}

/* ------------------------------------------------------------ lifters on the map */
// Any lifter with a raw or knee-wraps full-power result in the last ten years can be put on a map. The name
// list (data/lifters/names.txt, strongest first) is downloaded the first time someone uses a search box; a
// lifter's details come from a small file (data/lifters/<first two letters of the name>.json) when added.
let LIFTER = {};                                   // id -> details, for lifters loaded so far
let picked = { M: null, F: null };                 // null = use the defaults
const chartArgs = {};                              // last arguments per map, for redraws
const MAXL = () => S.meta.max_map_lifters || 5;
const foldName = (n) => n.normalize("NFKD").toLowerCase();
const nameKey = (n) => (foldName(n).replace(/[^a-z]/g, "") + "__").slice(0, 2);   // same as run_pipeline.name_key
const searchText = (n) => " " + foldName(n).replace(/[^a-z0-9]+/g, " ").trim() + " ";
let DUP = new Set();                               // display names shared by several lifters (keep their "#n")
const shortName = (id) => id.replace(/ #\d+$/, "");
const displayName = (id) => DUP.has(shortName(id)) ? id : shortName(id);
function fromRow(id, r) {
  return { id, n: displayName(id), s: r[0], p: [r[1] / 1000, r[2] / 1000, r[3] / 1000], t: r[4], bw: r[5], dots: r[6],
    fed: r[7], y: r[8], eq: r[9] ? "knee wraps" : "raw", c: r[10] };
}
let NAMES = null, namesReady = false;
function loadNames() {
  if (!NAMES) NAMES = fetch(`data/lifters/names.txt?v=${V()}`).then(r => { if (!r.ok) throw new Error("names"); return r.text(); }).then(txt => {
    const ids = [], sex = [], text = [], rank = [], seen = new Map(), per = { M: 0, F: 0 };
    for (const line of txt.split(/\r?\n/)) {
      if (!line) continue;
      const tab = line.indexOf("\t"), sx = line.slice(0, tab), id = line.slice(tab + 1);
      ids.push(id); sex.push(sx); text.push(searchText(id)); rank.push(++per[sx]);
      const k = shortName(id); seen.set(k, (seen.get(k) || 0) + 1);
    }
    DUP = new Set([...seen].filter(([, n]) => n > 1).map(([k]) => k));
    Object.values(LIFTER).forEach(l => { l.n = displayName(l.id); });
    namesReady = true;
    return { ids, sex, text, rank };
  }).catch(e => { NAMES = null; throw e; });
  return NAMES;
}
function searchNames(N, q, sx, skip, limit = 8) {
  const words = searchText(q).trim().split(" ").filter(Boolean);
  if (words.join("").length < 2) return [];
  const out = [];
  for (let i = 0; i < N.ids.length && out.length < limit; i++) {
    if (N.sex[i] !== sx || skip.includes(N.ids[i])) continue;
    if (words.every(w => N.text[i].includes(" " + w))) out.push(i);
  }
  return out;
}
const SHARDS = {};
async function loadLifter(id) {
  if (LIFTER[id]) return LIFTER[id];
  const k = nameKey(id);
  if (!SHARDS[k]) SHARDS[k] = fetch(`data/lifters/${k}.json?v=${V()}`).then(r => r.ok ? r.json() : {}).catch(() => { delete SHARDS[k]; return {}; });
  const row = (await SHARDS[k])[id];
  if (row) LIFTER[id] = fromRow(id, row);
  return LIFTER[id];
}
function pickedIds(sex) {
  return (picked[sex] ?? S.meta.default_lifters[sex]).filter(id => LIFTER[id] && LIFTER[id].s === sex).slice(0, MAXL());
}
function redrawMaps(sex) {
  Object.entries(chartArgs).forEach(([id, a]) => {
    if (!sex || a.sex === sex) a.three ? profile3d(id, a.sex, a.r) : profileMap(id, a.sex, a.r, a.pc);
  });
}
function setPicked(sex, ids) {
  picked[sex] = ids;
  try { localStorage.setItem("plstats-lifters", JSON.stringify(picked)); } catch (_) {}
  redrawMaps(sex);
}
async function loadSavedPicks() {                // picks remembered from an earlier visit
  const ids = [...(picked.M || []), ...(picked.F || [])].filter(id => !LIFTER[id]);
  if (!ids.length) return;
  await Promise.all(ids.map(loadLifter));
  redrawMaps();
}
function renderPicker(id, sex) {
  const box = document.getElementById(`${id}-pick`);
  if (!box) return;
  const ids = pickedIds(sex), full = ids.length >= MAXL(), who = sex === "M" ? "men" : "women";
  const n = S.meta.n_searchable_lifters;
  box.innerHTML = `<div class="chips">${ids.length ? ids.map(i => `<span class="chip">${esc(LIFTER[i].n)}<button type="button" data-rm="${esc(i)}" aria-label="Remove ${esc(LIFTER[i].n)}">×</button></span>`).join("") : `<span class="hint">No lifters shown.</span>`}</div>
    <div class="pick-row">
      <div class="ac">
        <input type="search" autocomplete="off" spellcheck="false" role="combobox" aria-autocomplete="list" aria-expanded="false"
          aria-controls="${id}-res" aria-label="Search for a lifter to add to the map" ${full ? "disabled" : ""}
          placeholder="${full ? `The map is full (${MAXL()} lifters). Remove one to add another.` : "Search any lifter by name…"}">
        <ul class="ac-list" id="${id}-res" role="listbox" hidden></ul>
      </div>
      <button type="button" class="link" data-act="reset">Reset</button>
      <button type="button" class="link" data-act="clear">Clear</button>
    </div>
    <p class="hint">Up to ${MAXL()} lifters. Search ${n ? fmt(n) : "all"} lifters from the last ten years (raw or knee wraps). Each is shown at their best meet. This map shows ${who} only.</p>`;
  if (box.dataset.wired) return;
  box.dataset.wired = "1";
  let timer = null, results = [], active = -1;
  const input = () => box.querySelector("input[type=search]"), list = () => box.querySelector(".ac-list");
  const close = () => { const l = list(); if (l) l.hidden = true; input()?.setAttribute("aria-expanded", "false"); active = -1; };
  const show = (html) => { const l = list(); l.innerHTML = html; l.hidden = false; input().setAttribute("aria-expanded", "true"); };
  const highlight = () => list().querySelectorAll("[role=option]").forEach((li, k) => li.setAttribute("aria-selected", k === active));
  async function add(lid) {
    const s = chartArgs[id].sex, cur = pickedIds(s);
    if (cur.length >= MAXL() || cur.includes(lid)) return;
    close();
    const l = await loadLifter(lid);
    if (!l) { show(`<li class="ac-note">Couldn't load that lifter. Try again.</li>`); return; }
    setPicked(s, [...cur, lid]);
    input()?.focus();
  }
  async function run() {
    const q = input().value, s = chartArgs[id].sex;
    if (searchText(q).replace(/ /g, "").length < 2) { close(); return; }
    let N;
    try { if (!namesReady) show(`<li class="ac-note">Loading lifter names…</li>`); N = await loadNames(); }
    catch (_) { show(`<li class="ac-note">Couldn't load the lifter list. Check your connection and try again.</li>`); return; }
    if (input().value !== q) return;              // the user kept typing
    const hits = searchNames(N, q, s, pickedIds(s));
    results = hits.map(k => N.ids[k]); active = hits.length ? 0 : -1;
    show(hits.length ? hits.map((k, n) => `<li role="option" id="${id}-opt${n}" data-id="${esc(N.ids[k])}" aria-selected="${n === 0}">
        <span>${esc(displayName(N.ids[k]))}</span><small>#${fmt(N.rank[k])} by Dots</small></li>`).join("")
      : `<li class="ac-note">No ${s === "M" ? "men" : "women"} match “${esc(q)}”.</li>`);
  }
  box.addEventListener("input", (e) => { if (e.target.type === "search") { clearTimeout(timer); timer = setTimeout(run, 120); } });
  box.addEventListener("keydown", (e) => {
    if (e.target.type !== "search" || list().hidden || !results.length) { if (e.key === "Escape") close(); return; }
    if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); active = (active + (e.key === "ArrowDown" ? 1 : results.length - 1)) % results.length; highlight(); }
    else if (e.key === "Enter") { e.preventDefault(); if (active >= 0) add(results[active]); }
    else if (e.key === "Escape") close();
  });
  box.addEventListener("pointerdown", (e) => { const li = e.target.closest("[role=option]"); if (li) { e.preventDefault(); add(li.dataset.id); } });
  box.addEventListener("focusout", () => setTimeout(() => { if (!box.contains(document.activeElement)) close(); }, 150));
  box.addEventListener("focusin", (e) => { if (e.target.type === "search") loadNames().catch(() => {}); });   // start the download early
  box.addEventListener("click", (e) => {
    const s = chartArgs[id].sex, b = e.target.closest("button"); if (!b) return;
    if (b.dataset.rm) setPicked(s, pickedIds(s).filter(i => i !== b.dataset.rm));
    else if (b.dataset.act === "reset") setPicked(s, null);
    else if (b.dataset.act === "clear") setPicked(s, []);
  });
}

function profileMap(id, sex, r, pc = S.pca.by_sex[sex]) {
  chartArgs[id] = { sex, r, pc };
  const hl = pickedIds(sex).map(i => LIFTER[i]).map(l => ({ name: l.n, pc: project(l.p, pc), l }));
  const h = heat(pc.grid);
  const ev = pc.explained;
  const scale = 2 * Math.max(...pc.score_sd);
  const colors = [css("--squat"), css("--bench"), css("--dead")];
  const traces = [{
    type: "heatmap", x: h.x, y: h.y, z: h.z, customdata: h.counts,
    colorscale: [[0, css("--surface-2")], [1, css("--muted")]], showscale: false,
    hovertemplate: "%{customdata} lifters<extra></extra>",
  }, {
    type: "scatter", mode: "markers", x: hl.map(d => d.pc[0]), y: hl.map(d => d.pc[1]),
    text: hl.map(d => esc(d.name)),
    marker: { size: 9, color: "#f2b705", line: { color: "#000", width: 1 } }, name: "Lifters",
    hovertemplate: "<b>%{text}</b><br>%{customdata}<extra></extra>",
    customdata: hl.map(({ l }) => `${esc(l.fed)} ${l.y}${l.c ? ` (${esc(l.c)})` : ""}, ${l.eq} · ${fmt(l.t, l.t % 1 ? 1 : 0)} kg total at ${fmt(l.bw, 1)} kg · Dots ${l.dots}<br>` +
      l.p.map((p, i) => `${LIFTS[i]} ${(p * 100).toFixed(1)}%`).join(" · ")),
  }];
  if (r && r.pcs) traces.push({
    type: "scatter", mode: "markers", x: [r.pcs[0]], y: [r.pcs[1]], name: "You",
    marker: { symbol: "star", size: 20, color: css("--accent"), line: { color: css("--surface"), width: 1.5 } },
    hovertemplate: "You<extra></extra>",
  });
  // Lifter names as solid "chips" so they stay readable on top of the shading.
  // Alternate labels above/below (in order of height) so neighbours don't cover each other.
  const order = hl.map((d, i) => i).sort((i, j) => hl[i].pc[1] - hl[j].pc[1]);
  const names = hl.map((d, i) => ({
    x: d.pc[0], y: d.pc[1], text: `<b>${esc(d.name)}</b>`, showarrow: false,
    yshift: order.indexOf(i) % 2 ? 14 : -14,
    font: { size: 11, color: css("--text") }, bgcolor: css("--surface"),
    bordercolor: css("--line"), borderwidth: 1, borderpad: 2, opacity: 0.95,
  }));
  const ann = LIFTS.flatMap((l, i) => {
    const x = pc.components[0][i] * scale, y = pc.components[1][i] * scale;
    return [
      { x, y, ax: 0, ay: 0, axref: "x", ayref: "y", showarrow: true, arrowhead: 2, arrowwidth: 2.5,
        arrowcolor: colors[i], text: "" },
      { x: x * 1.25, y: y * 1.25, showarrow: false, text: `<b>${l}-heavy</b>`,
        font: { color: colors[i], size: 13 }, bgcolor: css("--surface"), opacity: 0.9 },
    ];
  });
  const lim = Math.max(scale * 1.45, Math.max(...pc.score_sd) * 3.2);
  Plotly.react(id, traces, layout({
    xaxis: { title: `PC1 · ${(ev[0] * 100).toFixed(1)}% of variance`, range: [-lim, lim], constrain: "domain", zeroline: true, gridcolor: css("--line"), zerolinecolor: css("--muted") },
    yaxis: { title: `PC2 · ${(ev[1] * 100).toFixed(1)}%`, range: [-lim, lim], constrain: "domain", scaleanchor: "x", zeroline: true, gridcolor: css("--line"), zerolinecolor: css("--muted") },
    annotations: [...names, ...ann], showlegend: false, margin: { l: 56, r: 10, t: 10, b: 50 },
  }), PCONF);
  renderPicker(id, sex);
}

/* 3-D version of the default group's profile map: the two profile axes plus Dots as height. */
let CLOUD = null;
const loadCloud = () => CLOUD || (CLOUD = fetch(`data/pca3d.json?v=${V()}`).then(r => {
  if (!r.ok) throw new Error(`pca3d.json: ${r.status}`);
  return r.json();
}).then(d => {
  if (d.snapshot !== S.meta.snapshot) throw new Error("pca3d.json is from another snapshot");
  return d;
}).catch(e => { CLOUD = null; throw e; }));

async function profile3d(id, sex, r) {
  const pc = S.pca.by_sex[sex], args = { sex, r, pc, three: true };
  chartArgs[id] = args;
  let cl;
  try { cl = (await loadCloud())[sex]; } catch (e) {
    console.error(e);
    if (chartArgs[id] === args) { Plotly.purge(id); $("#" + id).innerHTML = `<p class="hint">The 3-D view couldn't be loaded.</p>`; }
    return;
  }
  if (chartArgs[id] !== args) return;               // the view changed while loading
  const hl = pickedIds(sex).map(i => LIFTER[i]).map(l => ({ name: l.n, pc: project(l.p, pc), l }));
  const lim = Math.max(2 * Math.max(...pc.score_sd) * 1.45, Math.max(...pc.score_sd) * 3.2);
  const traces = [{
    type: "scatter3d", mode: "markers", x: cl.pc1, y: cl.pc2, z: cl.dots, hoverinfo: "skip",
    marker: { size: 3.5, color: cl.dots, colorscale: [[0, css("--line")], [1, css("--muted")]], opacity: 0.7 },
  }, {
    type: "scatter3d", mode: "markers+text", x: hl.map(d => d.pc[0]), y: hl.map(d => d.pc[1]), z: hl.map(d => d.l.dots),
    text: hl.map(d => esc(d.name)), textposition: "top center", textfont: { size: 11, color: css("--text") },
    marker: { size: 7, color: "#f2b705", line: { color: "#000", width: 1 } },
    hovertemplate: "<b>%{text}</b><br>Dots %{z}<extra></extra>",
  }];
  const dots = r && r.scores.Dots.v, you = r && project(r.shares, pc);
  if (r && Number.isFinite(dots)) traces.push({
    type: "scatter3d", mode: "markers+text", x: [you[0]], y: [you[1]], z: [dots], text: ["<b>You</b>"],
    textposition: "top center", textfont: { size: 12, color: css("--accent") },
    marker: { size: 9, symbol: "diamond", color: css("--accent") }, hovertemplate: "You · Dots %{z:.1f}<extra></extra>",
  });
  const ax = (title, range) => ({ title, range, gridcolor: css("--line"), zerolinecolor: css("--muted"),
    showbackground: false, color: css("--text"), showspikes: false });
  Plotly.react(id, traces, layout({
    scene: {
      xaxis: ax("PC1: bench ← → legs", [-lim, lim]), yaxis: ax("PC2: deadlift ← → squat", [-lim, lim]), zaxis: ax("Dots"),
      aspectmode: "manual", aspectratio: { x: 1, y: 1, z: 0.8 }, camera: { eye: { x: 1.45, y: -1.45, z: 0.85 } },
    },
    showlegend: false, margin: { l: 0, r: 0, t: 0, b: 0 },
  }), PCONF);
  renderPicker(id, sex);
}

/* ------------------------------------------------------------ deep dive */
const table = (head, rows) => `<div class="tbl-wrap"><table><thead><tr>${head.map(h => `<th>${h}</th>`).join("")}</tr></thead>
  <tbody>${rows.map(r => `<tr>${r.map(c => `<td>${c}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
const p1 = (x) => (x * 100).toFixed(1) + "%";
const sg = (x, d = 3) => (x >= 0 ? "+" : "−") + Math.abs(x).toFixed(d);

function renderClean() {
  const c = S.meta.cleaning;
  $("#d-clean").innerHTML = `<p>All data comes from the public OpenPowerlifting database (${S.meta.source_file}).
    The table shows how the default group is built: US, drug-tested, raw, full-power meets in Open, Junior and
    Collegiate divisions from the last ten years of the file (${S.meta.data_from} to ${S.meta.data_to}). The other comparison
    groups use the same quality filters but can include other countries, untested federations, knee wraps and every age
    division. The research on this page (PCA, N-Score and the regression) uses the default group.</p>` +
    table(["Filter", "Rows left", "Removed"], c.map((s, i) => [s.step, fmt(s.rows), i ? fmt(c[i - 1].rows - s.rows) : "—"])) +
    `<p class="cap">The "every lift ≥ 15% of total" filter removes token lifts, e.g. a bench specialist who opens the
    squat with an empty-ish bar only to post a total. Those rows would otherwise form artificial streaks on the profile map.</p>
    <p><b>Each lifter counts once.</b> Many people compete often, and some enter two divisions at one meet. So that
    regulars don't count extra, every percentile, chart and count uses each lifter's best result: best total for totals,
    best Dots for Dots, and so on. The ${fmt(S.meta.n_rows)} results above come from ${fmt(S.meta.n_lifters)} lifters.</p>
    <p class="cap">Federations name their divisions differently, so the division filter knows names like "OpenT" and "Seniors",
    and leaves out youth and masters divisions such as "Juniors 13-15" or "Open M1".</p>`;
}

function renderPCA() {
  const P = S.pca, M = P.by_sex.M, F = P.by_sex.F;
  const evRow = (name, ev) => [name, ...ev.map(p1), p1(ev[0] + ev[1])];
  const loadRows = (d) => LIFTS.map((l, i) => [l, sg(d.components[0][i]), sg(d.components[1][i]), p1(d.mean[i]), p1(d.sd[i]), p1(d.sd[i] / d.mean[i])]);
  const lrKeys = [["squat/deadlift", "Squat ÷ deadlift"], ["squat/bench", "Squat ÷ bench"], ["deadlift/bench", "Deadlift ÷ bench"]];
  $("#d-pca").innerHTML = `
    <p>Principal component analysis (PCA) finds the directions in which lifters differ the most. Here it looks only at the
      <b>shape</b> of a total, meaning how it splits between squat, bench and deadlift, not how big it is. It uses the default group (US drug-tested raw lifters).
      Men and women are analysed separately, and each lifter appears once, at their best meet by Dots (${fmt(M.n)} men and ${fmt(F.n)} women).</p>
    <h4>Why log-ratios?</h4>
    <p>A lifter's three shares (e.g. 36% squat, 23% bench, 41% deadlift) always add up to 100%, so if one goes up another must
      go down. That built-in constraint creates negative correlations between shares even when the lifts have nothing to do
      with each other. The standard fix (Aitchison, 1986) is to analyse the <b>ratios between lifts</b> on a log scale
      (the centred log-ratio): <span class="mono">ln(share) − average of the three ln(share)</span>.</p>
    <h4>Why three components, and how much do they explain?</h4>
    <p>PCA produces one component per input, and we have three lifts, so three is the maximum. Because the three log-ratios
      of each lifter add up to zero, the data lie on a flat 2-D plane: PC3 explains exactly 0%, and PC1 + PC2 explain 100%.
      The profile map is therefore a complete picture, not an approximation. For comparison, PCA on raw kilograms is
      dominated by PC1, "strong at everything".</p>
    ${table(["Input", "PC1", "PC2", "PC3", "PC1 + PC2"], [evRow("Raw kg, z-scored (both sexes)", P.raw.explained), evRow("Lift log-ratios, men", M.explained), evRow("Lift log-ratios, women", F.explained)])}
    <p>PC1 and PC2 are fairly close in size, so there isn't one dominant direction: lifters vary in two comparable ways.</p>
    <div class="seg-row" style="margin-top:14px">
      <div class="seg small" id="pca-sex"><button type="button" data-v="M" class="on">Men</button><button type="button" data-v="F">Women</button></div>
      <div class="seg small" id="pca-view"><button type="button" data-v="2d" class="on">Map</button><button type="button" data-v="3d">3-D</button></div>
    </div>
    <div id="ch-pca" class="chart tall"></div>
    <div class="picker" id="ch-pca-pick"></div>
    <p class="cap" id="pca-cap"></p>
    <h4>What the components mean</h4>
    <div class="two" style="gap:16px">
      <div>${table(["Men", "PC1", "PC2", "Mean share", "SD", "SD ÷ mean"], loadRows(M))}</div>
      <div>${table(["Women", "PC1", "PC2", "Mean share", "SD", "SD ÷ mean"], loadRows(F))}</div>
    </div>
    <p><b>PC1 is bench against the two lower-body lifts.</b> For women it is almost exactly bench vs (squat + deadlift equally);
      for men, bench mostly trades against the deadlift. <b>PC2 is squat against deadlift.</b> Bench is the most distinctive lift:
      its share varies about 50% more relative to its size than the other two (the "SD ÷ mean" column).</p>
    <h4>Do squat and deadlift trade off?</h4>
    <p>How much each <b>ratio</b> between two lifts varies from lifter to lifter (the variance of its log):</p>
    ${table(["Ratio", "Men", "Women"], lrKeys.map(([k, label]) => [label, M.logratio_var[k].toFixed(4), F.logratio_var[k].toFixed(4)]))}
    <p class="note">The squat-to-deadlift ratio is the <b>most consistent</b> of the three for both sexes. Lifters who are strong
      at one lower-body lift tend to be strong at the other; it's the bench that varies most independently. (Correlations of
      the raw shares suggest the opposite, but that's the 100% constraint at work, which is why we use log-ratios.)</p>
    <h4>Does your profile depend on bodyweight?</h4>
    ${table(["Correlation of bodyweight with", "Men", "Women"], LIFTS.map((l, i) => [`${l} share`, sg(M.bw_corr[i]), sg(F.bw_corr[i])]))}
    <p>Yes, mostly for men: heavier lifters get less of their total from the deadlift and more from squat and bench.</p>
    <h4>Are there "types" of lifter?</h4>
    <p>No. The map is one continuous cloud with no gaps between groups. A "specialist" is someone out in one tail of that cloud,
      not a member of a separate group. The calculator's balanced/specialist label is based on how far each of your shares
      is from the average (in standard deviations), not on PCA clusters.</p>`;
  const caps = {
    "2d": `Profile map (biplot). Shading is the number of lifters per cell on a log scale. Arrows show the direction a
      lifter moves as that lift makes up more of their total (the PCA loadings). Signs are fixed so PC1 points from
      bench-heavy (left) to lower-body-heavy (right) and PC2 points toward squat-heavy for both sexes.`,
    "3d": `The same map in 3-D, with each lifter's Dots as the height, so you can see profile and overall strength together.
      Drag to turn it, scroll or pinch to zoom. The height isn't a third PCA component (that one is empty, see above), and
      to keep it fast the view draws a random sample of ${fmt(4000)} lifters per sex.`,
  };
  let sex = "M", view = "2d";
  const draw = () => {
    const r = last && last.inp.sex === sex && C.key === S.cohorts.default ? last : null;
    $("#pca-cap").innerHTML = caps[view];
    Plotly.purge("ch-pca");
    view === "3d" ? profile3d("ch-pca", sex, r) : profileMap("ch-pca", sex, r);
  };
  draw();
  segToggle("#pca-sex", (v) => { sex = v; draw(); });
  segToggle("#pca-view", (v) => { view = v; draw(); });
}

function renderScoring() {
  const sc = S.scoring, pr = sc.params;
  const nf = S.meta.nscore_fit || { id: "?", fit_date: S.meta.generated, snapshot: S.meta.snapshot, n_fits: 1 };
  $("#d-scoring").innerHTML = `
    <p>Strength grows with body size, but less than proportionally: muscle force scales with cross-sectional area
      (∝ mass<sup>2/3</sup>) while bodyweight scales with volume. That suggests a power law
      <span class="mono">Total = a · BW<sup>b</sup></span>. Taking logs turns it into a straight line,
      <span class="mono">ln(Total) = ln(a) + b · ln(BW)</span>, which we fit by least squares for men and women separately.
      Each lifter carries the same weight in the fit: someone with ten meets gets a tenth of the weight per meet, so regulars
      don't drag the curve toward themselves.</p>
    ${table(["", "a", "b", "R² (log scale)", "Test R², power law", "Test R², 5th-degree polynomial", "Results", "Lifters"],
      ["M", "F"].map(s => [s === "M" ? "Men" : "Women", pr[s].A.toFixed(2), pr[s].b.toFixed(3), pr[s].r2_log.toFixed(3),
        pr[s].test_r2_power.toFixed(3), pr[s].test_r2_poly5.toFixed(3), fmt(pr[s].n), pr[s].n_lifters ? fmt(pr[s].n_lifters) : "—"]))}
    <p class="cap">This is <b>version ${nf.id}</b>, made on ${nf.fit_date} from the ${nf.snapshot} data. N-Score is refit every week,
      so the same total can score slightly differently from one version to the next. All versions so far are saved in
      <a href="data/nscore_history.json">nscore_history.json</a>.</p>
    <p class="cap">"Test R²" is measured on lifters the model hasn't seen: each curve is fit on 80% of lifters and tested on
      the other 20%. The polynomial does slightly better in the middle but bends unrealistically at the extremes (see the
      chart), so we stick with the two-parameter power law. N-Score = Total ÷ (a·BW<sup>b</sup>) × ${pr.scale.toFixed(1)},
      which puts the top 1% of lifters' best scores, men and women together, above 500.</p>
    <div class="seg small" id="fit-sex"><button type="button" data-v="M" class="on">Men</button><button type="button" data-v="F">Women</button></div>
    <div id="ch-fit" class="chart"></div>
    <h4>Is each score fair across bodyweights?</h4>
    <p>A fair score has the same average at every bodyweight. Each line below shows a formula's average score at each
      bodyweight, as a percentage of its overall average so all four fit on one axis; a flat line at 100% is fair. Each
      lifter appears once, at their best meet for that formula.</p>
    <div class="seg small" id="bw-sex"><button type="button" data-v="M" class="on">Men</button><button type="button" data-v="F">Women</button></div>
    <div id="ch-bw" class="chart"></div>
    <p class="cap">The saw-tooth pattern (clearest for men) comes from weight classes: serious lifters cut to just under a class
      limit (66, 74, 83, 93 kg…), so the bins right below each limit hold stronger lifters than the bins just above.</p>
    ${table(["Formula", "Corr. with BW (men)", "Corr. with BW (women)", "Mean M / F", "99th pct M / F"],
      sc.evaluation.map(e => [e.formula, sg(e.corr_bw_M), sg(e.corr_bw_F), e.mf_ratio_mean.toFixed(3), e.mf_ratio_p99.toFixed(3)]))}
    <p class="note">With Wilks, Dots and IPF GL, heavier women score lower on average than lighter women, and men score
      higher than women on average. N-Score is about even across bodyweights for both sexes, and the average man and woman
      score about the same. That last part is by design, since each sex has its own curve, so it doesn't prove N-Score is
      fair between men and women. Among the top 1%, N-Score favours women, while the older formulas were tuned so elite
      men and women score alike.</p>`;

  const fit = (sex) => {
    const g = sc.fit_curves[sex], c = css(sex === "M" ? "--men" : "--women");
    Plotly.react("ch-fit", [
      { x: g.bw, y: g.power, name: `Power law: ${pr[sex].A.toFixed(1)}·BW^${pr[sex].b.toFixed(3)}`, line: { color: c, width: 3 } },
      { x: g.bw, y: g.poly5, name: "5th-degree polynomial", line: { color: "#f29e05", width: 2.5, dash: "dash" } },
    ], layout({ xaxis: { title: "Bodyweight (kg)", gridcolor: css("--line") }, yaxis: { title: "Expected total (kg)", gridcolor: css("--line") } }), PCONF);
  };
  const bw = (sex) => {
    const palette = { "Wilks": "#8e6bd8", "Dots": "#f29e05", "IPF GL": "#14a3a3", "N-Score": css("--accent") };
    const tr = Object.entries(sc.binned).map(([n, d]) => {
      const m = d[sex].mean.filter(v => v != null), avg = m.reduce((a, b) => a + b, 0) / m.length;
      return { x: d[sex].bw, y: d[sex].mean.map(v => v == null ? null : v / avg * 100), name: n,
        line: { color: palette[n], width: n === "N-Score" ? 3.5 : 2 }, hovertemplate: `${n}: %{y:.1f}%<extra></extra>` };
    });
    Plotly.react("ch-bw", tr, layout({
      xaxis: { title: "Bodyweight (kg)", gridcolor: css("--line") }, yaxis: { title: "Mean score (% of formula's average)", gridcolor: css("--line") },
      shapes: [{ type: "line", xref: "paper", x0: 0, x1: 1, y0: 100, y1: 100, line: { color: css("--muted"), dash: "dot" } }],
    }), PCONF);
  };
  fit("M"); bw("M");
  segToggle("#fit-sex", fit); segToggle("#bw-sex", bw);
}

function renderReg() {
  const r = S.regression;
  const labels = { "zBW": "ln(bodyweight)", "Male": "Male (vs female)", "zBW x Male": "ln(bodyweight) × Male", "zAge": "Age", "zAge^2": "Age²", "zYear": "Meet year" };
  const rows = r.terms.slice(1).map((t, j) => {
    const i = j + 1, b = r.beta[i], se = r.se[i];
    return [labels[t], sg(b, 4), se.toFixed(4), `${sg(b - 1.96 * se, 3)} to ${sg(b + 1.96 * se, 3)}`, sg((Math.exp(b) - 1) * 100, 1) + "%"];
  });
  $("#d-reg").innerHTML = `
    <p>We model the log of the total from bodyweight, sex, age and meet year:</p>
    <p class="eq">ln(Total) = β₀ + β₁·zBW + β₂·Male + β₃·(zBW × Male) + β₄·zAge + β₅·zAge² + β₆·zYear</p>
    <ul>
      <li><b>Standardised predictors.</b> Every continuous variable is centred and divided by its standard deviation
        (z-score), so each coefficient is the effect of a <em>one-standard-deviation</em> change. That puts kilograms and years on
        the same footing, and coefficients can be compared directly. (1 SD: ln BW ${r.std.lbw_sd.toFixed(3)} ≈ ${p1(Math.exp(r.std.lbw_sd) - 1)} heavier;
        age ${r.std.age_sd.toFixed(1)} years; year ${r.std.year_sd.toFixed(1)} years.)</li>
      <li><b>Sex is categorical</b>, so it enters as an indicator: <span class="mono">Male = 1</span> for men, <span class="mono">0</span> for women.
        β₂ is the difference between men and women at average bodyweight and age.</li>
      <li><b>zBW × Male</b> is that indicator times standardised bodyweight. For women it is always 0, so their bodyweight slope is β₁;
        for men it equals zBW, so their slope is β₁ + β₃. This is equivalent to giving each sex its own bodyweight slope, and β₃ is the difference between the two slopes.</li>
      <li><b>Age²</b> lets strength rise and then fall with age. The fitted curve peaks at <b>${r.peak_age.toFixed(1)} years</b>.
        This compares different lifters of different ages, not the same people over time, so it isn't a forecast of when you'll peak.</li>
    </ul>
    <h4>Who's in the model</h4>
    <p>Every result in the default group (US, drug-tested, raw, Open/Junior/Collegiate, last ten years) with a recorded age:
      ${fmt(r.n)} results from ${fmt(r.n_lifters)} lifters. The ${fmt(r.n_no_age)} results with no age are left out. Some ages are
      OpenPowerlifting's estimate from the lifter's age class (such as 24.5). The other filters are under "Data and cleaning".</p>
    ${table(["Predictor", "Coefficient", "SE (clustered)", "95% CI", "Effect on total"], rows)}
    <p class="cap">Most lifters appear more than once, so the standard errors are <b>clustered by lifter</b>. That makes them about ${(r.se.slice(1).reduce((a, s, i) => a + s / r.se_iid[i + 1], 0) / (r.se.length - 1)).toFixed(1)}×
      larger than if every result were treated as independent. R² = ${r.r2_log.toFixed(3)} on the log scale. "Effect on total" is
      e<sup>β</sup> − 1: the % change in total per 1 SD (or male vs female). Because Age and Age² work together, read them as a pair.</p>
    <h4>Which variables matter most?</h4>
    <p>The cleanest measure of importance is how much R² drops when a variable (and every term containing it) is removed from the model.</p>
    <div id="ch-imp" class="chart" style="height:240px"></div>
    <h4>Predicted vs actual total</h4>
    <p>The model's predicted total (converted back to kg) against what each lifter actually lifted. Points on the dashed line are
      predicted perfectly. In kg the model has R² = ${r.r2_kg.toFixed(3)} and a typical error (RMSE) of ${fmt(r.rmse_kg)} kg.
      The two blobs are women (left) and men (right).</p>
    <div id="ch-pva" class="chart tall"></div>
    <p class="note">About 30% of the variation is left unexplained. Training history, genetics, technique and nutrition aren't in the data,
      which is why the calculator gives a range ("80% of lifters like you…") rather than a single number.</p>
    <h4>Age curve</h4>
    <div id="ch-age" class="chart"></div>
    <p class="cap">Model-predicted total by age for a man and a woman at the dataset's average bodyweight (${fmt(Math.exp(r.std.lbw_mean))} kg), meet year ${S.meta.data_to.slice(0, 4)}.</p>`;

  const u = Object.entries(r.unique_r2).sort((a, b) => a[1] - b[1]);
  Plotly.react("ch-imp", [{ type: "bar", orientation: "h", y: u.map(d => d[0]), x: u.map(d => d[1] * 100),
    marker: { color: css("--good") }, text: u.map(d => (d[1] * 100).toFixed(1) + "%"), textposition: "outside", hoverinfo: "skip" }],
  layout({ xaxis: { title: "Unique ΔR² (percentage points)", gridcolor: css("--line") }, yaxis: { automargin: true }, margin: { l: 90, r: 40, t: 10, b: 50 } }), PCONF);

  const h = heat(r.pred_vs_actual), lo = h.x[0], hi = h.x[h.x.length - 1];
  Plotly.react("ch-pva", [
    { type: "heatmap", x: h.x, y: h.x, z: h.z, customdata: h.counts, colorscale: "Viridis", showscale: false,
      hovertemplate: "predicted %{x:.0f} kg<br>actual %{y:.0f} kg<br>%{customdata} lifters<extra></extra>" },
    { x: [lo, hi], y: [lo, hi], mode: "lines", line: { color: css("--accent"), dash: "dash", width: 2 }, name: "Perfect prediction", hoverinfo: "skip" },
  ], layout({ xaxis: { title: "Predicted total (kg)", range: [lo, hi], gridcolor: css("--line") }, yaxis: { title: "Actual total (kg)", range: [lo, hi], gridcolor: css("--line") }, showlegend: false }), PCONF);

  const ages = Array.from({ length: 51 }, (_, i) => 15 + i), year = +S.meta.data_to.slice(0, 4);
  Plotly.react("ch-age", ["M", "F"].map(s => ({
    x: ages, y: ages.map(a => Math.exp(regPredict(Math.exp(r.std.lbw_mean), s, a, year)) * r.smear),
    name: s === "M" ? "Men" : "Women", line: { color: css(s === "M" ? "--men" : "--women"), width: 3 },
    hovertemplate: "age %{x}: %{y:.0f} kg<extra></extra>",
  })), layout({ xaxis: { title: "Age", gridcolor: css("--line") }, yaxis: { title: "Predicted total (kg)", gridcolor: css("--line") } }), PCONF);
}

function segToggle(sel, fn) {
  const el = $(sel);
  el.addEventListener("click", (e) => {
    const b = e.target.closest("button"); if (!b) return;
    el.querySelectorAll("button").forEach(x => x.classList.toggle("on", x === b));
    fn(b.dataset.v);
  });
}

/* ------------------------------------------------------------ boot */
/* ------------------------------------------------------------ comparison groups */
const COHORT_FIELDS = ["region", "testing", "equipment", "ages"];
function cohortKey() {
  const f = new FormData($("#lifter"));
  return COHORT_FIELDS.map(k => f.get(k)).join("-");
}
/** e.g. "men in US drug-tested raw powerlifting (Open, Junior & College divisions)" */
function cohortDesc(who) {
  const [region, testing, equip, ages] = C.key.split("-");
  return `${who} in ${region === "us" ? "US" : "worldwide"} ${testing === "tested" ? "drug-tested" : "tested and untested"} ` +
    `${equip === "raw" ? "raw" : "raw and knee-wraps"} powerlifting${ages === "core" ? "" : " (all age divisions)"}`;
}
async function loadCohort() {
  const key = cohortKey();
  if (!cohortCache[key]) cohortCache[key] = fetch(`data/cohorts/${key}.json?v=${V()}`).then(r => {
    if (!r.ok) throw new Error(`no data for ${key}`);
    return r.json();
  }).then(c => {
    // stats.json and the group files are published together; a mismatch means a stale cached copy
    if (c.snapshot !== S.meta.snapshot) throw new Error(`data for ${key} is out of date; reload the page`);
    return c;
  }).catch(e => { delete cohortCache[key]; throw e; });
  C = await cohortCache[key];
  $("#cohort-n").textContent = `${fmt(C.n_lifters)} lifters (${fmt(C.n_rows)} meet results)`;
}

function setUnits() {
  const u = new FormData($("#lifter")).get("unit");
  document.querySelectorAll("i.u").forEach(i => i.textContent = `(${u})`);
}

async function boot() {
  // On GitHub Pages (user.github.io/PLStats) link the nav to the source repo.
  if (location.hostname.endsWith("github.io")) {
    $("#gh-link").href = `https://github.com/${location.hostname.split(".")[0]}/${location.pathname.split("/")[1] || "PLStats"}`;
  }
  S = await fetch("data/stats.json", { cache: "no-cache" }).then(r => r.json());
  LIFTER = Object.fromEntries(Object.entries(S.lifters).map(([id, row]) => [id, fromRow(id, row)]));
  try { picked = Object.assign({ M: null, F: null }, JSON.parse(localStorage.getItem("plstats-lifters") || "{}")); } catch (_) {}
  for (const k of ["M", "F"]) if (!Array.isArray(picked[k]) || !picked[k].every(x => typeof x === "string")) picked[k] = null;
  loadSavedPicks();
  $("#meta-line").textContent = `OpenPowerlifting snapshot ${S.meta.snapshot || S.meta.data_to} (refreshed weekly). Meets ${S.meta.data_from} to ${S.meta.data_to}, ${fmt(S.meta.n_rows)} results from ${fmt(S.meta.n_lifters)} lifters.`;
  renderClean();

  const form = $("#lifter");
  setUnits();
  form.addEventListener("change", async (e) => {
    if (e.target.name === "unit") {
      const k = e.target.value === "lb" ? 1 / LB : LB;
      ["bw", "squat", "bench", "deadlift"].forEach(n => { const v = parseFloat(form[n].value); if (Number.isFinite(v)) form[n].value = +(v * k).toFixed(1); });
      setUnits();
    }
    if (COHORT_FIELDS.includes(e.target.name)) await loadCohort();
    if (last && form.checkValidity()) render(compute(readForm()));
  });
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    await loadCohort();
    render(compute(readForm()));
    $("#results").scrollIntoView({ behavior: "smooth", block: "start" });
  });
  $("#example").addEventListener("click", () => {
    const kg = new FormData(form).get("unit") === "kg", k = kg ? 1 : 1 / LB;
    const ex = { bw: 83, age: 24, squat: 210, bench: 135, deadlift: 250 };
    Object.entries(ex).forEach(([n, v]) => form[n].value = n === "age" ? v : +(v * k).toFixed(0));
    form.querySelector('input[name=sex][value=M]').checked = true;
    form.requestSubmit();
  });

  $("#cmp-toggle").addEventListener("click", (e) => {
    const b = e.target.closest("button"); if (!b) return;
    cmpMode = b.dataset.v;
    $("#cmp-toggle").querySelectorAll("button").forEach(x => x.classList.toggle("on", x === b));
    renderRanks();
  });
  $("#dist-toggle").innerHTML = SCORE_NAMES.map(n => `<button type="button" data-v="${n}" class="${n === distFormula ? "on" : ""}">${n}</button>`).join("");
  segToggle("#dist-toggle", (v) => { distFormula = v; renderDist(); });
  segToggle("#profile-view", (v) => { profileView = v; if (last && C.pca[last.inp.sex]) drawProfileMap(); });

  const done = {};
  document.querySelectorAll("details[data-render]").forEach(d => d.addEventListener("toggle", () => {
    const k = d.dataset.render;
    if (d.open && !done[k]) { done[k] = true; ({ pca: renderPCA, scoring: renderScoring, reg: renderReg })[k](); }
  }));

  try {
    const saved = JSON.parse(localStorage.getItem("plstats") || "null");
    if (saved) {
      for (const [k, v] of Object.entries(saved)) {
        const el = form.querySelector(`[name="${k}"][value="${v}"]`) || form.querySelector(`input[name="${k}"]:not([type=radio])`);
        if (!el) continue;
        if (el.type === "radio") el.checked = true; else el.value = v;
      }
      setUnits();
    }
  } catch (_) {}
  await loadCohort().catch(async () => {          // saved group no longer exists: fall back
    COHORT_FIELDS.forEach(k => form.querySelector(`input[name=${k}]`).checked = true);
    await loadCohort();
  });
  if (form.checkValidity()) render(compute(readForm()));
}

boot().catch(err => {
  document.querySelector(".hero").insertAdjacentHTML("beforeend",
    `<p class="note">Could not load data/stats.json (${err.message}). If you opened this file directly, serve the folder instead: <span class="mono">python -m http.server -d docs</span></p>`);
});
