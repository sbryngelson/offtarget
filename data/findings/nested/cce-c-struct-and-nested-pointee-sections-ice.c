// # Finding (nested-data): CCE craycc crashes in CodeGen: a target construct maps a structure and the structure and array
// # reached through an embedded structure and a pointer
//
// - toolchains and modes that fail: cce19 (CCE 19.0.0), cce20 (CCE 20.0.2), cce21 (CCE 21.0.3), cce21_4 (CCE 21.0.4); modes:
//   unified, copy; -O2
// - build: craycc -fopenmp -fopenmp-targets=amdgcn-amd-amdhsa -Xopenmp-target=amdgcn-amd-amdhsa -march=gfx942 -O2
// - failure: ice
// - observed: `PLEASE submit a bug report to HPE at https://support.hpe.com/ and include the crash backtrace, preprocessed source,
//   and associated run script.`; identical signature on 8 of 8 failing cells
// - expected: compiles and prints `tot= 16` with `check=pass`
// - rule: "A structure and an element of it may both be list items" in the sense of 5.2 §5.8.3 p.156 l.6-7 ("unless one
//   is the containing structure of the other"), and a section reached through pointer members is a list item of a map
//   clause (§5.8.3 p.151 l.13); the construct maps r, then r.nx.nx[0:1] and r.nx.nx->a[0:8] through the embedded
//   structure r.nx and its pointer member
// - same-compiler control: controls/j1-embedded-struct-pointer-to-struct.c (one change from this file; correct on cce19 (CCE
//   19.0.0), cce20 (CCE 20.0.2), cce21 (CCE 21.0.3), cce21_4 (CCE 21.0.4); rows
//   results/findings-baseline/nested-j-controls.cce.jsonl, results/nested/red/tuo4.jsonl, results/nested/red/tuo5.jsonl,
//   results/nested/red/wgs.jsonl, results/nested/red/wnv.jsonl); controls/j6-ctl-struct-and-one-pointee-level.c (one change from
//   this file; correct on cce19 (CCE 19.0.0), cce20 (CCE 20.0.2), cce21 (CCE 21.0.3), cce21_4 (CCE 21.0.4); rows
//   results/findings-baseline/nested-j-controls.cce.jsonl, results/nested/red/tuo5.jsonl, results/nested/red/wgs.jsonl,
//   results/nested/red/wnv.jsonl); controls/j7-ctl-struct-and-embedded-pointee.c (one change from this file; correct on cce19 (CCE
//   19.0.0), cce20 (CCE 20.0.2), cce21 (CCE 21.0.3), cce21_4 (CCE 21.0.4); rows
//   results/findings-baseline/nested-j-controls.cce.jsonl, results/nested/red/tuo5.jsonl, results/nested/red/wgs.jsonl,
//   results/nested/red/wnv.jsonl); controls/j2-ctl-pointer-instead-of-embedded.c (one change from this file; correct on cce19 (CCE
//   19.0.0), cce20 (CCE 20.0.2), cce21 (CCE 21.0.3), cce21_4 (CCE 21.0.4); rows
//   results/findings-baseline/nested-j-controls.cce.jsonl, results/nested/red/tuo5.jsonl, results/nested/red/wgs.jsonl,
//   results/nested/red/wnv.jsonl)
// - other families: afar (AFAR 24.3.0), nvhpc (NVHPC 25.11), nvhpc269 (NVHPC 26.9), gcc_g90 (GCC 16.2.0), gcc_sm80 (GCC 16.2.0) run
//   the file correctly (rows results/nested/red/tuo5.jsonl, results/nested/red/wgs.jsonl, results/nested/red/wnv.jsonl, site rows,
//   check case site-nested--cce-c-struct-and-nested-pointee-sections-ice)
// - gate and confirmer: campaign gate of the programs below: 40 cells, 40 confirmed in the four environments (a-d; (c) on another
//   node or GPU; rows results/nested/big/gate_reruns.part.tuolumne1010.3222831.jsonl,
//   results/nested/big/gate_reruns.part.tuolumne1012.1040717.jsonl, results/nested/big/gate_reruns.part.tuolumne1030.1284552.jsonl,
//   results/nested/big/gate_reruns.part.tuolumne1176.1251749.jsonl, results/nested/big/gate_reruns.part.tuolumne1245.1517583.jsonl,
//   results/nested/big/gate_reruns.part.tuolumne1246.1434668.jsonl, results/nested/big/rows.part.tuolumne1010.1956389.jsonl,
//   results/nested/big/rows.part.tuolumne1040.1523848.jsonl, results/nested/big/rows.part.tuolumne1604.1239313.jsonl,
//   results/nested/big/rows.part.tuolumne1624.1197409.jsonl, results/nested/big/rows.part.tuolumne1797.1146311.jsonl,
//   results/nested/main/gate_reruns.part.tuolumne1095.961942.jsonl, results/nested/main/gate_reruns.part.tuolumne1789.919396.jsonl,
//   results/nested/main/gate_reruns.part.tuolumne1955.3910568.jsonl,
//   results/nested/main/gate_reruns.part.tuolumne1955.4072524.jsonl, results/nested/main/rows.part.tuolumne1955.994167.jsonl)
// - programs (5): nd-c-omp-always-chain-d2-53712162, nd-c-omp-always-chain-d3-71393589, nd-c-omp-close-chain-d3-87bce034,
//   nd-c-omp-one-chain-d3-9f7ac271, nd-c-omp-one-chain-d3-d6c766c9
// - legality: the rules (offload.engine.rules) accept it; AFAR's clang compiles and runs it (a front end of another family)
#include <stdio.h>
#include <stdlib.h>
#include <omp.h>
struct n2 { int *a; };
struct n1 { struct n2 *nx; };
struct n0 { int v; struct n1 nx; };
int main(void)
{
  int hf = 1, i, tot = 0, ok;
  struct n0 r;
  r.v = 0; r.nx.nx = calloc(1, sizeof *r.nx.nx); r.nx.nx->a = malloc(8 * sizeof(int));
  for (i = 0; i < 8; i++) r.nx.nx->a[i] = 2;
  #pragma omp target map(from: hf)
  hf = omp_is_initial_device() ? 1 : 0;
  #pragma omp target map(tofrom: tot) map(tofrom: r) map(tofrom: r.nx.nx[0:1]) map(tofrom: r.nx.nx->a[0:8])
  {
    for (int q = 0; q < 8; q++) tot += r.nx.nx->a[q];
  }
  ok = tot == 16;
  printf("tot= %d\n", tot);
  printf("RESULT ran_on_host=%d check=%s\n", hf, ok ? "pass" : "fail");
  return 0;
}

// site:
// title: CCE: compiler crash on nested pointee sections in one target construct
// summary: The CCE front end crashes on a target construct mapping nested structures through pointer members.
// control: nested/controls/j1-embedded-struct-pointer-to-struct.c one change from the finding; correct on cce19, cce20, cce21,
// + cce21_4
// control: nested/controls/j6-ctl-struct-and-one-pointee-level.c one change from the finding; correct on cce19, cce20, cce21,
// + cce21_4
// control: nested/controls/j7-ctl-struct-and-embedded-pointee.c one change from the finding; correct on cce19, cce20, cce21,
// + cce21_4
// control: nested/controls/j2-ctl-pointer-instead-of-embedded.c one change from the finding; correct on cce19, cce20, cce21,
// + cce21_4
// end site
