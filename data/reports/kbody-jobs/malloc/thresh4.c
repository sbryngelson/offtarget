#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <omp.h>
/* Overlap or stale data? Every thread claims its block address in a table with an atomic compare-and-swap.
   A claim that finds the SAME address already claimed by another live thread is a double allocation.
   Independently: is the block wrong immediately after the thread's own stores (counted as in thresh3.c)? */
typedef struct { int loc[3]; int ib; } gp_t;
#define TBITS 24
#define TMASK ((1UL << TBITS) - 1)
int main(int argc, char **argv) {
  long n = atol(argv[1]);
  gp_t *gps = (gp_t *)calloc(n, sizeof(gp_t));
  unsigned long *tab = (unsigned long *)omp_target_alloc((1UL << TBITS) * sizeof(unsigned long), omp_get_default_device());
#pragma omp target is_device_ptr(tab)
  for (unsigned long q = 0; q < 1; q++) {}
#pragma omp target teams distribute parallel for is_device_ptr(tab)
  for (long q = 0; q < (1L << TBITS); q++) tab[q] = 0;
  long dup = 0, bad_pre = 0, collide = 0, nulls = 0;
#pragma omp target enter data map(alloc : gps[0 : n])
#pragma omp target teams distribute parallel for is_device_ptr(tab) reduction(+ : dup, bad_pre, collide, nulls)
  for (long cc = 0; cc < n; cc++) {
    int *tmp = (int *)malloc(3 * sizeof(int));
    if (!tmp) { nulls++; continue; }
    unsigned long a = (unsigned long)tmp, idx = (a >> 4) & TMASK, expected = 0;
    int claimed = __atomic_compare_exchange_n(&tab[idx], &expected, a, 0, __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE);
    if (!claimed) { if (expected == a) dup++; else collide++; }
    tmp[0] = (int)cc; tmp[1] = (int)(cc >> 8); tmp[2] = (int)(cc ^ 1234);
    volatile int *vt = tmp;
    if (vt[0] != (int)cc || vt[1] != (int)(cc >> 8) || vt[2] != (int)(cc ^ 1234)) bad_pre++;
    memcpy(gps[cc].loc, tmp, 3 * sizeof(int));
    if (claimed) __atomic_store_n(&tab[idx], 0UL, __ATOMIC_RELEASE);
    free(tmp);
    gps[cc].ib = 1;
  }
#pragma omp target update from(gps[0 : n])
  long bad = 0;
  for (long cc = 0; cc < n; cc++)
    if (gps[cc].loc[0] != (int)cc || gps[cc].loc[1] != (int)(cc >> 8) || gps[cc].loc[2] != (int)(cc ^ 1234) || gps[cc].ib != 1) bad++;
  printf("n %ld  same block live in two threads %ld  table collisions %ld  block wrong after own stores %ld  records wrong %ld\n", n, dup, collide, bad_pre, bad);
  return 0;
}
