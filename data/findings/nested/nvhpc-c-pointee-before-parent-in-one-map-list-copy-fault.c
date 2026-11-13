// # Finding (nested-data): NVHPC, separate memory: a target construct that lists the pointee of a pointer member before the
// # structure that holds the pointer fails with CUDA_ERROR_ILLEGAL_ADDRESS (the other order is correct)
//
// - toolchains and modes that fail: nvhpc (NVHPC 25.11), nvhpc269 (NVHPC 26.9); modes: copy; -O2
// - build: nvc -mp=gpu -gpu=cc80 -gpu=mem:separate -O2
// - failure: run_error
// - observed: `exit_status: 1; without mandatory: exit_status: 1`; identical signature on 2 of 2 failing cells
// - expected: compiles and prints `tot= 1638` with `check=pass`
// - rule: attachment is decided on the storage of the whole construct: OpenMP 6.0 §7.9.6 p.284 l.8-10: "for which a
//   corresponding pointer exists in the device data environment after all mappable storage blocks are mapped" (the
//   OpenMP 5.2 text at §5.8.3 p.152 l.5-7 is worded for the state on entry and is weaker; the finding rests on the 6.0
//   wording), so the order of the clauses of one construct does not change the result
// - same-compiler control: controls/v2-ctl-parent-first.c (one change from this file; correct on nvhpc (NVHPC 25.11), nvhpc269
//   (NVHPC 26.9); rows results/nested/red/red13.jsonl, results/nested/red/tuo12.jsonl, results/nested/red/wgs.jsonl,
//   results/nested/red/wnv.jsonl); controls/v4-ctl-embedded-member.c (one change from this file; correct on nvhpc (NVHPC 25.11),
//   nvhpc269 (NVHPC 26.9); rows results/nested/red/red13.jsonl, results/nested/red/tuo12.jsonl, results/nested/red/wgs.jsonl,
//   results/nested/red/wnv.jsonl)
// - other families: afar (AFAR 24.3.0), cce19 (CCE 19.0.0), cce20 (CCE 20.0.2), cce21 (CCE 21.0.3), cce21_4 (CCE 21.0.4), gcc_g90
//   (GCC 16.2.0), gcc_sm80 (GCC 16.2.0) run the file correctly (rows results/nested/red/red13.jsonl,
//   results/nested/red/tuo12.jsonl, results/nested/red/wgs.jsonl)
// - gate and confirmer: 2 of 2 cells reproduce in all four environments (a-d; (c) node not recorded for every cell; rows
//   results/nested/red/wgate_abd.jsonl, results/nested/red/wgate_c.jsonl, results/nested/red/wnv.jsonl)
// - legality: the rules (offload.engine.rules) accept it; AFAR and CCE compile and run it correctly (front ends of two other
//   families)
#include <stdio.h>
#include <stdlib.h>
#include <omp.h>
struct s1 { int a[8]; };
struct s0 { int v; struct s1 *nx; };
int main(void)
{
  int hf = 1, i, tot = 0, ok;
  #pragma omp target map(from: hf)
  hf = omp_is_initial_device() ? 1 : 0;
  struct s0 *r = malloc(sizeof *r);
  r->v = 10;
  r->nx = malloc(sizeof *r->nx);
  for (i = 0; i < 8; i++) r->nx->a[i] = 200 + i;
  #pragma omp target map(tofrom: tot) map(to: r->nx[0:1]) map(to: r[0:1])
  {
    tot += r->v;
    for (int q = 0; q < 8; q++) tot += r->nx->a[q];
  }
  ok = tot == 1638;
  printf("tot= %d\n", tot);
  printf("RESULT ran_on_host=%d check=%s\n", hf, ok ? "pass" : "fail");
  return 0;
}

// site:
// title: NVHPC: pointee listed before its parent in one map list faults in separate memory
// summary: In separate memory NVHPC faults when a map list names a pointee before the structure holding the pointer.
// control: nested/controls/v2-ctl-parent-first.c one change from the finding; correct on nvhpc, nvhpc269
// control: nested/controls/v4-ctl-embedded-member.c one change from the finding; correct on nvhpc, nvhpc269
// end site
