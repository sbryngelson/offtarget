// NVHPC 25.11, NVIDIA A100 80GB PCIe (wingtip, sm_80), both memory
// modes: nvc stops with "NVC++-F-0155-Compiler failed to translate OpenMP
// region" on a parallel for with firstprivate nested in a target region
// (the catalog's lastprivate program fails the same way; its
// schedule(monotonic: dynamic) program fails because it has
// firstprivate(mine), not because of the schedule).
// Spec: firstprivate on a worksharing-loop construct: each new list item
// "is initialized from the original list item that exists before the
// construct" (5.2 §5.4.4 p.112); the program is legal.
// Vendor: "The private, firstprivate, and collapse clauses are supported"
// (worksharing-loop) and "The num_threads, default, private,
// firstprivate, and shared clauses are supported" (parallel), HPC
// Compilers User's Guide 25.11 §7.4, 2.9.2 and 2.6. The guide's §2.20
// sentence "nested teams or parallel regions in a target region are not
// supported" is read as a parallel region nested in another parallel (or
// teams) region inside a target region; here the parallel region is the
// only one in the target region, the shape §7.4's parallel entry covers.
// Expected: "c=1 every b[i] % 100 == 1: yes", exit 0. Each thread's copy
// of c starts at 1 and grows by 100 per iteration it runs, so b[i] is
// 1 + 100k (k = iterations its thread ran before i; the schedule is
// implementation defined, so k is not known); the host's c is unchanged.
// Observed (2026-10-24, nvc 25.11-0, -O2; this check rerun the same day,
// separate and managed memory): compile exit status 2,
// "NVC++-F-0155-Compiler failed to translate OpenMP region (b1.c: 7)".
// The same with private(c) (c set in the loop) compiles and is correct;
// nvfortran compiles the Fortran form of the catalog program; gcc
// (host fallback) prints the expected line.
// Found by the catalog (omp52/60-c-clause-firstprivate, -lastprivate,
// -schedule-monotonic: confirmer R10-compile-ice); reduced by hand.
// NVHPC 26.9 (26.9-0, the latest release; rerun 2026-10-24 on wingtip with
// the same flags): still present -- the same: "NVC++-F-0155-Compiler failed to translate OpenMP region", both modes.
// Fix (2026-10-24): rerun on 25.11 and 26.9 in both memory modes,
// each with its own runtime libraries (LD_LIBRARY_PATH = the release's
// compilers/lib; the first 26.9 runs had loaded 25.11's): still present
// on both releases, the same output.
// NVHPC: nvc -mp=gpu -gpu=cc80 -gpu=mem:separate -O2
// Run:   OMP_TARGET_OFFLOAD=mandatory ./a.out
#include <stdio.h>
int main(void) {
  int b[64];
  int c = 1;
  #pragma omp target map(from: b) map(tofrom: c)
  {
    #pragma omp parallel for default(none) shared(b) firstprivate(c)
    for (int i = 0; i < 64; i++) {
      b[i] = c;
      c = c + 100;
    }
  }
  int ok = (c == 1);
  for (int i = 0; i < 64; i++)
    ok = ok && (b[i] % 100 == 1);
  printf("c=%d every b[i] %% 100 == 1: %s\n", c, ok ? "yes" : "no");
  return ok ? 0 : 1;
}
// site:
// title: nvc -mp=gpu: "Compiler failed to translate OpenMP region" for firstprivate on a parallel for in a target region
// control: ../vendor/checks/src/nvhpc/control/nvhpc-c-parallel-for-firstprivate-in-target-control.c private(c) with c set to 1
// + in each
// + iteration
// + instead of firstprivate(c)
// end site
