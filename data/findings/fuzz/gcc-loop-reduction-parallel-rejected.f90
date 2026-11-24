! # Finding (leads): GCC 16.2 fails to link on a Fortran OpenMP program with a loop construct, a reduction clause and a parallel
!   construct
!
! - toolchains and modes that fail: gcc (GCC 16.2.0); modes: copy; -O2
! - build: gfortran -fopenmp -foffload=amdgcn-amdhsa -foffload-options=amdgcn-amdhsa=-march=gfx942 -O2
! - failure: rejected
! - observed: `ld: error: undefined symbol: __atomic_fetch_xor_2`; identical signature on 1 of 1 failing cells
! - expected: compiles and prints `checksum= 810871836` with `check=pass`
! - rule: a conforming program compiles and links: "A loop construct specifies that the logical iterations of the associated loops
!   may execute concurrently and permits the encountering threads to execute the loop accordingly." (OpenMP 5.2 §11.7 p.257 l.8-9);
!   "For each list item, a private copy is created for each implicit task or SIMD lane and is initialized with the initializer value
!   of the reduction-identifier." (OpenMP 5.2 §5.5.8 p.134 l.21-22); "When a thread encounters a parallel construct, a team of
!   threads is created to execute the parallel region (see Section 10.1.1 for more information about how the number of threads in
!   the team is determined, including the evaluation of the if and num_threads clauses)." (OpenMP 5.2 §10.1 p.223 l.12-14)
! - same-compiler control: controls/lead-g1x0-o3-955-gcc-delete-clause-reduction-ieor-r1a-control.f90 (one change from this file;
!   correct on gcc (GCC 16.2.0); rows results/leads/reduce/lead-g1x0-o3-955-gcc/rows.jsonl);
!   controls/lead-g1x0-o3-955-gcc-shorten-target-parallel-to-target-control.f90 (one change from this file; correct on gcc (GCC
!   16.2.0); rows results/leads/reduce/lead-g1x0-o3-955-gcc/rows.jsonl); controls/lead-g1x0-o3-955-gcc-unwrap-loop-control.f90 (one
!   change from this file; correct on gcc (GCC 16.2.0); rows results/leads/reduce/lead-g1x0-o3-955-gcc/rows.jsonl)
! - other families: afar (AFAR 24.3.0), afar244 (AFAR 24.4.0), cce19 (CCE 19.0.0), cce20 (CCE 20.0.2), cce21 (CCE 21.0.3), cce21_4
!   (CCE 21.0.4) run the file correctly (site rows, check case site-fuzz--gcc-loop-reduction-parallel-rejected)
! - programs (1): g1x0-o3:955
! - legality: the rules engine accepts it (offload.engine.prerun.rules_witness); the legality verdict is computed
!   (tools/review/review.py mechanical)
integer function ge1(x)
  implicit none
  integer, intent(in) :: x
  !$omp declare target
  ge1 = 0
end function ge1
!@file fuzz_prog.f90
program fuzz_prog
  use omp_lib, only: omp_get_thread_num, omp_is_initial_device
  implicit none
  interface
    integer function ge1(x)
      !$omp declare target
      integer, intent(in) :: x
    end function ge1
  end interface
  integer, parameter :: n = 128, m = 5
  type :: nd_t
    integer :: k(n)
    real(8) :: w(n)
  end type nd_t
  type :: rec_t
    integer :: a(n)
    real(8) :: b(n)
    integer, allocatable :: q(:)
    type(nd_t) :: nd
  end type rec_t
  type(rec_t) :: dr
  integer, allocatable :: ia(:)
  integer, allocatable :: ib(:)
  integer :: ic(n, m)
  integer, allocatable :: as1
  integer, allocatable :: o2(:)
  integer, allocatable :: s2(:)
  double precision :: xr8(n)
  logical, allocatable :: xl(:)
  integer(2) :: xk2(n)
  integer(8) :: xk8(n)
  logical :: o1(n, m)
  integer(2) :: r1a
  integer :: i, j, jj, p1, hf1, hf2
  integer(8) :: cs
  allocate(ia(n))
  allocate(ib(n))
  allocate(xl(n))
  allocate(o2(n))
  allocate(s2(n))
  allocate(as1)
  allocate(dr%q(n))
  do i = 1, n
    ia(i) = mod(i * 54 + 29, 211) - 86
  end do
  do i = 1, n
    ib(i) = mod(i * 26 + 47, 97) - 11
  end do
  do j = 1, m
    do i = 1, n
      ic(i, j) = mod((i + 2 * j) * 7 + 11, 1009) - 262
    end do
  end do
  do i = 1, n
    xr8(i) = real(mod(i * 28 + 2, 101) - 39, 8) * 0.5d0
    xl(i) = mod(i * 9 + 24, 3) == 0
    xk2(i) = int(mod(i * 20 + 48, 16001) - 8000, 2)
    xk8(i) = int(i, 8) * 1000000007_8 + int(29, 8)
    dr%a(i) = mod(i * 56 + 44, 211) - 82
    dr%b(i) = real(mod(i * 30 + 44, 211) - 102, 8) * 0.5_8
    dr%nd%k(i) = mod(i * 35 + 39, 1009) - 120
    dr%nd%w(i) = real(mod(i * 15 + 21, 211) - 71, 8) * 0.5_8
    dr%q(i) = mod(i * 50 + 3, 1009) - 45
  end do
  as1 = -11
  o1 = .false.
  o2 = 0
  s2 = 0
  p1 = -7
  hf1 = 0
  hf2 = 0
  r1a = 6_2
  ! fuzz: kernels
  call kp1(as1, ic, o1, xk2, xl, dr)
  ! fuzz: checksum
  cs = 0
  cs = modulo(cs * 31_8 + int(r1a, 8), 2147483629_8)
  do j = 1, m
    do i = 1, n
      cs = modulo(cs * 31_8 + merge(1_8, 0_8, o1(i, j)), 2147483629_8)
    end do
  end do
  do i = 1, n
    cs = modulo(cs * 31_8 + int(o2(i), 8), 2147483629_8)
  end do
  print '(a,i0)', 'checksum= ', cs
  print '(a,i0,a,a)', 'RESULT ran_on_host=', max(hf1, hf2, 0), ' check=', merge('pass', 'fail', cs == 810871836_8)
contains
  subroutine kp1(as1, ic, o1, xk2, xl, dr)
    integer, intent(in) :: as1
    integer, intent(inout) :: ic(n, m)
    logical, intent(inout) :: o1(n, m)
    integer(2), intent(inout) :: xk2(:)
    logical, intent(inout) :: xl(n)
    type(rec_t), intent(inout) :: dr
    integer :: i, j, jj
    !$omp target parallel map(always, tofrom: hf1)
      if (omp_get_thread_num() == 0) hf1 = merge(1, 0, omp_is_initial_device())
      !$omp loop reduction(ieor: r1a)
      do i = 1, n
      end do
      !$omp end loop
    !$omp end target parallel
  end subroutine kp1
end program fuzz_prog

! site:
! title: GCC: rejected with loop, reduction and parallel
! summary: GCC 16.2 fails to link on a Fortran OpenMP program with a loop construct, a reduction clause and a parallel construct.
! control: fuzz/controls/lead-g1x0-o3-955-gcc-delete-clause-reduction-ieor-r1a-control.f90 one change from the finding; correct on
! + gcc
! control: fuzz/controls/lead-g1x0-o3-955-gcc-shorten-target-parallel-to-target-control.f90 one change from the finding; correct on
! + gcc
! control: fuzz/controls/lead-g1x0-o3-955-gcc-unwrap-loop-control.f90 one change from the finding; correct on gcc
! end site
