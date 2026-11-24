! # Finding (leads): GCC 16.2 aborts at run time on a Fortran OpenMP program with a target construct, a teams loop construct and a
!   thread_limit clause
!
! - toolchains and modes that fail: gcc (GCC 16.2.0); modes: copy; -O2
! - build: gfortran -fopenmp -foffload=amdgcn-amdhsa -foffload-options=amdgcn-amdhsa=-march=gfx942 -O2
! - failure: crash
! - observed: `Memory access fault by GPU node-7 (Agent handle: 0x5a5e60) on address 0x800000000. Reason: Unknown.` (killed by
!   signal 6); identical signature on 1 of 1 failing cells
! - expected: compiles and prints `checksum= 0` with `check=pass`
! - rule: a conforming program runs to completion: "The target construct provides a superset of the functionality provided by the
!   target data directive, except for the use_device_ptr and use_device_addr clauses." (OpenMP 5.2 §13.8 p.284 l.11-12); "When a
!   thread encounters a teams construct, a league of teams is created." (OpenMP 5.2 §10.2 p.230 l.12); "A loop construct specifies
!   that the logical iterations of the associated loops may execute concurrently and permits the encountering threads to execute the
!   loop accordingly." (OpenMP 5.2 §11.7 p.257 l.8-9); "As described in Section 2.4, some constructs limit the number of threads
!   that may participate in a contention group initiated by each team by setting the value of the thread-limit-var ICV for the
!   initial task to an implementation-defined value greater than zero." (OpenMP 5.2 §13.3 p.277 l.17-19)
! - same-compiler control: controls/lead-g1x0-o3-1522-gcc-delete-clause-thread-limit-1-control.f90 (one change from this file;
!   correct on gcc (GCC 16.2.0); rows results/leads/reduce/lead-g1x0-o3-1522-gcc/rows.jsonl);
!   controls/lead-g1x0-o3-1522-gcc-delete-clause-thread-limit-64-control.f90 (one change from this file; correct on gcc (GCC
!   16.2.0); rows results/leads/reduce/lead-g1x0-o3-1522-gcc/rows.jsonl); controls/lead-g1x0-o3-1522-gcc-unwrap-target-control.f90
!   (one change from this file; correct on gcc (GCC 16.2.0); rows results/leads/reduce/lead-g1x0-o3-1522-gcc/rows.jsonl);
!   controls/lead-g1x0-o3-1522-gcc-unwrap-teams-loop-control.f90 (one change from this file; correct on gcc (GCC 16.2.0); rows
!   results/leads/reduce/lead-g1x0-o3-1522-gcc/rows.jsonl)
! - other families: afar (AFAR 24.3.0), afar244 (AFAR 24.4.0), cce20 (CCE 20.0.2), cce21 (CCE 21.0.3), cce21_4 (CCE 21.0.4) run the
!   file correctly (site rows, check case site-fuzz--gcc-target-teams-loop-thread-limit-abort); cce19 (CCE 19.0.0) fail it another
!   way, e.g. `ftn-1370 ftn: ERROR FUZZ_PROG, File = site-fuzz--gcc-target-teams-loop-thread-limit-abort.f90, Line = 96, Column =
!   16`
! - programs (1): g1x0-o3:1522
! - legality: the rules engine accepts it (offload.engine.prerun.rules_witness); afar, afar244, cce20, cce21 run it correctly in the
!   confirmer's runs (tools/confirm.py case); the legality verdict is computed (tools/review/review.py mechanical)
module fuzz_bmod
  implicit none
contains
  integer function gb1(x)
    !$omp declare target
    integer, intent(in) :: x
    gb1 = 0
  end function gb1
end module fuzz_bmod
!@file fuzz_ext.f90
integer function ge1(x)
  implicit none
  integer, intent(in) :: x
  !$omp declare target
  ge1 = 0
end function ge1
!@file fuzz_prog.f90
program fuzz_prog
  use omp_lib, only: omp_is_initial_device
  use fuzz_bmod, only: gb1
  implicit none
  interface
    integer function ge1(x)
      !$omp declare target
      integer, intent(in) :: x
    end function ge1
  end interface
  integer, parameter :: n = 32, m = 8
  type :: nd_t
    integer :: k(n)
  end type nd_t
  type :: rec_t
    integer :: a(n)
    integer, allocatable :: q(:)
    integer, pointer :: pc(:)
    type(nd_t) :: nd
  end type rec_t
  type(rec_t) :: dr
  integer, allocatable :: ib(:)
  integer, allocatable :: ic(:, :)
  logical :: xl(n)
  integer(kind=8) :: o2(n, m)
  logical, allocatable :: o3(:)
  integer :: i, j, p1, hf2, t1
  integer(8) :: cs
  allocate(ib(n))
  allocate(ic(n, m))
  allocate(o3(n))
  allocate(dr%q(n))
  do i = 1, n
    ib(i) = mod(i * 20 + 8, 30011) - 2435
  end do
  do j = 1, m
    do i = 1, n
      ic(i, j) = mod((i + 1 * j) * 61 + 39, 30011) - 3747
    end do
  end do
  do i = 1, n
    xl(i) = mod(i * 60 + 45, 3) == 0
    dr%a(i) = mod(i * 9 + 15, 211) - 35
    dr%nd%k(i) = mod(i * 28 + 21, 97) - 12
    dr%q(i) = mod(i * 41 + 44, 211) - 21
  end do
  o2 = 0
  o3 = .false.
  p1 = 6
  hf2 = 0
  ! fuzz: kernels
  !$omp target thread_limit(1)
    !$omp teams loop private(t1) thread_limit(64)
    do i = 1, n
    end do
    !$omp end teams loop
  !$omp end target
  ! fuzz: checksum
  cs = 0
  do j = 1, m
    do i = 1, n
      cs = modulo(cs * 31_8 + int(o2(i, j), 8), 2147483629_8)
    end do
  end do
  do i = 1, n
    cs = modulo(cs * 31_8 + merge(1_8, 0_8, o3(i)), 2147483629_8)
  end do
  print '(a,i0)', 'checksum= ', cs
  print '(a,i0,a,a)', 'RESULT ran_on_host=', max(hf2, 0), ' check=', merge('pass', 'fail', cs == 0_8)
contains
  subroutine kp1(ib, ic, o2, dr, p1)
    integer, intent(inout) :: ib(:)
    integer, allocatable, intent(inout) :: ic(:, :)
    integer(8), intent(inout) :: o2(:, :)
    type(rec_t), intent(inout) :: dr
    integer, intent(in) :: p1
    !$omp target teams map(to: dr%a(1:n), dr%q) map(tofrom: hf2)
      !$omp distribute
      do i = 1, n
        if (i == 1) hf2 = merge(1, 0, omp_is_initial_device())
      end do
    !$omp end target teams
  end subroutine kp1
  subroutine kp2(o3, xl)
    logical, allocatable, intent(inout) :: o3(:)
    logical, intent(inout) :: xl(:)
  end subroutine kp2
end program fuzz_prog

! site:
! title: GCC: abort with target, teams loop and thread_limit
! summary: GCC 16.2 aborts at run time on a Fortran OpenMP program with a target construct, a teams loop construct and a
! + thread_limit clause.
! control: fuzz/controls/lead-g1x0-o3-1522-gcc-delete-clause-thread-limit-1-control.f90 one change from the finding; correct on gcc
! control: fuzz/controls/lead-g1x0-o3-1522-gcc-delete-clause-thread-limit-64-control.f90 one change from the finding; correct on gcc
! control: fuzz/controls/lead-g1x0-o3-1522-gcc-unwrap-target-control.f90 one change from the finding; correct on gcc
! control: fuzz/controls/lead-g1x0-o3-1522-gcc-unwrap-teams-loop-control.f90 one change from the finding; correct on gcc
! end site
