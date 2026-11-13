! NVHPC 25.11, NVIDIA A100 80GB PCIe (wingtip, sm_80), both memory modes
! (-gpu=mem:separate and -gpu=mem:managed): an if clause on a parallel do
! nested in a target region makes the device compiler fail
! (nvvmCompileProgram: failed with error 9: NVVM_ERROR_COMPILATION, "parse
! invalid forward reference to function 'nvkernel_MAIN__...' with wrong
! type!") instead of compiling the program or giving a diagnostic.
! Spec: the if clause is one of the inputs that "are used to determine the
! number of threads to use in the region" (5.2 §10.1.1 p.226); an if clause
! that evaluates to false gives a team of one thread. The program is legal.
! Vendor: "The if and copyin clauses are supported only for CPU targets;
! the compiler emits an error for GPU targets" (HPC Compilers User's Guide
! 25.11 §7.4, 2.6 Parallel Construct): documented unsupported, so the bug
! is the internal device-compiler failure where a diagnostic is promised.
! The guide's §2.20 sentence "nested teams or parallel regions in a
! target region are not supported" is read as a parallel region nested in
! another parallel (or teams) region inside a target region; here the
! parallel do is the only parallel region in the target region.
! Expected: "sum 2080" (or a diagnostic naming the if clause).
! Observed (2026-10-24, nvfortran 25.11-0, -O2): compile exit status 2 with
! the NVVM error and "NVFORTRAN-W-0155-Compiler failed to translate
! accelerator region (see -Minfo messages): Device compiler exited with
! error status code"; the same for the C port (nvc) of the catalog program.
! Found by the catalog (omp50/52/60-clause-if, omp52/60-c-clause-if:
! confirmer R10-compile-ice); reduced by hand.
! NVHPC 26.9 (26.9-0, the latest release; rerun 2026-10-24 on wingtip with
! the same flags): still present -- the same NVVM failure, now after a new warning "NVFORTRAN-W-0155-Passing external procedure as
! argument in OpenACC/OpenMP device routine context - runtime behavior may be unsupported"; both modes.
! Fix (2026-10-24): rerun on 25.11 and 26.9 in both memory modes,
! each with its own runtime libraries (LD_LIBRARY_PATH = the release's
! compilers/lib; the first 26.9 runs had loaded 25.11's): still present
! on both releases, the same output.
! Coverage-parity fuzz, stratum c1 (2026-11-03): program par-c1-nvhpc-nvhpc269:2306, a
! parallel do with proc_bind(spread) and if(parallel: lpar) in a target region, stops the same way
! on 25.11 and 26.9 (nvvmCompileProgram: failed with error 9: NVVM_ERROR_COMPILATION; rows
! results/parity/wingtip/results/fuzz/par-c1-nvhpc-nvhpc269/programs.jsonl; the gate confirms both
! cells in a-d, results/parity/wingtip/results/parity/gate/fuzz/verdicts.nvhpc-topup.jsonl). New
! facet: the if clause with the parallel directive-name modifier reaches the NVVM failure too, while
! six other c1 cells with if(parallel: ...) get the documented diagnostic "GPU target doesn't
! support 'if' clauses for managing parallel region". No separate finding.
! NVHPC: nvfortran -mp=gpu -gpu=cc80 -gpu=mem:separate -O2
! Run:   OMP_TARGET_OFFLOAD=mandatory ./a.out
program p
  implicit none
  integer :: a(64), i
  logical :: use_par
  use_par = .false.
  a = 0
  !$omp target map(tofrom: a)
    !$omp parallel do if(use_par)
    do i = 1, 64
      a(i) = i
    end do
  !$omp end target
  print *, 'sum', sum(a)
end program p
! site:
! title: nvfortran/nvc -mp=gpu: if clause on a parallel loop in a target region gives an internal NVVM error instead of the
! + documented diagnostic
! control: ../vendor/checks/src/nvhpc/control/nvhpc-parallel-if-in-target-nvvm-ice-control.f90 the if clause removed
! end site
