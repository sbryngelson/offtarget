! # Finding (leads): GCC 16.2 fails to link on a Fortran OpenMP program with a defaultmap clause, a reduction clause and a parallel
!   do construct
!
! - toolchains and modes that fail: gcc (GCC 16.2.0); modes: copy; -O2
! - build: gfortran -fopenmp -foffload=amdgcn-amdhsa -foffload-options=amdgcn-amdhsa=-march=gfx942 -O2
! - failure: rejected
! - observed: `ld: error: undefined symbol: __atomic_fetch_or_1`; identical signature on 1 of 1 failing cells
! - expected: compiles and prints `checksum= 13` with `check=pass`
! - rule: a conforming program compiles and links: "The defaultmap clause determines the implicit data-mapping or data-sharing
!   attribute of certain variables that are referenced in a target construct, in accordance with the rules given in Section 5.8.1."
!   (OpenMP 5.2 §5.8.7 p.161 l.14-16); "For each list item, a private copy is created for each implicit task or SIMD lane and is
!   initialized with the initializer value of the reduction-identifier." (OpenMP 5.2 §5.5.8 p.134 l.21-22); "When a thread
!   encounters a parallel construct, a team of threads is created to execute the parallel region (see Section 10.1.1 for more
!   information about how the number of threads in the team is determined, including the evaluation of the if and num_threads
!   clauses)." (OpenMP 5.2 §10.1 p.223 l.12-14); "Separating directives scan Clauses allocate, collapse, firstprivate, lastprivate,
!   linear, nowait, order, ordered, private, reduction, schedule Semantics The do construct is a worksharing-loop construct."
!   (OpenMP 5.2 §11.5.2 p.251 l.2-9)
! - other families: afar (AFAR 24.3.0), afar244 (AFAR 24.4.0), cce19 (CCE 19.0.0), cce20 (CCE 20.0.2), cce21 (CCE 21.0.3), cce21_4
!   (CCE 21.0.4) run the file correctly (site rows, check case site-fuzz--gcc-defaultmap-reduction-parallel-do-rejected)
! - programs (1): def1:1336
! - legality: the rules engine accepts it (offload.engine.prerun.rules_witness); the legality verdict is computed
!   (tools/review/review.py mechanical)
program fuzz_prog
  use omp_lib, only: omp_is_initial_device
  implicit none
  integer, parameter :: n = 24, m = 4
  integer, allocatable :: o1(:, :)
  integer, pointer :: o2(:, :)
  integer(1) :: r2a
  integer :: i, j, hf2
  integer(8) :: cs
  allocate(o1(n, m))
  o1 = 0
  o2 = 0
  hf2 = 0
  r2a = 13_1
  ! fuzz: kernels
  !$omp target map(tofrom: hf2) defaultmap(to: scalar)
    hf2 = merge(1, 0, omp_is_initial_device())
    !$omp parallel do reduction(ior: r2a)
    do i = 1, n
    end do
    !$omp end parallel do
  !$omp end target
  !$omp target exit data map(from: o1, o2)
  ! fuzz: checksum
  cs = 0
  do j = 1, m
    do i = 1, n
      cs = modulo(cs * 31_8 + int(o1(i, j), 8), 2147483629_8)
    end do
  end do
  cs = modulo(cs * 31_8 + int(r2a, 8), 2147483629_8)
  print '(a,i0)', 'checksum= ', cs
  print '(a,i0,a,a)', 'RESULT ran_on_host=', max(hf2, 0), ' check=', 'pass'
end program fuzz_prog

! site:
! title: GCC: rejected with defaultmap, reduction and parallel do
! summary: GCC 16.2 fails to link on a Fortran OpenMP program with a defaultmap clause, a reduction clause and a parallel do
! + construct.
! end site
