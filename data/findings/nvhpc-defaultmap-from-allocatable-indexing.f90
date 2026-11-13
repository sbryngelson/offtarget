! NVHPC 25.11, NVIDIA A100 80GB PCIe (wingtip, sm_80), both memory modes
! (-gpu=mem:separate and mem:managed): defaultmap(from) (likewise defaultmap(alloc)) on a
! target construct breaks the indexing of allocatable arrays the construct
! maps EXPLICITLY: b(i) = a(i) stores the wrong elements.
! Spec: "The defaultmap clause determines the implicit data-mapping or
! data-sharing attribute of certain variables" (5.2 §5.8.7 p.161) and
! "When specified, explicit data-environment attribute clauses on target
! directives determine the attributes" of the variables they name (5.2
! §5.8.1 p.148): a and b keep map(to:) and map(from:).
! Vendor: "The defaultmap clause is supported using OpenMP 5.0 semantics"
! (HPC Compilers User's Guide 25.11 §7.4, 2.12.5 Target Construct).
! Expected: "b(1) 1 b(64) 64 sum 2080".
! Observed (2026-10-24, nvfortran 25.11-0, -O2, two runs, the same):
! "b(1) 2 b(64) 0 sum 2079" (b shifted by one element); with
! defaultmap(alloc): "b(1) 0 b(64) 64 sum 2079"; with defaultmap(tofrom)
! or without defaultmap, and with fixed-size arrays: correct. The
! array descriptor of an allocatable looks mapped by the defaultmap
! behaviour (from: not copied to the device).
! Found by the catalog (omp50/52/60-clause-defaultmap-from: confirmer
! R20-runtime-bug); reduced by hand.
! NVHPC 26.9 (26.9-0, the latest release; rerun 2026-10-24 on wingtip with
! the same flags): still present -- the same: "b(1) 2 b(64) 0 sum 2079", in separate and in managed memory (25.11 likewise in both
! modes).
! Fix (2026-10-24): rerun on 25.11 and 26.9 in both memory modes,
! each with its own runtime libraries (LD_LIBRARY_PATH = the release's
! compilers/lib; the first 26.9 runs had loaded 25.11's): still present
! on both releases, the same output.
! Coverage-parity fuzz, stratum c1 (2026-11-03): program par-c1-nvhpc-nvhpc269:1572 (a target
! region with defaultmap(alloc: scalar) that indexes explicitly mapped allocatable arrays) gives a
! wrong checksum on 25.11 and 26.9 (rows
! results/parity/wingtip/results/fuzz/par-c1-nvhpc-nvhpc269/programs.jsonl; the gate confirms
! both cells in a-d, results/parity/wingtip/results/parity/gate/fuzz/verdicts.nvhpc-topup.jsonl).
! Without the defaultmap clause it gives the expected checksum; a reduced form reads a(i+1) for
! a(i) of an allocatable array, mapped implicitly or explicitly, and is correct with
! defaultmap(tofrom: scalar), defaultmap(firstprivate: scalar) or an explicit-shape array: this
! appears to be the shift of this finding, reached through the scalar category, which names no
! array (exploration runs on both releases, no result rows).
! No separate finding; if the scalar-category form holds up in rows, the title and control of this
! finding are narrower than the defect.
! NVHPC: nvfortran -mp=gpu -gpu=cc80 -gpu=mem:separate -O2
! Run:   OMP_TARGET_OFFLOAD=mandatory ./a.out
program p
  implicit none
  integer, allocatable :: a(:), b(:)
  integer :: i
  allocate(a(64), b(64))
  a = [(i, i = 1, 64)]
  b = 0
  !$omp target map(to: a) map(from: b) defaultmap(from)
    do i = 1, 64
      b(i) = a(i)
    end do
  !$omp end target
  print *, 'b(1)', b(1), 'b(64)', b(64), 'sum', sum(b), '(expected 1 64 2080)'
end program p
! site:
! title: nvfortran -mp=gpu: defaultmap(from) or defaultmap(alloc) shifts explicitly mapped allocatable arrays
! control: ../vendor/checks/src/nvhpc/control/nvhpc-defaultmap-from-allocatable-indexing-control.f90 defaultmap(tofrom) instead of
! + defaultmap(from)
! end site
