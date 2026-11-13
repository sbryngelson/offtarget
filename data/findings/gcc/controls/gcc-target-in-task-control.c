#include <stdio.h>
#include <omp.h>

enum { n = 64 };

int main(void) {
  int a[n], b[n];
  int host_flag = 1, bad = 0;
  for (int i = 0; i < n; i++) {
    a[i] = i + 1;
    b[i] = 0;
  }
  {
    #pragma omp target map(to: a) map(from: b) map(tofrom: host_flag)
    {
      host_flag = omp_is_initial_device();
      for (int i = 0; i < n; i++)
        b[i] = 2 * a[i] + 1;
    }
  }
  for (int i = 0; i < n; i++)
    bad += b[i] != 2 * (i + 1) + 1;
  printf("bad= %d\n", bad);
  printf("RESULT ran_on_host=%d check=%s\n", host_flag, bad == 0 ? "pass" : "fail");
  return 0;
}
