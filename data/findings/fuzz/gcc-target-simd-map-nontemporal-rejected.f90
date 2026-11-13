! # Finding (GCC 16.2, fuzz sample): the same array in map and nontemporal of target simd is rejected (Fortran)
!
! - toolchains: gcc_g90 (GCC 16.2.0, AMD Instinct MI250X gfx90a, Tioga) and gcc_sm80 (GCC 16.2.0, NVIDIA A100 sm_80, wingtip);
!   separate memory only; -O2
! - build: gfortran -fopenmp -foffload=amdgcn-amdhsa -foffload-options=amdgcn-amdhsa=-march=gfx90a -O2 (gcc_g90);
!   -foffload=nvptx-none -foffload-options=nvptx-none=-march=sm_80 -foffload-options=nvptx-none=-latomic -O2 (gcc_sm80)
! - failure: rejected: present on multiple clauses
! - observed: `Error: Symbol 'o' present on multiple clauses at (1)` at the nontemporal clause, on both targets; the C form
!   (results/parity/probes-r2/nontemporal_c.c) compiles and runs correctly on both (mandatory pass 5 of 5; unset pass 5 of 5)
! - expected: compiles; prints `bad= 0` and `RESULT ran_on_host=0 check=pass`
! - rule: on a combined construct each clause applies to the leaf constructs that allow it (5.2 §17.2 p.341): map to target,
!   nontemporal to simd; nontemporal is no data-sharing attribute clause, so the map restriction "A list item cannot appear in both
!   a map clause and a data-sharing attribute clause on the same construct" does not apply.
! - same-compiler control (compiles; correct, gcc_sm80: mandatory pass 5 of 5; unset pass 5 of 5; gcc_g90: mandatory pass 5 of 5;
!   unset pass 5 of 5 (results/parity/<machine>/<tc>/probes.jsonl)): the same construct without nontemporal
!   (controls/gcc-target-simd-map-nontemporal-control.f90).
! - GCC's documentation: no row of libgomp.texi's tables names it (undocumented; nontemporal is OpenMP 5.0's).
! - other families: AFAR and CCE 19/20/21/21.0.4 run this file correctly in both memory modes; NVHPC 25.11/26.9 fail it another way
!   (site matrix). The site's finding matrix runs this file on every compiler.
! - fuzz programs (44 cells (22 gcc_g90, 22 gcc_sm80); gate: confirmed 44; confirmer: needs_human (R12b-compile-undecided) 35,
!   compiler_bug (R11-compile-rejection) 9): b0:227, b0:294, c1:1350, c1:1688, c1:1721, c1:18, c1:209, c1:227, c1:427, c1:469,
!   s1:1336, s1:1608, s1:2321, s1:327, s1:3745, s1:4530, s1:9979, x0-alloc:191, x0-declare:70, x0-multitu:111, x0-multitu:227,
!   x0-types:220
! - legality: two witnesses that are neither GCC nor a compiler this finding is about, offload.engine.rules and AFAR flang's
!   front end,
!   accept this file and its control (offload.engine.prerun.check; results/parity/tioga/results/parity/legality.jsonl) and the fuzz
!   programs (the campaign's legality gate; its base-language check, gfortran -std=f2008 without OpenMP, is a syntax check of the
!   base language only and no witness). GCC is a compiler under test only and never a legality witness.
program target_simd_map_nontemporal
  use omp_lib, only: omp_is_initial_device
  implicit none
  integer, parameter :: n = 64
  integer :: o(n), i, bad, host_flag
  o = 0
  host_flag = 1
  !$omp target map(tofrom: host_flag)
    host_flag = merge(1, 0, omp_is_initial_device())
  !$omp end target
  ! map applies to the target leaf, nontemporal to the simd leaf
  !$omp target simd map(tofrom: o) nontemporal(o)
  do i = 1, n
    o(i) = 2 * i
  end do
  bad = count(o /= [(2 * i, i = 1, n)])
  print '(a,i0)', 'bad= ', bad
  print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, ' check=', merge('pass', 'fail', bad == 0)
end program target_simd_map_nontemporal
! site:
! title: The same array in map and nontemporal clauses of a Fortran target simd construct is rejected
! summary: On target simd, map applies to the target leaf and nontemporal to the simd leaf. GCC 16.2's Fortran front end
! + rejects an array named in both ("present on multiple clauses") for both offload targets; the C form compiles and runs. Without
! + nontemporal the program compiles and runs correctly.
! control: fuzz/controls/gcc-target-simd-map-nontemporal-control.f90 the same construct without nontemporal
! end site
