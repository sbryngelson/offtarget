! # Finding (GCC 16.2, LLVM/AOMP harvest): matmul of allocatable array sections in target teams distribute parallel do simd:
!   internal compiler error in gfc_omp_clause_default_ctor
!
! - toolchains: gcc_g90 (GCC 16.2.0, AMD Instinct MI250X gfx90a, Tioga) and gcc_sm80 (GCC 16.2.0, NVIDIA A100 sm_80, wingtip);
!   separate memory only; -O2
! - build: gfortran -fopenmp -foffload=amdgcn-amdhsa -foffload-options=amdgcn-amdhsa=-march=gfx90a -O2 (gcc_g90);
!   -foffload=nvptx-none -foffload-options=nvptx-none=-march=sm_80 -foffload-options=nvptx-none=-latomic -O2 (gcc_sm80)
! - failure: ice: internal compiler error: in gfc_omp_clause_default_ctor
! - observed: `internal compiler error: in gfc_omp_clause_default_ctor, at fortran/trans-openmp.cc:840` at the combined directive,
!   on both targets (the host compiler fails before any offload code is made)
! - expected: compiles; prints `sum=   6720.0` and `RESULT ran_on_host=0 check=pass`
! - rule: a simd construct may contain calls ("The only OpenMP constructs that can be encountered during execution of a simd region
!   are ..." restricts OpenMP constructs, not procedure references: 5.2 §17.1 p.338 l.25-27); matmul is an intrinsic function of the
!   base language (Fortran 2018 16.9.124).
! - same-compiler control (compiles; correct, gcc_sm80: mandatory pass 5 of 5; unset pass 5 of 5; gcc_g90: mandatory pass 5 of 5;
!   unset pass 5 of 5 (results/parity/<machine>/<tc>/probes.jsonl)): the product as explicit loops in the same construct
!   (controls/gcc-teams-simd-matmul-allocatable-control.f90). With explicit-shape arrays the matmul form compiles and runs correctly
!   on both GPUs (mandatory pass 5 of 5; unset pass 5 of 5; results/parity/probes-r2/matmul_explicit.f90). Without simd it compiles;
!   it runs correctly on the MI250X (5 of 5), and on the A100 the offload image fails to load (`libgomp: Link error log error :
!   Prototype doesn't match for '_gfortran_matmul_r4'`, exit 1, 5 of 5; results/parity/probes-r2/matmul_nosimd.f90): a lead, not
!   part of this finding.
! - other families: AFAR and NVHPC 25.11/26.9 run the harvested program correctly (results/harvest/main); CCE fails it another way.
!   The site's finding matrix runs this file on every compiler.
! - harvested programs (2 cells (1 gcc_g90, 1 gcc_sm80); gate: confirmed 2; confirmer: compiler_bug (R10-compile-ice) 2):
!   hv-aomp-smoke-fails-flang-324387
! - legality: the pre-run check (offload.engine.prerun.check: the rules and AFAR's front end, two witnesses) accepts the harvested
!   program; GCC is a compiler under test only and never a legality witness.
program matmul_teams_simd
  use omp_lib, only: omp_is_initial_device
  implicit none
  integer :: k, host_flag
  real, allocatable :: a(:,:,:), b(:,:,:), c(:,:,:)
  allocate(a(5,7,16), b(7,6,16), c(5,6,16))
  a = 1.0
  b = 2.0
  c = 0.0
  host_flag = 1
  !$omp target teams distribute parallel do simd map(tofrom: a, b, c, host_flag)
  do k = 1, 16
    if (k == 1) host_flag = merge(1, 0, omp_is_initial_device())
    c(:,:,k) = c(:,:,k) + matmul(a(:,:,k), b(:,:,k))
  end do
  ! every element is 7 * (1.0 * 2.0)
  print '(a,f8.1)', 'sum= ', sum(c)
  print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, ' check=', merge('pass', 'fail', sum(c) == 5*6*16*14.0)
end program matmul_teams_simd
! site:
! title: matmul of allocatable array sections in target teams distribute parallel do simd: internal compiler error
! summary: A target teams distribute parallel do simd loop whose body assigns matmul of sections of allocatable arrays stops
! + GCC 16.2's Fortran front end with an internal compiler error (gfc_omp_clause_default_ctor), for both offload targets. The
! + same loop with the product written as loops compiles and runs correctly. AFAR and NVHPC run the harvested program correctly.
! control: harvest/controls/gcc-teams-simd-matmul-allocatable-control.f90 the product written as explicit loops
! end site
