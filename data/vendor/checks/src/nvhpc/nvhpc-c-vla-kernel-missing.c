#include <stdio.h>
#include <stdbool.h>
#include <omp.h>

enum { n = 64 };

int main(void) {
  int a[n], b[n], ref[n];
  int host_flag = 1;
  int m = n;
  for (int i = 0; i < n; i++) {
    a[i] = i + 1;
    b[i] = 0;
    ref[i] = 2 * (i + 1) + 1;
  }
  #pragma omp target map(to: a, m) map(from: b) map(tofrom: host_flag)
  {
    host_flag = omp_is_initial_device();
    int t[m];
    for (int k = 0; k < m; k++) t[k] = 2 * a[k] + 1;
    for (int k = 0; k < m; k++) b[k] = t[k];
  }
  bool ok = true;
  for (int i = 0; i < n; i++)
    ok = ok && (b[i] == ref[i]);
  printf("RESULT ran_on_host=%d check=%s\n", host_flag, ok ? "pass" : "fail");
  return 0;
}
