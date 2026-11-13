// # Finding (GCC 16.2, LLVM/AOMP harvest): the same variable in two map clauses of a target data construct: internal compiler
//   error in install_var_field
//
// - toolchains: gcc_g90 (GCC 16.2.0, AMD Instinct MI250X gfx90a, Tioga) and gcc_sm80 (GCC 16.2.0, NVIDIA A100 sm_80, wingtip);
//   separate memory only; -O2
// - build: gcc -fopenmp -foffload=amdgcn-amdhsa -foffload-options=amdgcn-amdhsa=-march=gfx90a -O2 (gcc_g90); -foffload=nvptx-none
//   -foffload-options=nvptx-none=-march=sm_80 -foffload-options=nvptx-none=-latomic -O2 (gcc_sm80)
// - failure: ice: internal compiler error: in install_var_field
// - observed: `internal compiler error: in install_var_field, at omp-low.cc:806` ("during GIMPLE pass: omplower") at the target
//   data directive, on both targets (the host compiler fails before any offload code is made)
// - expected: compiles; prints `x= 222` and `RESULT ran_on_host=0 check=pass`
// - rule: "A list item may appear more than once in the map clauses that are specified on the same directive" (5.2 §5.8.3 p.151
//   l.14-15).
// - same-compiler control (compiles; correct, gcc_sm80: mandatory pass 5 of 5; unset pass 5 of 5; gcc_g90: mandatory pass 5 of 5;
//   unset pass 5 of 5 (results/parity/<machine>/<tc>/probes.jsonl)): the variable in one map clause, map(from: x)
//   (controls/gcc-c-target-data-two-maps-control.c).
// - other families: AFAR runs the harvested programs correctly (copy mode, MI300A and MI250X); CCE 19/20/21 and NVHPC 25.11/26.9
//   fail them differently (results/harvest/main). The site's finding matrix runs this file on every compiler.
// - harvested programs (8 cells (4 gcc_g90, 4 gcc_sm80); gate: confirmed 8; confirmer: compiler_bug (R10-compile-ice)
//   8): h2-gomp-ccc-target-map-multi-4, hv-llvm-mapping-map-ordering-tgt-data-alloc-from,
//   hv-llvm-mapping-map-ordering-tgt-data-alloc-to-from, hv-llvm-mapping-map-ordering-tgt-exit-data-delete-from
// - legality: the pre-run check (offload.engine.prerun.check: the rules and AFAR's front end, two witnesses) accepts the harvested
//   programs; this file is read against the rule above. GCC is a compiler under test only and never a legality witness.
#include <stdio.h>
#include <omp.h>

int main(void) {
  int x = 111, host_flag = 1;
  /* the same list item in two map clauses of one target data construct */
#pragma omp target data map(alloc: x) map(from: x)
  {
#pragma omp target map(present, alloc: x) map(tofrom: host_flag)
    {
      host_flag = omp_is_initial_device();
      x = 222;
    }
  }
  printf("x= %d\n", x);
  printf("RESULT ran_on_host=%d check=%s\n", host_flag, x == 222 ? "pass" : "fail");
  return 0;
}
// site:
// title: The same variable in two map clauses of a target data construct: internal compiler error
// summary: OpenMP 5.2 allows a list item in more than one map clause of one directive. GCC 16.2 stops with an internal compiler
// + error (install_var_field, omplower) on a target data construct with map(alloc: x) map(from: x), for both offload targets.
// + With the variable in one map clause the same program compiles and runs correctly. AFAR runs the harvested programs
// + correctly.
// control: harvest/controls/gcc-c-target-data-two-maps-control.c the variable in one map clause, map(from: x)
// end site
