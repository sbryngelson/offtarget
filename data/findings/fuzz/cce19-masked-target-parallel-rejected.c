// # Finding (leads): CCE 19 fails to link on a C OpenMP program with a masked construct and a target parallel construct
//
// - toolchains and modes that fail: cce19 (CCE 19.0.0), cce20 (CCE 20.0.2), cce21 (CCE 21.0.3), cce21_4 (CCE 21.0.4); modes:
//   unified, copy; -O2
// - build: craycc -fopenmp -fopenmp-targets=amdgcn-amd-amdhsa -Xopenmp-target=amdgcn-amd-amdhsa -march=gfx942 -O2
// - failure: rejected
// - observed: `lld: error: undefined symbol: __kmpc_masked`; identical signature on 8 of 8 failing cells
// - expected: compiles and runs to completion, printing `RESULT checksum=0 ran_on_host=0`
// - rule: a conforming program compiles and links: "The masked construct specifies a structured block that is executed by a subset
//   of the threads of the current team." (OpenMP 5.2 §10.5 p.238 l.12-13); "The target construct provides a superset of the
//   functionality provided by the target data directive, except for the use_device_ptr and use_device_addr clauses." (OpenMP 5.2
//   §13.8 p.284 l.11-12); "When a thread encounters a parallel construct, a team of threads is created to execute the parallel
//   region (see Section 10.1.1 for more information about how the number of threads in the team is determined, including the
//   evaluation of the if and num_threads clauses)." (OpenMP 5.2 §10.1 p.223 l.12-14)
// - other families: afar (AFAR 24.3.0), afar244 (AFAR 24.4.0), gcc (GCC 16.2.0) run the file correctly (site rows, check case
//   site-fuzz--cce19-masked-target-parallel-rejected)
// - programs (1): c6c1:846
// - legality: the rules engine accepts it (offload.engine.prerun.rules_witness); the legality verdict is computed
//   (tools/review/review.py mechanical)
// - releases: CCE 19.0.0, 20.0.2, 21.0.3 and 21.0.4 fail it the same way
#include <stdio.h>
#include <stdint.h>
#include <stdbool.h>
#include <omp.h>


int main(void) {
  int hf1;
  int64_t cs;
  hf1 = 0;
  #pragma omp target parallel map(tofrom: hf1)
  {
    #pragma omp masked
    {
      hf1 = (omp_is_initial_device() ? 1 : 0);
    }
  }
  cs = 0;
  printf("RESULT checksum=%lld ran_on_host=%d\n", (long long)cs, (hf1 > 0 ? hf1 : 0));
  return 0;
}

// site:
// title: CCE: rejected with masked and target parallel
// summary: CCE 19 fails to link on a C OpenMP program with a masked construct and a target parallel construct.
// end site
