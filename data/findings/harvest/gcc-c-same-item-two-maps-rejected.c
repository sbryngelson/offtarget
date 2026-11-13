// # Finding (GCC 16.2, harvests): the same variable in two map clauses of one target construct is rejected
//
// - toolchains: gcc_g90 (GCC 16.2.0, AMD Instinct MI250X gfx90a, Tioga) and gcc_sm80 (GCC 16.2.0, NVIDIA A100 sm_80, wingtip);
//   separate memory only; -O2
// - build: gcc -fopenmp -foffload=amdgcn-amdhsa -foffload-options=amdgcn-amdhsa=-march=gfx90a -O2 (gcc_g90); -foffload=nvptx-none
//   -foffload-options=nvptx-none=-march=sm_80 -foffload-options=nvptx-none=-latomic -O2 (gcc_sm80)
// - failure: rejected: error: 'x' appears more than once in map clauses
// - observed: `error: 'x' appears more than once in map clauses` at the target directive, on both targets
// - expected: compiles; prints `x= 112` and `RESULT ran_on_host=0 check=pass`
// - rule: "A list item may appear more than once in the map clauses that are specified on the same directive" (5.2 §5.8.3 p.151
//   l.14-15).
// - same-compiler control (compiles; correct, gcc_sm80: mandatory pass 5 of 5; unset pass 5 of 5; gcc_g90: mandatory pass 5 of 5;
//   unset pass 5 of 5 (results/parity/<machine>/<tc>/probes.jsonl)): the variable in one map clause, map(tofrom: x)
//   (controls/gcc-c-same-item-two-maps-control.c).
// - GCC's documentation: no row of libgomp.texi's tables names it (undocumented). GCC's own development testsuite has programs of
//   this form (libgomp target-map-multi-*, harvested from gcc master 9e5dc385 into harvest2), so later GCC accepts it. On a target
//   data construct the same form ends in an internal compiler error instead (gcc-c-target-data-two-maps-ice.c).
// - other families: AFAR, CCE 19/20/21/21.0.4 and NVHPC 25.11/26.9 compile and run this file correctly (site matrix); on the
//   harvested programs AFAR and CCE are correct, NVHPC fails them another way. The site's finding matrix runs this file on every
//   compiler.
// - harvested programs (6 cells (3 gcc_g90, 3 gcc_sm80); gate: confirmed 6; confirmer: compiler_bug (R11-compile-rejection) 6):
//   h2-gomp-ccc-target-map-multi-1, h2-gomp-ccc-target-map-multi-2, hv-llvm-mapping-map-ordering-tgt-alloc-tofrom
// - legality: the pre-run check (offload.engine.prerun.check: the rules and AFAR's front end, two witnesses) accepts the harvested
//   programs. GCC is a compiler under test only and never a legality witness.
#include <stdio.h>
#include <omp.h>

int main(void) {
  int x = 111, host_flag = 1;
  /* the same list item in two map clauses of one construct */
#pragma omp target map(alloc: x) map(tofrom: x) map(tofrom: host_flag)
  {
    host_flag = omp_is_initial_device();
    x = x + 1;
  }
  printf("x= %d\n", x);
  printf("RESULT ran_on_host=%d check=%s\n", host_flag, x == 112 ? "pass" : "fail");
  return 0;
}
// site:
// title: The same variable in two map clauses of one target construct is rejected
// summary: OpenMP 5.2 allows a list item in more than one map clause of one directive. GCC 16.2 rejects a target construct
// + with map(alloc: x) map(tofrom: x) for both offload targets; its documentation does not list the gap.
// control: harvest/controls/gcc-c-same-item-two-maps-control.c the variable in one map clause, map(tofrom: x)
// end site
