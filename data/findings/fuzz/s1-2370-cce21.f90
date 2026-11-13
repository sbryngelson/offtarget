! Finding: CCE 19, 20, 21 reject firstprivate(i) on a combined
! parallel do nested in a teams distribute loop over i, under default(none)
! (ftn-1510 "Variable "I" must have its data scope explicitly declared
! because DEFAULT(NONE) was specified"; in other programs ftn-1310 "Object
! "I" is specified on the FIRSTPRIVATE clause. It must have a shared scope
! in the enclosing region").
!
! Legal OpenMP 5.2: firstprivate on a combined construct applies to the
! worksharing leaf, and "If the parallel construct is among the constituent
! constructs and the effect is not as if the firstprivate clause is applied
! to it by the above rules, then the effect is as if the shared clause with
! the same list item is applied to the parallel construct" (5.2 §17.2
! p.340), so i is shared in the parallel region (default(none) is
! satisfied, 5.2 §5.4.1 p.109) and the restriction on worksharing
! firstprivate items that are private in the binding parallel region (5.2
! §5.4.4) does not apply; in the teams region i is the iteration variable of
! the distribute loop, predetermined private ("The loop iteration variable
! in any associated loop of a loop-associated construct is otherwise
! private", 5.2 §5.1.1 p.97). (A gfortran -fopenmp accept is withdrawn as evidence, 2026-10-23.)
! Expected: "RESULT check=pass" (a(i, j) = 10 * i + j).
!
! Observed (tuolumne, MI300A, -O2, HSA_XNACK=1, 2026-10-23,
! results/t28_probe/dn_teams_loopvar*.json):
! - CCE 19.0.0, 20.0.2, 21.0.3: ftn-1510 for I at the firstprivate(i) of
!   the parallel do; without firstprivate(i) (data/evidence/dataenv_probe/
!   dn_teams_loopvar_nofp.f90) all three compile and run correctly;
! - AFAR amdflang 24.0.0git: "RESULT check=pass".
! - Tioga MI250X (gfx90a, HSA_XNACK=0): the same; CCE 19/20/21 reject,
!   AFAR passes (results/t28_probe/g90/dn_teams_loopvar.cce21_g90.json).
! Fuzz campaign s1: the ftn-1510 "I" and ftn-1310 "I" cells of CCE (rule
! R11, decisions D2 and D5), verdict compiler_bug. Representatives: s1
! seeds 2370 (cce21, copy) and 6443 (cce21); reproducer written by hand
! (data/evidence/dataenv_probe/dn_teams_loopvar.f90).
!
! ftn -fopenmp -O2
program p
  implicit none
  integer, parameter :: n = 8, m = 4
  integer :: a(n, m), i, j
  logical :: ok
  a = 0
  !$omp target map(tofrom: a)
  !$omp teams distribute default(none) shared(a) private(j)
  do i = 1, n
    !$omp parallel do default(none) shared(a) firstprivate(i)
    do j = 1, m
      a(i, j) = 10 * i + j
    end do
  end do
  !$omp end teams distribute
  !$omp end target
  ok = .true.
  do i = 1, n
    do j = 1, m
      ok = ok .and. a(i, j) == 10 * i + j
    end do
  end do
  if (ok) then
    print '(a)', 'RESULT check=pass'
  else
    print '(a)', 'RESULT check=fail'
  end if
end program p
! site:
! title: ftn: firstprivate(i) on a parallel do nested in a teams distribute loop over i rejected under default(none) (ftn-1510)
! control: ../vendor/checks/src/other/control/s1-2370-cce21-control.f90 firstprivate(i) removed from the parallel do
! end site
