! Finding: CCE 20 and 21 internal compiler error: optcg killed by
! signal 6 (ftn-2116 "optcg was terminated due to receipt of signal 06:
! Aborted") on a program with a target teams loop that maps a pointer
! component (map(always, tofrom: dr%pc)) and reduces with a user-defined
! reduction (reduction(padd: rp2a), declare reduction padd for a derived
! type), next to a target teams region with map(tofrom: dr) and
! reduction(min: r1a). CCE 19 does not implement user-defined reductions
! in target regions (not_implemented, a support gap).
!
! Legal OpenMP 5.2 (declare reduction §5.5.11 and its use on teams/loop,
! §5.5.8; a pointer component in a map clause, §5.8.3). Legality: offload.engine.prerun.check accepts
! it (rerun: offload.engine.rules with the race rule and the restriction checks, and the AFAR
! flang front end, not under test here); no compiler under test, gfortran or gcc is a legality
! witness.
!
! Observed (tuolumne, MI300A, -O2, 2026-10-23, results/t28_probe/icev2.log):
! the confirmer's reduction of s1 seed 6085 (results/confirm/drafts/
! fuzz_s1_6085_cce21_gfx942_unified, 216 -> 179 lines, ICE kept) gives the
! optcg abort on CCE 20 and 21; this file is that program reduced further
! on CCE 21 by deleting lines while the abort stays
! (data/evidence/dataenv_probe/min_ice.py; 179 -> 130 lines). Hand-written forms of
! the two kernels alone do not reproduce it (data/evidence/dataenv_probe/ice/b1-b3.f90:
! CCE reports "Unsupported OpenMP construct Calls -- __GET_DYNAMIC_TYPE" or
! compiles). Fuzz campaign s1: the ftn-2116 signal 06 cells of CCE 19/20/21.
!
! Fix: reduced further by clause and list-item
! deletion as well as lines (data/evidence/dataenv_probe/min_ice.py, 130 -> 56 lines,
! results/t28_probe/short/): two empty target teams constructs, one with
! map(tofrom: dr) (a structure with an allocatable component) and
! reduction(min: r1a), one a target teams loop with the user reduction
! reduction(padd: rp2a), and a module procedure in a submodule; the optcg
! abort stays on CCE 20 and 21, CCE 19 reports user reductions not
! implemented, AFAR compiles it (results/t28_probe/icev_fr1.log).
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
end module fuzz_dmod
!@file fuzz_smod.f90
module fuzz_smod
  implicit none
  interface
    module integer function gs1(x)
      integer, intent(in) :: x
    end function gs1
  end interface
end module fuzz_smod
!@file fuzz_ssub.f90
submodule (fuzz_smod) fuzz_ssub
  implicit none
contains
  module integer function gs1(x)
    integer, intent(in) :: x
  end function gs1
end submodule fuzz_ssub
!@file fuzz_prog.f90
program fuzz_prog
  use fuzz_dmod
  implicit none
  integer, parameter :: n = 100, m = 5
  type :: rec_t
    integer, allocatable :: o1(:)
  end type rec_t
  type(pair_t) :: rp2a
  integer :: i, r1a
contains
  subroutine kp1(xr4, dr)
    real(4), allocatable, intent(in) :: xr4(:)
    type(rec_t), intent(inout) :: dr
    !$omp target teams map(tofrom: dr) reduction(min: r1a)
    !$omp end target teams
  end subroutine kp1
  subroutine kp2(ic, xk1, xr4, dr, ms)
    integer, intent(inout) :: ic(:, :)
    integer(1), allocatable, intent(in) :: xk1(:)
    real(4), intent(in) :: xr4(:)
    type(rec_t), intent(inout) :: dr
    type(mt_t), intent(inout) :: ms
    !$omp target teams loop reduction(padd: rp2a)
    do i = 1, n
    end do
  end subroutine kp2
end program fuzz_prog
! site:
! title: craycc/ftn: OpenMP 5.1/5.2/6.0 forms HPE does not claim are rejected, and some crash the compiler instead of a diagnostic
! control: ../vendor/checks/src/other/control/s1-6085-cce21-control.f90 reduction(min: r1a) removed from the first target teams
! same_as: catalog/cce-c-map-iterator-ice
! end site
