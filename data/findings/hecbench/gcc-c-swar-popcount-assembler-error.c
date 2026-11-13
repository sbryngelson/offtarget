// # Finding (hecbench): GCC (gfx90a): a bit-counting loop in a target region makes the generated assembly invalid
// (v_bcnt_u32_b32)
//
// - toolchains and modes that fail: gcc_g90 (GCC 16.2.0); modes: copy; -O2
// - build: gcc -fopenmp -foffload=amdgcn-amdhsa -foffload-options=amdgcn-amdhsa=-march=gfx90a -O2
// - failure: ice
// - observed: `<tmpdir>/ccRlCeSn.mkoffload.2.s:126:2: error: too few operands for instruction`; identical signature on 1 of 1
//   failing cells
// - expected: compiles and prints `bad= 0` with `check=pass`
// - rule: "The functionality added to the target directive is the inclusion of an executable region to be executed on a device"
//   (5.2 §13.8 p.284 l.12-13): the region is a loop of integer shifts, masks and one multiplication (the parallel-sum popcount
//   idiom); the specification limits no integer operation in a target region, and with the last step written as shifts and adds,
//   or as __builtin_popcountll, the compile succeeds
// - same-compiler control: controls/pc-ctl-shift-sum.c (one change from this file; correct on gcc_g90 (GCC 16.2.0); rows
//   results/hecbench/red/tio_g90.jsonl, results/hecbench/red/tuo.jsonl, results/hecbench/red/wt1.jsonl);
//   controls/pc-ctl-builtin-popcount.c (one change from this file; correct on gcc_g90 (GCC 16.2.0); rows
//   results/hecbench/red/tio_g90.jsonl, results/hecbench/red/tuo.jsonl, results/hecbench/red/wt1.jsonl)
// - other families: afar (AFAR 24.3.0), cce19 (CCE 19.0.0), cce20 (CCE 20.0.2), cce21 (CCE 21.0.3), cce21_4 (CCE 21.0.4), nvhpc
//   (NVHPC 25.11), nvhpc269 (NVHPC 26.9), gcc_sm80 (GCC 16.2.0) run the file correctly (rows results/hecbench/red/tio_g90.jsonl,
//   results/hecbench/red/tuo.jsonl, results/hecbench/red/wt1.jsonl)
// - gate and confirmer: campaign gate of the programs below: 1 cells, 1 confirmed in the four environments (a-d; (c) on another
//   node or GPU; rows results/hecbench/dev/gate_reruns.part.tioga36.2090963.jsonl,
//   results/hecbench/dev/gate_reruns.part.tioga39.2185748.jsonl); 1 of 1 cells reproduce in all four environments (a-d; (c) on
//   another node or GPU than (a); rows results/hecbench/red/tio_g90.jsonl, results/hecbench/red/tio_gate_abd.jsonl,
//   results/hecbench/red/tio_gate_c.jsonl)
// - origin: HeCBench `src/popcount-omp/main.cpp` (https://github.com/ORNL/HeCBench, commit
//   8f44ff3e69fa003f870963045988190a275534cb), whose gcc_g90 cell fails at the link with `error: too few operands for
//   instruction` in mkoffload's assembly. This file is a small program written for this finding and reduced with tools/reduce.py;
//   the bit-counting steps are the textbook parallel-sum popcount, and it holds no benchmark source.
// - programs (1): hecbench-popcount-omp
// - legality: offload.engine.prerun.check (the rules, and AFAR's front end on Tuolumne, 2026-11-06: two witnesses) accepts this file
//   and the controls; AFAR, CCE and NVHPC compile and run it correctly (front ends of three other families). GCC is a compiler
//   under test only and never a legality witness.
#include <stdio.h>
#include <stdlib.h>
#include <omp.h>

#define M1 0x5555555555555555UL
#define M2 0x3333333333333333UL
#define M4 0x0f0f0f0f0f0f0f0fUL
#define H01 0x0101010101010101UL

int main(void)
{
  const int length = 1024;
  int hf = 1, bad = 0;
  unsigned long *data = malloc(length * sizeof(unsigned long));
  int *result = malloc(length * sizeof(int));
  for (int i = 0; i < length; i++)
    data[i] = (unsigned long)(i + 1) * 0x9E3779B97F4A7C15UL;
  #pragma omp target map(from: hf)
  hf = omp_is_initial_device() ? 1 : 0;

  #pragma omp target map(to: data[0:length]) map(from: result[0:length])
  for (int i = 0; i < length; i++) {
    unsigned long x = data[i];
    x -= (x >> 1) & M1;
    x = (x & M2) + ((x >> 2) & M2);
    x = (x + (x >> 4)) & M4;
    result[i] = (x * H01) >> 56;
  }

  for (int i = 0; i < length; i++) {
    int count = 0;
    for (unsigned long y = data[i]; y; count++) y &= y - 1;
    if (count != result[i]) bad++;
  }
  printf("bad= %d\n", bad);
  printf("RESULT ran_on_host=%d check=%s\n", hf, bad == 0 ? "pass" : "fail");
  free(data);
  free(result);
  return 0;
}

// site:
// title: GCC: invalid assembly for a bit-counting loop on MI250X
// summary: GCC 16.2 for gfx90a emits a v_bcnt_u32_b32 instruction with a missing operand for the parallel-sum popcount loop in a target region, so the offload link fails; shift-and-add and the builtin compile.
// control: hecbench/controls/pc-ctl-shift-sum.c one change from the finding; correct on gcc_g90
// control: hecbench/controls/pc-ctl-builtin-popcount.c one change from the finding; correct on gcc_g90
// end site
