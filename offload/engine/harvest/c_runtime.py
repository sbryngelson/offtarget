"""The C self-check appended to a converted C test
(offload.engine.harvest.convert). It follows the rules of
offload.engine.harvest.checks.match (tests/bench/test_harvest_runtime.py compares them).

Before the original ``main`` (renamed ``hv_orig_main``), one target region
records whether it ran on the host, and stdout goes to a file. At exit
(``atexit``) the captured output is echoed (``HV| `` lines, at most 300),
the CHECK directives are matched against it, and ``RESULT
ran_on_host=<0|1> check=<pass|fail>`` is printed, preceded by
``HV-FAIL <why>`` on a mismatch. The exit status stays the original's.

``DATA`` names the per-program arrays the converter emits: ``hv_n``,
``hv_kind`` (0 CHECK, 1 NEXT, 2 SAME, 3 NOT, 4 DAG, 5 EMPTY), ``hv_mode``
(0 tokens, 1 regex), ``hv_pat``, ``hv_defs``, ``hv_merge``, ``hv_nargs``,
``hv_args`` and ``hv_call``."""

KIND_CODE = {"CHECK": 0, "NEXT": 1, "SAME": 2, "NOT": 3, "DAG": 4, "EMPTY": 5}

PRELUDE = "#define _DEFAULT_SOURCE 1\n"

RUNTIME = r"""
/* ===== self-check (offload/engine/harvest/c_runtime.py) ===== */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>
#include <unistd.h>
#include <fcntl.h>
#include <regex.h>
#include <omp.h>

@@DATA@@

static int hv_host = 1, hv_out = -1, hv_err = -1, hv_done = 0;
static char hv_path[96];
static char **hv_line = 0;
static int hv_nl = 0;
static char *hv_vname[64], *hv_vval[64];
static int hv_nv = 0;

static int hv_isword(int c) { return isalnum(c) || c == '_'; }

/* the next token of s at or after i: [*st, *en); -1 at the end */
static int hv_tok(const char *s, int i, int *st, int *en) {
  while (s[i] && isspace((unsigned char)s[i])) i++;
  if (!s[i]) return -1;
  *st = i;
  if (isdigit((unsigned char)s[i]) ||
      (s[i] == '.' && isdigit((unsigned char)s[i + 1]))) {
    if (s[i] == '.') {
      i++;
      while (isdigit((unsigned char)s[i])) i++;
    } else {
      while (isdigit((unsigned char)s[i])) i++;
      if (s[i] == '.') {
        i++;
        while (isdigit((unsigned char)s[i])) i++;
      }
    }
    if (s[i] == 'e' || s[i] == 'E' || s[i] == 'd' || s[i] == 'D') {
      int j = i + 1;
      if (s[j] == '+' || s[j] == '-') j++;
      if (isdigit((unsigned char)s[j])) {
        while (isdigit((unsigned char)s[j])) j++;
        i = j;
      }
    }
  } else if (isalpha((unsigned char)s[i]) || s[i] == '_') {
    while (hv_isword((unsigned char)s[i])) i++;
  } else {
    i++;
  }
  *en = i;
  return 0;
}

/* 0 number, 1 word, 2 punctuation */
static int hv_tkind(const char *t, int n) {
  if (isdigit((unsigned char)t[0]) || (t[0] == '.' && n > 1)) return 0;
  if (isalpha((unsigned char)t[0]) || t[0] == '_') return 1;
  return 2;
}

static int hv_intlike(const char *t, int n) {
  for (int k = 0; k < n; k++)
    if (strchr(".eEdD", t[k])) return 0;
  return 1;
}

static double hv_num(const char *t, int n) {
  char b[128];
  if (n > 127) n = 127;
  for (int k = 0; k < n; k++)
    b[k] = (t[k] == 'd' || t[k] == 'D') ? 'e' : t[k];
  b[n] = 0;
  return strtod(b, 0);
}

static int hv_teq(const char *p, int pn, const char *o, int on) {
  if (hv_tkind(p, pn) == 0 && hv_tkind(o, on) == 0) {
    if (hv_intlike(p, pn) && hv_intlike(o, on)) {
      while (pn > 1 && p[0] == '0') { p++; pn--; }
      while (on > 1 && o[0] == '0') { o++; on--; }
      if (pn == 1 && p[0] == '0' && on == 1 && o[0] == '0') return 1;
      return pn == on && memcmp(p, o, pn) == 0;
    }
    double a = hv_num(p, pn), b = hv_num(o, on);
    double fa = a < 0 ? -a : a, fb = b < 0 ? -b : b;
    double m = fa > fb ? fa : fb;
    return a == b || (a - b <= 1e-5 * m && b - a <= 1e-5 * m);
  }
  return pn == on && memcmp(p, o, pn) == 0;
}

/* where: 0 only, 1 first, 2 last, 3 middle */
static int hv_tok_ok(const char *p, int pn, const char *o, int on,
                     int where) {
  if (hv_tkind(p, pn) == 1 && hv_tkind(o, on) == 1) {
    if (where == 0) {
      for (int k = 0; k + pn <= on; k++)
        if (memcmp(o + k, p, pn) == 0) return 1;
      return 0;
    }
    if (where == 1) return on >= pn && memcmp(o + on - pn, p, pn) == 0;
    if (where == 2) return on >= pn && memcmp(o, p, pn) == 0;
  }
  return hv_teq(p, pn, o, on);
}

#define HV_MAXT 8192
static int hv_ts[HV_MAXT], hv_te[HV_MAXT], hv_ps[HV_MAXT], hv_pe[HV_MAXT];

static int hv_tokens(const char *s, int *st, int *en) {
  int n = 0, i = 0, a, b;
  while (n < HV_MAXT && hv_tok(s, i, &a, &b) == 0) {
    st[n] = a;
    en[n] = b;
    n++;
    i = b;
  }
  return n;
}

/* the first occurrence of a segment's tokens in line at or after col */
static int hv_find_seg(const char *seg, const char *line, int col, int *ms,
                       int *me) {
  int np = hv_tokens(seg, hv_ps, hv_pe);
  int nt = hv_tokens(line, hv_ts, hv_te);
  if (np == 0) { *ms = *me = col; return 1; }
  for (int i = 0; i + np <= nt; i++) {
    if (hv_ts[i] < col) continue;
    int ok = 1;
    for (int j = 0; j < np && ok; j++) {
      int where = np == 1 ? 0 : j == 0 ? 1 : j == np - 1 ? 2 : 3;
      ok = hv_tok_ok(seg + hv_ps[j], hv_pe[j] - hv_ps[j],
                     line + hv_ts[i + j], hv_te[i + j] - hv_ts[i + j], where);
    }
    if (ok) {
      *ms = hv_ts[i];
      *me = hv_te[i + np - 1];
      return 1;
    }
  }
  return 0;
}

static int hv_find_tokens(const char *pat, const char *line, int col, int *ms,
                          int *me) {
  int start = -1, c = col, s, e;
  const char *p = pat;
  char seg[4096];
  while (1) {
    const char *q = strchr(p, '\002');
    size_t n = q ? (size_t)(q - p) : strlen(p);
    if (n >= sizeof seg) n = sizeof seg - 1;
    memcpy(seg, p, n);
    seg[n] = 0;
    if (n > 0) {
      if (!hv_find_seg(seg, line, c, &s, &e)) return 0;
      if (start < 0) start = s;
      c = e;
    }
    if (!q) break;
    p = q + 1;
  }
  if (start < 0) { *ms = *me = col; return 1; }
  *ms = start;
  *me = c;
  return 1;
}

static const char *hv_var(const char *name, size_t n) {
  for (int k = hv_nv - 1; k >= 0; k--)
    if (strlen(hv_vname[k]) == n && memcmp(hv_vname[k], name, n) == 0)
      return hv_vval[k];
  return 0;
}

static void hv_setvar(const char *name, size_t n, const char *val, size_t vn) {
  if (hv_nv >= 64) return;
  hv_vname[hv_nv] = (char *)malloc(n + 1);
  memcpy(hv_vname[hv_nv], name, n);
  hv_vname[hv_nv][n] = 0;
  hv_vval[hv_nv] = (char *)malloc(vn + 1);
  memcpy(hv_vval[hv_nv], val, vn);
  hv_vval[hv_nv][vn] = 0;
  hv_nv++;
}

static int hv_find_regex(int i, const char *line, int col, int *ms, int *me,
                         int capture) {
  static char ere[16384];
  size_t o = 0;
  const char *p = hv_pat[i];
  while (*p && o < sizeof ere - 4) {
    if (*p == '\001') {
      const char *q = strchr(p + 1, '\001');
      if (!q) return 0;
      const char *v = hv_var(p + 1, (size_t)(q - p - 1));
      if (!v) return 0;
      for (; *v && o < sizeof ere - 4; v++) {
        if (strchr("\\.[]{}()*+?^$|", *v)) ere[o++] = '\\';
        ere[o++] = *v;
      }
      p = q + 1;
    } else {
      ere[o++] = *p++;
    }
  }
  ere[o] = 0;
  regex_t rx;
  if (regcomp(&rx, ere, REG_EXTENDED) != 0) return 0;
  regmatch_t pm[32];
  int len = (int)strlen(line);
  if (col > len) col = len;
  int r = regexec(&rx, line + col, 32, pm, col > 0 ? REG_NOTBOL : 0);
  regfree(&rx);
  if (r != 0) return 0;
  *ms = col + (int)pm[0].rm_so;
  *me = col + (int)pm[0].rm_eo;
  if (capture && hv_defs[i][0]) {
    const char *d = hv_defs[i];
    while (*d) {
      const char *eq = strchr(d, '=');
      const char *sc = strchr(d, ';');
      if (!eq) break;
      int g = atoi(eq + 1);
      if (g < 32 && pm[g].rm_so >= 0)
        hv_setvar(d, (size_t)(eq - d), line + col + pm[g].rm_so,
                  (size_t)(pm[g].rm_eo - pm[g].rm_so));
      if (!sc) break;
      d = sc + 1;
    }
  }
  return 1;
}

static int hv_find(int i, const char *line, int col, int *ms, int *me,
                   int capture) {
  if (hv_mode[i] == 0) return hv_find_tokens(hv_pat[i], line, col, ms, me);
  return hv_find_regex(i, line, col, ms, me, capture);
}

static int hv_cur_line = 0, hv_cur_col = 0;

static int hv_search(int i, int l0, int c0, int only, int *L, int *S, int *E) {
  int from = only >= 0 ? only : l0, to = only >= 0 ? only : hv_nl - 1;
  for (int ln = from; ln <= to; ln++) {
    if (ln < 0 || ln >= hv_nl) continue;
    if (hv_find(i, hv_line[ln], ln == l0 ? c0 : 0, S, E, 1)) {
      *L = ln;
      return 1;
    }
  }
  return 0;
}

static int hv_nots[4096];
static int hv_nnots = 0;

/* the first pending CHECK-NOT found before (to_line, to_col), else -1 */
static int hv_check_nots(int to_line, int to_col) {
  for (int k = 0; k < hv_nnots; k++) {
    int last = to_line < hv_nl - 1 ? to_line : hv_nl - 1;
    for (int ln = hv_cur_line; ln <= last; ln++) {
      int s, e;
      if (hv_find(hv_nots[k], hv_line[ln], ln == hv_cur_line ? hv_cur_col : 0,
                  &s, &e, 0) &&
          (ln < to_line || e <= to_col))
        return hv_nots[k];
    }
  }
  return -1;
}

static const char *hv_kname(int k) {
  static const char *n[] = {"CHECK", "CHECK-NEXT", "CHECK-SAME", "CHECK-NOT",
                            "CHECK-DAG", "CHECK-EMPTY"};
  return n[k];
}

static int hv_match(char *why, size_t wn) {
  int started = 0, i = 0;
  hv_cur_line = 0;
  hv_cur_col = 0;
  hv_nnots = 0;
  while (i < hv_n) {
    int k = hv_kind[i], L = 0, S = 0, E = 0, bad;
    if (k == 3) {
      if (hv_nnots < 4096) hv_nots[hv_nnots++] = i;
      i++;
      continue;
    }
    if (k == 4) {
      int j = i, minl = 1 << 30, minc = 1 << 30, maxl = -1, maxc = -1;
      while (j < hv_n && hv_kind[j] == 4) {
        if (!hv_search(j, hv_cur_line, hv_cur_col, -1, &L, &S, &E)) {
          snprintf(why, wn, "CHECK-DAG not found: %s", hv_pat[j]);
          return 0;
        }
        if (L < minl || (L == minl && S < minc)) { minl = L; minc = S; }
        if (L > maxl || (L == maxl && E > maxc)) { maxl = L; maxc = E; }
        j++;
      }
      bad = hv_check_nots(minl, minc);
      if (bad >= 0) {
        snprintf(why, wn, "CHECK-NOT found: %s", hv_pat[bad]);
        return 0;
      }
      hv_nnots = 0;
      hv_cur_line = maxl;
      hv_cur_col = maxc;
      started = 1;
      i = j;
      continue;
    }
    int found;
    if (k == 5) {
      int nxt = started ? hv_cur_line + 1 : 0;
      if (nxt >= hv_nl || hv_line[nxt][0] != 0) {
        snprintf(why, wn, "CHECK-EMPTY: the next line is not empty");
        return 0;
      }
      found = 1;
      L = nxt;
      S = E = 0;
    } else if (k == 1 && started) {
      found = hv_search(i, hv_cur_line + 1, 0, hv_cur_line + 1, &L, &S, &E);
    } else if (k == 2 && started) {
      found = hv_search(i, hv_cur_line, hv_cur_col, hv_cur_line, &L, &S, &E);
    } else {
      found = hv_search(i, hv_cur_line, hv_cur_col, -1, &L, &S, &E);
    }
    if (!found) {
      snprintf(why, wn, "%s not found: %s", hv_kname(k), hv_pat[i]);
      return 0;
    }
    bad = hv_check_nots(L, S);
    if (bad >= 0) {
      snprintf(why, wn, "CHECK-NOT found: %s", hv_pat[bad]);
      return 0;
    }
    hv_nnots = 0;
    hv_cur_line = L;
    hv_cur_col = E;
    started = 1;
    i++;
  }
  int bad = hv_check_nots(hv_nl, 1 << 30);
  if (bad >= 0) {
    snprintf(why, wn, "CHECK-NOT found: %s", hv_pat[bad]);
    return 0;
  }
  return 1;
}

/* the captured text as lines, runs of blanks folded to one */
static void hv_split(char *buf, size_t n) {
  int cap = 64;
  hv_line = (char **)malloc(sizeof(char *) * cap);
  size_t i = 0;
  while (i < n) {
    size_t j = i;
    while (j < n && buf[j] != '\n') j++;
    size_t e = j;
    if (e > i && buf[e - 1] == '\r') e--;
    char *ln = (char *)malloc(e - i + 1);
    size_t o = 0;
    for (size_t k = i; k < e; k++) {
      char c = buf[k] == '\t' ? ' ' : buf[k];
      if (c == ' ' && o > 0 && ln[o - 1] == ' ') continue;
      ln[o++] = c;
    }
    ln[o] = 0;
    if (hv_nl == cap) {
      cap *= 2;
      hv_line = (char **)realloc(hv_line, sizeof(char *) * cap);
    }
    hv_line[hv_nl++] = ln;
    i = j + 1;
  }
}

static void hv_finish(void) {
  if (hv_done) return;
  hv_done = 1;
  fflush(stdout);
  fflush(stderr);
  if (hv_out >= 0) dup2(hv_out, 1);
  if (hv_err >= 0) dup2(hv_err, 2);
  size_t n = 0, cap = 65536;
  char *buf = (char *)malloc(cap);
  int fd = open(hv_path, O_RDONLY);
  if (fd >= 0) {
    ssize_t r;
    while ((r = read(fd, buf + n, cap - n)) > 0) {
      n += (size_t)r;
      if (n == cap) {
        cap *= 2;
        buf = (char *)realloc(buf, cap);
      }
    }
    close(fd);
    unlink(hv_path);
  }
  hv_split(buf, n);
  for (int k = 0; k < hv_nl && k < 300; k++)
    printf("HV| %.200s\n", hv_line[k]);
  char why[512] = "";
  int ok = fd >= 0 && hv_match(why, sizeof why);
  if (fd < 0) snprintf(why, sizeof why, "the captured output is missing");
  if (!ok) printf("HV-FAIL %.150s\n", why);
  printf("RESULT ran_on_host=%d check=%s\n", hv_host, ok ? "pass" : "fail");
  fflush(stdout);
}

static void hv_setup(void) {
  int h = 1;
#pragma omp target map(from: h)
  h = omp_is_initial_device();
  hv_host = h ? 1 : 0;
  fflush(stdout);
  fflush(stderr);
  snprintf(hv_path, sizeof hv_path, "hv_capture_%d.txt", (int)getpid());
  int fd = open(hv_path, O_RDWR | O_CREAT | O_TRUNC, 0600);
  if (fd < 0) return;
  hv_out = dup(1);
  dup2(fd, 1);
  if (hv_merge) {
    hv_err = dup(2);
    dup2(fd, 2);
  }
  close(fd);
}

int main(int argc, char **argv) {
  int rc = 0;
  hv_setup();
  atexit(hv_finish);
  (void)argc;
  (void)argv;
@@CALL@@
  return rc;
}
"""
