/* Finding (C): a declare target variable listed in shared on a
   combined target construct is read with its host value.

   Legal OpenMP 5.2 / 6.0 C. on_dev is a declare target variable (5.2
   §7.8.1); the first target region sets its device copy to 1 (the host
   copy stays 0). In the second region the shared clause applies only to
   the teams leaf (5.2 §17.2: shared applies to the leaves that permit it,
   target does not), so on_dev there is the target region's on_dev: the
   device copy, which is present (implicitly map(tofrom), 5.2 §5.8.1: no
   transfer for a present variable). Expected b[1] = 2*1 + 1 = 3, the same
   as the third region (no shared clause).

   Observed (HSA_XNACK 0 and 1, -O2): AFAR amdclang 24.0.0git, CCE craycc
   19.0.0, 20.0.2 and 21.0.3 all print b[1]=2 (the host value 0) and
   c[1]=3. The fourth region (teams loop nested in a target region, the
   shared clause on teams; expected d[1]=3): CCE 19 and 21 print d[1]=3,
   AFAR prints an indeterminate value (d[1]=1276187178 here), which makes
   omp52/60-c-directive-teams_loop wrong_answer on AFAR. AFAR amdflang
   and CCE ftn run the Fortran form of the same program
   (omp52-directive-target_teams_loop: shared(a, b, on_dev) under
   default(none)) correctly; the C ports of the five probe-region programs
   (target parallel for simd, target parallel loop, target teams
   distribute parallel for simd, target teams loop, 6.0 target teams
   distribute simd) fail on every toolchain because of this.

   amdclang -fopenmp --offload-arch=gfx942 -fopenmp-version=52 -O2
   craycc -fopenmp -fopenmp-targets=amdgcn-amd-amdhsa
          -Xopenmp-target=amdgcn-amd-amdhsa -march=gfx942 -O2 */
#include <stdio.h>
#include <omp.h>
int on_dev = 0;
#pragma omp declare target(on_dev)
int main(void) {
  int a[64], b[64], c[64], d[64];
  for (int i = 0; i < 64; i++) { a[i] = i; b[i] = 0; c[i] = 0; d[i] = 0; }
  #pragma omp target
  { on_dev = 1; }
  #pragma omp target teams loop map(to: a) map(from: b) shared(a, b, on_dev)
  for (int i = 0; i < 64; i++) b[i] = 2 * a[i] + on_dev;
  #pragma omp target teams loop map(to: a) map(from: c)
  for (int i = 0; i < 64; i++) c[i] = 2 * a[i] + on_dev;
  #pragma omp target map(to: a) map(from: d)
  {
    #pragma omp teams loop shared(a, d, on_dev)
    for (int i = 0; i < 64; i++) d[i] = 2 * a[i] + on_dev;
  }
  printf("with shared(on_dev): b[1]=%d  without: c[1]=%d  teams loop in "
         "target with shared(on_dev): d[1]=%d (device copy is 1, host copy "
         "%d)\n", b[1], c[1], d[1], on_dev);
  return 0;
}
// site:
// title: craycc: a declare target variable listed in shared on target teams loop is read with its host value
// control: ../vendor/checks/src/other/control/clang-c-shared-declare-target-combined-control.c shared(a, b, on_dev) removed from
// + the
// + first target
// + teams loop
// end site
