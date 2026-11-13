#include <stdio.h>
#include <stdbool.h>
#include <omp.h>

enum { n = 64 };
int dv = 1;
int dw = 1;
#pragma omp declare target enter(dv)
int f(int x) {
  int r_;
  r_ = 2 * x + 1;
  return r_;
}

int main(void) {
  int a[n];
  int b[n];
  int ref[n];
  int host_flag;
  bool ok;
  for (int i = 1; i <= n; i++) {
    a[i - 1] = i;
    b[i - 1] = 0;
    ref[i - 1] = 2 * i + 1;
  }
  host_flag = 1;
  #pragma omp target
  {
    dv = 5;
  }
  #pragma omp target map(to: a) map(from: b) map(tofrom: host_flag)
  {
    host_flag = (omp_is_initial_device() ? 1 : 0);
    for (int i = 1; i <= n; i++) {
      b[i - 1] = 2 * a[i - 1] + dv - 4;
    }
  }
  bool t1_ = true;
  for (int k2_ = 0; k2_ < n; k2_++)
    t1_ = t1_ && (b[k2_] == ref[k2_]);
  ok = t1_;
  printf("RESULT ran_on_host=%d check=%s\n", host_flag, ok ? "pass" : "fail");
  return 0;
}
