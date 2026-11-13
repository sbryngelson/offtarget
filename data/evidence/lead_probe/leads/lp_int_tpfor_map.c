// lead 2: int, target parallel for, explicit map
#include <stdio.h>
#include <omp.h>
int main(void) {
  int lp = -1;
  int dev = -1;
  #pragma omp target parallel for lastprivate(lp) map(tofrom: lp)
  for (int i = 1; i <= 64; i++)
    lp = 3 * i;
  #pragma omp target map(tofrom: dev)
  dev = omp_is_initial_device() ? 0 : 1;
  printf("lp= %d dev= %d\n", lp, dev);
  return 0;
}
