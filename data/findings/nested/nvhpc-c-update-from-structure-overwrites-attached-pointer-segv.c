// # Finding (nested-data): NVHPC, separate memory: target update from() or exit data map(from:) of a structure whose pointer
// # member is attached copies the device pointer back, and the next host access to the pointee crashes
// # (SIGSEGV)
//
// - toolchains and modes that fail: nvhpc (NVHPC 25.11), nvhpc269 (NVHPC 26.9); modes: copy; -O2
// - build: nvc -mp=gpu -gpu=cc80 -gpu=mem:separate -O2
// - failure: crash
// - observed: `crash: SIGSEGV; without mandatory: crash: SIGSEGV` (killed by signal SEGV); identical signature on 2 of 2 failing
//   cells
// - expected: compiles and prints `ha= 4028` with `check=pass`
// - rule: OpenMP 5.2 §5.9 p.166 l.5-7: "if the corresponding list item is an attached pointer, the original list item
//   will have the value it had on entry to the region": a target update from() of a structure must not overwrite its
//   pointer member while the member is attached (the same holds when exit data map(from:) copies the structure back
//   before the pointee is released)
// - same-compiler control: controls/nu3-ctl-update-pointee-only.c (one change from this file; correct on nvhpc (NVHPC 25.11),
//   nvhpc269 (NVHPC 26.9); rows results/nested/red/tuo23.jsonl, results/nested/red/wgs6.jsonl, results/nested/red/wnv6.jsonl);
//   controls/ns8-ctl-enter-together-exit-split.c (one change from this file; correct on nvhpc (NVHPC 25.11), nvhpc269 (NVHPC 26.9);
//   rows results/nested/red/tuo22.jsonl, results/nested/red/tuo23.jsonl, results/nested/red/wgs4.jsonl,
//   results/nested/red/wnv4.jsonl); controls/ns4-ctl-two-directives-struct-then-pointee.c (one change from this file; correct on
//   nvhpc (NVHPC 25.11), nvhpc269 (NVHPC 26.9); rows results/nested/red/red16.jsonl, results/nested/red/tuo22.jsonl,
//   results/nested/red/wgs3.jsonl, results/nested/red/wnv3.jsonl)
// - other families: afar (AFAR 24.3.0), cce21_4 (CCE 21.0.4), gcc_sm80 (GCC 16.2.0) run the file correctly (rows
//   results/nested/red/tuo23.jsonl, results/nested/red/wgs6.jsonl)
// - gate and confirmer: campaign gate of the programs below: 70 cells, 70 confirmed in the four environments (a-d; (c) on another
//   node or GPU; rows results/nested/big/gate_reruns.part.wingtip.501872.jsonl,
//   results/nested/big/gate_reruns.part.wingtip.501873.jsonl,
//   results/nested/big/gate_reruns.part.wingtip.711615.jsonl,
//   results/nested/big/gate_reruns.part.wingtip.724122.jsonl,
//   results/nested/big/rows.part.wingtip.3693360.jsonl,
//   results/nested/big/rows.part.wingtip.3790312.jsonl,
//   results/nested/main/gate_reruns.part.wingtip.3582436.jsonl,
//   results/nested/main/gate_reruns.part.wingtip.3582437.jsonl,
//   results/nested/main/gate_reruns.part.wingtip.3637854.jsonl,
//   results/nested/main/gate_reruns.part.wingtip.3639010.jsonl,
//   results/nested/main/rows.part.wingtip.3363229.jsonl,
//   results/nested/main/rows.part.wingtip.3363230.jsonl)
// - programs (35): nd-c-omp-enter-alias-d2-0f7b1c8d, nd-c-omp-enter-alias-d2-10f14204, nd-c-omp-enter-aliassub-d2-28acd136,
//   nd-c-omp-enter-aliassub-d2-30b02f09, nd-c-omp-enter-aliassub-d2-3cc740c1, nd-c-omp-enter-aliassub-d2-fd23e3be,
//   nd-c-omp-enter-chain-d1-7ce2e18f, nd-c-omp-enter-chain-d2-35aa80e0, nd-c-omp-enter-chain-d2-99ea7db8,
//   nd-c-omp-enter-chain-d2-fb177d2e, nd-c-omp-enter-chain-d3-41b3b77f, nd-c-omp-enter-chain-d3-5bca046a,
//   nd-c-omp-enter-chain-d3-c1680a02, nd-c-omp-enter-chain-d3-c2ca2645, nd-c-omp-enter-chain-d3-fc976865,
//   nd-c-omp-enter-diamond-d3-07ab92f3, nd-c-omp-enter-diamond-d3-41750fb6, nd-c-omp-enter-diamond-d3-5e5ed99d,
//   nd-c-omp-enter-diamond-d3-d5e537a9, nd-c-omp-enter-diamond-d3-f1a9c3e8, nd-c-omp-enter-list-d3-e11a72cd,
//   nd-c-omp-enter-tree-d3-e0467211, nd-c-omp-update-alias-d2-684cb0b8, nd-c-omp-update-chain-d1-a679e114,
//   nd-c-omp-update-chain-d2-1585f8af, nd-c-omp-update-chain-d2-2b8c33ae, nd-c-omp-update-chain-d2-44c37206,
//   nd-c-omp-update-chain-d2-60aec85d, nd-c-omp-update-chain-d2-a3703a98, nd-c-omp-update-chain-d2-b6fcbb9f,
//   nd-c-omp-update-chain-d2-cca853ce, nd-c-omp-update-chain-d2-db6ed5e2, nd-c-omp-update-chain-d3-5648fa65,
//   nd-c-omp-update-chain-d3-a9134361, nd-c-omp-update-chain-d3-c5604bb2
// - legality: the rules (offload.engine.rules) accept it; AFAR and CCE compile and run it correctly (front ends of two other
//   families)
#include <stdio.h>
#include <stdlib.h>
#include <omp.h>
enum { NM = 8 };
struct n0 { int s; int *a; };
int main(void)
{
  int hf = 1, i, ha = 0, ok;
  struct n0 *r = calloc(1, sizeof *r);
  #pragma omp target map(from: hf)
  hf = omp_is_initial_device() ? 1 : 0;
  r->a = malloc(NM * sizeof(int));
  r->s = -1;
  for (i = 0; i < NM; i++) r->a[i] = -1;
  #pragma omp target enter data map(alloc: r[0:1])
  #pragma omp target enter data map(alloc: r->a[0:8])
  #pragma omp target teams distribute parallel for
  for (int q = 0; q < NM; q++) r->a[q] = 500 + q;
  #pragma omp target update from(r[0:1])
  #pragma omp target update from(r->a[0:8])
  #pragma omp target exit data map(delete: r->a[0:8])
  #pragma omp target exit data map(delete: r[0:1])
  for (i = 0; i < NM; i++) ha += r->a[i];
  ok = ha == 4028;
  printf("ha= %d\n", ha);
  printf("RESULT ran_on_host=%d check=%s\n", hf, ok ? "pass" : "fail");
  return 0;
}

// site:
// title: NVHPC: update from of a structure overwrites its attached pointer member
// summary: NVHPC update from() of a structure copies the device pointer back and the next host access crashes.
// control: nested/controls/nu3-ctl-update-pointee-only.c one change from the finding; correct on nvhpc, nvhpc269
// control: nested/controls/ns8-ctl-enter-together-exit-split.c one change from the finding; correct on nvhpc, nvhpc269
// control: nested/controls/ns4-ctl-two-directives-struct-then-pointee.c one change from the finding; correct on nvhpc, nvhpc269
// end site
