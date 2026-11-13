/* Finding (C), reproducer replaced: at OpenMP 5.1
   (the default of both clang C front ends) the iterator map-type modifier
   is rejected.

   Legal OpenMP 5.1 C: iterator(iterators-definition) is a map-type-modifier
   of the map clause (5.1 §2.21.7.1 p.347). The iterator it = 0:1 has the
   one value 0 (C ranges exclude the end, 5.1 §2.1.6 p.49), so the map is
   map(tofrom: a[0:n]); with one instance no two instances share a
   containing array (5.1 §2.21.7.1 p.353: "the list item instances that
   would result from different values of the iterator must not have the
   same containing array"). The first reproducer, map(iterator(it = 0:n),
   tofrom: a[it]) as in omp_vv test_target_map_iterators.c, broke that
   restriction and was withdrawn.
   Expected: "RESULT ran_on_host=0 check=pass".

   Observed (tuolumne, MI300A, -O2, HSA_XNACK 1 and 0, 3 runs each,
   2026-10-22, data/evidence/triage_probe/map_iter.c, results/t27b/probes_fr1.jsonl):
   - AFAR amdclang 24.0.0git and CCE craycc 19.0.0, 20.0.2, 21.0.3, with
     their default flags and with -fopenmp-version=51: "error: incorrect
     map type modifier, expected one of: 'always', 'close', 'mapper',
     'present', 'ompx_hold'".
   - At -fopenmp-version=52: AFAR correct in both modes; CCE craycc 19, 20
     and 21 crash in the front end (internal compiler error, "clang
     frontend command failed due to signal").
   The AMD clang status table at the AFAR commit lists "device | iterators
   in map clause or motion clauses | done" in its 5.1 section.

   amdclang -fopenmp --offload-arch=gfx942 [-fopenmp-version=51] -O2
   craycc -fopenmp -fopenmp-targets=amdgcn-amd-amdhsa
          -Xopenmp-target=amdgcn-amd-amdhsa -march=gfx942 -O2 */
#include <stdio.h>
#include <omp.h>
enum { n = 8 };
int main(void) {
  int a[n], bad = 0, host_flag = 1;
  for (int i = 0; i < n; i++) a[i] = i;
  #pragma omp target map(iterator(it = 0:1), tofrom: a[it:n]) map(tofrom: host_flag)
  {
    host_flag = omp_is_initial_device() ? 1 : 0;
    for (int i = 0; i < n; i++) a[i] += 1;
  }
  for (int i = 0; i < n; i++) bad += a[i] != i + 1;
  printf("RESULT ran_on_host=%d check=%s\n", host_flag, bad ? "fail" : "pass");
  return 0;
}
// site:
// title: craycc/ftn: OpenMP 5.1/5.2/6.0 forms HPE does not claim are rejected, and some crash the compiler instead of a diagnostic
// control: ../vendor/checks/src/other/control/clang-c-map-iterator-omp51-control.c map(tofrom: a[0:n]) without the iterator
// + modifier
// same_as: catalog/cce-c-map-iterator-ice
// end site
