! # Finding (leads): GCC 16.2 gives a wrong result on a Fortran OpenMP program with a teams distribute simd construct and a simd
!   construct
!
! - toolchains and modes that fail: gcc (GCC 16.2.0); modes: copy; -O2
! - build: gfortran -fopenmp -foffload=amdgcn-amdhsa -foffload-options=amdgcn-amdhsa=-march=gfx942 -O2
! - failure: wrong_answer (check=fail)
! - observed: `checksum= 1403590242` with `check=fail`; identical signature on 1 of 1 failing cells
! - expected: compiles and prints `checksum= 1483577442` with `check=pass`
! - rule: a conforming program's result is the one its constructs define: "When a thread encounters a teams construct, a league of
!   teams is created." (OpenMP 5.2 §10.2 p.230 l.12); "The distribute construct specifies that the iterations of one or more loops
!   will be executed by the initial teams in the context of their implicit tasks." (OpenMP 5.2 §11.6 p.254 l.18-19); "The simd
!   construct enables the execution of multiple iterations of the associated loops concurrently by using SIMD instructions." (OpenMP
!   5.2 §10.4 p.235 l.12-13); "The simd construct enables the execution of multiple iterations of the associated loops concurrently
!   by using SIMD instructions." (OpenMP 5.2 §10.4 p.235 l.12-13)
! - same-compiler control: controls/lead-g1x0-o3-651-gcc-shorten-teams-distribute-simd-to-teams-d-control.f90 (one change from this
!   file; correct on gcc (GCC 16.2.0); rows results/leads/reduce/lead-g1x0-o3-651-gcc/rows.jsonl);
!   controls/lead-g1x0-o3-651-gcc-unwrap-teams-distribute-simd-control.f90 (one change from this file; correct on gcc (GCC 16.2.0);
!   rows results/leads/reduce/lead-g1x0-o3-651-gcc/rows.jsonl)
! - other families: afar (AFAR 24.3.0), afar244 (AFAR 24.4.0), cce19 (CCE 19.0.0), cce20 (CCE 20.0.2), cce21 (CCE 21.0.3), cce21_4
!   (CCE 21.0.4) run the file correctly (site rows, check case site-fuzz--gcc-teams-distribute-simd-simd-wrong)
! - programs (1): g1x0-o3:651
! - legality: the rules engine accepts it (offload.engine.prerun.rules_witness); afar, afar244, cce19, cce20, cce21 run it correctly
!   in the confirmer's runs (tools/confirm.py case); the legality verdict is computed (tools/review/review.py mechanical)
program fuzz_prog
  implicit none
  integer, parameter :: n = 16, m = 8
  type :: rec_t
  end type rec_t
  type(rec_t) :: dr
  integer :: ic(n, m)
  integer :: o1(n)
  integer(8) :: xk8(n)
  integer :: i, j
  integer(8) :: cs
  do j = 1, m
    do i = 1, n
      ic(i, j) = mod((i + 1 * j) * 39 + 41, 1009) - 471
    end do
  end do
  do i = 1, n
    xk8(i) = int(i, 8) * 1000000007_8 + int(22, 8)
  end do
  o1 = 0
  ! fuzz: kernels
  !$omp target
    !$omp teams distribute simd
    do i = 1, n
      o1(i) = mod(mod(iand(int(mod(xk8((mod(((i * 2) + 9), n) + 1)), 1000003_8)), ic(i, (mod(((i * &
          & 6) + 5), m) + 1))), 7), 1009)
    end do
    !$omp end teams distribute simd
  !$omp end target
  ! fuzz: checksum
  cs = 0
  do i = 1, n
    cs = modulo(cs * 31_8 + int(o1(i), 8), 2147483629_8)
  end do
  print '(a,i0)', 'checksum= ', cs
  print '(a,i0,a,a)', 'RESULT ran_on_host=', 0, ' check=', merge('pass', 'fail', cs == 1483577442_8)
end program fuzz_prog

! site:
! title: GCC: wrong with teams distribute simd and simd
! summary: GCC 16.2 gives a wrong result on a Fortran OpenMP program with a teams distribute simd construct and a simd construct.
! control: fuzz/controls/lead-g1x0-o3-651-gcc-shorten-teams-distribute-simd-to-teams-d-control.f90 one change from the finding;
! + correct on gcc
! control: fuzz/controls/lead-g1x0-o3-651-gcc-unwrap-teams-distribute-simd-control.f90 one change from the finding; correct on gcc
! end site
