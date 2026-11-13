/* Finding (C): with -fopenmp-version=45 CCE cannot link
   omp_is_initial_device called in a target region.

   Legal OpenMP 4.5 C (4.5 §3.2.34: omp_is_initial_device; runtime
   library routines may be called in target regions).

   Expected: "on_host=0".
   Observed: CCE craycc 19.0.0, 20.0.2 and 21.0.3 with
   -fopenmp-version=45 fail to link:
     lld: error: undefined symbol: omp_is_initial_device
     >>> referenced by ...-cce-openmp__llc.amdgpu:
         (omp_is_initial_device_cce$omp_redun_clone)
   With no version flag (default 5.1; CCE 19 also at 50 and 52) it
   links and prints "on_host=0". The first omp_vv C baseline (each test
   at the version of its spec directory) lost 115 of 315 tests on CCE to
   this; the baseline now compiles 4.5-5.1 tests with the default.

   craycc -fopenmp -fopenmp-targets=amdgcn-amd-amdhsa
          -Xopenmp-target=amdgcn-amd-amdhsa -march=gfx942
          -fopenmp-version=45 -O2 */
#include <stdio.h>
#include <omp.h>
int main(void) {
  int on_host = 1;
  #pragma omp target map(tofrom: on_host)
  on_host = omp_is_initial_device();
  printf("on_host=%d\n", on_host);
  return 0;
}
// site:
// title: craycc -fopenmp-version=45: omp_is_initial_device called in a target region is an undefined symbol at the device link
// control: ../vendor/checks/src/cce/control/cce-c-openmp45-device-link-control.c built without -fopenmp-version=45 (the default,
// + 5.1)
// end site
