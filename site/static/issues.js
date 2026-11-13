// Observed issues: filters, search, sort, one row per defect, shareable URL, CSV.
const CSV_COLUMNS = ['id', 'title', 'kind', 'phase', 'stage', 'symptom', 'legality', 'lang', 'model', 'versions_failing', 'targets_failing', 'status', 'status_version', 'regression', 'reproducers', 'specs'];
// FAM_NAME, TG_NAME, TG_SHORT and TG_ISA come from static/toolchains.js (generated from
// catalog/toolchains.yaml and catalog/machines.yaml), loaded before this script.
const KIND_NAME = { incorrect: 'Appears to behave incorrectly', unsupported: 'Appears not to support' };
const KIND_TAG = KIND_NAME;
const STAGE_NAME = { compile: 'At compile time', link: 'At link time', run: 'At run time' };
const LEGAL_NAME = { confirmed: 'Independently confirmed', supported: 'Supported by outside evidence',
  contested: 'Contested', unconfirmed: 'Not independently confirmed' };
const STATE_WORD = { 'fails-like': 'behaves incorrectly', 'fails-differently': 'fails another way', correct: 'correct',
  unknown: 'unknown', na: 'n/a' };
const ST_NAME = { open: 'Open', changed: 'Changed in a newer release', mixed: 'Mixed evidence', fixed: 'Fixed in a newer release',
  'not-reproduced': 'Not reproduced in current runs', 'not-run': 'Not yet run' };

let DATA = null;
let S = fromQuery(typeof location !== 'undefined' ? location.search : '');

function el(tag, attrs, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === 'class') e.className = v; else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
    else if (v !== false && v !== null && v !== undefined) e.setAttribute(k, v === true ? '' : v);
  }
  for (const k of kids.flat()) if (k !== null && k !== undefined) e.append(k.nodeType ? k : String(k));
  return e;
}

function set(patch) {
  S = Object.assign({}, S, patch);
  history.replaceState(null, '', location.pathname + toQuery(S));
  render();
}

function toggle(key, value) {
  const cur = S[key];
  set({ [key]: cur.includes(value) ? cur.filter((x) => x !== value) : cur.concat([value]) });
}

function famTcs(fam) { return VERSIONS[fam].map((v) => TC[v]); }

// The compiler buttons toggle a family; the last selected one stays selected.
function toggledFams(fams, fam) {
  const next = fams.includes(fam) ? fams.filter((f) => f !== fam) : fams.concat([fam]);
  return next.length ? FAMILIES.filter((f) => next.includes(f)) : fams;
}

// What an issue does on one compiler family: failing versions and targets and that family's
// status, over all its reproducers; absent when the issue does not concern it.
function view(i, fam) { return (i.fams || {})[fam]; }

// Whether an issue passes the filters that depend on the family, on family `fam`.
function famMatches(i, fam) {
  const v = view(i, fam);
  if (!v || !S.st.includes(v.status)) return false;
  if (S.vers.length && !v.versions.some((t) => S.vers.map((x) => TC[x]).includes(t))) return false;
  if (S.tg.length && !v.targets.some((t) => S.tg.includes(t))) return false;
  if (S.regOnly && !v.regression) return false;
  return true;
}

// The selected families an issue is listed under: one version strip each.
function shownFams(i) { return S.fams.filter((f) => famMatches(i, f)); }

function matches(i) {
  if (!shownFams(i).length) return false;
  if (S.kinds.length && !(i.kinds || [i.kind]).some((k) => S.kinds.includes(k))) return false;
  if (S.stages.length && !S.stages.includes(i.stage)) return false;
  if (S.legal.length && !S.legal.includes(i.legality)) return false;
  if (S.langs.length && !S.langs.includes(i.lang)) return false;
  if (S.models.length && !S.models.includes(i.model)) return false;
  const q = S.q.trim().toLowerCase();
  if (q && searchRank(i, q) > 2) return false;
  return true;
}

// The search ranks a match in the title first, then in the constructs, then the rest (id and
// the compiler messages); 3 = no match.
function searchRank(i, q) {
  if (i.title.toLowerCase().includes(q)) return 0;
  if (i.constructs.join(' ').toLowerCase().includes(q) || (i.specs || []).join(' ').toLowerCase().includes(q)) return 1;
  return (i.id + ' ' + (i.search || '')).toLowerCase().includes(q) ? 2 : 3;
}

// Wrong answers: an issue of the offload phase that appears to behave incorrectly.
function wrongAnswer(i) { return i.phase === 'offload' && (i.kinds || [i.kind]).includes('incorrect'); }

function sorted(rows) {
  // newest failing version: 0 when an issue fails on the newest release of a family it is shown
  // under, -1 on the one before, and so on
  const newest = (i) => Math.max(-99, ...shownFams(i).map((f) => {
    const tcs = famTcs(f);
    return Math.max(-99, ...view(i, f).versions.map((t) => tcs.indexOf(t) - (tcs.length - 1)));
  }));
  const reach = (i) => shownFams(i).reduce((s, f) => s + view(i, f).targets.length + view(i, f).versions.length, 0);
  const regression = (i) => shownFams(i).some((f) => view(i, f).regression);
  const q = S.q.trim().toLowerCase();
  const rank = (a, b) => (q ? searchRank(a, q) - searchRank(b, q) : 0);
  const by = {
    fixed: (a, b) => wrongAnswer(b) - wrongAnswer(a) || (regression(b) - regression(a))
      || reach(b) - reach(a) || a.title.localeCompare(b.title),
    version: (a, b) => newest(b) - newest(a) || a.title.localeCompare(b.title),
    construct: (a, b) => (a.constructs[0] || '').localeCompare(b.constructs[0] || '') || a.title.localeCompare(b.title),
  };
  return rows.slice().sort((a, b) => rank(a, b) || by[S.sort](a, b));
}

function statusText(i, fam) {
  const v = view(i, fam) || i;
  if (v.status === 'fixed' || v.status === 'changed') return `${v.status === 'fixed' ? 'Fixed' : 'Changed'} in ${v.status_version}`;
  return ST_NAME[v.status] || v.status;
}

// A version box of the list's strip: filled where the issue fails, outlined where the program
// ran correctly, grey where nothing is decided (not run, or the runs disagree).
function stripClass(w, tc) {
  if (w.versions.includes(tc)) return 's-fails-like';
  const st = (w.states || {})[tc];
  return 's-' + (st in STATE_WORD && st !== 'fails-like' ? st : 'unknown');
}

// One family's line of a row: its name (when several families are shown), the version strip,
// the GPUs where it fails and its status.
function famLine(i, fam) {
  const w = view(i, fam);
  const word = (v) => {
    const st = stripClass(w, TC[v]).slice(2);
    return st === 'fails-like' && i.kind === 'unsupported' && (i.kinds || [i.kind]).length < 2 ? 'not supported' : STATE_WORD[st];
  };
  const name = FAM_NAME[fam].split(' (')[0];
  const vstrip = el('div', { class: 'vers', role: 'img', 'aria-label': name + ': ' + VERSIONS[fam].map((v) => v + ': ' + word(v)).join('; ') },
    VERSIONS[fam].map((v) => el('span', { class: 'v ' + stripClass(w, TC[v]), title: word(v) }, v)));
  return el('div', { class: 'famline' }, S.fams.length > 1 ? el('div', { class: 'small fam' }, name) : null, vstrip,
    el('div', { class: 'small' }, w.targets.map((t) => TG_SHORT[t]).join(' · ')),
    el('div', { class: 'small' }, statusText(i, fam)));
}

function row(i) {
  const fams = shownFams(i);
  const regression = fams.some((f) => view(i, f).regression);
  return el('a', { class: 'item', href: 'issues/' + i.page + '.html' },
    el('div', {}, el('span', { class: 'tag ' + (i.status === 'mixed' ? 'k-mixed' : 'k-' + i.kind) },
      i.status === 'mixed' ? 'Mixed evidence' : KIND_TAG[i.kind]),
    i.failure ? el('div', { class: 'small' }, i.failure[0].toUpperCase() + i.failure.slice(1)) : null,
    i.legality ? el('div', { class: 'small lg lg-' + i.legality }, 'Legality: ' + (i.legality_words || '')) : null,
    el('div', { class: 'small' }, (i.lang === 'c' ? 'C' : 'Fortran') + ' · ' + (i.model === 'acc' ? 'OpenACC' : 'OpenMP')),
    regression ? el('div', { class: 'small' }, el('strong', { title: 'fails on a GPU where the previous version ran correctly' }, 'Regression')) : null),
    el('div', {}, el('div', { style: 'font-weight:500' }, i.title),
      el('div', { class: 'small mono' }, i.constructs.join(' · ')),
      (i.specs || []).length ? el('div', { class: 'small spec' }, 'Specification: ' + i.specs.join(' · ')) : null,
      i.reproducers > 1 ? el('div', { class: 'small' }, i.reproducers + ' reproducers') : null),
    el('div', {}, fams.map((f) => famLine(i, f))));
}

function check(key, v, names) {
  return el('label', { class: 'chk' }, el('input', { type: 'checkbox', checked: S[key].includes(v),
    'data-key': key, 'data-value': v, onchange: () => toggle(key, v) }), names[v] || v);
}

function checks(legend, key, values, names) {
  return el('fieldset', {}, el('legend', { class: 'lbl' }, legend), values.map((v) => check(key, v, names)));
}

// The GPUs a compiler has results on, grouped by ISA: each group is headed by the ISA code
// name, so the labels under it name the GPU and memory mode only.
function gpuChecks(legend, key, values, names) {
  const ran = DATA && DATA.ran && S.fams.flatMap((f) => DATA.ran[f] || []);
  const shown = ran ? values.filter((v) => ran.includes(v) || S[key].includes(v)) : values;
  const isas = [...new Set(shown.map((v) => TG_ISA[v]))];
  const label = Object.fromEntries(shown.map((v) => [v, (names[v] || v).replace(' (' + TG_ISA[v] + ')', '')]));
  return el('fieldset', {}, el('legend', { class: 'lbl' }, legend),
    isas.map((isa) => el('div', { class: 'isa-group' }, el('div', { class: 'small isa' }, isa),
      shown.filter((v) => TG_ISA[v] === isa).map((v) => check(key, v, label)))));
}

function renderFilters() {
  const f = document.getElementById('filters');
  f.replaceChildren(
    el('fieldset', {}, el('legend', { class: 'lbl' }, 'Compilers'),
      FAMILIES_LIST.map((fam) => el('button', { type: 'button', class: 'btn', 'aria-pressed': String(S.fams.includes(fam)),
        'data-key': 'fam', 'data-value': fam, onclick: () => {
          const fams = toggledFams(S.fams, fam);
          const vers = S.vers.filter((v) => fams.some((f) => VERSIONS[f].includes(v)));
          const tgs = new Set(fams.flatMap((f) => TARGETS[f]));
          set({ fams, vers, tg: S.tg.filter((t) => tgs.has(t)) });
        } }, FAM_NAME[fam]))),
    el('fieldset', {}, el('legend', { class: 'lbl' }, 'Behaves incorrectly on version'),
      S.fams.map((fam) => el('div', { class: 'vgroup' }, S.fams.length > 1 ? el('div', { class: 'small fam' }, FAM_NAME[fam].split(' (')[0]) : null,
        el('div', { class: 'row-wrap' }, VERSIONS[fam].map((v) => el('button', { type: 'button', class: 'pill',
          'aria-pressed': String(S.vers.includes(v)), 'data-key': 'vers', 'data-value': TC[v],
          onclick: () => toggle('vers', v) }, v))))),
      S.fams.some((f) => VERSIONS[f].length > 1) ? el('label', { class: 'chk' }, el('input', { type: 'checkbox', checked: S.regOnly,
        'data-key': 'reg', 'data-value': '1', onchange: () => set({ regOnly: !S.regOnly }) }),
      'Only regressions (the previous version was correct)') : null),
    gpuChecks('GPU and memory mode', 'tg', [...new Set(S.fams.flatMap((f) => TARGETS[f]))], TG_NAME),
    checks('Kind', 'kinds', ['incorrect', 'unsupported'], KIND_NAME),
    checks('When it fails', 'stages', ['compile', 'link', 'run'], STAGE_NAME),
    checks('Legality', 'legal', ['confirmed', 'supported', 'contested', 'unconfirmed'], LEGAL_NAME),
    checks('Language', 'langs', ['f90', 'c'], { f90: 'Fortran', c: 'C' }),
    checks('Model', 'models', ['omp', 'acc'], { omp: 'OpenMP', acc: 'OpenACC' }),
    checks('Status', 'st', ['open', 'changed', 'mixed', 'fixed', 'not-reproduced', 'not-run'], ST_NAME),
    el('button', { type: 'button', class: 'btn', 'data-key': 'reset', 'data-value': '',
      onclick: () => set(Object.assign({}, DEFAULTS, { fams: S.fams })) }, 'Reset filters'));
}

const FAMILIES_LIST = FAMILIES;  // static/toolchains.js: the family buttons' order

function render() {
  if (!DATA) return;
  renderFilters();
  const rows = sorted(DATA.issues.filter((i) => i.defect === i.id && matches(i)));
  const n = (k) => rows.filter((i) => i.kind === k).length;
  const findings = rows.reduce((s, i) => s + Math.max(1, i.reproducers), 0);
  const all = S.fams.length === FAMILIES.length;
  document.getElementById('heading').textContent = 'Observed issues' + (all ? '' : ': '
    + S.fams.map((f) => FAM_NAME[f].split(' (')[0]).join(', ')) + (S.vers.length ? ' ' + S.vers.join(', ') : '');
  document.getElementById('summary').textContent = `${rows.length} issues shown (${findings} reproducers): ` +
    `${n('incorrect')} appear to behave incorrectly, ${n('unsupported')} appear not to support a feature.`;
  const term = S.q.trim().toLowerCase();
  const others = term ? FAMILIES_LIST.filter((f) => !S.fams.includes(f)).map((f) => [f, DATA.issues.filter((i) => i.defect === i.id
    && (i.fams || {})[f] && S.st.includes(i.fams[f].status) && searchRank(i, term) <= 2).length]).filter(([, k]) => k) : [];
  document.getElementById('also').replaceChildren(...(others.length ? [el('span', { class: 'small' }, `"${S.q}" also matches: `),
    ...others.map(([f, k]) => el('button', { type: 'button', class: 'btn', onclick: () => set({ fams: toggledFams(S.fams, f) }) },
      `${FAM_NAME[f].split(' (')[0]} (${k})`))] : []));
  const list = document.getElementById('list');
  list.replaceChildren(...(rows.length ? rows.map(row) : [el('p', { class: 'sub', style: 'padding:16px' }, 'No issues match these filters.')]));
  document.getElementById('sorts').replaceChildren(el('span', { class: 'small' }, 'Sort by'),
    ...[['fixed', 'Wrong answers, regressions, reach'], ['version', 'Newest failing version'], ['construct', 'Construct']]
      .map(([k, l]) => el('button', { type: 'button', class: 'btn', 'aria-pressed': String(S.sort === k),
        'data-key': 'sort', 'data-value': k, onclick: () => set({ sort: k }) }, l)),
    el('button', { type: 'button', class: 'btn', id: 'copy-link', 'data-key': 'copy', onclick: copyLink },
      'Copy link to this view'),
    el('button', { type: 'button', class: 'btn', 'data-key': 'csv', onclick: () => downloadCsv(rows) }, 'Download CSV'),
    el('span', { id: 'copy-out', role: 'status', class: 'small' }));
  const q = document.getElementById('q');
  if (q && document.activeElement !== q) q.value = S.q;
}

// "Copy link": says so when the clipboard took it; where the clipboard API is missing or
// refuses, shows the URL selected, ready to copy by hand.
function copyLink() {
  const url = location.href;
  const out = document.getElementById('copy-out');
  const shown = () => {
    const box = el('input', { type: 'text', readonly: true, value: url, 'aria-label': 'Link to this view',
      class: 'mono', style: 'width:100%;max-width:520px;font:inherit' });
    out.replaceChildren(el('span', {}, 'Copy this link: '), box);
    box.focus(); box.select();
  };
  if (!navigator.clipboard || !window.isSecureContext) { shown(); return; }
  navigator.clipboard.writeText(url).then(() => { out.replaceChildren('Link copied.'); }, shown);
}

function downloadCsv(rows) {
  const esc = (v) => '"' + String(Array.isArray(v) ? v.join(' ') : v ?? '').replace(/"/g, '""') + '"';
  const text = [CSV_COLUMNS.join(',')].concat(rows.map((i) => CSV_COLUMNS.map((c) => esc(i[c])).join(','))).join('\n');
  const a = el('a', { href: URL.createObjectURL(new Blob([text], { type: 'text/csv' })), download: 'offload-issues.csv' });
  document.body.append(a); a.click(); a.remove();
}

if (typeof document !== 'undefined') document.addEventListener('DOMContentLoaded', () => {
  const q = document.getElementById('q');
  if (q) {
    q.form && q.form.addEventListener('submit', (e) => { e.preventDefault(); set({ q: q.value }); });
    q.addEventListener('input', () => set({ q: q.value }));
  }
  // on a narrow screen the filters start folded, so the list is the first thing below the heading
  const box = document.getElementById('filters-box');
  if (box && window.matchMedia && window.matchMedia('(max-width: 760px)').matches) box.open = false;
  fetch('data/issues.json').then((r) => r.json()).then((d) => { DATA = d; render(); })
    .catch(() => { document.getElementById('summary').textContent = 'The issue data could not be loaded.'; });
});
