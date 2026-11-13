/* Finding (C): dist_schedule(static) without a chunk size on a
   combined target teams distribute parallel for crashes on CCE.

   Legal OpenMP 5.2 C (5.2 §11.6.1: dist_schedule(static) divides the
   iterations into chunks of about equal size, one per team).

   Expected: "64 of 64".
   Observed at HSA_XNACK=1, -O2: CCE craycc 19.0.0, 20.0.2 and 21.0.3:
   the program dies with SIGSEGV (also without OMP_TARGET_OFFLOAD=
   mandatory; CCE 19 also at -O0). At HSA_XNACK=0 (copy mode) CCE 19
   prints "64 of 64". Without the dist_schedule clause, or with
   dist_schedule(static, 16), it prints "64 of 64" at HSA_XNACK=1. AFAR amdclang:
   "64 of 64". CCE ftn runs the Fortran form (omp52-clause-dist_schedule)
   correctly.

   craycc -fopenmp -fopenmp-targets=amdgcn-amd-amdhsa
          -Xopenmp-target=amdgcn-amd-amdhsa -march=gfx942
          -fopenmp-version=52 -O2 */
#include <stdio.h>
int main(void) {
  int b[64];
  for (int i = 0; i < 64; i++) b[i] = 0;
  #pragma omp target teams distribute parallel for map(from: b) \
      num_teams(4) dist_schedule(static)
  for (int i = 0; i < 64; i++) b[i] = i + 1;
  int n = 0;
  for (int i = 0; i < 64; i++) n += b[i] == i + 1;
  printf("%d of 64\n", n);
  return 0;
}
// site:
// title: craycc: dist_schedule(static) on target teams distribute parallel for crashes (SIGSEGV) at HSA_XNACK=1
// control: ../vendor/checks/src/cce/control/cce-c-dist-schedule-segv-control.c dist_schedule(static) removed
// end site
