! AFAR reports nothing present in the device data
! environment at HSA_XNACK=1 (unified memory).
! After target enter data map(to: a), a has corresponding storage in the
! device data environment, so omp_target_is_present must return true
! (5.2 §18.8.3 p.389: "returns true if ... ptr refers to storage that has
! corresponding storage in the device data environment"); after target
! exit data map(release: a) it must return false. The program has no
! requires directive.
! Expected: after enter data: present= 1, after exit data: present= 0
! Observed (tuolumne, MI300A, 2026-10-22, 3 runs each, -O2,
! OMP_TARGET_OFFLOAD=mandatory):
! - AFAR amdflang 24.0.0git at HSA_XNACK=1: present= 0 after enter data;
!   at HSA_XNACK=0: present= 1, as required. AFAR amdclang the same (C
!   reproducer: afar-c-xnack1-target-is-present.c).
! - CCE 19.0.0, 20.0.2, 21.0.3: present= 1 / 0 in both modes.
! The catalog's copy-mode programs skip their presence checks at
! HSA_XNACK=1; run with the presence checks at HSA_XNACK=1
! (tools/campaigns/presence_x1.py, tests/data/presence_x1_summary.json) every one of
! them fails on AFAR (Fortran and C map alloc/delete/release, target data,
! target enter/exit data, map iterator) and passes on CCE except the C
! map.delete programs (cce-c-map-delete-refcount.c). Those AFAR cells are
! correct at HSA_XNACK=0 only (portable verdict x0_only): 31 cells (19
! Fortran, 12 C; with C map.iterator and transparent 34 presence cells)
! that are ONE bug counted once per feature. The 5.2 basis:
! entering a map creates a corresponding storage block with a reference
! count even when it shares storage with the original (5.2 §5.8.3 p.153),
! and the routine reports that block (§18.8.3 p.389).
! AFAR: amdflang -fopenmp --offload-arch=gfx942 -O2
! Run:  OMP_TARGET_OFFLOAD=mandatory HSA_XNACK=1 ./a.out
program p
  use omp_lib
  use, intrinsic :: iso_c_binding, only: c_loc
  implicit none
  integer, target :: a(64)
  integer :: d
  a = 1
  d = omp_get_default_device()
  !$omp target enter data map(to: a)
  print *, 'after enter data: present=', omp_target_is_present(c_loc(a), d)
  !$omp target exit data map(release: a)
  print *, 'after exit data: present=', omp_target_is_present(c_loc(a), d)
end program p
! site:
! title: AFAR offload runtime at HSA_XNACK=1: omp_target_is_present returns false after target enter data, and map(present) of an
! + absent item does not terminate
! control: ../vendor/checks/src/afar/control/afar-xnack1-target-is-present-control.f90 run at HSA_XNACK=0
! end site
