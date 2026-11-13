#include <stdio.h>
#include <stdlib.h>
#include <string.h>
/* Only iterations that happen to run on an XCC in `mask` allocate (the others do nothing), so the allocating threads can
   be confined to one chiplet or to chosen chiplets while every other part of the launch is unchanged.
   argv: n mask (bit i = XCC i). Counts records written (ib==1) and damaged records among them. */
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
  long n = atol(argv[1]); int mask = (int)strtol(argv[2], 0, 0);
  gp_t *gps = (gp_t *)calloc(n, sizeof(gp_t));
#pragma omp target enter data map(alloc : gps[0 : n])
#pragma omp target teams distribute parallel for
  for (long cc = 0; cc < n; cc++) {
    if (!((mask >> xcc_id()) & 1)) continue;
    int *tmp = (int *)malloc(3 * sizeof(int));
    tmp[0] = (int)cc; tmp[1] = (int)(cc >> 8); tmp[2] = (int)(cc ^ 1234);
    memcpy(gps[cc].loc, tmp, 3 * sizeof(int));
    free(tmp);
    gps[cc].ib = 1;
  }
#pragma omp target update from(gps[0 : n])
  long ran = 0, bad = 0;
  for (long cc = 0; cc < n; cc++) {
    if (gps[cc].ib != 1) continue;
    ran++;
    if (gps[cc].loc[0] != (int)cc || gps[cc].loc[1] != (int)(cc >> 8) || gps[cc].loc[2] != (int)(cc ^ 1234)) bad++;
  }
  printf("n %ld mask 0x%x allocating iterations %ld damaged %ld\n", n, mask, ran, bad);
  return 0;
}
