! # Finding (GCC 16.2, fuzz sample): a declare reduction in a module is not found through use association
!
! - toolchains: gcc_g90 (GCC 16.2.0, AMD Instinct MI250X gfx90a, Tioga) and gcc_sm80 (GCC 16.2.0, NVIDIA A100 sm_80, wingtip);
!   separate memory only; -O2
! - build: gfortran -fopenmp -foffload=amdgcn-amdhsa -foffload-options=amdgcn-amdhsa=-march=gfx90a -O2 (gcc_g90);
!   -foffload=nvptx-none -foffload-options=nvptx-none=-march=sm_80 -foffload-options=nvptx-none=-latomic -O2 (gcc_sm80)
! - failure: rejected: !$OMP DECLARE REDUCTION padd not found
! - observed: `Error: !$OMP DECLARE REDUCTION padd not found at (1)` at the reduction clause, on both targets; the same happens on a
!   host parallel do
! - expected: compiles; prints `s%a= 5050 s%b= 100` and `RESULT ran_on_host=0 check=pass`
! - rule: "If the reduction identifier is defined in a declare reduction directive, the declare reduction directive must be in the
!   same subprogram, or accessible by host or use association" (5.2 §5.5.5 p.133 l.10-11): the directive is in module pair_m, which
!   the program uses.
! - same-compiler control (compiles; correct, gcc_sm80: mandatory pass 5 of 5; unset pass 5 of 5; gcc_g90: mandatory pass 5 of 5;
!   unset pass 5 of 5 (results/parity/<machine>/<tc>/probes.jsonl)): the same declare reduction directive in the program's own
!   specification part (controls/gcc-declare-reduction-module-control.f90).
! - GCC's documentation: no row of libgomp.texi's tables names it (undocumented; user-defined reductions are OpenMP 4.0's).
! - other families: no family runs this file: CCE 19/20/21/21.0.4 reject the reduction clause too, AFAR's front end accepts it and
!   its link fails (flang_rt_verbose_abort undefined) and NVHPC 25.11/26.9 do not implement declare reduction (site matrix); on the
!   fuzz programs every other family fails at another construct first. The claim rests on the rule and on GCC's own control. The
!   site's finding matrix runs this file on every compiler.
! - fuzz programs (380 cells (190 gcc_g90, 190 gcc_sm80); gate: confirmed 380; confirmer: needs_human (R12b-compile-undecided) 380):
!   n1:121, n1:22, n1:234, n1:31, n1:312, n1:362, n1:371, n1:41, n1:428, n1:430, n1:511, n1:748, n1:804, n1:809, n1:813, n1:832,
!   n1:841, n1:939, n1:944, n1:987, s1:1198, s1:1204, s1:1205, s1:1222, s1:1240, s1:1261, s1:1300, s1:1344, s1:1362, s1:1375,
!   s1:1455, s1:1556, s1:1610, s1:1631, s1:1723, s1:1727, s1:1802, s1:1849, s1:1899, s1:1957, and 150 more (the index entry lists
!   them)
! - legality: two witnesses that are neither GCC nor a compiler this finding is about, offload.engine.rules and AFAR flang's
!   front end,
!   accept this file and its control (offload.engine.prerun.check; results/parity/tioga/results/parity/legality.jsonl) and the fuzz
!   programs (the campaign's legality gate; its base-language check, gfortran -std=f2008 without OpenMP, is a syntax check of the
!   base language only and no witness). GCC is a compiler under test only and never a legality witness.
module pair_m
  implicit none
  type :: pair_t
    integer :: a, b
  end type pair_t
  !$omp declare reduction(padd: pair_t: omp_out = &
  !$omp& pair_t(omp_out%a + omp_in%a, omp_out%b + omp_in%b)) &
  !$omp& initializer(omp_priv = pair_t(0, 0))
end module pair_m

program udr_use_association
  use omp_lib, only: omp_is_initial_device
  use pair_m
  implicit none
  type(pair_t) :: s
  integer :: i, host_flag
  s = pair_t(0, 0)
  host_flag = 1
  !$omp target teams distribute parallel do reduction(padd: s) map(tofrom: s, host_flag)
  do i = 1, 100
    if (i == 1) host_flag = merge(1, 0, omp_is_initial_device())
    s%a = s%a + i
    s%b = s%b + 1
  end do
  print '(a,i0,a,i0)', 's%a= ', s%a, ' s%b= ', s%b
  print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, ' check=', merge('pass', 'fail', s%a == 5050 .and. s%b == 100)
end program udr_use_association
! site:
! title: A declare reduction in a module is not found through use association
! summary: A user-defined reduction declared in a module's specification part is accessible through use association. GCC
! + 16.2's Fortran front end rejects its use in a target teams distribute parallel do reduction clause ("!$OMP DECLARE
! + REDUCTION padd not found"), for both offload targets and on the host. With the declare reduction directive in the
! + program's own specification part the program compiles and runs correctly.
! control: fuzz/controls/gcc-declare-reduction-module-control.f90 the declare reduction directive in the program itself
! end site
