// # Finding (hecbench): GCC: a target region that reads an array of _Float16 values crashes the compiler (lto1)
//
// - toolchains and modes that fail: gcc_g90 (GCC 16.2.0), gcc_sm80 (GCC 16.2.0); modes: copy; -O2
// - build: gcc -fopenmp -foffload=amdgcn-amdhsa -foffload-options=amdgcn-amdhsa=-march=gfx90a -O2 (gcc_g90); gcc -fopenmp
//   -foffload=nvptx-none -foffload-options=nvptx-none=-march=sm_80 -foffload-options=nvptx-none=-latomic -O2 (gcc_sm80)
// - failure: ice
// - observed: `Please submit a full bug report, with preprocessed source (by using -freport-bug).`; identical signature on 2 of 2
//   failing cells
// - expected: compiles and prints `total= 2048.000000` with `check=pass`
// - rule: "The functionality added to the target directive is the inclusion of an executable region to be executed on a device"
//   (5.2 §13.8 p.284 l.12-13): the region here is a loop that converts each element of a mapped array of _Float16 to float, and
//   the specification names no base type that a target region may not use; with float elements instead the compile succeeds
// - same-compiler control: controls/f16-ctl-float-array.c (one change from this file; correct on gcc_g90 (GCC 16.2.0), gcc_sm80
//   (GCC 16.2.0); rows results/hecbench/red/tio_g90.jsonl, results/hecbench/red/tuo.jsonl, results/hecbench/red/wt1.jsonl)
// - other families: afar (AFAR 24.3.0), cce19 (CCE 19.0.0), cce20 (CCE 20.0.2), cce21 (CCE 21.0.3), cce21_4 (CCE 21.0.4), nvhpc
//   (NVHPC 25.11), nvhpc269 (NVHPC 26.9) run the file correctly (rows results/hecbench/red/tio_g90.jsonl,
//   results/hecbench/red/tuo.jsonl, results/hecbench/red/wt1.jsonl)
// - gate and confirmer: campaign gate of the programs below: 1 cells, 1 confirmed in the four environments (a-d; (c) on another
//   node or GPU; rows results/hecbench/dev/gate_reruns.part.tioga36.2090963.jsonl,
//   results/hecbench/dev/gate_reruns.part.tioga39.2185748.jsonl); 2 of 2 cells reproduce in all four environments (a-d; (c) on
//   another node or GPU than (a); rows results/hecbench/red/tio_g90.jsonl, results/hecbench/red/tio_gate_abd.jsonl,
//   results/hecbench/red/tio_gate_c.jsonl, results/hecbench/red/wt1.jsonl, results/hecbench/red/wt_gate_abd.jsonl,
//   results/hecbench/red/wt_gate_c.jsonl)
// - origin: HeCBench `src/f16sp-omp/main.cpp` (https://github.com/ORNL/HeCBench, commit
//   8f44ff3e69fa003f870963045988190a275534cb), whose gcc_g90 and gcc_sm80 cells fail with the same compiler line, `lto1: internal
//   compiler error: in make_ssa_name_fn, at tree-ssanames.cc:355`. This file is a small program written for this finding and
//   reduced with tools/reduce.py; it holds no benchmark source.
// - programs (1): hecbench-f16sp-omp
// - legality: offload.engine.prerun.check (the rules, and AFAR's front end on Tuolumne, 2026-11-06: two witnesses) accepts this file
//   and the control; CCE and NVHPC compile and run it correctly (front ends of two other families). GCC is a compiler under test
//   only and never a legality witness.
#include <stdio.h>
#include <stdlib.h>
#include <omp.h>

typedef _Float16 half_t;

int main(void)
{
  const int size = 1024;
  int hf = 1;
  half_t *ax = malloc(size * sizeof(half_t));
  float *out = malloc(size * sizeof(float));
  float total = 0.f;
  for (int i = 0; i < size; i++) { ax[i] = 2; out[i] = 0; }
  #pragma omp target map(from: hf)
  hf = omp_is_initial_device() ? 1 : 0;

  #pragma omp target map(to: ax[0:size]) map(from: out[0:size])
  for (int i = 0; i < size; i++)
    out[i] = (float)ax[i];

  for (int i = 0; i < size; i++) total += out[i];
  printf("total= %f\n", total);
  printf("RESULT ran_on_host=%d check=%s\n", hf, total == 2048.f ? "pass" : "fail");
  free(ax);
  free(out);
  return 0;
}

// site:
// title: GCC: compiler crash on _Float16 data in a target region
// summary: GCC 16.2 stops with an internal compiler error in lto1 when a target region reads an array of _Float16 values; the same program with float elements compiles and runs.
// control: hecbench/controls/f16-ctl-float-array.c one change from the finding; correct on gcc_g90, gcc_sm80
// end site
