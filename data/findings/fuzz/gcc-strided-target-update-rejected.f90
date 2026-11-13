! # Finding (GCC 16.2, fuzz sample): a Fortran array section with a stride in a target update motion clause is rejected
!
! - toolchains: gcc_g90 (GCC 16.2.0, AMD Instinct MI250X gfx90a, Tioga) and gcc_sm80 (GCC 16.2.0, NVIDIA A100 sm_80, wingtip);
!   separate memory only; -O2
! - build: gfortran -fopenmp -foffload=amdgcn-amdhsa -foffload-options=amdgcn-amdhsa=-march=gfx90a -O2 (gcc_g90);
!   -foffload=nvptx-none -foffload-options=nvptx-none=-march=sm_80 -foffload-options=nvptx-none=-latomic -O2 (gcc_sm80)
! - failure: rejected: Array is not contiguous
! - observed: `Error: Array is not contiguous at (1)` and `Error: Stride should not be specified for array section in FROM clause at
!   (1)` at the target update directive, on both targets
! - expected: compiles; prints `bad= 0` and `RESULT ran_on_host=0 check=pass` (only the odd elements come back)
! - rule: "The target update construct ... was modified to allow array sections that specify discontiguous storage" (5.2 §B.4 p.634
!   l.3-4, the changes from 4.5 to 5.0); the contiguous-storage restriction is the map clause's (5.2 §5.8.3 p.155 l.10), not the
!   motion clauses'.
! - GCC's documentation: libgomp.texi, OpenMP 5.0 table: "Discontiguous array section with target update construct: N" (not
!   supported, documented). The C form is harvest/gcc-c-strided-section-rejected.c.
! - other families: AFAR, CCE and NVHPC fail this file another way (site matrix; AFAR's own strided-update finding is
!   harvest/afar-flang-strided-target-update.f90). The site's finding matrix runs this file on every compiler.
! - fuzz programs (116 cells (58 gcc_g90, 58 gcc_sm80); gate: confirmed 116; confirmer: needs_human (R12b-compile-undecided) 106,
!   compiler_bug (R11-compile-rejection) 10): s1:1040, s1:1692, s1:1792, s1:2014, s1:2084, s1:2160, s1:2267, s1:2617, s1:2744,
!   s1:2949, s1:2970, s1:3049, s1:3197, s1:3219, s1:3392, s1:3457, s1:3503, s1:3685, s1:4207, s1:4477, s1:4501, s1:4655, s1:4680,
!   s1:4788, s1:5088, s1:5371, s1:5383, s1:547, s1:5522, s1:562, s1:6125, s1:6197, s1:6430, s1:6554, s1:6670, s1:6685, s1:6831,
!   s1:6915, s1:7055, s1:7099, and 18 more (the index entry lists them)
! - legality: two witnesses that are neither GCC nor a compiler this finding is about, offload.engine.rules and AFAR flang's front
!   end, accept this file (offload.engine.prerun.check; results/parity/tioga/results/parity/legality.jsonl) and the fuzz programs
!   (the campaign's legality gate; its base-language check, gfortran -std=f2008 without OpenMP, is a syntax check of the base
!   language only and no witness). GCC is a compiler under test only and never a legality witness.
program target_update_strided
  use omp_lib, only: omp_is_initial_device
  implicit none
  integer, parameter :: n = 16
  integer :: a(n), i, bad, host_flag
  a = -1
  !$omp target enter data map(to: a)
  host_flag = 1
  !$omp target map(tofrom: host_flag)
    host_flag = merge(1, 0, omp_is_initial_device())
    do i = 1, n
      a(i) = i
    end do
  !$omp end target
  ! every second element: a(1), a(3), ..., a(15)
  !$omp target update from(a(1:n:2))
  !$omp target exit data map(delete: a)
  bad = 0
  do i = 1, n
    if (mod(i, 2) == 1 .and. a(i) /= i) bad = bad + 1
    if (mod(i, 2) == 0 .and. a(i) /= -1) bad = bad + 1
  end do
  print '(a,i0)', 'bad= ', bad
  print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, ' check=', merge('pass', 'fail', bad == 0)
end program target_update_strided
! site:
! title: A Fortran array section with a stride in a target update motion clause is rejected
! summary: OpenMP 5.0 allows array sections that specify discontiguous storage in target update. GCC 16.2 rejects
! + from(a(1:n:2)) ("Array is not contiguous") for both offload targets; its documentation lists discontiguous array sections
! + in target update as not supported.
! same_as: harvest/gcc-c-strided-section-rejected
! end site
