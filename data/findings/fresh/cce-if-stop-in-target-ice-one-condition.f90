! # Finding (from the data/bench/fresh draft fresh-106): CCE ICE on an IF with one
!   operand that guards a STOP directly in a target region
!
! - the one-operand form of fresh/cce-if-stop-in-target-ice.f90 (see its header for the source):
!   `if (x /= 1) stop 1` directly in a target region; `if (allocated(j)) stop 1`,
!   `if (.not. allocated(j)) stop 1` and `if (allocated(j)) error stop 1` give the same ICE
!   (data/reports/fresh-drafts/d106-e2.f90, d106-e7.f90, d106-e6.f90; CCE 21 rejects the ERROR STOP
!   instead: "Non-localized coarray control/access statements are not allowed in an OpenMP
!   explicit region")
! - compilers: CCE 19.0.0, 20.0.2 and 21.0.3 ftn, -fopenmp -O2 (gfx942 and gfx90a)
! - expected: compiles and prints x 11 (OpenMP 5.2 §4.3 p.76 l.13-21: "A structured block ... may
!   contain STOP or ERROR STOP statements"); x is 1 on entry, so the STOP is not reached
! - actual: INTERNAL COMPILER ERROR "COND PDG 20 with no stmts." (pdgcs/v_fs.c line 2323 in CCE 19,
!   2325 in CCE 20 and 21)
! - control (same compiler): `if (x /= 1) x = -100` (data/reports/fresh-drafts/d106-r1-ctl.f90)
!   compiles and prints x 11
! - other families: AFAR compiles and prints x 11 (MI300A HSA_XNACK 1 and 0; MI250X)
! - related: catalog/cce-flang-stop-in-target-crash.f90
! - legality: legal by reading
! - evidence: results/fresh-drafts/tuo4-r*.jsonl, tioga/tioga2.jsonl (d106-r1.f90, identical to the
!   program below), tuo2-q1.jsonl (d106-e3.f90, the same with an unused allocatable) (review)
program p
  implicit none
  integer :: x
  x = 1
  !$omp target map(tofrom: x)
    if (x /= 1) stop 1
    x = 11
  !$omp end target
  print *, 'x', x
end program p
! site:
! title: ftn: an IF statement guarding STOP in device code: the STOP runs although its condition is false (target loop), or an
! + internal compiler error (directly in a target region)
! control: ../vendor/checks/src/cce/control/cce-if-stop-in-target-ice-one-condition-control.f90 the IF with an assignment instead
! + of STOP
! same_as: catalog/cce-flang-stop-in-target-crash
! end site
