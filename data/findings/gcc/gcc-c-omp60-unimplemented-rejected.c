// # Finding (GCC 16.2): OpenMP 6.0 forms GCC documents as not implemented are rejected (C); the reproducer is the catalog program
//   omp60-c-clause-induction
//
// - toolchains: gcc_g90 (GCC 16.2.0, AMD Instinct MI250X gfx90a, Tioga) and gcc_sm80 (GCC 16.2.0,
//   NVIDIA A100 sm_80, wingtip); separate memory only; -O2; OMP_TARGET_OFFLOAD=mandatory
// - build: gcc -fopenmp -foffload=amdgcn-amdhsa -foffload-options=amdgcn-amdhsa=-march=gfx90a -O2 (gcc_g90); -foffload=nvptx-none
//   -foffload-options=nvptx-none=-march=sm_80 -foffload-options=nvptx-none=-latomic -O2 (gcc_sm80)
// - failure: rejected: expected an OpenMP clause before
// - observed: a compile-time error for every program of the list (the first: `error: expected an OpenMP clause before 'induction'`;
//   nogroup on target_data: `'nogroup' is not valid for '#pragma omp target data'`; the ignored declare_mapper: `mapper 'mm' not
//   found`); the same on both GPUs.
// - expected: compiles; `RESULT ran_on_host=0 check=pass`
// - GCC 16.2 documentation (libgomp.texi of the GCC 16.2.0 release tarball, "OpenMP Implementation Status", OpenMP 6.0 table) lists
//   each of these as not implemented (N): "directive-name-modifier accepted in all clauses", "Support for inductions", "local
//   clause to declare_target directive", "New taskgraph construct including saved modifier and replayable clause", "New transparent
//   clause for multi-generational task-dependence graphs", "strict modifier keyword to num_threads", "default clause on the target
//   directive and accepting variable categories", "New storage map-type modifier", "self modifier to map and self as defaultmap
//   argument", "ref modifier to the map clause", "Reduction over private variables with reduction clause" (the original modifier),
//   "Boolean argument to nowait and nogroup may be non constant", "target_data as composite construct" (nogroup on target_data),
//   "All inarguable clauses take now an optional Boolean argument" (the requires clauses' argument), "For Fortran, the automap
//   modifier to the enter clause", "workdistribute directive for Fortran" and "Multi-word directives now use underscore by default"
//   (declare_simd, declare_mapper, target_loop). The two 6.0 forms no row covers (requires device_safesync, defaultmap(private))
//   are a finding of their own (gcc-c-omp60-undocumented-rejected).
// - spec: the induction clause (6.0 §7.6.13 p.257), the directive-name-modifier (6.0 §5.4 p.173), the replayable clause (6.0 §14.6
//   p.440), the transparent clause (6.0 §17.9.6 p.510).
// - other families: AFAR, CCE and NVHPC reject many of the same 6.0 forms (their own findings and the catalog's unsupported cells).
// - gate and confirmer: 168 cells (84 gcc_g90, 84 gcc_sm80), each confirmed in the gate's four environments (a-d;
//   results/gcc/gate-tioga/ and gate-wingtip/ verdicts.jsonl); confirmer verdicts (results/gcc/confirm/batch.gcc_*.jsonl):
//   unsupported (R11a-newer-form-unclaimed) 168
// - catalog programs (84): omp60-c-clause-aligned-directive_name, omp60-c-clause-allocate-directive_name,
//   omp60-c-clause-atomic_default_mem_order-directive_name, omp60-c-clause-bind-directive_name,
//   omp60-c-clause-collapse-directive_name, omp60-c-clause-default-aggregate, omp60-c-clause-default-all,
//   omp60-c-clause-default-directive_name, omp60-c-clause-default-pointer, omp60-c-clause-default-scalar,
//   omp60-c-clause-defaultmap-directive_name, omp60-c-clause-defaultmap-self, omp60-c-clause-defaultmap-storage,
//   omp60-c-clause-depend-directive_name, omp60-c-clause-device-directive_name, omp60-c-clause-device_type-directive_name,
//   omp60-c-clause-dist_schedule-directive_name, omp60-c-clause-dynamic_allocators-directive_name,
//   omp60-c-clause-dynamic_allocators-required, omp60-c-clause-enter-directive_name, omp60-c-clause-firstprivate-directive_name,
//   omp60-c-clause-firstprivate-saved, omp60-c-clause-from-directive_name, omp60-c-clause-has_device_addr-directive_name,
//   omp60-c-clause-in_reduction-directive_name, omp60-c-clause-indirect-directive_name, omp60-c-clause-induction,
//   omp60-c-clause-induction-directive_name, omp60-c-clause-induction-plus, omp60-c-clause-induction-relaxed,
//   omp60-c-clause-induction-step, omp60-c-clause-induction-strict, omp60-c-clause-induction-times,
//   omp60-c-clause-is_device_ptr-directive_name, omp60-c-clause-lastprivate-directive_name, omp60-c-clause-linear-directive_name,
//   omp60-c-clause-link-directive_name, omp60-c-clause-local, omp60-c-clause-local-directive_name,
//   omp60-c-clause-map-directive_name, omp60-c-clause-map-mapper, omp60-c-clause-map-self, omp60-c-clause-map-storage,
//   omp60-c-clause-message-directive_name, omp60-c-clause-nogroup, omp60-c-clause-nogroup-directive_name,
//   omp60-c-clause-nogroup-do_not_synchronize, omp60-c-clause-nontemporal-directive_name, omp60-c-clause-nowait-directive_name,
//   omp60-c-clause-nowait-do_not_synchronize, omp60-c-clause-num_teams-directive_name, omp60-c-clause-num_threads-directive_name,
//   omp60-c-clause-num_threads-strict, omp60-c-clause-order-directive_name, omp60-c-clause-ordered-directive_name,
//   omp60-c-clause-private-directive_name, omp60-c-clause-proc_bind-directive_name, omp60-c-clause-reduction-directive_name,
//   omp60-c-clause-reduction-original, omp60-c-clause-replayable, omp60-c-clause-replayable-directive_name,
//   omp60-c-clause-replayable-replayable_expression, omp60-c-clause-reverse_offload-directive_name,
//   omp60-c-clause-reverse_offload-required, omp60-c-clause-safelen-directive_name, omp60-c-clause-schedule-directive_name,
//   omp60-c-clause-self_maps-directive_name, omp60-c-clause-self_maps-required, omp60-c-clause-severity-directive_name,
//   omp60-c-clause-shared-directive_name, omp60-c-clause-simdlen-directive_name, omp60-c-clause-thread_limit-directive_name,
//   omp60-c-clause-to-directive_name, omp60-c-clause-transparent, omp60-c-clause-transparent-directive_name,
//   omp60-c-clause-transparent-impex_type, omp60-c-clause-unified_address-directive_name, omp60-c-clause-unified_address-required,
//   omp60-c-clause-unified_shared_memory-directive_name, omp60-c-clause-unified_shared_memory-required,
//   omp60-c-clause-use_device_addr-directive_name, omp60-c-clause-use_device_ptr-directive_name,
//   omp60-c-clause-uses_allocators-directive_name, omp60-c-directive-target_loop
// - legality: the catalog programs are legal by construction (offload.engine.gen, c_gen and acc_gen
//   check every program against the catalog rules and the offload scope as it is built; no
//   compiler). GCC is a compiler under test only: never a legality witness, here or for another
//   family's case (catalog/machines.yaml under_test_only).
// Generated by compliance.c_gen (OpenMP 6.0, C11): the C port (offload.engine.f2c) of omp60-clause-induction. Do not edit.
// id: omp60-c-clause-induction
// primary atom: omp.clause.induction
// legal: yes
// observable: yes
// ran_on_host: inside the target region of interest
// evidence: construct
// needs: none
// std: c11
#include <stdio.h>
#include <stdbool.h>
#include <omp.h>

enum { n = 64 };

int main(void) {
  int a[n];
  int b[n];
  int ref[n];
  int host_flag;
  bool ok;
  int x;
  for (int i = 1; i <= n; i++) {
    a[i - 1] = i;
    b[i - 1] = 0;
    ref[i - 1] = 2 * i + 1;
  }
  host_flag = 1;
  x = 3;
  #pragma omp target map(to: a) map(from: b) map(tofrom: x) map(tofrom: host_flag)
  {
    host_flag = (omp_is_initial_device() ? 1 : 0);
    #pragma omp parallel for default(none) shared(a, b) induction(step(1), +: x)
    for (int i = 1; i <= n; i++) {
      b[i - 1] = 2 * a[i - 1] + 1 + (x - (i + 2));
      x = x + 1;
    }
  }
  bool t1_ = true;
  for (int k2_ = 0; k2_ < n; k2_++)
    t1_ = t1_ && (b[k2_] == ref[k2_]);
  ok = t1_ && (x == n + 3);
  printf("RESULT ran_on_host=%d check=%s\n", host_flag, ok ? "pass" : "fail");
  return 0;
}
// site:
// title: OpenMP 6.0 features that GCC 16.2 lists as not implemented are rejected (directive-name modifiers, induction, taskgraph
// + clauses, map and defaultmap self/storage, and more)
// summary: GCC 16.2 rejects OpenMP 6.0 forms that its implementation status table lists as not implemented: directive-name
// + modifiers on clauses, the induction, local, replayable and transparent clauses, num_threads(strict:), variable categories on
// + default, defaultmap(self/storage), map(self:/storage:/ref_*), firstprivate(saved:), reduction(original:), arguments on requires
// + clauses and nowait, nogroup on target_data, and the underscore spellings of multi-word directives. Most stop with a syntax
// + error; declare target local stops with "Sorry, ... not implemented", nogroup with "'nogroup' is not valid for '#pragma omp
// + target data'", and the ignored declare_mapper leaves its mapper "not found". GCC 16.2 claims OpenMP 5.2 (_OPENMP 202111) and
// + parts of 6.0.
// end site
