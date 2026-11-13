// Feature support: a construct or clause -> what each compiler did with it, per GPU and memory mode.
// The rows (CU_TC), the GPU/mode columns (CU_TG), each row's GPU kind (CU_KIND) and the targets
// it ran on (CU_RUN) come from static/toolchains.js, generated from catalog/toolchains.yaml and
// loaded before this script.
// the data's states (offload/engine/site/data.py canuse) in the site's cell words
const CU_WORD = { correct: 'correct', incorrect: 'behaves incorrectly', unsupported: 'not supported', unknown: 'unknown' };
const CU_CLASS = { correct: 's-correct', incorrect: 's-fails-like', unsupported: 's-fails-like', unknown: 's-unknown' };

function cuEl(tag, attrs, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) e.setAttribute(k, v);
  for (const k of kids.flat()) if (k !== null && k !== undefined) e.append(k.nodeType ? k : String(k));
  return e;
}

function cuCell(r, tc, t) {
  const v = r.cells[tc + '|' + t];
  if (!v) {
    return (CU_RUN[tc] || []).includes(t) ? cuEl('span', { class: 'v s-unknown', title: 'not run' }, 'unknown')
      : cuEl('span', { class: 'v s-na', title: 'not run on this GPU' }, 'n/a');
  }
  return cuEl('span', Object.assign({ class: 'v ' + (CU_CLASS[v.state] || 's-unknown') }, v.reason ? { title: v.reason } : {}),
    CU_WORD[v.state] || 'unknown');
}

function cuShow(atom) {
  const out = document.getElementById('cu-out');
  if (!atom) { out.replaceChildren(); return; }
  fetch('data/canuse/' + atom[0] + '.json').then((r) => r.json()).then((part) => {
    const rows = part[atom] || [];
    if (!rows.length) { out.replaceChildren(cuEl('p', { class: 'sub' }, 'No catalog program for ' + atom + '.')); return; }
    const tgs = CU_TG.amd.concat(CU_TG.nvidia);
    out.replaceChildren(...rows.map((r) => {
      const head = cuEl('tr', {}, cuEl('th', { scope: 'col' }, 'Compiler'), ...tgs.map(([, n]) => cuEl('th', { scope: 'col' }, n)));
      const body = CU_TC.map(([tc, name]) => cuEl('tr', {}, cuEl('th', { scope: 'row' }, name),
        ...tgs.map(([t]) => cuEl('td', {}, cuCell(r, tc, t)))));
      const issues = (r.issues || []).length ? cuEl('div', {}, cuEl('h3', {}, 'Observed issues with ' + atom),
        cuEl('ul', {}, r.issues.map((i) => cuEl('li', {}, cuEl('a', { href: 'issues/' + i.page + '.html' }, i.title))))) : null;
      return cuEl('section', {}, cuEl('h2', {}, `${atom} (${r.model === 'acc' ? 'OpenACC' : 'OpenMP'} ${r.version}, ` +
        `${r.lang === 'c' ? 'C' : 'Fortran'})`),
      r.citation ? cuEl('p', { class: 'small' }, r.citation) : null,
      cuEl('div', { class: 'box' }, cuEl('table', {}, cuEl('thead', {}, head), cuEl('tbody', {}, body))),
      cuEl('p', { class: 'small' }, 'Hover a cell for the reason where one is recorded.'), issues);
    }));
  }).catch(() => { out.replaceChildren(cuEl('p', { class: 'sub' }, 'The data for ' + atom + ' could not be loaded.')); });
}

// The message for a construct named in the URL (?c=) that the catalog does not have; null when
// there is nothing to say (no name, or a known one).
function cuMissing(value, atoms) {
  if (!value || atoms.includes(value)) return null;
  return `No catalog program for "${value}". Type a construct or clause from the list` +
    (atoms.length ? `, e.g. ${atoms[0]}.` : '.');
}

// The browsable list of constructs and clauses, grouped by kind and then by name; the text box narrows it.
const CU_KINDS = [['directive', 'Directives'], ['clause', 'Clauses'], ['base', 'Base language in device code'],
  ['pair', 'Two features together'], ['form', 'Other forms']];

function cuBrowse(atoms, q, pick) {
  const box = document.getElementById('cu-browse');
  if (!box) return;
  const want = (q || '').trim().toLowerCase();
  const shown = atoms.filter((a) => !want || a.toLowerCase().includes(want));
  const sections = CU_KINDS.map(([k, title]) => {
    const mine = shown.filter((a) => a.split('.')[0] === k);
    if (!mine.length) return null;
    const groups = {};
    for (const a of mine) (groups[a.split('.')[1] || a] = groups[a.split('.')[1] || a] || []).push(a);
    const names = Object.keys(groups);
    // names break after an underscore or a dot, never inside a word
    const label = (x) => x.replace(/([_.+])/g, '$1\u200b');
    const link = (a) => {
      const l = cuEl('a', { href: '?c=' + encodeURIComponent(a) }, label(a.split('.').slice(1).join('.') || a));
      l.addEventListener('click', (ev) => { ev.preventDefault(); pick(a); });
      return l;
    };
    // a name with one entry is a link; a name with several folds them under it
    return cuEl('section', {}, cuEl('h2', {}, `${title} (${mine.length})`),
      cuEl('div', { class: 'browse-groups' }, names.map((n) => groups[n].length === 1
        ? cuEl('div', { class: 'one' }, link(groups[n][0]))
        : cuEl('details', want || names.length < 8 ? { open: '' } : {},
          cuEl('summary', {}, `${label(n)} (${groups[n].length})`),
          cuEl('ul', {}, groups[n].map((a) => cuEl('li', {}, link(a))))))));
  });
  box.replaceChildren(...(shown.length ? sections : [cuEl('p', { class: 'sub' }, 'Nothing matches "' + q + '".')]));
}

if (typeof document !== 'undefined') document.addEventListener('DOMContentLoaded', () => {
  const input = document.getElementById('cu-q');
  const out = document.getElementById('cu-out');
  fetch('data/canuse/index.json').then((r) => r.json()).then((atoms) => {
    const dl = document.getElementById('cu-atoms');
    dl.replaceChildren(...atoms.map((a) => cuEl('option', { value: a })));
    const show = (v) => { input.value = v; history.replaceState(null, '', '?c=' + encodeURIComponent(v)); cuShow(v);
      out.scrollIntoView({ block: 'start' }); };
    const pick = () => { const v = input.value.trim(); if (atoms.includes(v)) { show(v); } else { cuBrowse(atoms, v, show); } };
    input.addEventListener('change', pick);
    input.addEventListener('input', pick);
    cuBrowse(atoms, '', show);
    const first = new URLSearchParams(location.search).get('c');
    const miss = cuMissing(first, atoms);
    if (miss) { input.value = first; out.replaceChildren(cuEl('p', { class: 'sub', role: 'status' }, miss)); }
    else if (first) { input.value = first; cuShow(first); }
  }).catch(() => { out.replaceChildren(cuEl('p', { class: 'sub' }, 'The construct list could not be loaded.')); });
});
