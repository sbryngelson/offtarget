! NVHPC 25.11, NVIDIA A100 80GB PCIe (wingtip, sm_80), both memory modes:
! with defaultmap(firstprivate) on a target construct, the arrays and
! scalars the construct maps EXPLICITLY (map(from: b), map(tofrom:
! host_flag)) are not copied back: the host sees b and host_flag unchanged.
! Spec: "The defaultmap clause determines the implicit data-mapping or
! data-sharing attribute of certain variables" (5.2 §5.8.7 p.161); "When
! specified, explicit data-environment attribute clauses on target
! directives determine the attributes" of the variables they name (5.2
! §5.8.1 p.148).
! Vendor: "The defaultmap clause is supported using OpenMP 5.0 semantics"
! (HPC Compilers User's Guide 25.11 §7.4, 2.12.5).
! Expected: "sum 2144 host_flag 0".
! Observed (2026-10-24, nvfortran 25.11-0, -O2, OMP_TARGET_OFFLOAD=
! mandatory, two runs, the same): "sum 0 host_flag 1".
! Found by the catalog (omp50/52/60-clause-defaultmap-firstprivate: their
! cells read ran_on_host=1 check=fail; confirmer R20-runtime-bug); reduced
! by hand.
! NVHPC 26.9 (26.9-0, the latest release; rerun 2026-10-24 on wingtip with
! the same flags): still present -- the same: "sum 0 host_flag 1", both modes.
! Fix (2026-10-24): rerun on 25.11 and 26.9 in both memory modes,
! each with its own runtime libraries (LD_LIBRARY_PATH = the release's
! compilers/lib; the first 26.9 runs had loaded 25.11's): still present
! on both releases, the same output.
! NVHPC: nvfortran -mp=gpu -gpu=cc80 -gpu=mem:separate -O2
! Run:   OMP_TARGET_OFFLOAD=mandatory ./a.out
program p
  use omp_lib, only: omp_is_initial_device
  implicit none
  integer :: b(64), host_flag, i, c
  b = 0
  host_flag = 1
  c = 1
  !$omp target map(from: b) map(tofrom: host_flag) defaultmap(firstprivate)
    host_flag = merge(1, 0, omp_is_initial_device())
    do i = 1, 64
      b(i) = i + c
    end do
  !$omp end target
  print *, 'sum', sum(b), 'host_flag', host_flag
end program p
! site:
! title: nvfortran -mp=gpu: defaultmap(firstprivate) drops the copy-back of explicitly mapped variables
! control: ../vendor/checks/src/nvhpc/control/nvhpc-defaultmap-firstprivate-explicit-map-control.f90 defaultmap(firstprivate)
! + removed
! end site
