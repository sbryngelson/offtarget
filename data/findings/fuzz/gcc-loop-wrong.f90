! # Finding (leads): GCC 16.2 gives a wrong result on a Fortran OpenMP program with a loop construct
!
! - toolchains and modes that fail: gcc (GCC 16.2.0); modes: copy; -O2
! - build: gfortran -fopenmp -foffload=amdgcn-amdhsa -foffload-options=amdgcn-amdhsa=-march=gfx942 -O2
! - failure: wrong_answer (check=fail)
! - observed: `checksum= 79579206` with `check=fail`; identical signature on 1 of 1 failing cells
! - expected: compiles and prints `checksum= 1324150940` with `check=pass`
! - rule: a conforming program's result is the one its constructs define: "A loop construct specifies that the logical iterations of
!   the associated loops may execute concurrently and permits the encountering threads to execute the loop accordingly." (OpenMP 5.2
!   §11.7 p.257 l.8-9)
! - same-compiler control: controls/lead-def1-19377-gcc-unwrap-loop-control.f90 (one change from this file; correct on gcc (GCC
!   16.2.0); rows results/leads/reduce/lead-def1-19377-gcc/rows.jsonl)
! - other families: afar (AFAR 24.3.0), afar244 (AFAR 24.4.0), cce19 (CCE 19.0.0), cce20 (CCE 20.0.2), cce21 (CCE 21.0.3), cce21_4
!   (CCE 21.0.4) run the file correctly (site rows, check case site-fuzz--gcc-loop-wrong)
! - programs (1): def1:19377
! - legality: the rules engine accepts it (offload.engine.prerun.rules_witness); afar, afar244, cce19, cce20, cce21 run it correctly
!   in the confirmer's runs (tools/confirm.py case); the legality verdict is computed (tools/review/review.py mechanical)
program fuzz_prog
  use omp_lib, only: omp_is_initial_device
  implicit none
  integer, parameter :: n = 100, m = 3
  integer, allocatable, target :: ia(:)
  integer :: ic(n, m)
  integer(8) :: o1(n)
  integer :: i, j, hf1
  integer(8) :: cs
  allocate(ia(n))
  do i = 1, n
    ia(i) = mod(i * 6 + 31, 101) - 39
  end do
  do j = 1, m
    do i = 1, n
      ic(i, j) = mod((i + 2 * j) * 6 + 24, 30011) - 9787
    end do
  end do
  o1 = 0
  hf1 = 0
  ! fuzz: kernels
    !$omp target map(tofrom: hf1)
      hf1 = merge(1, 0, omp_is_initial_device())
      !$omp parallel
        !$omp loop
        do i = 1, n
          o1(i) = (int((ic(i, (mod(((i * 3) + 3), m) + 1)) + 9), 8) * int(ia(i), 8))
        end do
        !$omp end loop
      !$omp end parallel
    !$omp end target
  ! fuzz: checksum
  cs = 0
  do i = 1, n
    cs = modulo(cs * 31_8 + int(o1(i), 8), 2147483629_8)
  end do
  print '(a,i0)', 'checksum= ', cs
  print '(a,i0,a,a)', 'RESULT ran_on_host=', max(hf1, 0), ' check=', merge('pass', 'fail', cs == 1324150940_8)
end program fuzz_prog

! site:
! title: GCC: wrong with loop
! summary: GCC 16.2 gives a wrong result on a Fortran OpenMP program with a loop construct.
! control: fuzz/controls/lead-def1-19377-gcc-unwrap-loop-control.f90 one change from the finding; correct on gcc
! end site
