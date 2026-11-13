// An error directive with at(compilation) severity(warning) in a
// target region (OpenMP 6.0 §10.1: at(compilation) acts at compile time
// only; a warning lets the compilation go on). Expected: the warning, a
// successful build, "RESULT ... check=pass".
// Observed (AFAR amdclang 24.0.0git, -fopenmp --offload-arch=gfx942
// -fopenmp-version=60 -O2, 2026-10-21): the warning is printed twice (host
// and device pass), then the device link fails: "ld.lld: error: undefined
// symbol: __kmpc_error >>> referenced by ...img.lto.o:(__omp_offloading_..
// _main_l..)": the device code calls the runtime error routine, which the
// device runtime lacks (amdclang lowers at(compilation) to a run-time
// call: placed in the host part of main the program builds, and its run
// prints "OMP: Warning #290: ... Encountered user-directed warning: probe",
// which at(compilation) should not). The Fortran form (amdflang) builds and
// runs; CCE craycc 19, 20, 21 build and run both placements. Makes the C message, severity and
// severity.warning programs (6.0) a link failure on AFAR.
#include <stdio.h>
#include <omp.h>

int main(void) {
  int b[64];
  int host_flag = 1;
  #pragma omp target map(from: b) map(tofrom: host_flag)
  {
    #pragma omp error at(compilation) severity(warning) message("probe")
    host_flag = omp_is_initial_device();
    for (int i = 0; i < 64; i++) b[i] = 2 * i + 1;
  }
  int ok = 1;
  for (int i = 0; i < 64; i++) ok = ok && b[i] == 2 * i + 1;
  printf("RESULT ran_on_host=%d check=%s\n", host_flag, ok ? "pass" : "fail");
  return 0;
}
// site:
// title: amdclang -fopenmp-version=60: error at(compilation) severity(warning) in a target region fails at the device link
// + (__kmpc_error undefined)
// control: ../vendor/checks/src/afar/control/afar-c-error-directive-in-target-link-control.c the error directive removed
// end site
