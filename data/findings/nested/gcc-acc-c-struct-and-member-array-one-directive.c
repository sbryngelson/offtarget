// # Finding (nested-data): GCC OpenACC: copyin of a structure and of the array its pointer member points to in one data
// # directive stops at run time: "outer struct not mapped for attach"
//
// - toolchains and modes that fail: gcc_g90 (GCC 16.2.0), gcc_sm80 (GCC 16.2.0); modes: copy; -O2
// - build: gcc -fopenacc -foffload=amdgcn-amdhsa -foffload-options=amdgcn-amdhsa=-march=gfx90a -O2 (gcc_g90); gcc -fopenacc
//   -foffload=nvptx-none -foffload-options=nvptx-none=-march=sm_80 -foffload-options=nvptx-none=-latomic -O2 (gcc_sm80)
// - failure: wrong_answer (check=fail)
// - observed: `libgomp: outer struct not mapped for attach`; identical signature on 2 of 2 failing cells
// - expected: compiles and prints `tot= 15` with `check=pass`
// - rule: OpenACC 3.4 §2.7.8 p.55 l.1902-1903: "If var is a pointer reference, an attach pointer action is performed
//   followed by an increment counter action"; the attach actions of a directive are scheduled after its transfers: "The
//   implementation schedules pointer updates after any data transfers due to transfer in actions that are performed for
//   the same directive." (§2.7.2 p.52 l.1785-1786), so the structure and the array its member points to may be mapped by
//   one directive
// - same-compiler control: controls/c3-ctl-nested-data.c (one change from this file; correct on gcc_g90 (GCC 16.2.0), gcc_sm80 (GCC
//   16.2.0); rows results/nested/red/red6.jsonl, results/nested/red/wgs.jsonl, results/nested/red/wnv.jsonl);
//   controls/c5-acc-serial-struct-and-array.c (one change from this file; correct on gcc_g90 (GCC 16.2.0), gcc_sm80 (GCC 16.2.0);
//   rows results/nested/red/red6.jsonl, results/nested/red/wgs.jsonl, results/nested/red/wnv.jsonl)
// - other families: nvhpc (NVHPC 25.11), nvhpc269 (NVHPC 26.9) run the file correctly (rows results/nested/red/wnv.jsonl, site
//   rows, check case site-nested--gcc-acc-c-struct-and-member-array-one-directive)
// - gate and confirmer: campaign gate of the programs below: 82 cells, 82 confirmed in the four environments (a-d; (c) on another
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
// - programs (41): nd-c-acc-tdata-alias-d2-20ae973e, nd-c-acc-tdata-alias-d2-23c00982, nd-c-acc-tdata-alias-d2-72a1d7e8,
//   nd-c-acc-tdata-alias-d2-af2ec241, nd-c-acc-tdata-chain-d1-0ed1bf12, nd-c-acc-tdata-chain-d1-9886a523,
//   nd-c-acc-tdata-chain-d2-085c13be, nd-c-acc-tdata-chain-d2-1a584322, nd-c-acc-tdata-chain-d2-25c6c4d8,
//   nd-c-acc-tdata-chain-d2-361ca0f9, nd-c-acc-tdata-chain-d2-36b0e127, nd-c-acc-tdata-chain-d2-43985434,
//   nd-c-acc-tdata-chain-d2-462abe25, nd-c-acc-tdata-chain-d2-5e7728c0, nd-c-acc-tdata-chain-d2-85f2a830,
//   nd-c-acc-tdata-chain-d2-a3760a7a, nd-c-acc-tdata-chain-d2-af1ca1e6, nd-c-acc-tdata-chain-d2-d9e6a839,
//   nd-c-acc-tdata-chain-d2-f585dbe8, nd-c-acc-tdata-chain-d2-f85f821b, nd-c-acc-tdata-chain-d3-474c8b58,
//   nd-c-acc-tdata-chain-d3-475cfe44, nd-c-acc-tdata-chain-d3-4bf0e2c8, nd-c-acc-tdata-chain-d3-5c2aa78e,
//   nd-c-acc-tdata-chain-d3-63c6d8ed, nd-c-acc-tdata-chain-d3-8fa68caf, nd-c-acc-tdata-chain-d3-99924776,
//   nd-c-acc-tdata-chain-d3-9d855631, nd-c-acc-tdata-chain-d3-f891fd7c, nd-c-acc-tdata-diamond-d3-6974fab3,
//   nd-c-acc-tdata-diamond-d3-6fe9454b, nd-c-acc-tdata-diamond-d3-87e0b9a8, nd-c-acc-tdata-list-d2-1ab29ba9,
//   nd-c-acc-tdata-list-d2-cc8507d1, nd-c-acc-tdata-list-d3-367465a3, nd-c-acc-tdata-tree-d2-12d76b63,
//   nd-c-acc-tdata-tree-d2-87d4954e, nd-c-acc-tdata-tree-d2-aedfe6ab, nd-c-acc-tdata-tree-d2-fdcb2b5a,
//   nd-c-acc-tdata-tree-d3-335e85bb, nd-c-acc-tdata-tree-d3-98389330
// - legality: the rules (offload.engine.rules) accept it; both NVHPC releases compile and run the reduction correctly (a
//   compiler of another family; the registry has no OpenACC C clause checker, so this is acceptance and execution, not a
//   clause check)
#include <stdio.h>
#include <stdlib.h>
#include <openacc.h>
struct s0 { int v; int *a; };
int main(void)
{
  int hf = 1, i, tot = 0, ok;
  struct s0 r;
  r.v = 5; r.a = malloc(4 * sizeof(int));
  for (i = 0; i < 4; i++) r.a[i] = i + 1;
  #pragma acc serial copy(hf)
  hf = acc_on_device(acc_device_host) ? 1 : 0;
  #pragma acc data copyin(r, r.a[0:4])
  {
    #pragma acc serial copy(tot) present(r)
    {
      tot = r.v;
      for (int q = 0; q < 4; q++) tot += r.a[q];
    }
  }
  ok = tot == 15;
  printf("tot= %d\n", tot);
  printf("RESULT ran_on_host=%d check=%s\n", hf, ok ? "pass" : "fail");
  return 0;
}

// site:
// title: GCC OpenACC: structure and member array in one data directive stops at run time
// summary: GCC stops with "outer struct not mapped for attach" at a data directive naming a structure and its pointee array.
// control: nested/controls/c3-ctl-nested-data.c one change from the finding; correct on gcc_g90, gcc_sm80
// control: nested/controls/c5-acc-serial-struct-and-array.c one change from the finding; correct on gcc_g90, gcc_sm80
// end site
