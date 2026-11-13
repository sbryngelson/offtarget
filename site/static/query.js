// The issue list's state <-> the URL query string. Unknown or stale values fall
// back to the defaults, so a shared link never shows a broken page. The
// toolchains (FAMILIES, VERSIONS, TC, TARGETS) come from static/toolchains.js,
// generated from catalog/toolchains.yaml and loaded before this script.
const KINDS = ['incorrect', 'unsupported'];
const STAGES = ['compile', 'link', 'run'];
const LEGALITY = ['confirmed', 'supported', 'contested', 'unconfirmed'];
const LANGS = ['f90', 'c'];
const MODELS = ['omp', 'acc'];
const STATUSES = ['open', 'changed', 'mixed', 'fixed', 'not-reproduced', 'not-run'];
const SORTS = ['fixed', 'version', 'construct'];
// fams: the compiler families shown; all of them by default
const DEFAULTS = { fams: FAMILIES.slice(), vers: [], tg: [], kinds: [], stages: [], legal: [], langs: [], models: [], st: ['open', 'changed', 'mixed'],
  regOnly: false, q: '', sort: 'fixed' };

function pick(list, allowed) { return list.filter((x) => allowed.includes(x)); }

function fromQuery(search) {
  const p = new URLSearchParams(search || '');
  const many = (k) => (p.get(k) ? p.get(k).split(',') : []);
  const named = pick(FAMILIES, many('fam'));
  const fams = named.length ? named : DEFAULTS.fams.slice();
  const st = pick(many('st'), STATUSES);
  return {
    fams,
    vers: pick(many('vers'), fams.flatMap((f) => VERSIONS[f])),
    tg: pick(many('tg'), [...new Set(fams.flatMap((f) => TARGETS[f]))]),
    kinds: pick(many('kinds'), KINDS),
    stages: pick(many('stages'), STAGES),
    legal: pick(many('legal'), LEGALITY),
    langs: pick(many('langs'), LANGS),
    models: pick(many('models'), MODELS),
    st: st.length ? st : DEFAULTS.st.slice(),
    regOnly: p.get('reg') === '1',
    q: (p.get('q') || '').slice(0, 200),
    sort: SORTS.includes(p.get('sort')) ? p.get('sort') : DEFAULTS.sort,
  };
}

function toQuery(state) {
  const s = Object.assign({}, DEFAULTS, state);
  const p = new URLSearchParams();
  if (s.fams.length && s.fams.length < FAMILIES.length) p.set('fam', s.fams.join(','));
  for (const k of ['vers', 'tg', 'kinds', 'stages', 'legal', 'langs', 'models']) if (s[k].length) p.set(k, s[k].join(','));
  if (s.st.join(',') !== DEFAULTS.st.join(',')) p.set('st', s.st.join(','));
  if (s.regOnly) p.set('reg', '1');
  if (s.q) p.set('q', s.q);
  if (s.sort !== DEFAULTS.sort) p.set('sort', s.sort);
  const t = p.toString();
  return t ? '?' + t : '';
}

if (typeof module !== 'undefined') module.exports = { fromQuery, toQuery, DEFAULTS, VERSIONS, TC, TARGETS };
