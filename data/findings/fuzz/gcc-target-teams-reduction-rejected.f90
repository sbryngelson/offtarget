! # Finding (leads): GCC 16.2 fails to link on a Fortran OpenMP program with a target construct, a teams construct and a reduction
!   clause
!
! - toolchains and modes that fail: gcc (GCC 16.2.0); modes: copy; -O2
! - build: gfortran -fopenmp -foffload=amdgcn-amdhsa -foffload-options=amdgcn-amdhsa=-march=gfx942 -O2
! - failure: rejected
! - observed: `ld: error: undefined symbol: __atomic_fetch_and_2`; identical signature on 1 of 1 failing cells
! - expected: compiles and prints `checksum= 112294459` with `check=pass`
! - rule: a conforming program compiles and links: "The target construct provides a superset of the functionality provided by the
!   target data directive, except for the use_device_ptr and use_device_addr clauses." (OpenMP 5.2 §13.8 p.284 l.11-12); "When a
!   thread encounters a teams construct, a league of teams is created." (OpenMP 5.2 §10.2 p.230 l.12); "For each list item, a
!   private copy is created for each implicit task or SIMD lane and is initialized with the initializer value of the
!   reduction-identifier." (OpenMP 5.2 §5.5.8 p.134 l.21-22)
! - same-compiler control: controls/lead-g1x0-o3-98-gcc-delete-clause-reduction-iand-r2a-control.f90 (one change from this file;
!   correct on gcc (GCC 16.2.0); rows results/leads/reduce/lead-g1x0-o3-98-gcc/rows.jsonl);
!   controls/lead-g1x0-o3-98-gcc-unwrap-target-control.f90 (one change from this file; correct on gcc (GCC 16.2.0); rows
!   results/leads/reduce/lead-g1x0-o3-98-gcc/rows.jsonl); controls/lead-g1x0-o3-98-gcc-unwrap-teams-control.f90 (one change from
!   this file; correct on gcc (GCC 16.2.0); rows results/leads/reduce/lead-g1x0-o3-98-gcc/rows.jsonl)
! - other families: afar (AFAR 24.3.0), afar244 (AFAR 24.4.0), cce19 (CCE 19.0.0), cce20 (CCE 20.0.2), cce21 (CCE 21.0.3), cce21_4
!   (CCE 21.0.4) run the file correctly (site rows, check case site-fuzz--gcc-target-teams-reduction-rejected)
! - programs (1): g1x0-o3:98
! - legality: the rules engine accepts it (offload.engine.prerun.rules_witness); the legality verdict is computed
!   (tools/review/review.py mechanical)
program fuzz_prog
  use omp_lib, only: omp_is_initial_device
  implicit none
  integer, parameter :: n = 100, m = 8
  type :: rec_t
  end type rec_t
  type(rec_t) :: dr
  integer, target :: ia(n)
  integer, target :: ib(n)
  integer, allocatable, target :: ic(:, :)
  integer, allocatable :: as1
  integer, allocatable :: o1(:)
  integer :: o2(n)
  real(kind=4) :: xr4(n)
  integer(kind=2) :: r2a
  integer :: i, j, p1, hf1
  integer(8) :: cs
  allocate(ic(n, m))
  allocate(o1(n))
  allocate(as1)
  do i = 1, n
    ia(i) = mod(i * 34 + 11, 211) - 67
  end do
  do i = 1, n
    ib(i) = mod(i * 14 + 2, 1009) - 365
  end do
  do j = 1, m
    do i = 1, n
      ic(i, j) = mod((i + 9 * j) * 26 + 42, 30011) - 206
    end do
  end do
  do i = 1, n
    xr4(i) = real(mod(i * 20 + 41, 211) - 25, 4) * 0.5
  end do
  as1 = 33
  o1 = 0
  o2 = 0
  p1 = 8
  hf1 = 0
  r2a = 32767_2
  ! fuzz: kernels
  call kp2(as1, ia, ib, ic, o2, p1)
  ! fuzz: checksum
  cs = 0
  do i = 1, n
    cs = modulo(cs * 31_8 + int(o1(i), 8), 2147483629_8)
  end do
  cs = modulo(cs * 31_8 + int(r2a, 8), 2147483629_8)
  do i = 1, n
    cs = modulo(cs * 31_8 + int(o2(i), 8), 2147483629_8)
  end do
  print '(a,i0)', 'checksum= ', cs
  print '(a,i0,a,a)', 'RESULT ran_on_host=', max(hf1, 0), ' check=', merge('pass', 'fail', cs == 112294459_8)
contains
  subroutine kp1(as1, o1, xr4, p1)
    integer, intent(inout) :: as1
    integer, intent(inout) :: o1(n)
    real(kind=4), intent(inout) :: xr4(:)
    integer, intent(in) :: p1
      !$omp target map(tofrom: hf1) defaultmap(tofrom: scalar)
        hf1 = merge(1, 0, omp_is_initial_device())
      !$omp end target
  end subroutine kp1
  subroutine kp2(as1, ia, ib, ic, o2, p1)
    integer, intent(in) :: as1
    integer, intent(inout) :: ia(:)
    integer, intent(inout) :: ib(n)
    integer, intent(inout) :: ic(n, m)
    integer, intent(inout) :: o2(:)
    integer, value :: p1
    !$omp target
      !$omp teams reduction(iand: r2a)
      !$omp end teams
    !$omp end target
  end subroutine kp2
end program fuzz_prog

! site:
! title: GCC: rejected with target, teams and reduction
! summary: GCC 16.2 fails to link on a Fortran OpenMP program with a target construct, a teams construct and a reduction clause.
! control: fuzz/controls/lead-g1x0-o3-98-gcc-delete-clause-reduction-iand-r2a-control.f90 one change from the finding; correct on
! + gcc
! control: fuzz/controls/lead-g1x0-o3-98-gcc-unwrap-target-control.f90 one change from the finding; correct on gcc
! control: fuzz/controls/lead-g1x0-o3-98-gcc-unwrap-teams-control.f90 one change from the finding; correct on gcc
! end site
