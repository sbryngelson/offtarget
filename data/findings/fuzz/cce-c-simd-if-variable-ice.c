// # Finding (CCE): CCE craycc: a simd construct in a target region whose if clause has a variable condition crashes the device
//   compile (clang codegen, EmitLValueForLambdaField)
//
// - toolchains and modes that fail: cce19 (CCE 19.0.0), cce20 (CCE 20.0.2), cce21 (CCE 21.0.3), cce21_4 (CCE 21.0.4); modes:
//   unified, copy; -O2
// - build: craycc -fopenmp -fopenmp-targets=amdgcn-amd-amdhsa -Xopenmp-target=amdgcn-amd-amdhsa -march=gfx942 -O2
// - failure: ice
// - observed: `PLEASE submit a bug report to HPE at https://support.hpe.com/ and include the crash backtrace, preprocessed source,
//   and associated run script.`; identical signature on 8 of 8 failing cells
// - expected: compiles and runs to completion, printing `RESULT ran_on_host=0 check=pass`
// - rule: if is a clause of the simd construct: "Clauses aligned, collapse, if, lastprivate, linear, nontemporal, order, private,
//   reduction, safelen, simdlen" (OpenMP 5.2 §10.4 p.235 l.5-7), and its effect is a preference only: "When an if clause is present
//   and evaluates to false, the preferred number of iterations to be executed concurrently is one, regardless of whether a simdlen
//   clause is specified." (OpenMP 5.2 §10.4 p.235 l.20-21)
// - same-compiler control: controls/cce-c-simd-if-variable-ice-delete-clause-if-c-control.c (one change from this file: no if
//   clause; correct on cce19 (CCE 19.0.0), cce20 (CCE 20.0.2), cce21 (CCE 21.0.3), cce21_4 (CCE 21.0.4); site rows, check case
//   site-fuzz--cce-c-simd-if-variable-ice)
// - other families: afar (AFAR 24.3.0), afar244 (AFAR 24.4.0), gcc (GCC 16.2.0) run the file correctly (site rows, check case
//   site-fuzz--cce-c-simd-if-variable-ice)
// - legality: legal by reading: one target region with map(tofrom: host); a is mapped tofrom implicitly and written once per
//   iteration, c is firstprivate implicitly (a scalar in a target region) and only read, so there is no data race; the if clause
//   takes a scalar expression and applies to the simd construct, its only leaf. The rules witness (offload.engine.prerun) accepts
//   it, and AFAR's front end compiles and runs it correctly (the site rows); the fuzz program it was reduced from (c6c1 seed 1356,
//   generator fuzz-6c) passed the rules, the C11 base check and a sequential run that printed the model's checksum
// - releases: CCE 19.0.0, 20.0.2, 21.0.3 and 21.0.4 fail it the same way
#include <stdio.h>
#include <omp.h>
enum { n = 64 };
int main(void) {
  int a[n], host = 1, c = 0;
  #pragma omp target map(tofrom: host)
  {
    host = omp_is_initial_device();
    #pragma omp simd if(c)
    for (int i = 0; i < n; i++) a[i] = 2 * i;
  }
  int ok = 1;
  printf("RESULT ran_on_host=%d check=%s\n", host, ok ? "pass" : "fail");
  return 0;
}

// site:
// title: CCE C: simd if(variable) in a target region crashes the compiler
// summary: CCE 19, 20 and 21 crash compiling a C target region that holds a simd construct with an if clause whose condition is a
// + variable; a constant condition, or no if clause, compiles and runs.
// control: fuzz/controls/cce-c-simd-if-variable-ice-delete-clause-if-c-control.c one change from the finding; correct on cce19,
// + cce20, cce21, cce21_4
// end site
