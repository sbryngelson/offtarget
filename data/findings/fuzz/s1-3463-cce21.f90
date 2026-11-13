! Finding: CCE 19, 20, 21 internal compiler error "Error getting
! dope vector information" (v_dope_utl.c; line 931 in 19.0.0, 933 in
! 20.0.2, 935 in 21.0.3) on a target construct in an internal subroutine
! that maps components of a structure dummy (dr%a, dr%nd%k(1:n)) together
! with host-associated variables (an allocatable array, scalars), in a
! program with a default declare mapper for another type.
!
! Legal OpenMP 5.2 (structure components and array sections of them are
! map list items, 5.2 §5.8.3; host-associated variables in a map clause).
! Legality: offload.engine.prerun.check accepts it (rerun: offload.engine.rules with the race rule
! and the restriction checks, and the AFAR flang front end, not under test here); no compiler under
! test, gfortran or gcc is a legality witness. AFAR compiles and runs the
! unreduced program.
!
! : hand reductions that drop the unused module, types
! and dummies no longer show the ICE (it needs parts that look unused); the
! vendor packet uses this generated program.
!
! Observed (tuolumne, MI300A, -O2, 2026-10-23, results/t28_probe/icev2.log):
! the confirmer's reduction of s1 seed 3463 (results/confirm/drafts/
! fuzz_s1_3463_cce21_gfx942_unified, 252 -> 161 lines, ICE site kept)
! gives the ICE on CCE 19, 20 and 21; this file is that program reduced
! further on CCE 21 by deleting lines while the ICE stays
! (data/evidence/dataenv_probe/min_ice.py; 161 -> 106 lines). A hand-written form with
! only the structure dummy's component maps compiles
! (data/evidence/dataenv_probe/ice/d1.f90), so the trigger is not reduced further.
! Fuzz campaign s1: the "Error getting dope vector information" cells of
! CCE 19/20/21.
!
! Fix: reduced further by clause and list-item
! deletion as well as lines (data/evidence/dataenv_probe/min_ice.py, 106 -> 49 lines,
! results/t28_probe/short/); the ICE stays on CCE 19, 20 and 21 at their
! v_dope_utl.c sites and AFAR compiles it (results/t28_probe/icev_fr1.log).
! The remaining program: an internal subroutine with a target construct
! mapping dr%nd%k(1:n) of a structure dummy, next to an unused internal
! subroutine with a character(len=*) dummy, an optional assumed-shape
! dummy and complex dummies, and a module declare reduction; removing any
! of these makes the ICE go away.
!
! ftn -fopenmp -O2 (a bundle: 
!@file fuzz_dmod.f90
module fuzz_dmod
  implicit none
  type :: mt_t
  end type mt_t
  type :: pair_t
    integer :: x, y
  end type pair_t
  !$omp declare reduction(padd: pair_t: omp_out = pair_t(omp_out%x + omp_in%x, omp_out%y + omp_in%y)) &
  !$omp& initializer(omp_priv = pair_t(0, 0))
contains
end module fuzz_dmod
!@file fuzz_prog.f90
program fuzz_prog
  use omp_lib, only: omp_get_team_num, omp_get_thread_num, omp_is_initial_device
  use fuzz_dmod
  implicit none
  integer, parameter :: n = 48, m = 8
  type :: nd_t
    integer :: k(n)
  end type nd_t
  type :: rec_t
    type(nd_t) :: nd
  end type rec_t
contains
  subroutine kp2(ia, ib, ic, xs, xz4, xz8, dr, ms, zopt)
    integer, intent(inout) :: ia(:)
    integer, intent(in) :: ib(:)
    integer, intent(in) :: ic(n, m)
    character(len=*), intent(in) :: xs
    complex, intent(in) :: xz4(n)
    complex(kind=8), intent(in) :: xz8(n)
    type(rec_t), intent(inout) :: dr
    type(mt_t), intent(inout) :: ms
    integer, intent(in), optional :: zopt(:)
  end subroutine kp2
  subroutine kp3(ia, ib, o3, xc, dr)
    integer, intent(inout) :: ia(n)
    integer, intent(in) :: ib(n)
    integer, intent(inout) :: o3(n)
    character(len=4), intent(inout) :: xc(n)
    type(rec_t), intent(inout) :: dr
    !$omp target map(dr%nd%k(1:n))
      if (omp_get_team_num() == 0) then
      end if
    !$omp end target
  end subroutine kp3
end program fuzz_prog
! site:
! title: ftn: internal compiler error "Error getting dope vector information" mapping a component section of a structure dummy
! control: ../vendor/checks/src/other/control/s1-3463-cce21-control.f90 the map clause dropped from the target construct
! end site
