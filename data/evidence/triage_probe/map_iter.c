// id: omp51-probe-map_iter
// probe: the OpenMP 5.1 iterator map-type modifier on target (5.1 §2.21.7.1 p.347), one iterator value (it = 0:1 is the value 0), so the one instance a[0:n] shares its containing array with no other (5.1 p.353)
#include <stdio.h>
#include <omp.h>
enum { n = 8 };
int main(void) {
  int a[n], bad = 0, host_flag = 1;
  for (int i = 0; i < n; i++) a[i] = i;
  #pragma omp target map(iterator(it = 0:1), tofrom: a[it:n]) map(tofrom: host_flag)
  {
    host_flag = omp_is_initial_device() ? 1 : 0;
    for (int i = 0; i < n; i++) a[i] += 1;
  }
  for (int i = 0; i < n; i++) bad += a[i] != i + 1;
  printf("RESULT ran_on_host=%d check=%s\n", host_flag, bad ? "fail" : "pass");
  return 0;
}
