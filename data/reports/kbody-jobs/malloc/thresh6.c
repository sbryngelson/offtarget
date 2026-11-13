#include <stdio.h>
#include <stdlib.h>
#include <string.h>
/* Reduction of the device-malloc failure with the trip count n and the share of allocating iterations separated.
   Each iteration with (hash % 100) < frac mallocs 12 bytes, stores a tag, copies it into its own record of a
   map-allocated array and frees. One trial per process (the failure is a first-launch effect). */
typedef struct { int loc[3]; int ib; } gp_t;
int main(int argc, char **argv) {
  long n = atol(argv[1]);
  int frac = atoi(argv[2]);
  int fl = argc > 3 ? atoi(argv[3]) : 0;   /* 0 none, 1 device(agent)-scope release before free, 2 system-scope release before free, 3 system-scope seq_cst before free */
  gp_t *gps = (gp_t *)calloc(n, sizeof(gp_t));
  long mallocs = 0;
#pragma omp target enter data map(alloc : gps[0 : n])
#pragma omp target teams distribute parallel for
  for (long cc = 0; cc < n; cc++) {
    unsigned h = (unsigned)cc * 2654435761u;
    if ((int)((h >> 8) % 100u) < frac) {
      int *tmp = (int *)malloc(3 * sizeof(int));
      tmp[0] = (int)cc; tmp[1] = (int)(cc >> 8); tmp[2] = (int)(cc ^ 1234);
      memcpy(gps[cc].loc, tmp, 3 * sizeof(int));
      if (fl == 1) __scoped_atomic_thread_fence(__ATOMIC_RELEASE, __MEMORY_SCOPE_DEVICE);
      if (fl == 2) __scoped_atomic_thread_fence(__ATOMIC_RELEASE, __MEMORY_SCOPE_SYSTEM);
      if (fl == 3) __scoped_atomic_thread_fence(__ATOMIC_SEQ_CST, __MEMORY_SCOPE_SYSTEM);
      free(tmp);
      gps[cc].ib = 1;
    }
  }
#pragma omp target update from(gps[0 : n])
  long bad = 0;
  for (long cc = 0; cc < n; cc++) {
    unsigned h = (unsigned)cc * 2654435761u;
    if ((int)((h >> 8) % 100u) < frac) {
      mallocs++;
      if (gps[cc].loc[0] != (int)cc || gps[cc].loc[1] != (int)(cc >> 8) || gps[cc].loc[2] != (int)(cc ^ 1234) || gps[cc].ib != 1) bad++;
    }
  }
  printf("n %ld mallocs %ld bad %ld\n", n, mallocs, bad);
  return 0;
}
