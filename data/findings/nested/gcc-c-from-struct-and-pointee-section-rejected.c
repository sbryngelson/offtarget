// # Finding (nested-data): GCC rejects map(from: r) together with a section a pointer-array member points to: "map-type other
// # than to, from, tofrom or alloc"
//
// - toolchains and modes that fail: gcc_g90 (GCC 16.2.0), gcc_sm80 (GCC 16.2.0); modes: copy; -O2
// - build: gcc -fopenmp -foffload=amdgcn-amdhsa -foffload-options=amdgcn-amdhsa=-march=gfx90a -O2 (gcc_g90); gcc -fopenmp
//   -foffload=nvptx-none -foffload-options=nvptx-none=-march=sm_80 -foffload-options=nvptx-none=-latomic -O2 (gcc_sm80)
// - failure: rejected
// - observed: `site-nested--gcc-c-from-struct-and-pointee-section-rejected.c:50:62: error: ‘#pragma omp target’ with map-type other
//   than ‘to’, ‘from’, ‘tofrom’ or ‘a`; identical signature on 2 of 2 failing cells
// - expected: compiles and prints `tot= 7` with `check=pass`
// - rule: "A map-type in a map clause must be to, from, tofrom or alloc." (5.2 §13.8 p.286 l.33) and map(from:) is one
//   of them; a structure and an element of it may both be list items: "Two list items of the map clauses on the same
//   construct must not share original storage unless they are the same list item or unless one is the containing
//   structure of the other." (5.2 §5.8.3 p.156 l.6-7); the section r.nx[0][0:1] is storage the pointer member points to,
//   not part of r
// - same-compiler control: controls/g3-ctl-from-struct-no-element.c (one change from this file; correct on gcc_g90 (GCC 16.2.0),
//   gcc_sm80 (GCC 16.2.0); rows results/nested/red/red2.jsonl, results/nested/red/wgs.jsonl, results/nested/red/wnv.jsonl);
//   controls/g3-ptrs-two-elements-to.c (one change from this file; correct on gcc_g90 (GCC 16.2.0), gcc_sm80 (GCC 16.2.0); rows
//   results/nested/red/red2.jsonl, results/nested/red/wgs.jsonl, results/nested/red/wnv.jsonl);
//   controls/g3-ptrs-two-elements-tofrom.c (one change from this file; correct on gcc_g90 (GCC 16.2.0), gcc_sm80 (GCC 16.2.0); rows
//   results/nested/red/red2.jsonl, results/nested/red/wgs.jsonl, results/nested/red/wnv.jsonl)
// - other families: afar (AFAR 24.3.0), cce19 (CCE 19.0.0), cce20 (CCE 20.0.2), cce21 (CCE 21.0.3), cce21_4 (CCE 21.0.4), nvhpc
//   (NVHPC 25.11), nvhpc269 (NVHPC 26.9) run the file correctly in copy mode (rows results/nested/red/wnv.jsonl, site rows, check
//   case site-nested--gcc-c-from-struct-and-pointee-section-rejected); nvhpc (NVHPC 25.11), nvhpc269 (NVHPC 26.9) fail it another
//   way in managed mode, e.g. `Failing in Thread:1`
// - gate and confirmer: campaign gate of the programs below: 18 cells, 18 confirmed in the four environments (a-d; (c) on another
//   node or GPU; rows results/nested/big/gate_reruns.part.tioga37.523062.jsonl,
//   results/nested/big/gate_reruns.part.tioga38.1371141.jsonl, results/nested/big/gate_reruns.part.tioga39.1163127.jsonl,
//   results/nested/big/gate_reruns.part.tioga39.517665.jsonl,
//   results/nested/big/gate_reruns.part.wingtip.2487708.jsonl,
//   results/nested/big/gate_reruns.part.wingtip.2487709.jsonl,
//   results/nested/big/gate_reruns.part.wingtip.2545453.jsonl,
//   results/nested/big/gate_reruns.part.wingtip.2551979.jsonl,
//   results/nested/big/gate_reruns.part.wingtip.501873.jsonl,
//   results/nested/big/gate_reruns.part.wingtip.724122.jsonl, results/nested/big/rows.part.tioga39.397000.jsonl,
//   results/nested/big/rows.part.wingtip.3886921.jsonl,
//   results/nested/main/gate_reruns.part.tioga37.2711328.jsonl, results/nested/main/gate_reruns.part.tioga39.351539.jsonl,
//   results/nested/main/gate_reruns.part.wingtip.3374144.jsonl,
//   results/nested/main/gate_reruns.part.wingtip.3374146.jsonl,
//   results/nested/main/gate_reruns.part.wingtip.3386107.jsonl,
//   results/nested/main/gate_reruns.part.wingtip.3391074.jsonl,
//   results/nested/main/gate_reruns.part.wingtip.3582436.jsonl,
//   results/nested/main/gate_reruns.part.wingtip.3637854.jsonl,
//   results/nested/main/rows.part.tioga37.2691037.jsonl, results/nested/main/rows.part.wingtip.3363229.jsonl,
//   results/nested/main/rows.part.wingtip.3363230.jsonl)
// - programs (9): nd-c-omp-always-chain-d2-53712162, nd-c-omp-always-chain-d2-a0cb4117, nd-c-omp-always-chain-d3-1e86a491,
//   nd-c-omp-always-chain-d3-5b819c3d, nd-c-omp-one-chain-d2-3557bfd6, nd-c-omp-one-chain-d2-cad870f5,
//   nd-c-omp-present-chain-d2-60119b21, nd-c-omp-present-chain-d3-1435023d, nd-c-omp-present-chain-d4-f8a7e0f5
// - legality: the rules accept it; AFAR's clang front end accepts it
#include <stdio.h>
#include <stdlib.h>
#include <omp.h>
struct s1 { int a[4]; };
struct s0 { int v; struct s1 *nx[2]; };
int main(void)
{
  int hf = 1, i, tot = 0, ok;
  struct s0 r;
  r.v = 1;
  for (i = 0; i < 2; i++) {
    r.nx[i] = malloc(sizeof *r.nx[i]);
    for (int q = 0; q < 4; q++) r.nx[i]->a[q] = 10 * (i + 1) + q;
  }
  #pragma omp target map(from: hf)
  hf = omp_is_initial_device() ? 1 : 0;
  #pragma omp target map(tofrom: tot) map(from: r) map(from: r.nx[0][0:1])
  {
    tot = r.v;
    for (int q = 0; q < 4; q++) { r.nx[0]->a[q] = 5; } tot = 7;
  }
  ok = tot == 7;
  printf("tot= %d\n", tot);
  printf("RESULT ran_on_host=%d check=%s\n", hf, ok ? "pass" : "fail");
  return 0;
}

// site:
// title: GCC: map(from:) of a structure with a pointee section rejected
// summary: GCC rejects map(from: r) combined with a section of a pointer-array member.
// control: nested/controls/g3-ctl-from-struct-no-element.c one change from the finding; correct on gcc_g90, gcc_sm80
// control: nested/controls/g3-ptrs-two-elements-to.c one change from the finding; correct on gcc_g90, gcc_sm80
// control: nested/controls/g3-ptrs-two-elements-tofrom.c one change from the finding; correct on gcc_g90, gcc_sm80
// end site
