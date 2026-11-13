! Finding: CCE 19, 20, 21 internal compiler error "Should never
! reach this code (doehmke)" (v_mt_util_misc.c; line 2697 in 19.0.0, 2711
! in 20.0.2, 2719 in 21.0.3) on a target region with in_reduction(*: r),
! inside taskgroup task_reduction(*: r), that reads a substring of a
! character dummy (ichar(xs(1:1))). With a constant instead of the
! substring all three compile (data/evidence/dataenv_probe/ice/e2.f90).
!
! Legal OpenMP 5.2: in_reduction on target (5.2 §5.5.10), task_reduction on
! taskgroup (§5.5.9), a character dummy referenced in the region (mapped
! implicitly). (A gfortran -fopenmp accept is no evidence: owner, 2026-10-23.) Expected: ichar('k') =
! 107 and mod(107, 13) = 3, so every factor is 1 and r stays -1: "RESULT
! check=pass".
!
! Observed (tuolumne, MI300A, -O2, HSA_XNACK=1 and 0, 2026-10-23,
! results/t28_probe/ice_inred_char_substring.f90.*.json):
! - CCE 19.0.0, 20.0.2, 21.0.3: the ICE above, both modes;
! - AFAR amdflang 24.0.0git: "RESULT check=pass" in both modes;
! - Tioga MI250X (gfx90a, HSA_XNACK=0): CCE 21 the same ICE
!   (results/t28_probe/g90/ice_inred_char_substring.cce21_g90.json).
! Fuzz campaign s1: the "Should never reach this code (doehmke)" cells of
! CCE 19/20/21. Representative s1 seed 2592 on cce21; the confirmer's
! reduction (results/confirm/drafts/fuzz_s1_2592_cce21_gfx942_unified,
! 189 -> 98 lines, ICE kept) reduced further by hand.
!
! ftn -fopenmp -O2
program p
  implicit none
  integer, parameter :: n = 16
  character(len=8) :: xs
  integer :: r
  xs = 'kPACnWLl'
  r = -1
  call kp1(xs)
  if (r == -1) then
    print '(a)', 'RESULT check=pass'
  else
    print '(a,i0)', 'RESULT check=fail r=', r
  end if
contains
  subroutine kp1(xs)
    character(len=*), intent(in) :: xs
    integer :: i
    !$omp taskgroup task_reduction(*: r)
      !$omp target defaultmap(tofrom: scalar) in_reduction(*: r)
        do i = 1, n
          r = r * merge(-1, 1, mod(ichar(xs(1:1)), 13) == 0)
        end do
      !$omp end target
    !$omp end taskgroup
  end subroutine kp1
end program p
! site:
! title: ftn: internal compiler error "Should never reach this code (doehmke)" for in_reduction on target reading a character
! + substring
! control: ../vendor/checks/src/other/control/s1-2592-cce21-control.f90 ichar('k') instead of ichar(xs(1:1))
! end site
