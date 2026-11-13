/* C lastprivate on combined target constructs, the variant
   target teams distribute lastprivate(l) map(tofrom: l). Expected: l= 2560 dev= 1 (lastprivate gives the sequentially last
   iteration's value, 5.2 §5.4.5; on a combined target construct the item is
   also map(tofrom), 5.2 §17.2 p.339 l.27-30) */
#include <stdio.h>
#include <omp.h>
int main(void) {
  long long l = 0, out[1] = {0};
  int dev = -1;
  #pragma omp target teams distribute lastprivate(l) map(tofrom: l)
  for (int i = 1; i <= 64; i++)
    l = (long long) i * 40;
  #pragma omp target map(tofrom: dev)
  dev = omp_is_initial_device() ? 0 : 1;
  printf("l= %lld dev= %d\n", l, dev);
  return 0;
}
