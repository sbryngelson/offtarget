#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <omp.h>
#define M 439
#define N 329
#define P 329
#define B 10
#define L 3
#define NJ (N + 1 + 2 * B)
#define NK (P + 1 + 2 * B)
#define IX(i, j, k) ((((long)((i) + B)) * NJ + ((j) + B)) * NK + ((k) + B))
typedef struct { int loc[3]; int ib; } gp_t;
int main(int argc, char **argv) {
  int trials = argc > 1 ? atoi(argv[1]) : 2; long warm = argc > 2 ? atol(argv[2]) : 0L; int dev = omp_get_default_device();
  size_t tot = (size_t)(M + 1 + 2 * B) * NJ * NK; int *sf = calloc(tot, sizeof(int)); long nc = (long)(M + 1) * (N + 1) * (P + 1);
  long ng = nc;
  long nrec = nc; gp_t *gps = calloc(nrec, sizeof(gp_t));
  int *sfp = sf;
  gp_t *gpp = gps;
#pragma omp target enter data map(to : sf[0 : tot]) map(alloc : gps[0 : nrec])
  int host = 1; long tbad = 0;
#pragma omp target map(from : host)
  host = omp_is_initial_device();
  printf("cells %ld ghost %ld\n", nc, ng);
  if (warm > 0) { long wb = 0;
#pragma omp target teams distribute parallel for reduction(+ : wb)
    for (long w = 0; w < warm; w++) { int *p = (int *)malloc(3 * sizeof(int)); if (!p) { wb++; continue; }
      p[0] = (int)w; if (p[0] != (int)w) wb++; free(p); }
    printf("warm-up: bad %ld\n", wb); }
  for (int t = 1; t <= trials; t++) {
    int count = 0;
#pragma omp target teams distribute parallel for map(to : count)
    for (long cc = 0; cc < nc; cc++) {
      int i = (int)(cc / ((long)(N + 1) * (P + 1))), j = (int)((cc / (P + 1)) % (N + 1)), k = (int)(cc % (P + 1));
      {
        long li = ((long)i * (N + 1) + j) * (P + 1) + k;
        int tmp[3]; tmp[0] = i; tmp[1] = j; tmp[2] = k; memcpy(gpp[li].loc, tmp, 3 * sizeof(int));
        gpp[li].ib = 1;
      }
    }
#pragma omp target update from(gps[0 : nrec])
    long bad = 0, dup = 0, miss = 0; int *hits = calloc(nc, sizeof(int));
    for (int i = 0; i <= M; i++) for (int j = 0; j <= N; j++) for (int k = 0; k <= P; k++) {
      gp_t *r = &gps[((long)i * (N + 1) + j) * (P + 1) + k];
      if (r->loc[0] != i || r->loc[1] != j || r->loc[2] != k) bad++; }
    printf("trial %d: bad %ld dup %ld missing %ld\n", t, bad, dup, miss); free(hits);
    tbad += bad + dup + miss;
  }
  printf("RESULT ran_on_host=%d check=%s\n", host, tbad == 0 ? "pass" : "fail");
  return 0;
}
