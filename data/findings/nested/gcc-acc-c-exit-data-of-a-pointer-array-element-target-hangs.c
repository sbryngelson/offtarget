// # Finding (nested-data): GCC OpenACC: exit data of the target of an element of a pointer array stops at run time:
// # "goacc_exit_data_internal UNHANDLED kind 0x50" (the program hangs)
//
// - toolchains and modes that fail: gcc_g90 (GCC 16.2.0), gcc_sm80 (GCC 16.2.0); modes: copy; -O2
// - build: gcc -fopenacc -foffload=amdgcn-amdhsa -foffload-options=amdgcn-amdhsa=-march=gfx90a -O2 (gcc_g90); gcc -fopenacc
//   -foffload=nvptx-none -foffload-options=nvptx-none=-march=sm_80 -foffload-options=nvptx-none=-latomic -O2 (gcc_sm80)
// - failure: timeout
// - observed: `RUN_TIMEOUT`; identical signature on 2 of 2 failing cells
// - expected: compiles and prints `tot= 6` with `check=pass`
// - rule: OpenACC 3.4 §2.7.1 p.49 l.1686-1688 describes how the pointers of dynamically allocated dimensions are filled
//   in; the text has no sentence that names a subarray of the target of an element of a pointer array (r.nx[0][0:1]) as
//   a var form, so the legality of the program rests on the rules' reading of var forms and on NVHPC accepting and
//   running it. Exit data with delete or copyout of a var that is present decrements its counters and, for a pointer
//   reference, its attachment counter (3.4 §2.7.12 p.58 l.2023-2024)
// - same-compiler control: controls/f3-pointer-array-only.c (one change from this file; correct on gcc_g90 (GCC 16.2.0), gcc_sm80
//   (GCC 16.2.0); rows results/nested/red/red10.jsonl, results/nested/red/wgs.jsonl, results/nested/red/wnv.jsonl);
//   controls/f5-ctl-copyout-exit.c (one change from this file; correct on gcc_g90 (GCC 16.2.0), gcc_sm80 (GCC 16.2.0); rows
//   results/nested/red/red10.jsonl, results/nested/red/wgs.jsonl, results/nested/red/wnv.jsonl);
//   controls/f6-ctl-pointer-to-struct-array.c (one change from this file; correct on gcc_g90 (GCC 16.2.0), gcc_sm80 (GCC 16.2.0);
//   rows results/nested/red/red10.jsonl, results/nested/red/wgs.jsonl, results/nested/red/wnv.jsonl)
// - other families: nvhpc (NVHPC 25.11), nvhpc269 (NVHPC 26.9) run the file correctly (rows results/nested/red/wnv.jsonl)
// - gate and confirmer: campaign gate of the programs below: 14 cells, 14 confirmed in the four environments (a-d; (c) on another
//   node or GPU; rows results/nested/big/gate_reruns.part.tioga38.1371141.jsonl,
//   results/nested/big/gate_reruns.part.tioga39.517665.jsonl,
//   results/nested/big/gate_reruns.part.wingtip.501872.jsonl,
//   results/nested/big/gate_reruns.part.wingtip.501873.jsonl,
//   results/nested/big/gate_reruns.part.wingtip.711615.jsonl,
//   results/nested/big/gate_reruns.part.wingtip.724122.jsonl, results/nested/big/rows.part.tioga39.397000.jsonl,
//   results/nested/big/rows.part.wingtip.3886921.jsonl,
//   results/nested/main/gate_reruns.part.tioga37.2711328.jsonl, results/nested/main/gate_reruns.part.tioga39.351539.jsonl,
//   results/nested/main/gate_reruns.part.wingtip.3582436.jsonl,
//   results/nested/main/gate_reruns.part.wingtip.3582437.jsonl,
//   results/nested/main/gate_reruns.part.wingtip.3637854.jsonl,
//   results/nested/main/gate_reruns.part.wingtip.3639010.jsonl,
//   results/nested/main/rows.part.tioga37.2691037.jsonl, results/nested/main/rows.part.wingtip.3363230.jsonl)
// - programs (7): nd-c-acc-enter-chain-d2-a882d869, nd-c-acc-enter-chain-d2-e7da4dab, nd-c-acc-enter-chain-d3-315d10d9,
//   nd-c-acc-enter-chain-d3-358c069c, nd-c-acc-enter-chain-d3-b9bb6619, nd-c-acc-enter-chain-d4-1fa7e914,
//   nd-c-acc-enter-chain-d4-658d9bcd
// - legality: the rules (offload.engine.rules) accept it; both NVHPC releases compile and run the reduction correctly (a
//   compiler of another family; the registry has no OpenACC C clause checker, so this is acceptance and execution, not a
//   clause check)
#include <stdio.h>
#include <stdlib.h>
#include <openacc.h>
struct s1 { int *a; };
struct s0 { int v; struct s1 **nx; };
int main(void)
{
  int hf = 1, i, tot = 0, ok;
  struct s0 r;
  r.v = 5;
  r.nx = malloc(2 * sizeof *r.nx);
  for (i = 0; i < 2; i++) {
    r.nx[i] = malloc(sizeof *r.nx[i]);
    r.nx[i]->a = malloc(4 * sizeof(int));
    for (int q = 0; q < 4; q++) r.nx[i]->a[q] = 10 * (i + 1) + q;
  }
  #pragma acc serial copy(hf)
  hf = acc_on_device(acc_device_host) ? 1 : 0;
  #pragma acc enter data copyin(r)
  #pragma acc enter data copyin(r.nx[0:2])
  #pragma acc enter data copyin(r.nx[0][0:1])
  #pragma acc serial copy(tot) present(r)
  {
    tot = r.v;
    tot += 1;
  }
  #pragma acc exit data delete(r.nx[0][0:1])
  #pragma acc exit data delete(r.nx[0:2])
  #pragma acc exit data delete(r)
  ok = tot == 6;
  printf("tot= %d\n", tot);
  printf("RESULT ran_on_host=%d check=%s\n", hf, ok ? "pass" : "fail");
  return 0;
}

// site:
// title: GCC OpenACC: exit data of a pointer-array element target hangs
// summary: GCC prints "UNHANDLED kind 0x50" and hangs after exit data of an element target of a pointer array.
// control: nested/controls/f3-pointer-array-only.c one change from the finding; correct on gcc_g90, gcc_sm80
// control: nested/controls/f5-ctl-copyout-exit.c one change from the finding; correct on gcc_g90, gcc_sm80
// control: nested/controls/f6-ctl-pointer-to-struct-array.c one change from the finding; correct on gcc_g90, gcc_sm80
// end site
