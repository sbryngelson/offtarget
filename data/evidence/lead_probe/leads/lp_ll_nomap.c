// lead 2: long long, no map (the finding's form)
#include <stdio.h>
#include <omp.h>
int main(void) {
  long long lp = -1;
  int dev = -1;
  #pragma omp target teams distribute parallel for lastprivate(lp)
  for (int i = 1; i <= 64; i++)
    lp = 3 * i;
  #pragma omp target map(tofrom: dev)
  dev = omp_is_initial_device() ? 0 : 1;
  printf("lp= %lld dev= %d\n", lp, dev);
  return 0;
}
