// # Finding (GCC 16.2, OpenMP Examples harvest): members of one structure in a target data construct, the pointer member as an
//   array section before itself: internal compiler error (segmentation fault) in the gimplifier
//
// - toolchains: gcc_g90 (GCC 16.2.0, AMD Instinct MI250X gfx90a, Tioga) and gcc_sm80 (GCC 16.2.0, NVIDIA A100 sm_80, wingtip);
//   separate memory only; -O2
// - build: gcc -fopenmp -foffload=amdgcn-amdhsa -foffload-options=amdgcn-amdhsa=-march=gfx90a -O2 (gcc_g90); -foffload=nvptx-none
//   -foffload-options=nvptx-none=-march=sm_80 -foffload-options=nvptx-none=-latomic -O2 (gcc_sm80)
// - failure: ice: internal compiler error: Segmentation fault
// - observed: `internal compiler error: Segmentation fault` at the target data directive, on both targets; the host compiler stops
//   before any offload code is made (the same with -foffload=disable and at -O0). A debugger shows the fault in
//   omp_gather_mapping_groups_1 (gimplify.cc:11160), called from gimplify_adjust_omp_clauses for the target data construct.
// - expected: compiles; prints `sum= 14` and `RESULT ran_on_host=0 check=pass`
// - rule: "All map clause list items that have the same containing structure or share storage result in a single mappable
//   storage block that contains the storage of the list items" (5.2 §5.8.3 p.152 l.29-31): s.p[:4], s.p and s.a are map clause
//   list items of one structure, and nothing in 5.2 limits the order of the list items of one map clause list. The OpenMP
//   Examples (target_struct_map.4, Case 1) write the form `map(S1.p[:N],S1.p,S1.a,S1.b)` and document that it works.
// - trigger (hand-reduced from the Examples program; compile-only probes on gcc_sm80, 2026-11-01): the construct maps two or more
//   members of one structure and the member with the highest offset is a pointer that is listed both as an array section and by
//   itself, the section first. Reordering the list is the only change in the control: `map(s.p, s.p[:4], s.a)` compiles, as do
//   `map(s.p[:4], s.a, s.p)` and `map(s.a, s.p[:4], s.p)`. The pointer member alone (`map(s.p[:4], s.p)`) compiles, and so does
//   the list with a mapped member of higher offset than the pointer (`struct S { int a; int *p; int b; }` with
//   `map(s.p[:4], s.p, s.b)`); the fault needs the pointer to be the last mapped member. It also occurs on `target` and
//   `target enter data` with the same list, and with a second pointer member in the place of `a`. The repeat `map(s.p[:4], s.p,
//   s.p, s.a)` stops with an internal compiler error in omp_group_base (gimplify.cc:11337). The program of
//   harvest/cce-c-implicit-struct-map-partly-present.c (`map(s.p[:N], s.p, s.a, s.b)`, the pointer last in the structure) stops
//   with the same error on both targets (site matrix rows, 2026-11-01).
// - gate (this file, 2026-11-01): the internal compiler error in all four environments on both targets: gcc_sm80 a, b and d on
//   wingtip GPU 0 (b in a build directory named in upper-case letters only), c on GPU 1; gcc_g90 a, b and d on
//   tioga39, c on tioga38 (results/triage2/wingtip/gcc_sm80/gate.jsonl, results/triage2/tioga/gcc_g90/gate.jsonl).
// - same-compiler control (compiles; correct, in each of the four environments on gcc_sm80 and gcc_g90: mandatory pass 5 of 5;
//   unset pass 5 of 5): the same three list items with the pointer member first, map(s.p, s.p[:4], s.a)
//   (controls/gcc-c-target-data-struct-pointer-section-control.c).
// - not the defect of gcc-c-target-data-two-maps-ice.c: that one repeats a scalar in two map clauses and stops in
//   install_var_field (omplower); this one needs the structure members and stops earlier, in the gimplifier.
// - other families: AFAR (amdclang) and CCE 19/20/21/21.0.4 compile and run this file and the control correctly (MI300A, HSA_XNACK
//   0 and 1; results/triage2/other3.jsonl); NVHPC 25.11 and 26.9 run this file correctly in separate and managed memory and stop
//   on the control with `variable in data clause is partially present on the device: name=s.p[:4]`
//   (results/triage2/wingtip/nvhpc/nv2.a.jsonl). The site's finding matrix runs this file on every compiler.
// - harvested program (2 cells (1 gcc_g90, 1 gcc_sm80); gate: gcc_g90 confirmed, gcc_sm80 reproduced in a, b, c and d (the gate
//   field of its confirmer row is unset); confirmer: compiler_bug (R10-compile-ice) 2): h2-ompex-target-struct-map-4-c
//   (data/bench/harvest2; OpenMP Examples target_struct_map.4.c, whose Case 1 is the trigger). CCE and NVHPC fail the same program
//   another way (harvest/cce-c-implicit-struct-map-partly-present.c).
// - legality: offload.engine.prerun.check (the rules with the race rule, and the AFAR clang front end: two witnesses) accepts this
//   file and the control (2026-11-01, Tuolumne pbatch; results/triage2/legal2.json), and accepts the harvested program
//   (results/harvest2/rules.jsonl, prerun.part.*.jsonl). GCC is a compiler under test only and never a legality witness.
#include <stdio.h>
#include <omp.h>

struct S { int a; int *p; };

int main(void) {
  int v[4] = {1, 2, 3, 4}, host_flag = 1, sum = 0;
  struct S s;
  s.a = 10;
  s.p = v;
  int *q = v;
  /* the pointer member as an array section and by itself, then another member of the same structure */
#pragma omp target data map(s.p[:4], s.p, s.a)
  {
#pragma omp target map(tofrom: q[:4], host_flag)
    {
      host_flag = omp_is_initial_device();
      for (int i = 0; i < 4; i++) q[i] += 1;
    }
  }
  for (int i = 0; i < 4; i++) sum += v[i];
  printf("sum= %d\n", sum);
  printf("RESULT ran_on_host=%d check=%s\n", host_flag, sum == 14 ? "pass" : "fail");
  return 0;
}
// site:
// title: Members of one structure in a target data construct: internal compiler error
// summary: OpenMP 5.2 allows a pointer member to be listed as an array section and by itself, next to another member of the same
// + structure (the OpenMP Examples show it). GCC 16.2 stops with an internal compiler error (segmentation fault in the
// + gimplifier) on a target data construct with map(s.p[:4], s.p, s.a), for both offload targets. With the pointer member
// + listed first, map(s.p, s.p[:4], s.a), the same program compiles and runs correctly.
// control: harvest/controls/gcc-c-target-data-struct-pointer-section-control.c the pointer member listed before its array section
// end site
