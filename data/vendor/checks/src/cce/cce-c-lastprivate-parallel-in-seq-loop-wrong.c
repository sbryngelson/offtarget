#include <stdio.h>
#include <stdbool.h>
#include <omp.h>

enum { n = 64 };

int main(void) {
  int a[n], b[n], ref[n];
  int host_flag = 1;
  for (int i = 0; i < n; i++) {
    a[i] = i + 1;
    b[i] = 0;
    ref[i] = i < 3 ? n + i : 0;
  }
  #pragma omp target map(to: a) map(tofrom: b, host_flag)
  {
    host_flag = omp_is_initial_device();
    for (int k = 0; k < 3; k++) {
      int last = 0;
      #pragma omp parallel for lastprivate(last)
      for (int i = 0; i < n; i++)
        last = a[i] + k;
      b[k] = last;
    }
  }
  bool ok = true;
  for (int i = 0; i < n; i++)
    ok = ok && (b[i] == ref[i]);
  printf("RESULT ran_on_host=%d check=%s\n", host_flag, ok ? "pass" : "fail");
  return 0;
}
