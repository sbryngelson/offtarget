// NVHPC 25.11, NVIDIA A100 80GB PCIe (wingtip, sm_80), both memory modes: the C
// form of nvhpc-parallel-if-in-target-nvvm-ice.f90. An if clause on a parallel
// for in a target region, whose body calls omp_get_num_threads, makes the
// device compiler fail (nvvmCompileProgram: failed with error 9:
// NVVM_ERROR_COMPILATION, "'@nvkernel_main_...' defined with type 'void (i8*,
// i8*, i8*)*'") instead of compiling the program or giving a diagnostic.
// Without the omp_get_num_threads call the program compiles.
// Spec: the if clause is one of the inputs that "are used to determine the
// number of threads to use in the region" (5.2 §10.1.1 p.226).
// Vendor: "The if and copyin clauses are supported only for CPU targets; the
// compiler emits an error for GPU targets" (HPC Compilers User's Guide 25.11
// §7.4, 2.6): documented unsupported, so the bug is the internal failure where
// a diagnostic is promised. The guide's §2.20 sentence "nested teams or
// parallel regions in a target region are not supported" is read as a
// parallel region nested in another parallel (or teams) region inside a
// target region; here the parallel region is the only one in the target
// region.
// Expected: "sum 2080 nthr 1" (or a diagnostic naming the if clause).
// Observed (2026-10-24, nvc 25.11-0, -O2): compile exit status 2 with the NVVM
// error.
// Found by the catalog (omp52/60-c-clause-if: confirmer R10-compile-ice);
// reduced by hand.
// NVHPC 26.9 (26.9-0, the latest release; rerun 2026-10-24 on wingtip with
// the same flags): still present -- the same NVVM error, both modes.
// Fix (2026-10-24): rerun on 25.11 and 26.9 in both memory modes,
// each with its own runtime libraries (LD_LIBRARY_PATH = the release's
// compilers/lib; the first 26.9 runs had loaded 25.11's): still present
// on both releases, the same output.
// NVHPC: nvc -mp=gpu -gpu=cc80 -gpu=mem:separate -O2
#include <stdio.h>
#include <stdbool.h>
#include <omp.h>
int main(void) {
  int a[64];
  int nthr = 0;
  bool use_par = false;
  for (int i = 0; i < 64; i++) a[i] = 0;
  #pragma omp target map(tofrom: a) map(from: nthr)
  {
    #pragma omp parallel for if(use_par)
    for (int i = 0; i < 64; i++) {
      a[i] = i + 1;
      if (i == 0) nthr = omp_get_num_threads();
    }
  }
  int s = 0;
  for (int i = 0; i < 64; i++) s += a[i];
  printf("sum %d nthr %d\n", s, nthr);
  return 0;
}
// site:
// title: nvfortran/nvc -mp=gpu: if clause on a parallel loop in a target region gives an internal NVVM error instead of the
// + documented diagnostic
// control: ../vendor/checks/src/nvhpc/control/nvhpc-c-parallel-if-in-target-nvvm-ice-control.c the if clause removed
// same_as: nvhpc-parallel-if-in-target-nvvm-ice
// end site
