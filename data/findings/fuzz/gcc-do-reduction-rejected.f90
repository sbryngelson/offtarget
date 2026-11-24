! # Finding (leads): GCC 16.2 fails to link on a Fortran OpenMP program with a do construct and a reduction clause
!
! - toolchains and modes that fail: gcc (GCC 16.2.0); modes: copy; -O2
! - build: gfortran -fopenmp -foffload=amdgcn-amdhsa -foffload-options=amdgcn-amdhsa=-march=gfx942 -O2
! - failure: rejected
! - observed: `ld: error: undefined symbol: __atomic_fetch_or_2`; identical signature on 1 of 1 failing cells
! - expected: compiles and prints `checksum= 657155505` with `check=pass`
! - rule: a conforming program compiles and links: "Separating directives scan Clauses allocate, collapse, firstprivate,
!   lastprivate, linear, nowait, order, ordered, private, reduction, schedule Semantics The do construct is a worksharing-loop
!   construct." (OpenMP 5.2 §11.5.2 p.251 l.2-9); "For each list item, a private copy is created for each implicit task or SIMD lane
!   and is initialized with the initializer value of the reduction-identifier." (OpenMP 5.2 §5.5.8 p.134 l.21-22)
! - same-compiler control: controls/lead-g1x0-o3-589-gcc-delete-clause-reduction-ior-r1a-control.f90 (one change from this file;
!   correct on gcc (GCC 16.2.0); rows results/leads/reduce/lead-g1x0-o3-589-gcc/rows.jsonl);
!   controls/lead-g1x0-o3-589-gcc-unwrap-do-control.f90 (one change from this file; correct on gcc (GCC 16.2.0); rows
!   results/leads/reduce/lead-g1x0-o3-589-gcc/rows.jsonl)
! - other families: afar (AFAR 24.3.0), afar244 (AFAR 24.4.0), cce19 (CCE 19.0.0), cce20 (CCE 20.0.2), cce21 (CCE 21.0.3), cce21_4
!   (CCE 21.0.4) run the file correctly (site rows, check case site-fuzz--gcc-do-reduction-rejected)
! - programs (1): g1x0-o3:589
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
  use omp_lib, only: omp_is_initial_device
  implicit none
  interface
    integer function ge1(x)
      !$omp declare target
      integer, intent(in) :: x
    end function ge1
  end interface
  integer, parameter :: n = 24, m = 4
  type :: nd_t
    integer :: k(n)
  end type nd_t
  type :: rec_t
    integer, pointer :: pc(:)
    type(nd_t) :: nd
  end type rec_t
  type :: el_t
  end type el_t
  type(rec_t) :: dr
  type(el_t) :: ds(n)
  integer :: o1(n, m)
  integer(2) :: r1a
  integer :: i, j, hf1
  integer(8) :: cs
  do i = 1, n
    dr%nd%k(i) = mod(i * 36 + 18, 1009) - 96
  end do
  o1 = 0
  hf1 = 0
  r1a = 13_2
  ! fuzz: kernels
  !$omp target map(to: dr%pc) map(tofrom: dr%nd%k(1:n), o1(:, :), hf1, r1a)
    hf1 = merge(1, 0, omp_is_initial_device())
    !$omp parallel
      !$omp do reduction(ior: r1a)
      do i = 1, n
      end do
    !$omp end parallel
  !$omp end target
  !$omp target exit data map(from: o1)
  ! fuzz: checksum
  cs = 0
  cs = modulo(cs * 31_8 + int(r1a, 8), 2147483629_8)
  do j = 1, m
    do i = 1, n
      cs = modulo(cs * 31_8 + int(o1(i, j), 8), 2147483629_8)
    end do
  end do
  print '(a,i0)', 'checksum= ', cs
  print '(a,i0,a,a)', 'RESULT ran_on_host=', max(hf1, 0), ' check=', merge('pass', 'fail', cs == 657155505_8)
end program fuzz_prog

! site:
! title: GCC: rejected with do and reduction
! summary: GCC 16.2 fails to link on a Fortran OpenMP program with a do construct and a reduction clause.
! control: fuzz/controls/lead-g1x0-o3-589-gcc-delete-clause-reduction-ior-r1a-control.f90 one change from the finding; correct on
! + gcc
! control: fuzz/controls/lead-g1x0-o3-589-gcc-unwrap-do-control.f90 one change from the finding; correct on gcc
! end site
