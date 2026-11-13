// # Finding (nested-data): AFAR and CCE (clang front end) reject target update with a structure and one of its pointer members'
// # arrays in one clause
//
// - toolchains and modes that fail: afar (AFAR 24.3.0), cce19 (CCE 19.0.0), cce20 (CCE 20.0.2), cce21 (CCE 21.0.3), cce21_4 (CCE
//   21.0.4); modes: unified, copy; -O2
// - build: amdclang -fopenmp --offload-arch=gfx942 -O2 (afar); craycc -fopenmp -fopenmp-targets=amdgcn-amd-amdhsa
//   -Xopenmp-target=amdgcn-amd-amdhsa -march=gfx942 -O2 (cce19, cce20, cce21, cce21_4)
// - failure: rejected
// - observed: `site-nested--afar-cce-c-update-struct-and-member-rejected.c:57:40: error: same pointer dereferenced in multiple
//   different ways in map clause expressio`; identical signature on 10 of 10 failing cells
// - expected: compiles and prints `tot= 105` with `check=pass`
// - rule: the list items of a data-motion clause are locators; "The list items that appear in a map clause may include
//   array sections and structure elements" (5.2 §5.8.3 p.151 l.13) and a to or from clause on target update names list
//   items the same way (§5.9 p.165 l.7-14); the restrictions of data-motion clauses are only "Each list item clause must
//   have a mappable type." (5.2 §5.9 p.166 l.13-14); the target update construct has no restriction on two list items
//   with one base variable (§13.9 p.289)
// - same-compiler control: controls/u3-ctl-update-member-only.c (one change from this file; correct on afar (AFAR 24.3.0), cce19
//   (CCE 19.0.0), cce20 (CCE 20.0.2), cce21 (CCE 21.0.3), cce21_4 (CCE 21.0.4); rows results/nested/red/red7.jsonl,
//   results/nested/red/tuo1.jsonl, results/nested/red/wgs.jsonl, results/nested/red/wnv.jsonl); controls/u4-ctl-two-updates.c (one
//   change from this file; correct on afar (AFAR 24.3.0), cce19 (CCE 19.0.0), cce20 (CCE 20.0.2), cce21 (CCE 21.0.3), cce21_4 (CCE
//   21.0.4); rows results/nested/red/red7.jsonl, results/nested/red/tuo1.jsonl, results/nested/red/wgs.jsonl,
//   results/nested/red/wnv.jsonl); controls/u5-ctl-same-list-in-map.c (one change from this file; correct on afar (AFAR 24.3.0),
//   cce19 (CCE 19.0.0), cce20 (CCE 20.0.2), cce21 (CCE 21.0.3), cce21_4 (CCE 21.0.4); rows results/nested/red/red7.jsonl,
//   results/nested/red/tuo1.jsonl, results/nested/red/wgs.jsonl, results/nested/red/wnv.jsonl)
// - other families: nvhpc (NVHPC 25.11), nvhpc269 (NVHPC 26.9), gcc_g90 (GCC 16.2.0), gcc_sm80 (GCC 16.2.0) run the file correctly
//   in managed mode (rows results/nested/red/red7.jsonl, results/nested/red/wgs.jsonl, results/nested/red/wnv.jsonl, site rows,
//   check case site-nested--afar-cce-c-update-struct-and-member-rejected); nvhpc (NVHPC 25.11), nvhpc269 (NVHPC 26.9) fail it
//   another way in copy mode, e.g. `Failing in Thread:1`
// - gate and confirmer: campaign gate of the programs below: 590 cells, 590 confirmed in the four environments (a-d; (c) on another
//   node or GPU; rows results/nested/big/gate_reruns.part.tuolumne1010.3222831.jsonl,
//   results/nested/big/gate_reruns.part.tuolumne1012.1040717.jsonl, results/nested/big/gate_reruns.part.tuolumne1030.1284552.jsonl,
//   results/nested/big/gate_reruns.part.tuolumne1176.1251749.jsonl, results/nested/big/gate_reruns.part.tuolumne1245.1517583.jsonl,
//   results/nested/big/gate_reruns.part.tuolumne1246.1434668.jsonl, results/nested/big/rows.part.tuolumne1010.1956389.jsonl,
//   results/nested/big/rows.part.tuolumne1040.1523848.jsonl, results/nested/big/rows.part.tuolumne1604.1239313.jsonl,
//   results/nested/big/rows.part.tuolumne1624.1197409.jsonl, results/nested/big/rows.part.tuolumne1797.1146311.jsonl,
//   results/nested/main/gate_reruns.part.tuolumne1095.961942.jsonl, results/nested/main/gate_reruns.part.tuolumne1789.919396.jsonl,
//   results/nested/main/gate_reruns.part.tuolumne1955.3910568.jsonl,
//   results/nested/main/gate_reruns.part.tuolumne1955.4072524.jsonl, results/nested/main/rows.part.tuolumne1955.994167.jsonl)
// - programs (59): nd-c-omp-update-alias-d2-332dddeb, nd-c-omp-update-alias-d2-684cb0b8, nd-c-omp-update-alias-d2-7e63bd9c,
//   nd-c-omp-update-aliassub-d2-7f474889, nd-c-omp-update-aliassub-d2-94cac870, nd-c-omp-update-aliassub-d2-c7c56309,
//   nd-c-omp-update-chain-d1-7fac5787, nd-c-omp-update-chain-d1-a679e114, nd-c-omp-update-chain-d2-114e1ffc,
//   nd-c-omp-update-chain-d2-1585f8af, nd-c-omp-update-chain-d2-15c71a46, nd-c-omp-update-chain-d2-1f314a7c,
//   nd-c-omp-update-chain-d2-1fcc5e18, nd-c-omp-update-chain-d2-2b8c33ae, nd-c-omp-update-chain-d2-2d0d559e,
//   nd-c-omp-update-chain-d2-44c37206, nd-c-omp-update-chain-d2-60aec85d, nd-c-omp-update-chain-d2-61da37e6,
//   nd-c-omp-update-chain-d2-6af5c7e2, nd-c-omp-update-chain-d2-7f8add9c, nd-c-omp-update-chain-d2-86fbbf97,
//   nd-c-omp-update-chain-d2-a3703a98, nd-c-omp-update-chain-d2-b6fcbb9f, nd-c-omp-update-chain-d2-b7041f75,
//   nd-c-omp-update-chain-d2-bd065bcd, nd-c-omp-update-chain-d2-cca853ce, nd-c-omp-update-chain-d2-db6ed5e2,
//   nd-c-omp-update-chain-d3-05025df3, nd-c-omp-update-chain-d3-0c64953c, nd-c-omp-update-chain-d3-0f5b4780,
//   nd-c-omp-update-chain-d3-1f5ebce9, nd-c-omp-update-chain-d3-2620c220, nd-c-omp-update-chain-d3-2be3a628,
//   nd-c-omp-update-chain-d3-4643770f, nd-c-omp-update-chain-d3-5648fa65, nd-c-omp-update-chain-d3-65936503,
//   nd-c-omp-update-chain-d3-6bc24e3c, nd-c-omp-update-chain-d3-6f0b33d0, nd-c-omp-update-chain-d3-700e7c94,
//   nd-c-omp-update-chain-d3-70128cef, nd-c-omp-update-chain-d3-8b59135d, nd-c-omp-update-chain-d3-8ba10689,
//   nd-c-omp-update-chain-d3-8f2a97eb, nd-c-omp-update-chain-d3-97a31dfc, nd-c-omp-update-chain-d3-a29029aa,
//   nd-c-omp-update-chain-d3-a9134361, nd-c-omp-update-chain-d3-b91a32d4, nd-c-omp-update-chain-d3-c5604bb2,
//   nd-c-omp-update-chain-d4-19f9f60a, nd-c-omp-update-diamond-d3-3f65ce61, nd-c-omp-update-diamond-d3-41a1f708,
//   nd-c-omp-update-diamond-d3-5b90e213, nd-c-omp-update-list-d2-58efae8c, nd-c-omp-update-list-d3-842299a3,
//   nd-c-omp-update-tree-d2-5148e00e, nd-c-omp-update-tree-d2-78bc7f0b, nd-c-omp-update-tree-d2-bf7639b6,
//   nd-c-omp-update-tree-d3-725ebde6, nd-c-omp-update-tree-d3-ca80229f
// - legality: the rules (offload.engine.rules) accept it; GCC compiles and runs it (GCC is no legality witness); the
//   AFAR/CCE C front ends reject it with a diagnostic, so the only other front end is NVHPC nvc, which accepted the
//   campaign's update programs of this form where it ran at all (results/nested/main/witness*.jsonl)
#include <stdio.h>
#include <stdlib.h>
#include <omp.h>
struct s { int v; int *a; };
int main(void)
{
  int hf = 1, i, tot = 0, ok;
  struct s *r = malloc(sizeof *r);
  r->v = 5; r->a = malloc(4 * sizeof(int));
  for (i = 0; i < 4; i++) r->a[i] = i + 1;
  #pragma omp target map(from: hf)
  hf = omp_is_initial_device() ? 1 : 0;
  #pragma omp target enter data map(to: r[0:1]) map(to: r->a[0:4])
  for (i = 0; i < 4; i++) r->a[i] = 10 * (i + 1);
  #pragma omp target update to(r[0:1], r->a[0:4])
  #pragma omp target map(tofrom: tot)
  { tot = r->v; for (int q = 0; q < 4; q++) tot += r->a[q]; }
  #pragma omp target exit data map(release: r->a[0:4]) map(release: r[0:1])
  ok = tot == 105;
  printf("tot= %d\n", tot);
  printf("RESULT ran_on_host=%d check=%s\n", hf, ok ? "pass" : "fail");
  return 0;
}

// site:
// title: target update with a structure and a member array in one clause rejected
// summary: AFAR and CCE reject a target update clause naming a structure and the array its pointer member points to.
// control: nested/controls/u3-ctl-update-member-only.c one change from the finding; correct on afar, cce19, cce20, cce21, cce21_4
// control: nested/controls/u4-ctl-two-updates.c one change from the finding; correct on afar, cce19, cce20, cce21, cce21_4
// control: nested/controls/u5-ctl-same-list-in-map.c one change from the finding; correct on afar, cce19, cce20, cce21, cce21_4
// end site
