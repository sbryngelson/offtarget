! Finding: CCE 21 (and CCE 19/20 in the campaign) reports ftn-1510
! "Variable "HF2" must have its data scope explicitly declared because
! DEFAULT(NONE) was specified" for an assignment in a target region of the
! internal subroutine kp2, which has no default clause anywhere: the
! default(none) is on an (empty) parallel construct in a sibling internal
! subroutine kp1.
!
! Legal OpenMP 5.2: default(none) restricts only "each variable that is
! referenced in the construct" (5.2 §5.4.1 p.109); hf2 is referenced only
! in kp2's target region, which has no default clause. Legality: offload.engine.prerun.check accepts it
! (rerun: offload.engine.rules with the race rule and the restriction checks, and the AFAR
! flang front end, not under test here); no compiler under test, gfortran or gcc is a legality
! witness. (CCE also has the known ICE for masked in a target
! region, cce19-target-parallel-single-ice.f90; this diagnostic comes
! first.)
!
! : hand reductions that drop the unused module, types
! and dummies no longer show ftn-1510, and the program also needs the masked
! construct, which CCE documents as unsupported in offload regions; the vendor
! packet uses this generated program.
!
! Observed (tuolumne, -O2, 2026-10-23): CCE 21.0.3 ftn-1510 for HF2 at
! the assignment. Fuzz campaign s1: the ftn-1510 cells of CCE 19/20/21 for
! variables other than a loop's iteration variable (decision D3; R11 where
! AFAR compiles). Representative s1 seed 91 (cce21, copy mode; compile
! only): the confirmer's reduction (results/confirm/drafts/
! fuzz_s1_91_cce21_gfx942_copy, 223 -> 148 lines) reduced further by
! deleting lines while the diagnostic stays (data/evidence/dataenv_probe/min_ice.py,
! 148 -> 61 lines). A hand-written two-subroutine form without the
! structure maps compiles (it ICEs on the masked construct instead), so
! the trigger is not reduced further.
!
! Fix: the empty fuzz_ext file is gone and the
! program is reduced further by clause and list-item deletion as well as
! lines (data/evidence/dataenv_probe/min_ice.py, 61 -> 41 lines, results/t28_probe/
! short/): kp1 holds an empty parallel default(none) in a target region,
! its sibling kp2 a target region whose masked construct assigns hf2; CCE
! 21 reports ftn-1510 for HF2, CCE 19 and 20 stop earlier at their ICE for
! masked in a target region (results/t28_probe/icev_fr1.log); AFAR
! compiles it. kp2's unused dummies stay because min_ice does not edit
! argument lists.
!
! ftn -fopenmp -O2 (a bundle: 
!@file fuzz_dmod.f90
module fuzz_dmod
  implicit none
  type :: mt_t
  end type mt_t
end module fuzz_dmod
!@file fuzz_prog.f90
program fuzz_prog
  use omp_lib, only: omp_is_initial_device
  use fuzz_dmod
  implicit none
  type :: rec_t
  end type rec_t
  type(rec_t) :: dr
  integer :: hf2
  !$omp target data map(tofrom: dr)
  !$omp end target data
contains
  subroutine kp1(dr)
    type(rec_t), intent(inout) :: dr
    !$omp target 
      !$omp parallel default(none)
      !$omp end parallel
    !$omp end target
  end subroutine kp1
  subroutine kp2(ia, ic, xk1, xr8, dr, ms, p2)
    integer, intent(inout) :: ia(:)
    integer, allocatable, intent(inout) :: ic(:, :)
    integer(kind=1), intent(inout) :: xk1(:)
    real(kind=8), intent(in) :: xr8(:)
    type(rec_t), intent(inout) :: dr
    type(mt_t), intent(inout) :: ms
    integer, intent(in), optional :: p2
    !$omp target &
    !$omp& map(tofrom: hf2)
      !$omp masked
        hf2 = merge(1, 0, omp_is_initial_device())
      !$omp end masked
    !$omp end target
  end subroutine kp2
end program fuzz_prog
! site:
! title: ftn: default(none) on a parallel construct in one internal subroutine makes a variable of another subroutine's target
! + region an error (ftn-1510)
! control: ../vendor/checks/src/other/control/s1-91-cce21-control.f90 default(none) removed from the empty parallel construct of
! + kp1 (the
! + ftn-1510
! + for HF2 goes away; CCE then stops at the masked construct, documented as unsupported in offload regions)
! end site
