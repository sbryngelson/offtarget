#include <stdio.h>
#include <stdlib.h>
#include <string.h>
/* thresh.c with in-kernel checks: is the malloc'd block already wrong right after the stores (allocator), still
   right after the memcpy (copy path), and is the final record right? */
typedef struct { int loc[3]; int ib; } gp_t;
int main(int argc, char **argv) {
  long n = atol(argv[1]);
  gp_t *gps = (gp_t *)calloc(n, sizeof(gp_t));
  long bad_pre = 0, bad_post = 0, nulls = 0;
#pragma omp target enter data map(alloc : gps[0 : n])
#pragma omp target teams distribute parallel for reduction(+ : bad_pre, bad_post, nulls)
  for (long cc = 0; cc < n; cc++) {
    int *tmp = (int *)malloc(3 * sizeof(int));
    if (!tmp) { nulls++; continue; }
    tmp[0] = (int)cc; tmp[1] = (int)(cc >> 8); tmp[2] = (int)(cc ^ 1234);
    volatile int *vt = tmp;
    if (vt[0] != (int)cc || vt[1] != (int)(cc >> 8) || vt[2] != (int)(cc ^ 1234)) bad_pre++;
    memcpy(gps[cc].loc, tmp, 3 * sizeof(int));
    if (vt[0] != (int)cc || vt[1] != (int)(cc >> 8) || vt[2] != (int)(cc ^ 1234)) bad_post++;
    free(tmp);
    gps[cc].ib = 1;
  }
#pragma omp target update from(gps[0 : n])
  long bad = 0, wrong_first = -1;
  for (long cc = 0; cc < n; cc++)
    if (gps[cc].loc[0] != (int)cc || gps[cc].loc[1] != (int)(cc >> 8) || gps[cc].loc[2] != (int)(cc ^ 1234) || gps[cc].ib != 1) { bad++; if (wrong_first < 0) wrong_first = cc; }
  printf("n %ld  block wrong after stores %ld  block wrong after memcpy %ld  null %ld  records wrong %ld (first at %ld)\n",
         n, bad_pre, bad_post, nulls, bad, wrong_first);
  return 0;
}
