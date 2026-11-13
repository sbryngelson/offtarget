/* GCC smoke: libm in a target region (does -lm reach the device link?) */
#include <math.h>
#include <omp.h>
#include <stdio.h>
int main(void) {
  double s = 0.0;
  int on_host = 1;
#pragma omp target map(tofrom: s, on_host)
  {
    on_host = omp_is_initial_device();
    for (int i = 1; i <= 100; i++) s += sqrt((double)i) * exp(-0.01 * i);
  }
  double w = 0.0;
  for (int i = 1; i <= 100; i++) w += sqrt((double)i) * exp(-0.01 * i);
  int ok = fabs(s - w) < 1e-9 * fabs(w) && !on_host;
  printf("math.c s=%.12f w=%.12f on_host=%d %s\n", s, w, on_host, ok ? "PASS" : "FAIL");
  return !ok;
}
