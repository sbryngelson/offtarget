#include <stdio.h>
#include <stdlib.h>
#include <string.h>
/* Does the damage need the previous owner of a chunk to have run on another XCC?
   Each iteration mallocs a 16-byte chunk and reads word 3 BEFORE writing (the tag the previous owner left: 0 = never
   tagged, otherwise 1+XCC), then writes three data words and its own tag (1+XCC), copies the data into its record and
   frees. Records: my XCC, the tag seen. Host side tabulates damage by (tag seen == 0 / same XCC / other XCC). */
typedef struct { int loc[3]; int ib; } gp_t;
#pragma omp declare target
static inline int xcc_id(void) {
#if defined(__AMDGCN__)
  unsigned v; __asm__ volatile("s_getreg_b32 %0, hwreg(HW_REG_XCC_ID)" : "=s"(v)); return (int)(v & 0xf);
#else
  return 0;
#endif
}
#pragma omp end declare target
int main(int argc, char **argv) {
  long n = atol(argv[1]);
  gp_t *gps = (gp_t *)calloc(n, sizeof(gp_t));
  unsigned char *mine = (unsigned char *)calloc(n, 1), *seen = (unsigned char *)calloc(n, 1);
#pragma omp target enter data map(alloc : gps[0 : n], mine[0 : n], seen[0 : n])
#pragma omp target teams distribute parallel for
  for (long cc = 0; cc < n; cc++) {
    int x = xcc_id();
    int *tmp = (int *)malloc(16);
    volatile int *vt = tmp;
    int prev = vt[3];
    tmp[0] = (int)cc; tmp[1] = (int)(cc >> 8); tmp[2] = (int)(cc ^ 1234); tmp[3] = 1 + x;
    memcpy(gps[cc].loc, tmp, 3 * sizeof(int));
    free(tmp);
    gps[cc].ib = 1; mine[cc] = (unsigned char)x; seen[cc] = (unsigned char)(prev > 0 && prev < 16 ? prev : 0);
  }
#pragma omp target update from(gps[0 : n], mine[0 : n], seen[0 : n])
  long tot[3] = {0, 0, 0}, bad[3] = {0, 0, 0};
  for (long cc = 0; cc < n; cc++) {
    int cls = seen[cc] == 0 ? 0 : (seen[cc] - 1 == mine[cc] ? 1 : 2);
    int dmg = gps[cc].loc[0] != (int)cc || gps[cc].loc[1] != (int)(cc >> 8) || gps[cc].loc[2] != (int)(cc ^ 1234) || gps[cc].ib != 1;
    tot[cls]++; bad[cls] += dmg;
  }
  printf("n %ld | tag seen 0 (fresh or stale): %ld damaged %ld | previous owner same XCC: %ld damaged %ld | other XCC: %ld damaged %ld\n",
         n, tot[0], bad[0], tot[1], bad[1], tot[2], bad[2]);
  return 0;
}
