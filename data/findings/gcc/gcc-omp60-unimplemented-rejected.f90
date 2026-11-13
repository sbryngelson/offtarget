! # Finding (GCC 16.2): OpenMP 6.0 forms GCC documents as not implemented are rejected (Fortran); the reproducer is the catalog
!   program omp60-clause-induction
!
! - toolchains: gcc_g90 (GCC 16.2.0, AMD Instinct MI250X gfx90a, Tioga) and gcc_sm80 (GCC 16.2.0,
!   NVIDIA A100 sm_80, wingtip); separate memory only; -O2; OMP_TARGET_OFFLOAD=mandatory
! - build: gfortran -fopenmp -foffload=amdgcn-amdhsa -foffload-options=amdgcn-amdhsa=-march=gfx90a -O2 (gcc_g90);
!   -foffload=nvptx-none -foffload-options=nvptx-none=-march=sm_80 -foffload-options=nvptx-none=-latomic -O2 (gcc_sm80)
! - failure: rejected
! - observed: a compile-time error for every program of the list (the first: `Error: Failed to match clause at (1)`; declare target
!   local: `Sorry, OMP DECLARE TARGET with LOCAL clause not implemented`); the same on both GPUs.
! - expected: compiles; `RESULT ran_on_host=0 check=pass`
! - GCC 16.2 documentation (libgomp.texi of the GCC 16.2.0 release tarball, "OpenMP Implementation Status", OpenMP 6.0 table) lists
!   each of these as not implemented (N): "directive-name-modifier accepted in all clauses", "Support for inductions", "local clause
!   to declare_target directive", "New taskgraph construct including saved modifier and replayable clause", "New transparent clause
!   for multi-generational task-dependence graphs", "strict modifier keyword to num_threads", "default clause on the target
!   directive and accepting variable categories", "New storage map-type modifier", "self modifier to map and self as defaultmap
!   argument", "ref modifier to the map clause", "Reduction over private variables with reduction clause" (the original modifier),
!   "Boolean argument to nowait and nogroup may be non constant", "target_data as composite construct" (nogroup on target_data),
!   "All inarguable clauses take now an optional Boolean argument" (the requires clauses' argument), "For Fortran, the automap
!   modifier to the enter clause", "workdistribute directive for Fortran" and "Multi-word directives now use underscore by default"
!   (declare_simd, declare_mapper, target_loop). The two 6.0 forms no row covers (requires device_safesync, defaultmap(private)) are
!   a finding of their own (gcc-c-omp60-undocumented-rejected).
! - spec: the induction clause (6.0 §7.6.13 p.257), the directive-name-modifier (6.0 §5.4 p.173), the replayable clause (6.0 §14.6
!   p.440), the transparent clause (6.0 §17.9.6 p.510).
! - gate and confirmer: 184 cells (92 gcc_g90, 92 gcc_sm80), each confirmed in the gate's four environments (a-d;
!   results/gcc/gate-tioga/ and gate-wingtip/ verdicts.jsonl); confirmer verdicts (results/gcc/confirm/batch.gcc_*.jsonl):
!   unsupported (R11a-newer-form-unclaimed) 184
! - catalog programs (92): omp60-clause-aligned-directive_name, omp60-clause-allocate-directive_name,
!   omp60-clause-atomic_default_mem_order-directive_name, omp60-clause-bind-directive_name, omp60-clause-collapse-directive_name,
!   omp60-clause-default-aggregate, omp60-clause-default-all, omp60-clause-default-allocatable, omp60-clause-default-directive_name,
!   omp60-clause-default-pointer, omp60-clause-default-scalar, omp60-clause-defaultmap-directive_name, omp60-clause-defaultmap-self,
!   omp60-clause-defaultmap-storage, omp60-clause-depend-directive_name, omp60-clause-device-directive_name,
!   omp60-clause-device_type-directive_name, omp60-clause-dist_schedule-directive_name,
!   omp60-clause-dynamic_allocators-directive_name, omp60-clause-dynamic_allocators-required, omp60-clause-enter-automap,
!   omp60-clause-enter-directive_name, omp60-clause-firstprivate-directive_name, omp60-clause-firstprivate-saved,
!   omp60-clause-from-directive_name, omp60-clause-has_device_addr-directive_name, omp60-clause-in_reduction-directive_name,
!   omp60-clause-indirect-directive_name, omp60-clause-induction, omp60-clause-induction-directive_name,
!   omp60-clause-induction-plus, omp60-clause-induction-relaxed, omp60-clause-induction-step, omp60-clause-induction-strict,
!   omp60-clause-induction-times, omp60-clause-is_device_ptr-directive_name, omp60-clause-lastprivate-directive_name,
!   omp60-clause-linear-directive_name, omp60-clause-linear-ref, omp60-clause-linear-uval, omp60-clause-link-directive_name,
!   omp60-clause-local, omp60-clause-local-directive_name, omp60-clause-map-directive_name, omp60-clause-map-ref_ptee,
!   omp60-clause-map-ref_ptr, omp60-clause-map-ref_ptr_ptee, omp60-clause-map-self, omp60-clause-map-storage,
!   omp60-clause-message-directive_name, omp60-clause-nogroup, omp60-clause-nogroup-directive_name,
!   omp60-clause-nogroup-do_not_synchronize, omp60-clause-nontemporal-directive_name, omp60-clause-nowait-directive_name,
!   omp60-clause-nowait-do_not_synchronize, omp60-clause-num_teams-directive_name, omp60-clause-num_threads-directive_name,
!   omp60-clause-num_threads-strict, omp60-clause-order-directive_name, omp60-clause-ordered-directive_name,
!   omp60-clause-private-directive_name, omp60-clause-proc_bind-directive_name, omp60-clause-reduction-directive_name,
!   omp60-clause-reduction-original, omp60-clause-replayable, omp60-clause-replayable-directive_name,
!   omp60-clause-replayable-replayable_expression, omp60-clause-reverse_offload-directive_name,
!   omp60-clause-reverse_offload-required, omp60-clause-safelen-directive_name, omp60-clause-schedule-directive_name,
!   omp60-clause-self_maps-directive_name, omp60-clause-self_maps-required, omp60-clause-severity-directive_name,
!   omp60-clause-shared-directive_name, omp60-clause-simdlen-directive_name, omp60-clause-thread_limit-directive_name,
!   omp60-clause-to-directive_name, omp60-clause-transparent, omp60-clause-transparent-directive_name,
!   omp60-clause-transparent-impex_type, omp60-clause-unified_address-directive_name, omp60-clause-unified_address-required,
!   omp60-clause-unified_shared_memory-directive_name, omp60-clause-unified_shared_memory-required,
!   omp60-clause-use_device_addr-directive_name, omp60-clause-use_device_ptr-directive_name,
!   omp60-clause-uses_allocators-directive_name, omp60-directive-target_loop, omp60-directive-target_teams_workdistribute,
!   omp60-directive-teams_workdistribute
! - legality: the catalog programs are legal by construction (offload.engine.gen, c_gen and acc_gen
!   check every program against the catalog rules and the offload scope as it is built; no
!   compiler). GCC is a compiler under test only: never a legality witness, here or for another
!   family's case (catalog/machines.yaml under_test_only).
! Generated by compliance.gen (OpenMP 6.0, free-form Fortran). Do not edit.
! id: omp60-clause-induction
! primary atom: omp.clause.induction
! legal: yes
! observable: yes
! ran_on_host: inside the target region of interest
! evidence: construct
! needs: none
! std: f2008
program gen_prog
  use omp_lib, only: omp_is_initial_device
  implicit none
  integer, parameter :: n = 64
  integer, allocatable, target :: a(:), b(:)
  integer :: ref(n)
  integer :: i, host_flag
  logical :: ok
  integer :: x
  allocate(a(n), b(n))
  do i = 1, n
    a(i) = i
    b(i) = 0
    ref(i) = 2*i + 1
  end do
  host_flag = 1
  x = 3
  !$omp target map(to: a) map(from: b) map(tofrom: x) map(tofrom: host_flag)
    host_flag = merge(1, 0, omp_is_initial_device())
    !$omp parallel do default(none) shared(a, b) induction(step(1), +: x)
      do i = 1, n
        b(i) = 2*a(i) + 1 + (x - (i + 2))
        x = x + 1
      end do
    !$omp end parallel do
  !$omp end target
  ok = all(b == ref) .and. (x == n + 3)
  print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, ' check=', merge('pass', 'fail', ok)
  deallocate(a, b)
end program gen_prog
! site:
! title: OpenMP 6.0 features that GCC 16.2 lists as not implemented are rejected (Fortran)
! summary: GCC 16.2 rejects OpenMP 6.0 forms that its implementation status table lists as not implemented: directive-name modifiers
! + on clauses, the induction, local, replayable and transparent clauses, num_threads(strict:), variable categories on default,
! + defaultmap(self/storage), map(self:/storage:/ref_*), firstprivate(saved:), reduction(original:), arguments on requires clauses
! + and nowait, nogroup on target_data, and the underscore spellings of multi-word directives. Most stop with a syntax error;
! + declare target local stops with "Sorry, ... not implemented", nogroup with "'nogroup' is not valid for '#pragma omp target
! + data'", and the ignored declare_mapper leaves its mapper "not found". GCC 16.2 claims OpenMP 5.2 (_OPENMP 202111) and parts of
! + 6.0.
! same_as: gcc/gcc-c-omp60-unimplemented-rejected
! end site
