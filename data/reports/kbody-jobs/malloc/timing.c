#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <omp.h>
/* Cost of the allocator change: kernel time only (omp_get_wtime around the target region, data already resident),
   malloc(12)+store+copy+free per iteration, `reps` launches in one process. argv: n reps mode (0 = host-mapped records,
   1 = records in device memory from omp_target_alloc). Prints each launch's time in ms. */
typedef struct { int loc[3]; int ib; } gp_t;
int main(int argc, char **argv) {
  long n = atol(argv[1]); int reps = atoi(argv[2]); int mode = atoi(argv[3]);
  gp_t *gps;
  if (mode) gps = (gp_t *)omp_target_alloc(n * sizeof(gp_t), omp_get_default_device());
  else { gps = (gp_t *)calloc(n, sizeof(gp_t));
#pragma omp target enter data map(alloc : gps[0 : n])
  }
  for (int k = 0; k < reps; k++) {
    double t0 = omp_get_wtime();
    if (mode) {
#pragma omp target teams distribute parallel for is_device_ptr(gps)
      for (long cc = 0; cc < n; cc++) { int *tmp = (int *)malloc(3 * sizeof(int)); tmp[0] = (int)cc; tmp[1] = (int)(cc >> 8); tmp[2] = (int)(cc ^ 1234); memcpy(gps[cc].loc, tmp, 12); free(tmp); gps[cc].ib = 1; }
    } else {
#pragma omp target teams distribute parallel for
      for (long cc = 0; cc < n; cc++) { int *tmp = (int *)malloc(3 * sizeof(int)); tmp[0] = (int)cc; tmp[1] = (int)(cc >> 8); tmp[2] = (int)(cc ^ 1234); memcpy(gps[cc].loc, tmp, 12); free(tmp); gps[cc].ib = 1; }
    }
    printf("%.2f ", (omp_get_wtime() - t0) * 1000.0);
  }
  printf("\n");
  return 0;
}
