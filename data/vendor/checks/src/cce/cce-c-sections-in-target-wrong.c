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
    ref[i] = 2 * (i + 1) + 1;
  }
  #pragma omp target parallel map(to: a) map(tofrom: b, host_flag)
  {
    #pragma omp sections
    {
      #pragma omp section
      {
        for (int i = 0; i < n / 2; i++) b[i] = 2 * a[i] + 1;
        host_flag = omp_is_initial_device();
      }
      #pragma omp section
      {
        for (int i = n / 2; i < n; i++) b[i] = a[i] + a[i] + 1;
      }
    }
  }
  bool ok = true;
  for (int i = 0; i < n; i++)
    ok = ok && (b[i] == ref[i]);
  printf("RESULT ran_on_host=%d check=%s\n", host_flag, ok ? "pass" : "fail");
  return 0;
}
