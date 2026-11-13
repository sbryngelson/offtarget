// lead 2: int, the same loop with the target and the teams
// distribute parallel for split (target map(tofrom: lp) around it)
#include <stdio.h>
#include <omp.h>
int main(void) {
  int lp = -1;
  int dev = -1;
  #pragma omp target map(tofrom: lp)
  #pragma omp teams distribute parallel for lastprivate(lp)
  for (int i = 1; i <= 64; i++)
    lp = 3 * i;
  #pragma omp target map(tofrom: dev)
  dev = omp_is_initial_device() ? 0 : 1;
  printf("lp= %d dev= %d\n", lp, dev);
  return 0;
}
