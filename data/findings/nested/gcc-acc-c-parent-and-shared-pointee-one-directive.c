// # Finding (nested-data): GCC OpenACC: copyin of a new parent and of its pointer member's target, which is already present, in
// # one enter data directive stops at run time: "enclosing struct not mapped for attach"
//
// - toolchains and modes that fail: gcc_g90 (GCC 16.2.0), gcc_sm80 (GCC 16.2.0); modes: copy; -O2
// - build: gcc -fopenacc -foffload=amdgcn-amdhsa -foffload-options=amdgcn-amdhsa=-march=gfx90a -O2 (gcc_g90); gcc -fopenacc
//   -foffload=nvptx-none -foffload-options=nvptx-none=-march=sm_80 -foffload-options=nvptx-none=-latomic -O2 (gcc_sm80)
// - failure: run_error
// - observed: `exit_status: 1`; identical signature on 2 of 2 failing cells
// - expected: compiles and prints `tot= 25` with `check=pass`
// - rule: OpenACC 3.4 §2.7.8 p.55 l.1902-1903: "If var is a pointer reference, an attach pointer action is performed
//   followed by an increment counter action"; attach actions are scheduled after the transfers of the same directive
//   (§2.7.2 p.52 l.1785-1786), and the target of the pointer is present (it was mapped by the first parent)
// - same-compiler control: controls/e2-ctl-two-directives.c (one change from this file; correct on gcc_g90 (GCC 16.2.0), gcc_sm80
//   (GCC 16.2.0); rows results/nested/red/red9.jsonl, results/nested/red/wgs.jsonl, results/nested/red/wnv.jsonl);
//   controls/e3-ctl-attach-clause.c (one change from this file; correct on gcc_g90 (GCC 16.2.0), gcc_sm80 (GCC 16.2.0); rows
//   results/nested/red/red9.jsonl, results/nested/red/wgs.jsonl, results/nested/red/wnv.jsonl)
// - other families: nvhpc (NVHPC 25.11), nvhpc269 (NVHPC 26.9) run the file correctly (rows results/nested/red/wnv.jsonl)
// - gate and confirmer: campaign gate of the programs below: 32 cells, 32 confirmed in the four environments (a-d; (c) on another
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
//   results/nested/main/rows.part.tioga37.2691037.jsonl, results/nested/main/rows.part.wingtip.3363229.jsonl,
//   results/nested/main/rows.part.wingtip.3363230.jsonl)
// - programs (16): nd-c-acc-enter-alias-d2-7309596a, nd-c-acc-enter-alias-d2-8d638b4c, nd-c-acc-enter-alias-d2-afeabcf3,
//   nd-c-acc-enter-aliassub-d2-0a90f75a, nd-c-acc-enter-aliassub-d2-0ca27fa7, nd-c-acc-enter-aliassub-d2-a27eabb0,
//   nd-c-acc-enter-aliassub-d2-deeda44f, nd-c-acc-enter-aliassub-d2-e893a050, nd-c-acc-enter-diamond-d3-10d00adc,
//   nd-c-acc-enter-diamond-d3-35c7e4c2, nd-c-acc-enter-diamond-d3-5ba7e8ba, nd-c-acc-enter-diamond-d3-699c342b,
//   nd-c-acc-enter-diamond-d3-76ded6c0, nd-c-acc-enter-diamond-d3-ac852196, nd-c-acc-enter-diamond-d3-b4186a11,
//   nd-c-acc-enter-diamond-d3-b5ee2a63
// - legality: the rules (offload.engine.rules) accept it; both NVHPC releases compile and run the reduction correctly (a
//   compiler of another family; the registry has no OpenACC C clause checker, so this is acceptance and execution, not a
//   clause check)
#include <stdio.h>
#include <stdlib.h>
#include <openacc.h>
struct leaf { int *a; };
struct mid { struct leaf *c; };
struct top { int v; struct mid *l; struct mid *r; };
int main(void)
{
  int hf = 1, i, tot = 0, ok;
  struct top t;
  t.v = 5;
  t.l = malloc(sizeof *t.l);
  t.r = malloc(sizeof *t.r);
  t.l->c = malloc(sizeof *t.l->c);
  t.r->c = t.l->c;                       /* one leaf, two parents */
  t.l->c->a = malloc(4 * sizeof(int));
  for (i = 0; i < 4; i++) t.l->c->a[i] = i + 1;
  #pragma acc serial copy(hf)
  hf = acc_on_device(acc_device_host) ? 1 : 0;
  #pragma acc enter data copyin(t)
  #pragma acc enter data copyin(t.l[0:1])
  #pragma acc enter data copyin(t.l->c[0:1])
  #pragma acc enter data copyin(t.l->c->a[0:4])
  #pragma acc enter data copyin(t.r[0:1], t.r->c[0:1])
  #pragma acc serial copy(tot) present(t)
  {
    tot = t.v;
    for (int q = 0; q < 4; q++) tot += t.l->c->a[q] + t.r->c->a[q];
  }
  #pragma acc exit data delete(t.r->c[0:1])
  #pragma acc exit data delete(t.r[0:1])
  #pragma acc exit data delete(t.l->c->a[0:4])
  #pragma acc exit data delete(t.l->c[0:1])
  #pragma acc exit data delete(t.l[0:1])
  #pragma acc exit data delete(t)
  ok = tot == 25;
  printf("tot= %d\n", tot);
  printf("RESULT ran_on_host=%d check=%s\n", hf, ok ? "pass" : "fail");
  return 0;
}

// site:
// title: GCC OpenACC: second parent of a present pointee stops at run time
// summary: GCC stops with "enclosing struct not mapped for attach" at an enter data naming a second parent of a present pointee.
// control: nested/controls/e2-ctl-two-directives.c one change from the finding; correct on gcc_g90, gcc_sm80
// control: nested/controls/e3-ctl-attach-clause.c one change from the finding; correct on gcc_g90, gcc_sm80
// end site
