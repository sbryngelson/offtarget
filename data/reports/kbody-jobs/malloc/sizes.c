#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
/* The same damage test over allocation sizes (slab chunk classes, few-chunks-per-slab sizes that force whole slabs to
   be emptied and reused, and sizes >= 1 MiB that bypass the slabs). Each thread mallocs `size` bytes, stores three tags
   (first, middle, last 8 bytes), copies them into its record of a map-allocated array, frees. argv: n size rounds.
   `rounds` repeats the kernel inside one process with a different size class between launches to make slabs change
   chunk size (Slab::reset path). Prints damaged records per round. */
typedef struct { uint64_t t[3]; int ib; } rec_t;
int main(int argc, char **argv) {
  long n = atol(argv[1]);
  long size = atol(argv[2]);
  int rounds = atoi(argv[3]);
  rec_t *r = (rec_t *)calloc(n, sizeof(rec_t));
#pragma omp target enter data map(alloc : r[0 : n])
  long total = 0;
  for (int k = 0; k < rounds; k++) {
    long sz = (k % 2) ? size : (size / 2 > 16 ? size / 2 : 16);   /* alternate two size classes between launches */
#pragma omp target teams distribute parallel for map(alloc : r[0 : n])
    for (long cc = 0; cc < n; cc++) {
      uint64_t *p = (uint64_t *)malloc(sz);
      if (p) {
        long w = sz / 8;
        p[0] = (uint64_t)cc * 3 + 1; p[w / 2] = (uint64_t)cc * 5 + 2; p[w - 1] = (uint64_t)cc * 7 + 3;
        r[cc].t[0] = p[0]; r[cc].t[1] = p[w / 2]; r[cc].t[2] = p[w - 1];
        free(p);
        r[cc].ib = k + 1;
      } else r[cc].ib = -1;
    }
#pragma omp target update from(r[0 : n])
    long bad = 0, nul = 0;
    for (long cc = 0; cc < n; cc++) {
      if (r[cc].ib == -1) { nul++; continue; }
      if (r[cc].t[0] != (uint64_t)cc * 3 + 1 || r[cc].t[1] != (uint64_t)cc * 5 + 2 || r[cc].t[2] != (uint64_t)cc * 7 + 3 || r[cc].ib != k + 1) bad++;
    }
    printf("size %ld n %ld round %d damaged %ld null %ld\n", sz, n, k, bad, nul);
    total += bad;
    memset(r, 0, n * sizeof(rec_t));
#pragma omp target update to(r[0 : n])
  }
  printf("TOTAL size %ld damaged %ld\n", size, total);
  return 0;
}
