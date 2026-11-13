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
  int touch = argc > 3 ? atoi(argv[3]) : 0;   /* 0 calloc (untouched pages), 1 host pre-touch, 2 GPU pre-touch, 3 host pre-touch with nonzero */
  gp_t *gps = (gp_t *)(touch == 0 || touch == 2 ? calloc(n, sizeof(gp_t)) : malloc(n * sizeof(gp_t)));
  if (touch == 1) memset(gps, 0, n * sizeof(gp_t));
  if (touch == 3) memset(gps, 0xff, n * sizeof(gp_t));
  long mallocs = 0;
#pragma omp target enter data map(alloc : gps[0 : n])
  if (touch == 2) {
    long np = (long)((n * sizeof(gp_t)) / 4096);
#pragma omp target teams distribute parallel for
    for (long q = 0; q < np; q++) gps[q * 256].ib = 0;
  }
#pragma omp target teams distribute parallel for
  for (long cc = 0; cc < n; cc++) {
    unsigned h = (unsigned)cc * 2654435761u;
    if ((int)((h >> 8) % 100u) < frac) {
      int *tmp = (int *)malloc(3 * sizeof(int));
      tmp[0] = (int)cc; tmp[1] = (int)(cc >> 8); tmp[2] = (int)(cc ^ 1234);
      memcpy(gps[cc].loc, tmp, 3 * sizeof(int));
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
