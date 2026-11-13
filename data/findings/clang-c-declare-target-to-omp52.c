/* Finding (C): at -fopenmp-version=52 both clang C front ends
   reject the deprecated but normative `to` clause of declare target.

   Legal OpenMP 5.2 C. "The clause-name to may be used as a synonym for the
   clause-name enter. This use has been deprecated." (5.2 §5.8.4 p.158; also
   Appendix B.1 p.625), and "deprecated"
   is "the property that it is normative in the current specification but
   is considered obsolescent and will be removed in the future" (5.2
   §1.2.7 p.20); 6.0 removes it (the catalog's 6.0 programs use enter).
   Expected: "RESULT ran_on_host=0 check=pass".

   Observed (tuolumne, MI300A, HSA_XNACK=1, -O2, 2026-10-22,
   data/evidence/triage_probe/dt_to.c, results/t27b/probes.jsonl): AFAR amdclang
   24.0.0git and CCE craycc 19.0.0, 20.0.2, 21.0.3 at -fopenmp-version=52:
   "error: unexpected 'to' clause, use 'enter' instead"; without the flag
   (their default, OpenMP 5.1) all four compile and run it correctly. The
   catalog's omp52-c-clause-device_type, -device_type-any, -device_type-
   nohost programs were rejected on every compiler because of it; since
   Those C ports use enter(f), so they measure
   device_type.

   Legality rests on the quoted spec text only: there is no independent
   compiler witness (cited gcc 13.3.1 -fopenmp; gfortran/gcc -fopenmp
   are withdrawn as offload legality witnesses, data/reports/rulings.md).

   amdclang -fopenmp --offload-arch=gfx942 -fopenmp-version=52 -O2
   craycc -fopenmp -fopenmp-targets=amdgcn-amd-amdhsa
          -Xopenmp-target=amdgcn-amd-amdhsa -march=gfx942
          -fopenmp-version=52 -O2 */
#include <stdio.h>
#include <omp.h>
enum { n = 64 };
int f(int x) { return 2 * x + 1; }
#pragma omp declare target to(f) device_type(any)
int main(void) {
  int a[n], b[n], bad = 0, host_flag = 1;
  for (int i = 0; i < n; i++) { a[i] = i + 1; b[i] = 0; }
  #pragma omp target map(to: a) map(from: b) map(tofrom: host_flag)
  {
    host_flag = omp_is_initial_device() ? 1 : 0;
    for (int i = 0; i < n; i++) b[i] = f(a[i]);
  }
  for (int i = 0; i < n; i++) bad += b[i] != 2 * (i + 1) + 1;
  printf("RESULT ran_on_host=%d check=%s\n", host_flag, bad ? "fail" : "pass");
  return 0;
}
// site:
// title: amdclang -fopenmp-version=52: declare target to(f) rejected ("unexpected 'to' clause, use 'enter' instead")
// control: ../vendor/checks/src/other/control/clang-c-declare-target-to-omp52-control.c enter(f) instead of to(f)
// end site
