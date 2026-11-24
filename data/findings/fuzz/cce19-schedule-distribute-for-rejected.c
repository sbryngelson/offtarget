// # Finding (leads): CCE 19 fails to link on a C OpenMP program with a schedule clause, a distribute construct and a for construct
//
// - toolchains and modes that fail: cce19 (CCE 19.0.0); modes: unified, copy; -O2
// - build: craycc -fopenmp -fopenmp-targets=amdgcn-amd-amdhsa -Xopenmp-target=amdgcn-amd-amdhsa -march=gfx942 -O2
// - failure: rejected
// - observed: `lld: error: undefined symbol: __kmpc_dispatch_deinit`; identical signature on 2 of 2 failing cells
// - expected: compiles and runs to completion, printing `RESULT checksum=0 ran_on_host=0`
// - rule: a conforming program compiles and links: "The schedule clause specifies how iterations of associated loops of a
//   worksharing-loop construct are divided into contiguous non-empty subsets, called chunks, and how these chunks are distributed
//   among threads of the team." (OpenMP 5.2 §11.5.3 p.252 l.10-12); "The distribute construct specifies that the iterations of one
//   or more loops will be executed by the initial teams in the context of their implicit tasks." (OpenMP 5.2 §11.6 p.254 l.18-19);
//   "Separating directives scan Clauses allocate, collapse, firstprivate, lastprivate, linear, nowait, order, ordered, private,
//   reduction, schedule Semantics The for construct is a worksharing-loop construct." (OpenMP 5.2 §11.5.1 p.250 l.2-9)
// - other families: afar (AFAR 24.3.0), afar244 (AFAR 24.4.0), cce20 (CCE 20.0.2), cce21 (CCE 21.0.3), cce21_4 (CCE 21.0.4), gcc
//   (GCC 16.2.0) run the file correctly (site rows, check case site-fuzz--cce19-schedule-distribute-for-rejected)
// - programs (1): c6c1:1293
// - legality: the rules engine accepts it (offload.engine.prerun.rules_witness); the legality verdict is computed
//   (tools/review/review.py mechanical)
// - releases: CCE 19.0.0 fails it the same way; CCE 20.0.2, 21.0.3 and 21.0.4 run it correctly
#include <stdio.h>
#include <stdint.h>
#include <stdbool.h>
#include <omp.h>

enum { n = 64, m = 2 };

int main(void) {
  int ia[n];
  int ic[n][m];
  int o1[n][m];
  int hf1;
  int64_t cs;
  hf1 = 0;
  #pragma omp target teams map(tofrom: hf1)
  {
    #pragma omp distribute
    for (int i = 1; i <= n; i++) {
      if (i == 1) hf1 = (omp_is_initial_device() ? 1 : 0);
      {
        #pragma omp for schedule(monotonic: dynamic, 1)
        for (int j = 1; j <= m; j += 2) {
          o1[i - 1][j - 1] = ((ia[40] - ic[i - 1][j - 1]) > (-7) ? (ia[40] - ic[i - 1][j - 1]) : (-7));
        }
      }
    }
  }
  #pragma omp target exit data map(from: o1)
  cs = 0;
  printf("RESULT checksum=%lld ran_on_host=%d\n", (long long)cs, (hf1 > 0 ? hf1 : 0));
  return 0;
}

// site:
// title: CCE: rejected with schedule, distribute and for
// summary: CCE 19 fails to link on a C OpenMP program with a schedule clause, a distribute construct and a for construct.
// end site
