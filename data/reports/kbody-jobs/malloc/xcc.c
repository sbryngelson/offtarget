#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <omp.h>
/* thresh.c plus: which XCC (compute chiplet) each sampled iteration ran on, a team-count parameter, and for every
   damaged record the XCC that wrote it. argv: n frac teams (0 = runtime default) */
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
  int frac = atoi(argv[2]);
  int teams = argc > 3 ? atoi(argv[3]) : 0;
  gp_t *gps = (gp_t *)calloc(n, sizeof(gp_t));
  unsigned char *who = (unsigned char *)calloc(n, 1);
  int hist[16] = {0};
#pragma omp target enter data map(alloc : gps[0 : n], who[0 : n]) map(to : hist[0 : 16])
  if (teams > 0) {
#pragma omp target teams distribute parallel for num_teams(teams) map(alloc : who[0 : n])
    for (long cc = 0; cc < n; cc++) {
      int *tmp = (int *)malloc(3 * sizeof(int));
      tmp[0] = (int)cc; tmp[1] = (int)(cc >> 8); tmp[2] = (int)(cc ^ 1234);
      memcpy(gps[cc].loc, tmp, 3 * sizeof(int));
      free(tmp);
      gps[cc].ib = 1;
      who[cc] = (unsigned char)xcc_id();
    }
  } else {
#pragma omp target teams distribute parallel for
    for (long cc = 0; cc < n; cc++) {
      int *tmp = (int *)malloc(3 * sizeof(int));
      tmp[0] = (int)cc; tmp[1] = (int)(cc >> 8); tmp[2] = (int)(cc ^ 1234);
      memcpy(gps[cc].loc, tmp, 3 * sizeof(int));
      free(tmp);
      gps[cc].ib = 1;
      who[cc] = (unsigned char)xcc_id();
    }
  }
#pragma omp target update from(gps[0 : n], who[0 : n])
  long bad = 0, badx[16] = {0}, seen[16] = {0};
  for (long cc = 0; cc < n; cc++) {
    seen[who[cc] & 15]++;
    if (gps[cc].loc[0] != (int)cc || gps[cc].loc[1] != (int)(cc >> 8) || gps[cc].loc[2] != (int)(cc ^ 1234) || gps[cc].ib != 1) { bad++; badx[who[cc] & 15]++; }
  }
  printf("n %ld teams %d bad %ld | iterations per XCC:", n, teams, bad);
  for (int i = 0; i < 16; i++) if (seen[i]) printf(" %d:%ld", i, seen[i]);
  printf(" | damaged per XCC:");
  for (int i = 0; i < 16; i++) if (badx[i]) printf(" %d:%ld", i, badx[i]);
  printf("\n");
  return 0;
}
