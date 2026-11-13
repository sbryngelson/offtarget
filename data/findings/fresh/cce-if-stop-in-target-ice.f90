! # Finding (from the data/bench/fresh draft fresh-106): CCE ICE on an IF that guards a STOP
!   directly in a target region
!
! - source: data/bench/fresh/fresh-106.f90 (GCC Bugzilla 119905, libgomp map-alloc-comp-11.f90:
!   recursive allocatable components, checks that end in STOP inside the target region). The ICE
!   needs neither the derived types nor ALLOCATED: it needs an IF whose action is STOP, directly in
!   a target region (not inside a loop construct: the catalog's `if (a(i) < 0) stop 1` inside
!   target teams distribute parallel do compiles, see Related). With two operands joined by .or.
!   (this file) the ICE is the draft's; with one operand it is another ICE
!   (fresh/cce-if-stop-in-target-ice-one-condition.f90)
! - compilers: CCE 19.0.0, 20.0.2 and 21.0.3 ftn, -fopenmp -O2 (gfx942 and gfx90a)
! - expected: compiles and prints x 11. "A structured block ... may contain STOP or ERROR STOP
!   statements" (OpenMP 5.2 §4.3 p.76 l.13-21); x is 1 on entry, so the STOP is not reached
! - actual: INTERNAL COMPILER ERROR "Condition statement not found in condition node"
!   (pdgcs/v_region.c line 636 in CCE 19 and 20, line 646 in CCE 21), the ICE of the draft
! - control (same compiler): the same IF with an assignment instead of the STOP,
!   `if (x /= 1 .or. x > 5) x = -100` (data/reports/fresh-drafts/d106-r2-ctl.f90), compiles and
!   prints x 11
! - other families: AFAR compiles and prints x 11 (MI300A HSA_XNACK 1 and 0; MI250X). NVHPC rejects
!   the draft's recursive allocatable components (a Fortran 2008 feature)
! - related: catalog/cce-flang-stop-in-target-crash.f90 (an unreached IF ... STOP inside a target
!   loop compiles, and the device executes the STOP): the same construct, a different outcome,
!   plausibly the same root cause (the condition of an IF whose action is STOP is lost)
! - legality: legal by reading
! - evidence: results/fresh-drafts/tuo4-r*.jsonl, tioga/tioga2.jsonl (d106-r2.f90, identical to the
!   program below), tuo2-q1.jsonl, tuo3-r*-c.jsonl, tioga/tioga-d.jsonl (d106-e4.f90, the same with an
!   unused allocatable) (review)
program p
  implicit none
  integer :: x
  x = 1
  !$omp target map(tofrom: x)
    if (x /= 1 .or. x > 5) stop 1
    x = 11
  !$omp end target
  print *, 'x', x
end program p
! site:
! title: ftn: an IF statement guarding STOP in device code: the STOP runs although its condition is false (target loop), or an
! + internal compiler error (directly in a target region)
! control: ../vendor/checks/src/cce/control/cce-if-stop-in-target-ice-control.f90 the IF with an assignment instead of STOP
! same_as: catalog/cce-flang-stop-in-target-crash
! end site
