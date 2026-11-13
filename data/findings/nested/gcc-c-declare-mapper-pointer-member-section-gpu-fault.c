// # Finding (nested-data): GCC: a declare mapper for a structure with a pointer member that maps a section of the pointee makes
// # the kernel fault on the GPU
//
// - toolchains and modes that fail: gcc_g90 (GCC 16.2.0), gcc_sm80 (GCC 16.2.0); modes: copy; -O2
// - build: gcc -fopenmp -foffload=amdgcn-amdhsa -foffload-options=amdgcn-amdhsa=-march=gfx90a -O2 (gcc_g90); gcc -fopenmp
//   -foffload=nvptx-none -foffload-options=nvptx-none=-march=sm_80 -foffload-options=nvptx-none=-latomic -O2 (gcc_sm80)
// - failure: crash
// - observed: `Memory access fault by GPU node-4 (Agent handle: 0x794640) on address 0xbed000. Reason: Unknown.` (killed by signal
//   6); identical signature on 1 of 2 failing cells (gcc_sm80 on a100-s: `libgomp: cuCtxSynchronize error: an illegal memory access
//   was encountered` differ)
// - counted as this failure: gcc_sm80 (GCC 16.2.0): on the A100 the CUDA runtime reports the same dereference of the unattached
//   pointer as an illegal memory access (libgomp: cuCtxSynchronize error, exit status 1) where the HSA runtime on the MI250X aborts
//   with a GPU memory access fault; one defect, reported differently by the two runtimes (50 of 50 repeat runs fail on the A100,
//   data/reports/nested-visibility/wt_repeat.log)
// - expected: compiles and prints `ha= 4028` with `check=pass`
// - rule: OpenMP 5.2 §5.8.8 p.164 l.1-2: "All map clauses that are introduced by a mapper are further subject to mappers
//   that are in scope, except a map clause with list item var maps var without invoking a mapper": the mapper maps the
//   structure and a section of its pointer member, and a map(tofrom: r) applies it; the expected result relies on the
//   mapper attaching that section to the device copy of r (inside the region r.a must refer to the device copy of
//   r.a[0:NM])
// - same-compiler control: controls/gp2-ctl-no-mapper-explicit-maps.c (one change from this file; correct on gcc_g90 (GCC 16.2.0),
//   gcc_sm80 (GCC 16.2.0); rows results/nested/red/red15.jsonl, results/nested/red/tuo22.jsonl, results/nested/red/tuo23.jsonl,
//   results/nested/red/wgs2.jsonl, results/nested/red/wnv2.jsonl)
// - other families: afar (AFAR 24.3.0), cce19 (CCE 19.0.0), cce20 (CCE 20.0.2), cce21 (CCE 21.0.3), cce21_4 (CCE 21.0.4) run the
//   file correctly (rows results/nested/red/tuo23.jsonl, site rows, check case
//   site-nested--gcc-c-declare-mapper-pointer-member-section-gpu-fault); nvhpc (NVHPC 25.11), nvhpc269 (NVHPC 26.9) fail it another
//   way, e.g. `"site-nested--gcc-c-declare-mapper-pointer-member-section-gpu-fault.c", line 38: error: invalid text in pragma`
// - gate and confirmer: campaign gate of the programs below: 44 cells, 43 confirmed in the four environments (a-d; (c) on another
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
// - programs (23): nd-c-omp-mapper-chain-d1-f314e872, nd-c-omp-mapper-chain-d2-647b801f, nd-c-omp-mapper-chain-d2-6cace278,
//   nd-c-omp-mapper-chain-d2-724db78d, nd-c-omp-mapper-chain-d2-75564642, nd-c-omp-mapper-chain-d2-95162abf,
//   nd-c-omp-mapper-chain-d2-9525642f, nd-c-omp-mapper-chain-d2-aa6b2219, nd-c-omp-mapper-chain-d2-b7881884,
//   nd-c-omp-mapper-chain-d2-dbed9877, nd-c-omp-mapper-chain-d2-e3b718a2, nd-c-omp-mapper-chain-d3-12f05097,
//   nd-c-omp-mapper-chain-d3-1eb36c71, nd-c-omp-mapper-chain-d3-70dd651f, nd-c-omp-mapper-chain-d3-ec8da702,
//   nd-c-omp-mapper-chain-d4-0eb32acd, nd-c-omp-mapper-chain-d4-36e66203, nd-c-omp-mapper_enter-chain-d1-dc9d313d,
//   nd-c-omp-mapper_enter-chain-d2-07229cfd, nd-c-omp-mapper_enter-chain-d2-df4f2688, nd-c-omp-mapper_enter-chain-d3-09a92f8a,
//   nd-c-omp-mapper_enter-chain-d3-7babd15f, nd-c-omp-mapper_enter-chain-d3-ec1b1655
// - run condition: on gfx90a the GPU fault shows with all eight MI250X GCDs of the node visible to the program
//   (ROCR_VISIBLE_DEVICES unset: the nested campaign's and the gate's run environment): 20 of 20 repeat runs on tioga39
//   and tioga38 (2026-11-03), and the campaign program nd-c-omp-mapper-chain-d2-647b801f 10 of 10. With a single GCD
//   visible (the site matrix pinned one GPU per run) the same binary completes with the correct sum in 40 of 40 runs,
//   environments a-d on two nodes, on every GCD 0-7, and so does the campaign program; two GCDs visible fault 15 of 15,
//   four pass 10 of 10. The control passes either way (10 of 10 with all eight visible). The visible set changes the
//   host address layout after HSA initialization and nothing else, so in both outcomes the device dereferences the host
//   address of r.a, which the mapper did not attach: the fault and the silently right sum are how that one missing
//   mapping surfaces, not two defects. The A100 build fails 50 of 50 runs whatever is visible. The site matrix therefore
//   runs this case with every device visible on the gfx90a toolchain (the site block's devices line). Logs and scripts:
//   data/reports/nested-visibility/
// - legality: the rules (offload.engine.rules) accept it; AFAR and CCE compile and run it correctly (front ends of two other
//   families); NVHPC does not accept the directive in C
#include <stdio.h>
#include <stdlib.h>
#include <omp.h>
enum { NM = 8 };
struct n0 { int s; int *a; };
#pragma omp declare mapper(struct n0 v) map(tofrom: v) map(tofrom: v.a[0:NM])
int main(void)
{
  int hf = 1, i, ha = 0, ok;
  struct n0 r = {0};
  #pragma omp target map(from: hf)
  hf = omp_is_initial_device() ? 1 : 0;
  r.a = malloc(NM * sizeof(int));
  r.s = 10;
  for (i = 0; i < NM; i++) r.a[i] = 100 + i;
  #pragma omp target teams distribute parallel for map(tofrom: r)
  for (int q = 0; q < NM; q++) r.a[q] = 500 + q;
  for (i = 0; i < NM; i++) ha += r.a[i];
  ok = ha == 4028;
  printf("ha= %d\n", ha);
  printf("RESULT ran_on_host=%d check=%s\n", hf, ok ? "pass" : "fail");
  return 0;
}

// site:
// title: GCC: declare mapper with a pointer-member section faults on the GPU
// summary: GCC kernels fault when a declare mapper maps a section of a pointer member.
// control: nested/controls/gp2-ctl-no-mapper-explicit-maps.c one change from the finding; correct on gcc_g90, gcc_sm80
// devices: all gcc_g90
// end site
