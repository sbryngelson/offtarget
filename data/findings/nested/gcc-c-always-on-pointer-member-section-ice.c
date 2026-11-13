// # Finding (nested-data): GCC: map(always, to:) of a section of a pointer member of an embedded structure crashes the compiler
// # (error: Segmentation fault)
//
// - toolchains and modes that fail: gcc_g90 (GCC 16.2.0), gcc_sm80 (GCC 16.2.0); modes: copy; -O2
// - build: gcc -fopenmp -foffload=amdgcn-amdhsa -foffload-options=amdgcn-amdhsa=-march=gfx90a -O2 (gcc_g90); gcc -fopenmp
//   -foffload=nvptx-none -foffload-options=nvptx-none=-march=sm_80 -foffload-options=nvptx-none=-latomic -O2 (gcc_sm80)
// - failure: ice
// - observed: `Please submit a full bug report, with preprocessed source (by using -freport-bug).`; identical signature on 2 of 2
//   failing cells
// - expected: compiles and prints `tot= 1638` with `check=pass`
// - rule: the always map-type-modifier may be given on any map clause list item, including a section of a pointer member
//   reached through an embedded structure (OpenMP 5.2 §5.8.3 p.153 l.15-17)
// - same-compiler control: controls/gt2-ctl-no-always.c (one change from this file; correct on gcc_g90 (GCC 16.2.0), gcc_sm80 (GCC
//   16.2.0); rows results/nested/red/red16.jsonl, results/nested/red/tuo22.jsonl, results/nested/red/tuo23.jsonl,
//   results/nested/red/wgs3.jsonl, results/nested/red/wnv3.jsonl); controls/gt3-ctl-always-on-structure-only.c (one change from
//   this file; correct on gcc_g90 (GCC 16.2.0), gcc_sm80 (GCC 16.2.0); rows results/nested/red/red16.jsonl,
//   results/nested/red/tuo22.jsonl, results/nested/red/tuo23.jsonl, results/nested/red/wgs3.jsonl, results/nested/red/wnv3.jsonl)
// - other families: afar (AFAR 24.3.0), cce21_4 (CCE 21.0.4), nvhpc (NVHPC 25.11), nvhpc269 (NVHPC 26.9) run the file correctly
//   (rows results/nested/red/tuo22.jsonl, results/nested/red/tuo23.jsonl, results/nested/red/wnv3.jsonl)
// - gate and confirmer: campaign gate of the programs below: 20 cells, 20 confirmed in the four environments (a-d; (c) on another
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
//   results/nested/main/gate_reruns.part.wingtip.3386107.jsonl,
//   results/nested/main/gate_reruns.part.wingtip.3582436.jsonl,
//   results/nested/main/gate_reruns.part.wingtip.3637854.jsonl,
//   results/nested/main/rows.part.tioga37.2691037.jsonl, results/nested/main/rows.part.wingtip.3363229.jsonl,
//   results/nested/main/rows.part.wingtip.3363230.jsonl)
// - programs (10): nd-c-omp-always-chain-d2-54e7fc79, nd-c-omp-always-chain-d2-ba438256, nd-c-omp-always-chain-d2-d3bf9d59,
//   nd-c-omp-always-chain-d3-33791e60, nd-c-omp-always-chain-d3-37f3561f, nd-c-omp-always-chain-d3-6f147348,
//   nd-c-omp-always-chain-d3-755bad14, nd-c-omp-always-chain-d3-bdb8bc3d, nd-c-omp-always-chain-d3-dfa07978,
//   nd-c-omp-always-list-d2-f31eac01
// - legality: the rules (offload.engine.rules) accept it; AFAR, CCE and NVHPC compile and run it correctly (front ends of
//   three other families)
#include <stdio.h>
#include <stdlib.h>
#include <omp.h>
enum { NM = 8 };
struct n1 { int s; int *a; };
struct n0 { int s; struct n1 nx; };
int main(void)
{
  int hf = 1, i, tot = 0, ok;
  struct n0 *r = calloc(1, sizeof *r);
  #pragma omp target map(from: hf)
  hf = omp_is_initial_device() ? 1 : 0;
  r->nx.a = malloc(NM * sizeof(int));
  r->s = 10;
  for (i = 0; i < NM; i++) r->nx.a[i] = 200 + i;
  #pragma omp target map(tofrom: tot) map(to: r[0:1]) map(always, to: r->nx.a[0:8])
  {
    tot += r->s;
    for (int q = 0; q < NM; q++) tot += r->nx.a[q];
  }
  ok = tot == 1638;
  printf("tot= %d\n", tot);
  printf("RESULT ran_on_host=%d check=%s\n", hf, ok ? "pass" : "fail");
  return 0;
}

// site:
// title: GCC: compiler crash on map(always) of a pointer-member section
// summary: GCC crashes on map(always, to:) of a section of a pointer member of an embedded structure.
// control: nested/controls/gt2-ctl-no-always.c one change from the finding; correct on gcc_g90, gcc_sm80
// control: nested/controls/gt3-ctl-always-on-structure-only.c one change from the finding; correct on gcc_g90, gcc_sm80
// end site
