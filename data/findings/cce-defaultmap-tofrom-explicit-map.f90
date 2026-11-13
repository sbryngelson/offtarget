! CCE 19 applies defaultmap(tofrom) to an array the
! same target construct maps EXPLICITLY with map(alloc:) or map(to:): on
! exit it copies the device values back to the host.
! Spec: on exit from the region the original list item is updated only "if
! the map-type is from or tofrom" (5.2 §5.8.3 p.154, exit step 1a); alloc
! and to have no from transfer. "The defaultmap clause determines the
! implicit data-mapping or data-sharing attribute of certain variables"
! (5.2 §5.8.7 p.161), and "explicit data-environment attribute clauses on
! target directives determine the attributes" of the variables they name
! (5.2 §5.8.1 p.148), so defaultmap(tofrom) does not change a's map type.
! Premise: the original and corresponding items do not share storage. The
! spec allows shared storage (5.2 §5.8.3 p.153, "may share storage"), so
! the evidence holds only where they are separate: run at HSA_XNACK=0 (on
! MI300A copy mode, on MI250X a discrete GPU), and the control regions 1
! and 3 (the same maps without defaultmap) must leave the host a unchanged
! (64 of 64): separate storage in the same configuration without
! defaultmap; for regions 2 and 4 separate storage is the premise.
! Expected: every region prints "host a unchanged: 64".
! Observed (2026-10-22, -O2, OMP_TARGET_OFFLOAD=mandatory, HSA_XNACK=0, two
! runs each, the same every run; tioga30 MI250X gfx90a and tuolumne1047
! MI300A gfx942):
! - CCE 19.0.0: regions 1 and 3: 64; regions 2 and 4
!   (with defaultmap(tofrom)), ran_on_host=0: 0 -- the device's writes
!   reached the host a.
! - CCE 20.0.2 and AFAR 24.0.0git: 64 in every region (correct).
! - CCE 21.0.3 and 21.0.4 : regions 2 and 4 print
!   ran_on_host=1, but that is the map(tofrom) host_flag, which CCE 21 does
!   not copy back in a region with defaultmap (cce21-defaultmap-aggregate-
!   flag.f90): the label `ran_on_host=` names no independent measurement,
!   and the regions run on the device. At HSA_XNACK=0 CCE 21.0.3 and 21.0.4
!   copy a back in regions 2 and 4 (host a unchanged: 0): this defect, fixed
!   in 20.0.2, is back in 21 (data/vendor/hpe/cce21-defaultmap-aggregate-
!   flag.md, variants: confirmed in the four environments on both releases).
! Found by the gfx90a map-mutant audit (data/reports/map-mutant-audit-
! gfx90a.md): the weaken_map and swap_to_from mutants of the defaultmap-
! tofrom programs survive on CCE 19.
! CCE:  ftn -fopenmp -O2 (module load cce/<v> craype-accel-amd-<gfx>
!       rocm/<r>; module unload cray-mpich)
! AFAR: amdflang -fopenmp --offload-arch=<gfx> -O2
! Run:  OMP_TARGET_OFFLOAD=mandatory HSA_XNACK=0 ./a.out
program p
  use omp_lib, only: omp_is_initial_device
  implicit none
  integer, parameter :: n = 64
  integer, allocatable :: a(:)
  integer :: i, k, host_flag
  do k = 1, 4
    allocate(a(n))
    a = [(i, i = 1, n)]
    host_flag = 1
    select case (k)
    case (1)
      !$omp target map(alloc: a) map(tofrom: host_flag)
        host_flag = merge(1, 0, omp_is_initial_device())
        do i = 1, n
          a(i) = -i
        end do
      !$omp end target
    case (2)
      !$omp target map(alloc: a) map(tofrom: host_flag) defaultmap(tofrom)
        host_flag = merge(1, 0, omp_is_initial_device())
        do i = 1, n
          a(i) = -i
        end do
      !$omp end target
    case (3)
      !$omp target map(to: a) map(tofrom: host_flag)
        host_flag = merge(1, 0, omp_is_initial_device())
        do i = 1, n
          a(i) = -i
        end do
      !$omp end target
    case (4)
      !$omp target map(to: a) map(tofrom: host_flag) defaultmap(tofrom)
        host_flag = merge(1, 0, omp_is_initial_device())
        do i = 1, n
          a(i) = -i
        end do
      !$omp end target
    end select
    print '(a,i0,a,i0,a,i0)', 'region ', k, ': ran_on_host=', host_flag, &
      ' host a unchanged: ', count(a == [(i, i = 1, n)])
    deallocate(a)
  end do
end program p
! site:
! title: ftn: with a defaultmap clause on target, an explicitly mapped map(tofrom) scalar is not copied back, and with
! + defaultmap(tofrom) an array in map(alloc) or map(to) is copied back
! control: ../vendor/checks/src/cce/control/cce-defaultmap-tofrom-explicit-map-control.f90 defaultmap(tofrom) removed from
! + regions 2 and 4
! same_as: cce21-defaultmap-aggregate-flag
! end site
