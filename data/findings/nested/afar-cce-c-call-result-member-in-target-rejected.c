// # Finding (nested-data): AFAR and CCE (clang front end) reject a member access through a call result inside a target region:
// # "expected addressable lvalue in 'map' clause"
//
// - toolchains and modes that fail: afar (AFAR 24.3.0), cce19 (CCE 19.0.0), cce20 (CCE 20.0.2), cce21 (CCE 21.0.3), cce21_4 (CCE
//   21.0.4); modes: unified, copy; -O2
// - build: amdclang -fopenmp --offload-arch=gfx942 -O2 (afar); craycc -fopenmp -fopenmp-targets=amdgcn-amd-amdhsa
//   -Xopenmp-target=amdgcn-amd-amdhsa -march=gfx942 -O2 (cce19, cce20, cce21, cce21_4)
// - failure: rejected
// - observed: `site-nested--afar-cce-c-call-result-member-in-target-rejected.c:48:50: error: expected addressable lvalue in 'map'
//   clause`; identical signature on 10 of 10 failing cells
// - expected: compiles and prints `tot= 10` with `check=pass`
// - rule: only variables referenced in a target construct get an implicit data-mapping attribute: "the first matching
//   rule from the following list determines the implicit data-mapping (or data-sharing) attribute for variables
//   referenced in a target construct" (5.2 §5.8.1 p.148 l.3-5); the member `child(r)->a` is a structure element reached
//   through a function result, not a variable, and r->nx->a[0:4] is mapped explicitly
// - same-compiler control: controls/p2-ctl-pointer-variable.c (one change from this file; correct on afar (AFAR 24.3.0), cce19 (CCE
//   19.0.0), cce20 (CCE 20.0.2), cce21 (CCE 21.0.3), cce21_4 (CCE 21.0.4); rows results/nested/red/red7.jsonl,
//   results/nested/red/tuo1.jsonl, results/nested/red/wgs.jsonl, results/nested/red/wnv.jsonl); controls/p3-ctl-direct-member.c
//   (one change from this file; correct on afar (AFAR 24.3.0), cce19 (CCE 19.0.0), cce20 (CCE 20.0.2), cce21 (CCE 21.0.3), cce21_4
//   (CCE 21.0.4); rows results/nested/red/red7.jsonl, results/nested/red/tuo1.jsonl, results/nested/red/wgs.jsonl,
//   results/nested/red/wnv.jsonl)
// - other families: nvhpc (NVHPC 25.11), nvhpc269 (NVHPC 26.9), gcc_g90 (GCC 16.2.0), gcc_sm80 (GCC 16.2.0) run the file correctly
//   (rows results/nested/red/red7.jsonl, results/nested/red/wgs.jsonl, results/nested/red/wnv.jsonl, site rows, check case
//   site-nested--afar-cce-c-call-result-member-in-target-rejected)
// - gate and confirmer: campaign gate of the programs below: 10 cells, 10 confirmed in the four environments (a-d; (c) on another
//   node or GPU; rows results/nested/big/gate_reruns.part.tuolumne1012.1040717.jsonl,
//   results/nested/big/gate_reruns.part.tuolumne1030.1284552.jsonl, results/nested/big/gate_reruns.part.tuolumne1176.1251749.jsonl,
//   results/nested/big/gate_reruns.part.tuolumne1245.1517583.jsonl, results/nested/big/gate_reruns.part.tuolumne1246.1434668.jsonl,
//   results/nested/big/rows.part.tuolumne1010.1956389.jsonl, results/nested/big/rows.part.tuolumne1040.1523848.jsonl,
//   results/nested/big/rows.part.tuolumne1604.1239313.jsonl, results/nested/big/rows.part.tuolumne1624.1197409.jsonl,
//   results/nested/big/rows.part.tuolumne1797.1146311.jsonl, results/nested/main/gate_reruns.part.tuolumne1095.961942.jsonl,
//   results/nested/main/gate_reruns.part.tuolumne1789.919396.jsonl,
//   results/nested/main/gate_reruns.part.tuolumne1955.3910568.jsonl,
//   results/nested/main/gate_reruns.part.tuolumne1955.4072524.jsonl, results/nested/main/rows.part.tuolumne1955.994167.jsonl)
// - programs (1): nd-fnres-c-child-pointer
// - legality: the rules (offload.engine.rules) accept it; GCC compiles and runs it; the clang front ends of AFAR and CCE are
//   the two compilers that reject it (they share a lineage, so neither witnesses the other)
#include <stdio.h>
#include <stdlib.h>
#include <omp.h>
struct n { int *a; struct n *nx; };
#pragma omp declare target
static struct n *child(struct n *r) { return r->nx; }
#pragma omp end declare target
int main(void)
{
  int hf = 1, i, tot = 0, ok;
  struct n *r = calloc(1, sizeof *r);
  r->nx = calloc(1, sizeof *r->nx);
  r->nx->a = malloc(4 * sizeof(int));
  for (i = 0; i < 4; i++) r->nx->a[i] = i + 1;
  #pragma omp target map(from: hf)
  hf = omp_is_initial_device() ? 1 : 0;
  #pragma omp target map(tofrom: tot) map(to: r[0:1]) map(to: r->nx[0:1]) map(to: r->nx->a[0:4])
  {
    for (int q = 0; q < 4; q++) tot += child(r)->a[q];
  }
  ok = tot == 10;
  printf("tot= %d\n", tot);
  printf("RESULT ran_on_host=%d check=%s\n", hf, ok ? "pass" : "fail");
  return 0;
}

// site:
// title: AFAR and CCE: member of a function result in a target region rejected
// summary: AFAR and CCE reject a member access through a function call result inside a target region.
// control: nested/controls/p2-ctl-pointer-variable.c one change from the finding; correct on afar, cce19, cce20, cce21, cce21_4
// control: nested/controls/p3-ctl-direct-member.c one change from the finding; correct on afar, cce19, cce20, cce21, cce21_4
// end site
