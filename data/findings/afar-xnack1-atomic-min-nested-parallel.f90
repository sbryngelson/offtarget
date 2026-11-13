! AFAR (amdflang 24.0.0git, drop 24.3.0), MI300A gfx942, -O2:
! an `atomic` min update of a mapped scalar inside a `parallel do` nested in
! `target teams distribute`, with an allocatable array written in the same
! loop, faults at HSA_XNACK=1 ("memory access fault ... Write access to a
! read-only page"); at HSA_XNACK=0 it prints r=0 s=0 (correct).
! Needed: an array written in the loop, the inner parallel do (without it: correct), and an
! atomic update whose right-hand side depends on i. An atomic add with a constant right-hand
! side is correct; r = r + mod(i, n) faults like the atomic min. In this combined form the
! allocatable o1 faults and an explicit-shape array is correct; with separate directives the
! explicit-shape array faults too (18-program matrix: data/reports/fuzz5-oop-afar.md, cluster C).
! map(always) or an explicit map of o1 do not matter.
! Hand-reduced from data/findings/fuzz/b2-183-afar.f90.
!   amdflang -fopenmp --offload-arch=gfx942 -O2 afar-xnack1-atomic-min-nested-parallel.f90
!   HSA_XNACK=1 OMP_TARGET_OFFLOAD=mandatory ./a.out
program p
  implicit none
  integer, parameter :: n = 24, m = 2
  integer, allocatable :: o1(:,:)
  integer :: i, j, r
  allocate(o1(n, m))
  o1 = 0
  r = 7
  !$omp target teams distribute map(tofrom: r)
  do i = 1, n
    !$omp parallel do
    do j = 1, m
      o1(i, j) = 0
      !$omp atomic
      r = min(r, mod(i, n))
    end do
    !$omp end parallel do
  end do
  !$omp end target teams distribute
  print '(a,i0,a,i0)', 'r=', r, ' s=', sum(o1)
end program p
! site:
! title: amdflang at HSA_XNACK=1: atomic min in a parallel do nested in target teams distribute with an allocatable array faults
! + (write to a read-only page)
! control: ../vendor/checks/src/afar/control/afar-xnack1-atomic-min-nested-parallel-control.f90 o1 an explicit-shape array
! + instead of an
! + allocatable
! end site
! spec (requirement): In Fortran an atomic update may have the form x = intrinsic-procedure-name(x, expr-list) where
!   the intrinsic is MAX or MIN.
! "x = intrinsic-procedure-name (x, expr-list)" (5.2 §4.3.1.3 p.81 l.14)
! spec (requirement): The atomic construct makes the access to the storage location atomic, so concurrent updates by
!   the threads of nested parallel regions produce no indeterminate value.
! "The atomic construct ensures that a specific storage location is accessed atomically so that possible simultaneous
!   reads and writes by multiple threads do not result in indeterminate values." (5.2 §15.8.4 p.311 l.29-30)
! spec (this program): The atomic min update of the mapped scalar r runs in a parallel do nested in target teams
!   distribute and must give r = 0; the spec has no text on memory faults with unified-memory settings (HSA_XNACK=1 is
!   a vendor runtime setting), so the cited text states only that the update must complete correctly, and the write
!   access fault to a read-only page is a deviation from it.
