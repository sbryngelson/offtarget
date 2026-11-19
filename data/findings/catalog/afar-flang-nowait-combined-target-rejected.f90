! # Finding (reduce): amdflang 24.4.0 rejects nowait on a combined target teams distribute parallel do at OpenMP 5.0 and 5.2
! # ("This compound directive does not allow NOWAIT clause")
!
! - toolchains and modes that fail: afar244 (AFAR 24.4.0); modes: unified, copy; -O2
! - build: amdflang -fopenmp --offload-arch=gfx942 -O2
! - failure: rejected
! - observed: `site-catalog--afar-flang-nowait-combined-target-rejected.f90:23:9: error: This compound directive does not allow
!   NOWAIT clause`; identical signature on 2 of 2 failing cells
! - expected: compiles and runs to completion, printing `RESULT ran_on_host=0 check=pass`
! - rule: OpenMP 5.2 §17.2 p.341 l.23: "The effect of the nowait clause is as if it is applied to the outermost leaf construct
!   that permits it." The target construct permits it (5.2 §13.8 p.284 l.5, its clauses: "in_reduction, is_device_ptr, map,
!   nowait, private, thread_limit,"), so on target teams distribute parallel do the clause applies to target
! - same-compiler control: controls/afar-flang-nowait-combined-target-rejected-delete-clause-nowait-control.f90 (one change from
!   this file; correct on afar244 (AFAR 24.4.0); rows results/reduce/nowait/rows.jsonl);
!   controls/afar-flang-nowait-combined-target-rejected-shorten-target-teams-distribute-parallel-control.f90 (one change from this
!   file; correct on afar244 (AFAR 24.4.0); rows results/reduce/nowait/rows.jsonl)
! - other families: afar (AFAR 24.3.0), cce19 (CCE 19.0.0), cce20 (CCE 20.0.2), cce21 (CCE 21.0.3), cce21_4 (CCE 21.0.4) run the
!   file correctly (site rows, check case site-catalog--afar-flang-nowait-combined-target-rejected)
! - legality: legal by reading: one combined target construct with map clauses and nowait, and a taskwait before b is read;
!   the rules witness (offload.engine.prerun) accepts it, and another family's front end, CCE ftn 19, 20 and 21, compiles and
!   runs it correctly (site rows). AFAR 24.3.0 runs it correctly, and AFAR 24.4.0 accepts it at -fopenmp-version=60
! - releases: AFAR 24.3.0 runs it correctly; AFAR 24.4.0 fails it the same way
program repro
  use omp_lib, only: omp_is_initial_device
  implicit none
  integer, parameter :: n = 64
  integer :: a(n), b(n), i, on_host
  a = [(i, i = 1, n)]
  b = 0
  on_host = 1
  !$omp target teams distribute parallel do map(to: a) map(tofrom: b, on_host) nowait
  do i = 1, n
    b(i) = 2*a(i)
    if (i == 1) on_host = merge(1, 0, omp_is_initial_device())
  end do
  !$omp end target teams distribute parallel do
  !$omp taskwait
  print '(a,i0,a,a)', 'RESULT ran_on_host=', on_host, ' check=', merge('pass', 'fail', all(b == &
      & 2*a))
end program repro

! site:
! title: AFAR 24.4.0: nowait rejected on target teams distribute parallel do
! summary: AFAR 24.4.0 rejects a nowait clause on a combined target teams distribute parallel do at OpenMP 5.0 and 5.2,
! + where OpenMP applies it to the target leaf; AFAR 24.3.0 and CCE compile and run the program.
! control: catalog/controls/afar-flang-nowait-combined-target-rejected-delete-clause-nowait-control.f90 one change from the finding;
! + correct on afar244
! control: catalog/controls/afar-flang-nowait-combined-target-rejected-shorten-target-teams-distribute-parallel-control.f90 one
! + change from the finding; correct on afar244
! end site
