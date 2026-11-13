// control for hk-030: the same program without nowait
// source: https://forums.developer.nvidia.com/t/openmp-target-region-inside-parallel-region-causes-internal-compiler-error/251225
// edits:
//   1) the posted program is cut off in the forum archive (text after '<'
//      lost); restored from the thread: a target nowait region inside an
//      omp for loop of a parallel region whose trip count is the variable
//      num_iterations ("Both the nowait clause and the num_iterations
//      variable are important"); NVHPC 23.3 "Internal compiler error.
//      targetinfo symbol not found in uplevel struct" (TPR 33521, fixed in
//      25.7)
//   2) the target region writes one element of a mapped array (a[i:1]);
//      the deferred target tasks finish at the barrier that ends the
//      parallel region; added a printed check
// expected: check=pass
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
        for (int i = 0; i < num_iterations; ++i) {
            #pragma omp target map(tofrom: a[i:1])
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
