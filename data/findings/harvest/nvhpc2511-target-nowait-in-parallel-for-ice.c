// # Finding (known-issues harvest): NVHPC 25.11 crashes compiling a target nowait
//   region in the worksharing loop of a parallel region
//
// - source: the NVIDIA forum topic 251225 (NVHPC 23.3, "Internal compiler error. targetinfo
//   symbol not found in uplevel struct"; TPR 33521, "fixed in our 25.7 release" per the vendor);
//   data/bench/harvest-known hk-030 (trip count num_iterations, the posted form); this file has a
//   constant trip count (data/reports/harvest-known/c030-const-trip.c), which fails the same way
// - compilers: NVHPC nvc 25.11, -mp=gpu -gpu=cc80; NVHPC 26.9 compiles and runs it
// - expected: the program compiles and prints bad = 0, RESULT ... check=pass: each target task
//   writes one element of a[i:1]; the deferred target tasks complete at the implicit barrier
//   that ends the parallel region
// - actual: "NVC++-F-0000-Internal compiler error. targetinfo symbol not found in uplevel struct
//   1209", both memory-mode builds
// - control (same compiler): without nowait the program compiles and runs
//   (data/reports/harvest-known/c030-no-nowait.c); NVHPC 26.9 compiles and runs this file
// - other families: AFAR compiles and runs it (bad = 0) on gfx90a and gfx942; CCE 19/20/21
//   compile it. CCE 19 and 21 at HSA_XNACK=0 lost one target task's element of the posted form
//   (hk-030) in the loaded matrix run (bad = 1, then 2; gate: nondeterministic; 20 repeats on an
//   idle node pass, as do its controls); not claimed
// - legality: "The target construct generates a target task ... If the nowait clause is
//   present, execution of the target task may be deferred" (OpenMP 5.2 §13.8 p.284 l.14-17).
//   Ruled legal by hand (fix; the confirmer's scope rule does not vet host parallel and
//   for, R04): a is shared in the parallel region, i is private to the worksharing loop and
//   firstprivate in the target; each target task maps a disjoint one-element section a[i:1], so
//   no storage is mapped twice; the deferred target tasks complete by the worksharing loop's
//   implicit barrier, and the host code that reads a runs after the region. An internal compiler
//   error is a defect on any input. The pre-run check accepts the program
// - evidence: results/harvest-known/main.wingtip (hk-030, gate: confirmed), results/harvest-known/probes.wingtip.jsonl
#include <omp.h>
#include <stdio.h>

int main(void)
{
    int num_iterations = 100;
    int a[100];
    for (int i = 0; i < 100; ++i) a[i] = -1;
    #pragma omp parallel
    {
        #pragma omp for
        for (int i = 0; i < 100; ++i) {
            #pragma omp target nowait map(tofrom: a[i:1])
            {
                a[i] = 2 * i + 1;
            }
        }
    }
    int bad = 0;
    for (int i = 0; i < num_iterations; ++i)
        if (a[i] != 2 * i + 1) ++bad;
    printf("bad = %d\n", bad);
    int hk_host = 1;
    #pragma omp target map(tofrom: hk_host)
    hk_host = omp_is_initial_device();
    printf("RESULT ran_on_host=%d check=%s\n", hk_host, bad == 0 ? "pass" : "fail");
    return 0;
}
// site:
// title: nvc 25.11 crashes compiling a target nowait region in the worksharing loop of a parallel region
// end site
