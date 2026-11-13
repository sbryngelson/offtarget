! # Finding (known-issues harvest): CCE rejects a module's named-constant array
!   referenced in a declare target routine
!
! - source: holdout (a case of the known-issues harvest, held out); this file is the
!   minimal form (data/reports/harvest-known/v-param-array-routine.f90)
! - compilers: CCE 19.0.0, 20.0.2, 21.0.3 (ftn -fopenmp), gfx942 and gfx90a
! - expected: the program compiles and prints RESULT ... check=pass: pick returns c(i), a
!   module named constant [1.5, 2.5]
! - actual: "ftn-7066 ftn: ERROR PICK ... Unsupported accelerator code error: Global in
!   accelerator routine without declare -- c" on every CCE release and both architectures. HPE
!   lists CAST-36609 ("ftn-7066 ... Global in accelerator routine without declare") as resolved
!   in CCE 19.0.0 (data/index/claims/hpe-cce-19.0.0-release_info.txt line 114); this trigger remains
! - control (same compiler): passes with a scalar named constant in the routine
!   (c-param-scalar-routine.f90), with the array a named constant of the routine itself
!   (c-param-array-local.f90), and with the array indexed in the target region itself
!   (c-param-array-region-only.f90); all in data/reports/harvest-known/
! - other families: AFAR compiles and runs it (check=pass); NVHPC 25.11 and 26.9 reject it too
!   (harvest/nvhpc-named-constant-array-declare-target-routine-rejected.f90)
! - legality: Fortran named constants are not variables; OpenMP 5.2's declare target
!   requirement covers variables only: "A variable referenced in a target region but not the
!   target construct that is not declared in the target region must appear in a declare target
!   directive" (§13.8 p.286 l.31-32), and named constants are predetermined shared (§5.1.1 p.98
!   l.11: "Assumed-size arrays and named constants are shared"); a named constant is a list
!   item only "in clauses where it is explicitly allowed" (§3.2.1 p.61 l.10), and declare
!   target's clauses do not name it. The pre-run check (rules and the AFAR front end) accepts the
!   program
! - the OpenACC form (routine seq; hk-015) fails the same way on CCE, but OpenACC 3.4
!   §2.15.2 p.98 l.3623-3625 asks a declare directive for "Fortran module ... variables or arrays"
!   used in accelerator routines, which may cover a named-constant array: not claimed here
! - evidence: results/harvest-known/main.tioga (gate: confirmed), main (Tuolumne),
!   the MI250X probe runs' output (results/harvest-known/logs/tioga/probe.f656gDkdAd9R.log and
!   probe.f656iLRSBypT.log; their rows file probes.tioga.jsonl was not kept); the three controls on CCE 19/20/21, both modes:
!   results/findings-baseline/harvest-cparam-controls.cce.jsonl
module vpa_m
  implicit none
  real(8), parameter :: c(2) = [1.5d0, 2.5d0]
contains
  subroutine pick(i, x)
    !$omp declare target
    integer, intent(in) :: i
    real(8), intent(out) :: x
    x = c(i)
  end subroutine pick
end module vpa_m

program vpa
  use omp_lib
  use vpa_m
  implicit none
  integer :: k, bad, hk_host
  real(8) :: r(100)
  r = 0
  !$omp target teams distribute parallel do map(from: r)
  do k = 1, 100
    call pick(1 + mod(k, 2), r(k))
  end do
  bad = 0
  do k = 1, 100
    if (r(k) /= c(1 + mod(k, 2))) bad = bad + 1
  end do
  hk_host = 1
  !$omp target map(tofrom: hk_host)
  if (.not. omp_is_initial_device()) hk_host = 0
  !$omp end target
  print '(a,i0,a,a)', 'RESULT ran_on_host=', hk_host, ' check=', merge('pass', 'fail', bad == 0)
end program vpa
! site:
! title: ftn rejects a module's named-constant array referenced in a declare target routine
! end site
