// # Finding (AFAR, CCE): amdclang and craycc reject a reduction clause on a loop construct that binds to the teams region of a
//   target teams construct (C)
//
// - toolchains and modes that fail: afar (AFAR 24.3.0), afar244 (AFAR 24.4.0), cce19 (CCE 19.0.0), cce20 (CCE 20.0.2), cce21 (CCE
//   21.0.3), cce21_4 (CCE 21.0.4); modes: unified, copy; -O2
// - build: amdclang -fopenmp --offload-arch=gfx942 -O2 (afar, afar244); craycc -fopenmp -fopenmp-targets=amdgcn-amd-amdhsa
//   -Xopenmp-target=amdgcn-amd-amdhsa -march=gfx942 -O2 (cce19, cce20, cce21, cce21_4)
// - failure: rejected
// - observed: `site-apps--clang-c-loop-bind-teams-reduction-rejected.c:20:5: error: 'reduction' clause not allowed with '#pragma
//   omp loop bind(teams)'`; identical signature on 12 of 12 failing cells
// - expected: compiles and prints `r= 55` with `check=pass`
// - rule: reduction is a clause of the loop construct: "Clauses bind, collapse, lastprivate, order, private, reduction" (OpenMP 5.2
//   §11.7 p.257 l.3-4), and the construct's restrictions on it are only that "If a reduction-modifier is specified in a reduction
//   clause that appears on the directive then the reduction modifier must be default" (§11.7 p.257 l.33-34); bind(teams) names the
//   enclosing teams region as the binding region (§11.7.1). The Fortran form of the same program is
//   afar-flang-loop-bind-teams-reduction.f90
// - other families: gcc (GCC 16.2.0) run the file correctly (site rows, check case
//   site-apps--clang-c-loop-bind-teams-reduction-rejected)
// - legality: legal by reading: the loop construct is closely nested in the teams region of target teams, so bind(teams) is
//   allowed; r is mapped tofrom and reduced across the teams region, i is the loop variable, and host is set in a separate target
//   region, so there is no data race. The rules witness accepts it; the front-end witness is AFAR's amdclang, a compiler under
//   test, which rejects it (offload.engine.prerun.check: witnesses disagree), so the legality rests on the reading and the review.
//   Found by the application corpus: NPB CG and EP in their OpenMP offload translation (npb-cg-c-omp, npb-ep-c-omp) use loop with
//   reduction inside target teams, and every clang-based toolchain rejects them
// - releases: CCE 19.0.0, 20.0.2, 21.0.3 and 21.0.4 fail it the same way; AFAR 24.3.0 and 24.4.0 fail it the same way
#include <stdio.h>
#include <omp.h>
int main(void) {
  int r = 0, host = 1;
  #pragma omp target map(tofrom: host)
  host = omp_is_initial_device();
  #pragma omp target teams map(tofrom: r)
  {
    #pragma omp loop bind(teams) reduction(+: r)
    for (int i = 1; i <= 10; i++)
      r = r + i;
  }
  printf("r= %d\n", r);
  printf("RESULT ran_on_host=%d check=%s\n", host, r == 55 ? "pass" : "fail");
  return 0;
}

// site:
// title: C loop reduction bound to teams rejected by amdclang and craycc
// summary: AMD's amdclang and CCE's craycc reject a reduction clause on a loop construct inside target teams, a form OpenMP 5.2
// + allows and the NAS Parallel Benchmarks' OpenMP offload port uses.
// end site
