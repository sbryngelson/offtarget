// id: omp52-probe-dt_to
// probe: declare target to(f) (5.2: deprecated, normative) with device_type(any)
#include <stdio.h>
#include <omp.h>
enum { n = 64 };
int f(int x) { return 2 * x + 1; }
#pragma omp declare target to(f) device_type(any)
int main(void) {
  int a[n], b[n], bad = 0, host_flag = 1;
  for (int i = 0; i < n; i++) { a[i] = i + 1; b[i] = 0; }
  #pragma omp target map(to: a) map(from: b) map(tofrom: host_flag)
  {
    host_flag = omp_is_initial_device() ? 1 : 0;
    for (int i = 0; i < n; i++) b[i] = f(a[i]);
  }
  for (int i = 0; i < n; i++) bad += b[i] != 2 * (i + 1) + 1;
  printf("RESULT ran_on_host=%d check=%s\n", host_flag, bad ? "fail" : "pass");
  return 0;
}
