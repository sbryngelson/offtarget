/* Audit, candidate 2, CONTROL (explicit map(tofrom: l)): lastprivate on a combined target construct
   without a map clause for the item: "If the target construct is among the
   constituent constructs and the list item is not specified in a map
   clause, the effect of the lastprivate clause is as if the same list item
   appears in a map clause with a map-type of tofrom" (OpenMP 5.0 §2.14
   p.218; 5.2 §17.2 p.339). Expected: l= 2560 dev= 1 */
#include <stdio.h>
#include <omp.h>
int main(void) {
  long long l = 0;
  int dev = -1;
  #pragma omp target teams distribute parallel for lastprivate(l) map(tofrom: l)
  for (int i = 1; i <= 64; i++)
    l = (long long) i * 40;
  #pragma omp target map(tofrom: dev)
  dev = omp_is_initial_device() ? 0 : 1;
  printf("l= %lld dev= %d\n", l, dev);
  return 0;
}
