#include <stdio.h>
#include <stdbool.h>
#include <omp.h>

enum { n = 64 };

int main(void) {
  int a[n];
  int b[n];
  int ref[n];
  int host_flag;
  bool ok;
  int c;
  int r;
  for (int i = 1; i <= n; i++) {
    a[i - 1] = i;
    b[i - 1] = 0;
    ref[i - 1] = 2 * i + 1;
  }
  host_flag = 1;
  r = 0;
  {
    host_flag = (omp_is_initial_device() ? 1 : 0);
    for (int i = 1; i <= n; i++) {
      b[i - 1] = 2 * a[i - 1] + 1;
    }
    #pragma omp parallel private(c)
    {
      c = 7;
      #pragma omp task default(shared)
      {
        c = 42;
      }
      #pragma omp taskwait
      if (omp_get_thread_num() == 0) r = c;
    }
  }
  bool t1_ = true;
  for (int k2_ = 0; k2_ < n; k2_++)
    t1_ = t1_ && (b[k2_] == ref[k2_]);
  ok = t1_ && (r == 42);
  printf("RESULT ran_on_host=%d check=%s\n", host_flag, ok ? "pass" : "fail");
  return 0;
}
