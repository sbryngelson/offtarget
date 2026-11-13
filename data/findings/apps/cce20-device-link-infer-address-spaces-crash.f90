! # CCE 20: device link crash in "Infer address spaces" (MFC's m_cbc kernel, reduced)
!
! MFC's OpenMP and OpenACC solvers do not link on CCE 20.0.2: lld (the device LTO link) crashes in
! "Infer address spaces" on the kernel at m_cbc.fpp:597 (s_cbc$m_cbc_$ck_L597_13), with
! "malloc_consolidate(): unaligned fastbin chunk detected". Reduced from MFC's preprocessed sources
! (the kernel, then m_compute_cbc's routines it calls) to this program.
! Compile: CCE `ftn -fopenmp -O2` after `module load cce/20.0.2 craype-accel-amd-gfx942 rocm/6.4.3;
! module unload cray-mpich` (gfx90a: craype-accel-amd-gfx90a); AFAR `amdflang -fopenmp --offload-arch=gfx942`;
! NVHPC `nvfortran -mp=gpu -gpu=cc80 -gpu=mem:separate|managed`; run with OMP_TARGET_OFFLOAD=mandatory.
! Expected: builds; prints bad= 0 out(:,1)=    0.00    9.50   11.00    6.00    8.00
!
! Observed (2026-10-25):
! - CCE 20.0.2 (gfx942 and gfx90a): the link fails: lld aborts, "Running pass 'Infer address spaces' on
!   function '@"cce20_infer_address_spaces_$ck_L..._3"'" (3 of 3 builds on gfx942, log). Under
!   valgrind, MFC's own kernel shows the cause: an invalid read in
!   llvm::RecursivelyDeleteTriviallyDeadInstructions called from
!   InferAddressSpacesImpl::rewriteWithNewAddressSpaces (a use after free), before the abort.
!   At -O0 CCE 20 builds it and prints bad= 0.
! - CCE 19.0.0 and 21.0.3, AFAR 24.0.0git (drop 24.3.0): builds, bad= 0 (MI300A at HSA_XNACK 1 and 0; MI250X).
! - NVHPC 25.11 and 26.9 (A100, separate and managed memory): bad= 0.
!
! What it needs (controls in apps/controls/, all link and print bad= 0 on CCE 20):
! - cbc-inline.f90: the same program without the !DIR$ INLINENEVER line (CCE inlines the two helpers when it
!   compiles the file): links. INLINENEVER is a Cray compiler directive (a comment to other compilers); with
!   it the helpers are inlined only by the device link's LTO; with -h ipa0 instead of the directive this
!   control crashes too. In MFC the trigger is the fypp line markers of the generated m_compute_cbc: with them
!   CCE emits different device code for its routines (smaller, the helpers' pointer arguments without
!   noalias) and the reduced m_cbc kernel crashes the link; without them it links
!   (data/reports/apps/mfc-device-link.txt). INLINENEVER is this program's way to reach the crash, not a
!   claim about what the markers do.
! - cbc-integers.f90: the index ranges as plain integer module variables instead of components of the
!   declare target derived-type variable eqn_idx: links.
! - Both helpers are needed: controls/cbc-only-density.f90 and controls/cbc-only-velocity.f90 (one of the two
!   calls removed) link on CCE 20; their check still counts the entries the removed helper fills (bad= 128).
! Logs: data/reports/apps/ (cce20-*.txt).
!
! Basis (OpenMP 5.2): a conforming program, so the implementation must build and run it.
! - §1.6 p.34 l.22-24: "An implementation of the OpenMP API is compliant if and only if it compiles and
!   executes all other conforming programs, and supports the tool interfaces, according to the syntax and
!   semantics laid out in Chapters 1 through 20."
! - §7.8 p.204 l.16-17: "Declare target directives apply to procedures and/or variables to ensure that they
!   can be executed or accessed on a device." (module variables, including a variable of derived type, and
!   the three procedures; §7.8.1, declare target with a list and in a procedure.)
! - §13.9 p.289 l.12-13: target update makes the device copies consistent before the region.
! - §5.4.3 p.111 l.9-12 and §5.3 p.105 l.21-30: L, mf, drho, dvel, lambda, c, dp, i are private to each
!   iteration; every element read is first written in that iteration (L by the helpers: 2..3 and 4..5, L(1)
!   stays 0).
! Race-free: out(:, r) is written by iteration r only. Legality was read against the spec; no compiler
! under test, gfortran or gcc is a legality witness.
!
! MFC workaround (checked on MFC's own objects, ee99151, OpenMP): compile m_compute_cbc.fpp at -O0 with CCE 20
! (CMakeLists.txt already sets per-file options for CCE, e.g. -Oipa0 for m_bubbles_EL;
! set_source_files_properties(<build>/fypp/simulation/m_compute_cbc.fpp.f90 PROPERTIES COMPILE_OPTIONS -O0)):
! the device link of every simulation object then succeeds (m_cbc alone at -O0 still crashes; both files at
! -O1 crash), and MFC's own build (tools/jobs/run_mfc.sh MFC_VARIANT=o0cbc) builds and links. Its copy-mode test
! subset: 155 of 159 pass; three Lagrange-bubble adap_dt tests (2122A4F6, 0D1FA5C5, 12ECE133) fail with "memory
! access fault by GPU"; one (20AE0551, 2D bc=-4) was still running after 10 minutes and was stopped (not
! examined).
! Dropping fypp's --line-numbering is not enough: that build crashes in the same kernel (s_cbc ... L1640).
module glob
  implicit none
  integer, parameter :: wp = kind(1.d0)
  type idx_bounds_info
    integer :: beg
    integer :: end
  end type idx_bounds_info
  type eqn_idx_info
    type(idx_bounds_info) :: cont, mom
  end type eqn_idx_info
  integer :: num_dims, num_fluids, sys_size
  type(eqn_idx_info) :: eqn_idx
  !$omp declare target (num_dims, num_fluids, sys_size, eqn_idx)
end module glob

module fill
  use glob
  implicit none
  ! CCE's compile-time inlining off for the two helpers: they are inlined at the device link (LTO)
  !DIR$ INLINENEVER s_fill_density, s_fill_velocity
contains
  subroutine s_fill_density(L, lambda2, c, mf, drho, dp)
    !$omp declare target
    real(wp), dimension(sys_size), intent(inout) :: L
    real(wp), dimension(num_fluids), intent(in) :: mf, drho
    real(wp), intent(in) :: lambda2, c, dp
    integer :: i
    do i = 2, eqn_idx%mom%beg
      L(i) = lambda2*(c*c*drho(i - 1) - mf(i - 1)*dp)
    end do
  end subroutine s_fill_density
  subroutine s_fill_velocity(L, lambda2, dvel)
    !$omp declare target
    real(wp), dimension(sys_size), intent(inout) :: L
    real(wp), dimension(num_dims), intent(in) :: dvel
    real(wp), intent(in) :: lambda2
    integer :: i
    do i = eqn_idx%mom%beg + 1, eqn_idx%mom%end
      L(i) = lambda2*dvel(i - eqn_idx%cont%end)
    end do
  end subroutine s_fill_velocity
  subroutine s_outflow(lambda, L, c, mf, drho, dp, dvel)
    !$omp declare target
    real(wp), dimension(3), intent(in) :: lambda
    real(wp), dimension(sys_size), intent(inout) :: L
    real(wp), dimension(num_fluids), intent(in) :: mf, drho
    real(wp), dimension(num_dims), intent(in) :: dvel
    real(wp), intent(in) :: c, dp
    call s_fill_density(L, lambda(2), c, mf, drho, dp)
    call s_fill_velocity(L, lambda(2), dvel)
  end subroutine s_outflow
end module fill

program cce20_infer_address_spaces
  use fill
  implicit none
  integer, parameter :: nr = 64
  real(wp), allocatable :: out(:, :)
  real(wp) :: L(5), mf(2), drho(2), dvel(3)
  real(wp) :: lambda(3), c, dp, expect
  integer :: r, i, bad
  num_dims = 3; num_fluids = 2
  eqn_idx%cont%beg = 1; eqn_idx%cont%end = num_fluids
  eqn_idx%mom%beg = eqn_idx%cont%end + 1; eqn_idx%mom%end = eqn_idx%cont%end + num_dims
  sys_size = eqn_idx%mom%end
  !$omp target update to(num_dims, num_fluids, sys_size, eqn_idx)
  allocate(out(sys_size, nr))
  out = 0
  !$omp target teams distribute parallel do private(L, mf, drho, dvel, lambda, c, dp, i) map(tofrom: out)
  do r = 1, nr
    do i = 1, num_fluids
      mf(i) = 0.5_wp*i
      drho(i) = 0.25_wp*i + r
    end do
    do i = 1, num_dims
      dvel(i) = 1._wp*i + r
    end do
    lambda = [1._wp, 2._wp, 3._wp]
    c = 2._wp; dp = 0.5_wp
    L = 0
    call s_outflow(lambda, L, c, mf, drho, dp, dvel)
    out(:, r) = L
  end do
  !$omp end target teams distribute parallel do
  bad = 0
  do r = 1, nr
    do i = 1, sys_size
      expect = 0
      if (i >= 2 .and. i <= 3) expect = 2*(4*(0.25_wp*(i - 1) + r) - 0.5_wp*(i - 1)*0.5_wp)
      if (i >= 4) expect = 2*(1._wp*(i - 2) + r)
      if (out(i, r) /= expect) bad = bad + 1
    end do
  end do
  print '(a,i0,a,5f8.2)', 'bad= ', bad, ' out(:,1)=', out(:, 1)
end program cce20_infer_address_spaces
! site:
! title: ftn 20: the device link crashes in "Infer address spaces" (an MFC kernel, reduced)
! control: ../vendor/checks/src/cce/control/cce20-device-link-infer-address-spaces-crash-control.f90 the !DIR$ INLINENEVER line
! + removed (CCE inlines the two helpers)
! end site
