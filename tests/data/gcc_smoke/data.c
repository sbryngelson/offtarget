#include <omp.h>
#include <stdio.h>
#include <stdlib.h>
#pragma omp declare target
static int scale(int x) { return 3 * x + 1; }
#pragma omp end declare target
int main(void) {
  int n = 4096, bad = 0, dev = -1;
  int *x = malloc(n * sizeof *x);
  for (int i = 0; i < n; i++) x[i] = i;
#pragma omp target enter data map(to: x[0:n])
#pragma omp target teams distribute parallel for map(tofrom: dev)
  for (int i = 0; i < n; i++) { x[i] = scale(x[i]); if (i == 7) dev = omp_is_initial_device(); }
  for (int i = 0; i < n; i++) x[i] = -1;          /* host copy clobbered */
#pragma omp target update from(x[0:n])
#pragma omp target exit data map(delete: x[0:n])
  for (int i = 0; i < n; i++) bad += (x[i] != 3 * i + 1);
  printf("data.c bad=%d on_host=%d %s\n", bad, dev, (!bad && dev == 0) ? "PASS" : "FAIL");
  free(x);
  return !(!bad && dev == 0);
}
