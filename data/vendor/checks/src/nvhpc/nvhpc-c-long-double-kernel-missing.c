#include <stdio.h>
#include <stdbool.h>
#include <omp.h>

enum { n = 64 };

int main(void) {
  int a[n], b[n], ref[n];
  int host_flag = 1;
  long double ld[n];
  for (int i = 0; i < n; i++) {
    a[i] = i + 1;
    b[i] = 0;
    ref[i] = 2 * (i + 1) + 1;
  }
  for (int i = 0; i < n; i++) ld[i] = 0.0L;
  #pragma omp target teams distribute parallel for map(to: a) map(from: ld) map(tofrom: \
      host_flag)
  for (int i = 0; i < n; i++) {
    ld[i] = (long double)a[i] * 2.0L + 1.0L;
    if (i == 0) host_flag = omp_is_initial_device();
  }
  for (int i = 0; i < n; i++) b[i] = (int)ld[i];
  bool ok = true;
  for (int i = 0; i < n; i++)
    ok = ok && (b[i] == ref[i]);
  printf("RESULT ran_on_host=%d check=%s\n", host_flag, ok ? "pass" : "fail");
  return 0;
}
