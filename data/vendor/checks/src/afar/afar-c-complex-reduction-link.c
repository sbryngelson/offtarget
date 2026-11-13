#include <stdio.h>
#include <stdbool.h>
#include <omp.h>
#include <complex.h>

enum { n = 64 };

int main(void) {
  int a[n], b[n], ref[n];
  int host_flag = 1;
  double _Complex z = 0;
  for (int i = 0; i < n; i++) {
    a[i] = i + 1;
    b[i] = 0;
    ref[i] = 0;
  }
  #pragma omp target teams distribute parallel for map(to: a) map(tofrom: host_flag) \
      reduction(+: z)
  for (int i = 0; i < n; i++) {
    z += (double)a[i] - (double)a[i] * I;
    if (i == 0) host_flag = omp_is_initial_device();
  }
  bool ok = true;
  for (int i = 0; i < n; i++)
    ok = ok && (b[i] == ref[i]);
  ok = ok && (creal(z) == n * (n + 1) / 2.0 && cimag(z) == -n * (n + 1) / 2.0);
  printf("RESULT ran_on_host=%d check=%s\n", host_flag, ok ? "pass" : "fail");
  return 0;
}
