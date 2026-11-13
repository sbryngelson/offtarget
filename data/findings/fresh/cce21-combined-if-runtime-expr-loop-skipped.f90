! # Finding (from the data/bench/fresh draft fresh-046): CCE 21 skips a target teams
!   distribute parallel do whose if clause has no modifier and a run-time expression
!
! - source: data/bench/fresh/fresh-046.f90 (llvm-project issue 208698): `target teams distribute parallel
!   do map(present, tofrom: data) if (should_offload)` with should_offload a module logical; CCE 21
!   leaves data untouched. Neither present, target enter data nor the loop length matters
! - compilers: CCE 21.0.3 ftn, -fopenmp -O2; MI300A HSA_XNACK 1 and 0, MI250X HSA_XNACK 0
! - expected: b(1) 1 b(64) 64 dev 1. "For a combined or composite construct, if no
!   directive-name-modifier is specified then the if clause applies to all constituent constructs to
!   which an if clause can apply" (OpenMP 5.2 §3.4 p.72 l.15-18). Whether teams is one of them, 5.2
!   does not say consistently: the if clause's directive list (§3.4 p.72 l.8-9) and the teams clause
!   list (§10.2 p.230 l.7-8) omit it, the teams semantics (p.230 l.18-21) describe it, and 6.0 §B.3
!   p.904 l.16 records it as a 5.1-to-5.2 change; under 5.0 the clause applies to target and parallel
!   only. The expected output does not depend on it: on is true on the host, so the region runs on
!   the device (dev 1), and whatever number of teams and threads results, every iteration runs once
! - actual: b(1) 0 b(64) 0 dev -1: no iteration runs, on the device or on the host, and the program
!   goes on without a message (every run, both memory modes, both machines). The same with an
!   integer module variable (if (k > 0), d046-min-int.f90) and with a local logical set from it
!   (d046-min-local.f90); if (.true.) is correct (d046-if-true.f90), and so is a local logical set
!   from a literal (d046-if-local.f90, which the compiler can fold). Fix: if (teams: on)
!   alone fails the same way (d046-min-teams.f90; MI300A both modes, MI250X), if (parallel: on) is
!   correct (d046-min-parallel.f90): the teams part of the if clause is where CCE 21 goes wrong
! - control (same compiler): if (target: on) on the same construct prints b(1) 1 b(64) 64 dev 1
!   (data/reports/fresh-drafts/d046-min-target.f90); so do the unmodified if (on) on target teams
!   distribute, target parallel do and target teams (d046-min-tdist.f90, d046-min-tpd.f90,
!   d046-min-tteams.f90)
! - other families: AFAR and CCE 19/20 print b(1) 1 b(64) 64 dev 1 (MI300A HSA_XNACK 1 and 0;
!   MI250X); NVHPC 25.11 and 26.9 run the draft without the present modifier correctly
!   (d046-no-present.f90, PASS; nvfortran rejects map(present, ...))
! - legality: legal by reading (dev is written by one iteration only); an if clause without a
!   modifier on this combined construct is also conforming under OpenMP 5.0, which HPE claims in full
! - evidence: results/fresh-drafts/tuo-p3.jsonl, tuo2-q3.jsonl, tuo3-r*-a.jsonl, tioga/tioga-c.jsonl,
!   tuo4-p.jsonl, tioga/tioga2.jsonl, wingtip/nv.jsonl (review)
module ctl
  implicit none
  logical :: on = .true.
end module ctl

program p
  use omp_lib, only: omp_is_initial_device
  use ctl
  implicit none
  integer :: b(64), i, dev
  b = 0
  dev = -1
  !$omp target teams distribute parallel do map(tofrom: b, dev) if (on)
  do i = 1, 64
    b(i) = i
    if (i == 1) dev = merge(0, 1, omp_is_initial_device())
  end do
  print *, 'b(1)', b(1), 'b(64)', b(64), 'dev', dev
end program p
! site:
! title: ftn: target teams distribute parallel do with if(<run-time true>) runs no iterations at all
! control: ../vendor/checks/src/cce/control/cce21-combined-if-runtime-expr-loop-skipped-control.f90 if (target: on) instead of if
! + (on)
! end site
