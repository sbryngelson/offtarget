! # Finding (leads): CCE 21 gives a wrong result on a Fortran OpenMP program with an if clause, a declare target construct and a
!   parallel construct
!
! - toolchains and modes that fail: cce21 (CCE 21.0.3), cce21_4 (CCE 21.0.4); modes: unified, copy; -O2
! - build: ftn -fopenmp -O2
! - failure: wrong_answer (check=fail)
! - observed: `checksum= 0` with `check=fail`; identical signature on 4 of 4 failing cells
! - expected: compiles and prints `checksum= 1550517818` with `check=pass`
! - rule: a conforming program's result is the one its constructs define: "If no directive-name-modifier is specified then the
!   effect is as if a directive-name-modifier was specified with the directive-name of the directive on which the clause appears."
!   (OpenMP 5.2 §3.4 p.72 l.11-12); "If the extended-list argument is specified, the effect is as if an enter clause was specified
!   with the extended-list as its argument." (OpenMP 5.2 §7.8.1 p.206 l.9-10); "When a thread encounters a parallel construct, a
!   team of threads is created to execute the parallel region (see Section 10.1.1 for more information about how the number of
!   threads in the team is determined, including the evaluation of the if and num_threads clauses)." (OpenMP 5.2 §10.1 p.223
!   l.12-14)
! - other families: afar (AFAR 24.3.0), afar244 (AFAR 24.4.0), cce19 (CCE 19.0.0), cce20 (CCE 20.0.2), gcc (GCC 16.2.0) run the file
!   correctly (site rows, check case site-fuzz--cce21-if-declare-target-parallel-wrong)
! - programs (1): g1x0-o3:1250
! - legality: the rules engine accepts it (offload.engine.prerun.rules_witness); afar, afar244, cce19, cce20 run it correctly in the
!   confirmer's runs (tools/confirm.py case); the legality verdict is computed (tools/review/review.py mechanical)
! - releases: CCE 19.0.0 and 20.0.2 run it correctly; CCE 21.0.3 and 21.0.4 fail it the same way
integer function ge1(x)
  implicit none
  integer, intent(in) :: x
  !$omp declare target
  ge1 = 0
end function ge1
!@file fuzz_prog.f90
program fuzz_prog
  use omp_lib, only: omp_get_team_num, omp_get_thread_num, omp_is_initial_device
  implicit none
  interface
    integer function ge1(x)
      !$omp declare target
      integer, intent(in) :: x
    end function ge1
  end interface
  integer, parameter :: n = 32, m = 5
  type :: rec_t
    integer :: a(n)
  end type rec_t
  type :: el_t
    integer :: u
  end type el_t
  type(rec_t) :: dr
  type(el_t) :: ds(n)
  integer :: ia(n)
  integer, allocatable :: ib(:)
  integer, allocatable :: ic(:, :)
  integer, allocatable :: as1
  real(4), allocatable :: xr4(:)
  real(8) :: xr8(n)
  complex :: xz4(n)
  complex(8) :: xz8(n)
  logical :: xl(n)
  character(len=4) :: xc(n)
  integer(1) :: xk1(n)
  integer(2) :: xk2(n)
  character(len=8) :: xs
  integer(1) :: o1(n)
  integer :: i, j, jj, p1, hf1
  logical :: lt
  integer(8) :: cs
  allocate(ib(n))
  allocate(ic(n, m))
  allocate(xr4(n))
  allocate(as1)
  do i = 1, n
    ia(i) = mod(i * 10 + 43, 97) - 45
  end do
  do i = 1, n
    ib(i) = mod(i * 4 + 10, 30011) - 14383
  end do
  do j = 1, m
    do i = 1, n
      ic(i, j) = mod((i + 3 * j) * 39 + 5, 30011) - 10872
    end do
  end do
  do i = 1, n
    xr4(i) = real(mod(i * 7 + 28, 101) - 44, 4) * 0.5
    xr8(i) = real(mod(i * 20 + 34, 211) - 89, 8) * 0.5_8
    xz4(i) = cmplx(mod(i * 9 + 5, 101) - 42, mod(i * 5, 17) - 8, 4)
    xz8(i) = cmplx(mod(i * 29 + 8, 101) - 25, mod(i * 8, 17) - 8, 8)
    xl(i) = mod(i * 8 + 13, 3) == 0
    xc(i) = achar(65 + mod(i * 60, 26)) // achar(97 + mod(i + 44, 26)) // achar(48 + mod(i, 10)) // &
        & '#'
    xk1(i) = int(mod(i * 11 + 26, 127), 1)
    xk2(i) = int(mod(i * 17 + 16, 16001) - 8000, 2)
    dr%a(i) = mod(i * 14 + 7, 97) - 14
    ds(i)%u = mod(i * 61 + 36, 97) - 2
  end do
  xs = 'NOQbHhgK'
  as1 = 33
  o1 = 0
  p1 = 8
  hf1 = 0
  lt = .true.
  ! fuzz: kernels
  call kp1(o1, xk1, xs)
  !$omp target exit data map(from: o1)
  ! fuzz: checksum
  cs = 0
  do i = 1, n
    cs = modulo(cs * 31_8 + int(o1(i), 8), 2147483629_8)
  end do
  print '(a,i0)', 'checksum= ', cs
  print '(a,i0,a,a)', 'RESULT ran_on_host=', max(hf1, 0), ' check=', merge('pass', 'fail', cs == 1550517818_8)
contains
  subroutine kp1(o1, xk1, xs)
    integer(kind=1), intent(out) :: o1(:)
    integer(1), intent(inout) :: xk1(:)
    character(len=8), intent(inout) :: xs
    integer :: i, j, jj, t1
    !$omp target teams map(tofrom: hf1) if(lt)
      if (omp_get_team_num() == 0) then
        !$omp parallel
          if (omp_get_thread_num() == 0) hf1 = merge(1, 0, omp_is_initial_device())
        !$omp end parallel
        do i = n, 1, -1
          o1(i) = i
        end do
      end if
    !$omp end target teams
  end subroutine kp1
end program fuzz_prog

! site:
! title: CCE: wrong with if, declare target and parallel
! summary: CCE 21 gives a wrong result on a Fortran OpenMP program with an if clause, a declare target construct and a parallel
! + construct.
! end site
