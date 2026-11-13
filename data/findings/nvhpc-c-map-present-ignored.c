// NVHPC 25.11, NVIDIA A100 80GB PCIe (wingtip, sm_80), both memory modes:
// nvc accepts the present map-type modifier and ignores it: a target
// construct with map(present, to: a) for an a that is not present runs on
// (it maps a), where the spec requires runtime error termination.
// Spec: "If a map clause with a present map-type-modifier appears on a
// construct and on entry to the region the corresponding list item is not
// present in the device data environment, runtime error termination is
// performed" (5.2 §5.8.3 p.152).
// Vendor: the 25.11 User's Guide names no present modifier (it lists
// always, close and mapper: §7.4, 2.19.7); nvfortran rejects the modifier
// at compile time (the Fortran catalog programs are rejected).
// Expected: runtime error termination before the printf.
// Observed (2026-10-24, nvc 25.11-0, -O2, OMP_TARGET_OFFLOAD=mandatory):
// "continued after map(present) of an absent a: b[63]=63", exit 0.
// The compile prints nothing (no warning, no message; exit 0) on 25.11 and
// 26.9.
// Found by the catalog (omp52/60-c-clause-map-present, negative probes:
// no_error_termination; confirmer R20-runtime-bug); reduced by hand.
// NVHPC 26.9 (26.9-0, the latest release; rerun 2026-10-24 on wingtip with
// the same flags): still present -- the same: the run goes on (b[63]=63), both modes.
// Fix (2026-10-24): rerun on 25.11 and 26.9 in both memory modes,
// each with its own runtime libraries (LD_LIBRARY_PATH = the release's
// compilers/lib; the first 26.9 runs had loaded 25.11's): still present
// on both releases, the same output.
// NVHPC: nvc -mp=gpu -gpu=cc80 -gpu=mem:separate -O2
// Run:   OMP_TARGET_OFFLOAD=mandatory ./a.out
#include <stdio.h>
int main(void) {
  int a[64], b[64];
  for (int i = 0; i < 64; i++) a[i] = i;
  #pragma omp target map(present, to: a) map(from: b)
  for (int i = 0; i < 64; i++)
    b[i] = a[i];
  printf("continued after map(present) of an absent a: b[63]=%d\n", b[63]);
  return 0;
}
// site:
// title: nvc -mp=gpu: map(present, ...) of an absent variable is accepted and ignored (no error termination)
// control: ../vendor/checks/src/nvhpc/control/nvhpc-c-map-present-ignored-control.c a enclosed in target data map(to: a), so it is
// + present (the
// + run must reach the printf)
// end site
