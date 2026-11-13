// # Finding (GCC 16.2, application corpus): OpenACC tile(32, 32) over loops whose trip counts are not multiples of 32 computes
//   wrong elements
//
// - toolchains: gcc_g90 (GCC 16.2.0, AMD Instinct MI250X gfx90a, Tioga) and gcc_sm80 (GCC 16.2.0, NVIDIA A100 sm_80, wingtip);
//   separate memory only; -O2
// - build: gcc -fopenacc -foffload=amdgcn-amdhsa -foffload-options=amdgcn-amdhsa=-march=gfx90a -O2 (gcc_g90); -foffload=nvptx-none
//   -foffload-options=nvptx-none=-march=sm_80 -foffload-options=nvptx-none=-latomic -O2 (gcc_sm80)
// - failure: wrong_answer
// - observed: `bad= 4342` (of the 10000 elements checked) and check=fail in every run (gcc_sm80: mandatory wrong 5 of 5; unset
//   wrong 5 of 5; gcc_g90: mandatory wrong 5 of 5; unset wrong 5 of 5 (results/parity/<machine>/<tc>/probes.jsonl))
// - expected: `bad= 0`, then `RESULT ran_on_host=0 check=pass`
// - rule: "Each loop in the nest will be split, or strip-mined, into two loops, an outer tile loop and an inner element loop. The
//   trip count of the element loop will be limited to the corresponding tile size from the size-expr-list" (OpenACC 3.4 §2.9.8
//   l.2486-2489): tiling reorders the iterations of the nest, each still runs once. The tile clause is OpenACC 2.0's; GCC documents
//   OpenACC 2.6.
// - same-compiler control (correct, gcc_sm80: mandatory pass 5 of 5; unset pass 5 of 5; gcc_g90: mandatory pass 5 of 5; unset pass
//   5 of 5 (results/parity/<machine>/<tc>/probes.jsonl)): collapse(2) in place of tile(32, 32) (controls/gcc-acc-c-tile-control.c).
//   With trip counts of 64 (multiples of the tile size) the tiled form is correct too, and so is a one-loop tile(32) (C and
//   Fortran, both GPUs, mandatory pass 5 of 5, unset pass 5 of 5; results/parity/probes-r2/tile_mult32.*, tile_one_loop.*).
// - application: prk-c-stencil-acc (C1z/stencil-openacc.c, stencil_openacc.h) of the Parallel Research Kernels
//   (data/bench/apps/manifest.yaml): its stencil kernels are `acc parallel loop tile(32,32)` over the interior of a 1000 x
//   1000 grid;
//   GCC's run prints `ERROR: L1 norm = 21.912356 Reference L1 norm = 22.000000`, exit 1 on both GPUs
//   (results/parity/<machine>/results/apps/runs). NVHPC 25.11 and 26.9 validate it (results/apps/wingtip/runs).
// - other families: NVHPC 25.11 and 26.9 run this file correctly in both memory modes (C OpenACC: no AFAR or CCE support) (site
//   matrix). The site's finding matrix runs this file on every compiler.
// - legality: OpenACC 3.4 §2.9.8; the nest is tightly nested and every iteration writes its own element (no race). GCC is a
//   compiler under test only and never a legality witness.
#include <stdio.h>
#include <stdlib.h>
#include <openacc.h>

int main(void) {
  const int n = 100;
  int *a = malloc(n * n * sizeof(int));
  int bad = 0, host_flag = 1;
  for (int k = 0; k < n * n; k++) a[k] = 0;
#pragma acc parallel loop tile(32, 32) copy(a[0:n*n])
  for (int i = 1; i < n - 1; i++)
    for (int j = 1; j < n - 1; j++)
      a[i * n + j] += i + j;
#pragma acc parallel num_gangs(1) copy(host_flag)
  host_flag = acc_on_device(acc_device_host);
  for (int i = 0; i < n; i++)
    for (int j = 0; j < n; j++) {
      int want = (i > 0 && i < n - 1 && j > 0 && j < n - 1) ? i + j : 0;
      bad += a[i * n + j] != want;
    }
  printf("bad= %d\n", bad);
  printf("RESULT ran_on_host=%d check=%s\n", host_flag, bad ? "fail" : "pass");
  free(a);
  return 0;
}
// site:
// title: OpenACC tile(32, 32) over loops whose trip counts are not multiples of the tile size computes wrong elements
// summary: A parallel loop tile(32, 32) over a 98 x 98 (or 100 x 100) nest should run every iteration once. GCC 16.2 leaves 4342 of
// + the 10000 elements it checks wrong (C and Fortran), on the MI250X and the A100. The same nest with collapse(2), or with trip
// + counts that are multiples of 32, is correct. Found through the Parallel Research Kernels' OpenACC stencil.
// control: apps/controls/gcc-acc-c-tile-control.c collapse(2) in place of tile(32, 32)
// end site
