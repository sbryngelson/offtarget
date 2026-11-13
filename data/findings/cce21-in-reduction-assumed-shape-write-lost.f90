! (reducing the reproduction gate's review queue entry
! 48, fuzz x0-alloc:197, whose kernel 4 is this pattern): CCE 21 loses the
! writes to an assumed-shape dummy array in a target region that has
! in_reduction (in a taskgroup with task_reduction), inside the procedure
! whose dummy it is. With explicit-shape dummies, or without the
! task_reduction/in_reduction pair, the writes come back.
! Spec: y is a mappable list item mapped tofrom (5.2 §5.8.3 p.150; the only
! Fortran list-item restriction, p.156, is on assumed-size arrays), so its
! values at the end of the region are assigned back to the original; the
! in_reduction clause on target (§5.5.10 p.138) and task_reduction on
! taskgroup (§5.5.9 p.137) do not change the mapping of other list items. r
! is not updated in the region. Expected: "r= 3 y(16)= 32".
! Observed (Tuolumne MI300A, -O2, OMP_TARGET_OFFLOAD=mandatory, 3 runs per
! cell, 2026-10-26; data/evidence/gate_probe/logs/reduce.txt, ids r2/inred_noh*):
! CCE 21.0.3 at HSA_XNACK 0 and 1: "r= 3 y(16)= 0" in every run.
! One-change controls of this program (after the later
! runs; data/evidence/gate_probe/reduce/): x(n), y(n) explicit-shape
! (inred_noh_explicit.f90) and the taskgroup and in_reduction removed
! (inred_noh_noinred.f90) each give "r= 3 y(16)= 32" in 6 of 6 runs on
! CCE 21, XNACK 0 and 1. CCE 19.0.0 and 20.0.2: right (both crash on the
! fuller fuzz kernel instead: data/reports/gate-queue.md, entry 48). The
! fix-round-1 form, which also printed an unwritten scalar h, gave the same
! (inred_host_noh.f90), and so did a form that writes and maps h
! (inred_host.f90).
! With r updated in the region (r = r + x(i)) CCE 21 does not link it
! ("undefined symbol: _cray$mt_taskwait": cce21-in-reduction-taskwait-link.f90),
! so this program leaves r alone.
! Another family: AFAR amdflang: "r= 3 y(16)= 32" (XNACK 0 and 1). NVHPC
! nvfortran 25.11 and 26.9 reject task_reduction ("Syntax error at or near
! identifier task_reduction" on data/evidence/gate_probe/reduce/unh_k2.f90 and
! unh_k4.f90, data/evidence/gate_probe/logs/wingtip5.log), so it is no witness.
! CCE: ftn -fopenmp -O2 (module load cce/21.0.3 craype-accel-amd-gfx942 rocm)
! Run: OMP_TARGET_OFFLOAD=mandatory HSA_XNACK=0 ./a.out
program p
  implicit none
  integer, parameter :: n = 16
  integer :: a(n), b(n), r, i
  do i = 1, n
    a(i) = i
    b(i) = 0
  end do
  r = 3
  call k(a, b)
  print '(a,i0,a,i0)', 'r= ', r, ' y(16)= ', b(n)
contains
  subroutine k(x, y)
    integer, intent(in) :: x(:)
    integer, intent(inout) :: y(:)
    integer :: i
    !$omp taskgroup task_reduction(+: r)
      !$omp target map(to: x) map(tofrom: y) in_reduction(+: r)
        do i = 1, n
          y(i) = 2 * x(i)
        end do
      !$omp end target
    !$omp end taskgroup
  end subroutine k
end program p
! site:
! title: ftn 21: writes to an assumed-shape dummy in a target region with in_reduction are lost
! end site
