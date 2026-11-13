// # Finding: CCE craycc stops with "overlaps present region but is
// # not contained" when a target region implicitly maps a structure some of
// # whose members a target data construct already mapped
//
// - compilers: CCE craycc 19.0.0, 20.0.2, 21.0.3, 21.0.4, -O2: this file on
//   MI300A gfx942 (HSA_XNACK 0 and 1); the OpenMP Examples program
//   target_struct_map.4 (Case 1 of which this file is) also on MI250X gfx90a.
// - expected: 4 202 dev= 1 (s.p[0] = 0*2+4, s.p[99] = 99*2+4)
// - actual: no output; the runtime stops at the target construct:
//   "ACC: libcrayacc/acc_present.c:762 CRAY_ACC_ERROR - Host region (... to
//   ...) overlaps present region (... to ... index 0) but is not contained
//   for 's'", exit status 1, every run, both memory modes.
// - rule: the target construct references s (the call saxpy(&s)), so s is
//   treated as if it appeared in a map clause with map-type tofrom (5.2 §5.8.1
//   p.149 l.4-5); s.a, s.b and s.p are already present as one storage block
//   (list items with the same containing structure form "a single mappable
//   storage block", 5.2 §5.8.3 p.152 l.28-31); and "If a single contiguous
//   part of the original storage of a list item with an implicit data-mapping
//   attribute has corresponding storage in the device data environment prior
//   to a task encountering the construct on which the map clause appears,
//   only that part of the original storage will have corresponding storage in
//   the device data environment as a result of the map clause" (5.2 §5.8.3
//   p.154 l.18-21; the same text in 5.0 §2.19.7.1 p.320 l.18-21). The
//   OpenMP Examples document this form as working (target_struct_map.4,
//   Case 1: "Explicitly mapping S1.p, S1.a, and S1.b rather than S1 avoids
//   mapping the entire structure").
// - same-compiler controls (correct, 4 202 dev= 1 on CCE 19, 20, 21, 21.0.4):
//   s.big added to the target data map (the whole structure present); no
//   target data and map(s.p[:N], s.a, s.b) on the target construct (the
//   Examples' Case 3, 5.2 §5.8.3 p.154 l.22-27). Both are files now
//   (controls/cce-c-implicit-struct-map-partly-present-whole-control.c and
//   controls/cce-c-implicit-struct-map-partly-present-target-only-control.c);
//   re-run 2026-11-01 on MI300A, HSA_XNACK 0 and 1: correct on CCE 19, 20,
//   21, 21.0.4 and on AFAR, while this file fails on CCE 19, 20, 21, 21.0.4
//   and is correct on AFAR (results/triage2/cce.jsonl).
// - also: the Examples' Case 2 (target data map(s.p[:N]), then target
//   map(s.p[:0], s.a, s.b) with s implicit) stops the same way on every CCE
//   cell; libgomp's target-link-2.c (declare target link(arr), enter data
//   map(arr[5:10]), then a target region that references arr) stops with the
//   same message on CCE 19, 20, 21 (gfx90a): an implicit map (5.2 §5.8.1
//   p.148 l.9-11) of a partly present array.
// - other families: AFAR amdclang prints 4 202 dev= 1 (this file and the
//   three Examples cases, gfx942 X0 and X1, gfx90a). NVHPC nvc 25.11 and 26.9
//   (A100, separate and managed memory) fail this file at run time, exit
//   status 1, with a different message: "FATAL ERROR: variable in data clause
//   is partially present on the device: name=s" at the target construct (the
//   present table lists s.a, s.b and, in separate memory, s.p[:100]). That is
//   the OpenACC runtime's partial-presence error, and it reaches further than
//   CCE's: NVHPC also fails the whole-structure control (s.big added, so every
//   member is present, each as its own entry) that CCE and AFAR run correctly,
//   and runs the target-only control correctly. All four gate environments
//   agree on both releases and both memory modes (site matrix rows,
//   2026-11-01, c on another GPU; a rerun of the file and both controls, three
//   runs each, in a, b, d on GPU 0 and c on GPU 1:
//   results/triage2/wingtip/nvhpc/nv.[abcd].jsonl). The Examples program's
//   SIGSEGV on NVHPC is the 8 MB stack (its three structures hold 12 MB): with
//   a 64 MB stack (ulimit -s 65536) it stops at Case 1 with the same
//   partial-presence error (name=S1; nv3.jsonl). The failure is NVHPC's own
//   and not CCE's, so this finding stays CCE's and the site shows NVHPC as
//   failing another way; an NVHPC finding (the whole-structure control is the
//   cleaner reproducer) is not made here. GCC 16.2 does not compile this file:
//   the target data map list is the trigger of an internal compiler error
//   on both targets (gcc-c-target-data-struct-pointer-section-ice.c).
// - harvest: dev programs h2-ompex-target-struct-map-4-c and
//   h2-gomp-ccc-target-link-2 (data/bench/harvest2), wrong_answer on every CCE
//   cell, gate confirmed on gfx90a.
// - legality: offload.engine.prerun.check accepts it (the rules with the race
//   rule, and the AFAR clang front end), and accepts both controls (re-checked
//   2026-11-01, Tuolumne pbatch; results/triage2/legal2.json). The rule it
//   relies on is the one quoted above (5.2 §5.8.3 p.154 l.18-21: the part of
//   an implicitly mapped list item that is present is the only part mapped);
//   AFAR runs the file correctly, and the OpenMP Examples document the form.
// CCE:  craycc -fopenmp -fopenmp-targets=amdgcn-amd-amdhsa
//       -Xopenmp-target=amdgcn-amd-amdhsa -march=gfx942 -fopenmp-version=52 -O2
// Run:  OMP_TARGET_OFFLOAD=mandatory ./a.out
#include <stdio.h>
#include <stdlib.h>
#include <omp.h>
#define N 100
struct foo { char big[200000]; float a, b; float *p; };
#pragma omp begin declare target
void saxpy(struct foo *s) { for (int i = 0; i < N; i++) s->p[i] = s->p[i] * s->a + s->b; }
#pragma omp end declare target
int main(void) {
  struct foo s;
  int dev = 0;
  s.a = 2; s.b = 4; s.p = malloc(sizeof(float) * N);
  for (int i = 0; i < N; i++) s.p[i] = i;
#pragma omp target data map(s.p[:N], s.p, s.a, s.b)
#pragma omp target map(from: dev)
  { saxpy(&s); dev = !omp_is_initial_device(); }
  printf("%.0f %.0f dev= %d\n", s.p[0], s.p[N - 1], dev);
  int ok = s.p[0] == 4 && s.p[N - 1] == 202;
  printf("RESULT ran_on_host=%d check=%s\n", !dev, ok ? "pass" : "fail");
  return 0;
}
// site:
// title: craycc stops with "overlaps present region but is not contained" when a target region implicitly maps a partly mapped
// + structure
// end site
