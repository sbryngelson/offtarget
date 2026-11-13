/* Finding (C): every map with the present modifier (and with the
   close modifier) aborts in CCE's offload runtime.

   Legal OpenMP 5.2 C. a is mapped by the enclosing target data, so
   map(present, to: a) finds it present (5.2 §5.8.3: the present modifier
   requires the item to be present, which it is) and the program prints
   ok=1.

   Observed (HSA_XNACK 0 and 1): CCE craycc 19.0.0, 20.0.2, 21.0.3 abort:
     libcrayacc/acc_clang_wrapper.c:761: void
     TransferList::validate_clang_flags(int64_t): Assertion
     `clang_flags == 0' failed.
   (line 1009 in CCE 20 and 21). The same assertion ends the program
   with map(close, to: a) in place of map(present, to: a) (CCE 19, and
   omp52/60-c-clause-map-close on CCE 19, 20, 21 in the matrix). The C
   negative probe omp52-c-clause-map-present therefore ends in this
   assertion instead of
   the present-table message CCE prints for Fortran (CRAY_ACC_ERROR -
   Variable not found in present table); AFAR amdclang prints ok=1 here and
   libomptarget's present message for the probe (HSA_XNACK=0).

   craycc -fopenmp -fopenmp-targets=amdgcn-amd-amdhsa
          -Xopenmp-target=amdgcn-amd-amdhsa -march=gfx942
          -fopenmp-version=52 -O2 */
#include <stdio.h>
#include <omp.h>
int main(void) {
  int a[64], b[64];
  for (int i = 0; i < 64; i++) { a[i] = i; b[i] = 0; }
  #pragma omp target data map(to: a)
  {
    #pragma omp target map(present, to: a) map(from: b)
    {
      for (int i = 0; i < 64; i++) b[i] = 2 * a[i];
    }
  }
  int ok = 1;
  for (int i = 0; i < 64; i++) ok = ok && b[i] == 2 * i;
  printf("ok=%d\n", ok);
  return 0;
}
// site:
// title: craycc: every map with the present (or close) modifier aborts in the runtime: Assertion `clang_flags == 0' failed
// control: ../vendor/checks/src/cce/control/cce-c-map-present-assert-control.c map(to: a) instead of map(present, to: a)
// end site
