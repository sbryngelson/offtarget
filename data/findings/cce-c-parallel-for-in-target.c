/* Finding (C): a parallel for nested in a target region loses
   iterations with schedule(static) and drops the final values of
   lastprivate and linear list items on CCE.

   Legal OpenMP 5.2 C. Inside the target region each parallel for must
   run all 64 iterations (5.2 §11.5: every iteration is executed once,
   whatever the schedule); lastprivate(t) gives t the value of the
   sequentially last iteration (5.2 §5.4.5) and linear(x: 1) gives x its
   value after the last iteration (5.2 §5.4.6), and the map(tofrom:)
   returns both to the host.

   Expected: "static 64 of 64; lastprivate t=63; linear 64 of 64, x=64".
   Observed (-O2, HSA_XNACK=1; CCE 19 also at HSA_XNACK=0 and at -O0):
   CCE craycc 19.0.0, 20.0.2 and 21.0.3 print "static 1 of 64; lastprivate t=-1; linear 64 of 64,
   x=0" (the region has one thread; without schedule(static) all 64
   iterations run, with schedule(static, 4) too). AFAR amdclang prints
   the expected line, and CCE ftn runs the Fortran forms correctly
   (omp52-clause-schedule-static, -lastprivate, -linear, -collapse).
   In the matrix this makes the C collapse, lastprivate, linear and
   schedule programs wrong_answer on CCE.

   Probe (data/evidence/triage_probe/pfor_*.c, results/t27b/probes.jsonl,
   tuolumne, both memory modes, 3 runs each): schedule(dynamic) loses
   iterations too on CCE 19, 20 and 21 (b computed wrong, bad > 0), with or
   without default(none) shared(a, b); the same parallel for without a
   schedule clause (with or without default(none)) is correct; AFAR is
   correct in every form. So schedule(static) without a chunk size,
   schedule(dynamic) and the catalog's auto, guided, runtime, monotonic and
   simd forms trigger it, as does lastprivate; schedule(static, 4) (above)
   does not, so not every schedule clause does.

   : three defects in one program (schedule(static)
   loses iterations; lastprivate and linear lose the final value); the
   control above covers only the first. The HPE packet splits them (cases
   cce-c-parallel-for-in-target-static, -lastprivate, -linear, each with its
   own control); a linear item's final value is lost with num_threads(1) too:
   the linear case's former control (num_threads(1) added, now dropped from
   the case) prints x=0 on CCE 19, 20, 21.0.3 and 21.0.4 in both modes
   (data/vendor/checks/results-compact), so it does not isolate the defect
   and is not listed as a control below.

   craycc -fopenmp -fopenmp-targets=amdgcn-amd-amdhsa
          -Xopenmp-target=amdgcn-amd-amdhsa -march=gfx942
          -fopenmp-version=52 -O2 */
#include <stdio.h>
int main(void) {
  int b[64], c[64], d[64], t = -1, x = 0;
  for (int i = 0; i < 64; i++) { b[i] = 0; c[i] = 0; d[i] = -1; }
  #pragma omp target map(from: b, c, d) map(tofrom: t, x)
  {
    #pragma omp parallel for schedule(static)
    for (int i = 0; i < 64; i++) b[i] = i + 1;
    #pragma omp parallel for lastprivate(t)
    for (int i = 0; i < 64; i++) { c[i] = i + 1; t = i; }
    #pragma omp parallel for linear(x: 1)
    for (int i = 0; i < 64; i++) { d[i] = x; x++; }
  }
  int nb = 0, nd = 0;
  for (int i = 0; i < 64; i++) { nb += b[i] == i + 1; nd += d[i] == i; }
  printf("static %d of 64; lastprivate t=%d; linear %d of 64, x=%d\n",
         nb, t, nd, x);
  return 0;
}
// site:
// title: craycc: parallel for schedule(static) in a target region runs 1 of 64 iterations
// control: ../vendor/checks/src/cce/control/cce-c-parallel-for-in-target-control.c schedule(static) removed from the first
// + parallel for
// + (the
// + first part of the output only)
// control: ../vendor/checks/src/cce/control/cce-c-parallel-for-in-target-static-control.c schedule(static) removed
// control: ../vendor/checks/src/cce/control/cce-c-parallel-for-in-target-lastprivate-control.c reduction(max: t) instead of
// + lastprivate(t)
// end site
