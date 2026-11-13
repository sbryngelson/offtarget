#include <stdio.h>
#include <stdbool.h>
#include <omp.h>

enum { n = 64 };
int on_dev = 0;
#pragma omp declare target(on_dev)

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
  #pragma omp target map(tofrom: host_flag)
  {
    host_flag = (omp_is_initial_device() ? 1 : 0);
    on_dev = 1;
  }
  #pragma omp target loop map(to: a) map(from: b)
  for (int i = 1; i <= n; i++) {
    b[i - 1] = 2 * a[i - 1] + on_dev;
  }
  bool t1_ = true;
  for (int k2_ = 0; k2_ < n; k2_++)
    t1_ = t1_ && (b[k2_] == 2 * a[k2_]);
  if (t1_) host_flag = 1;
  bool t3_ = true;
  for (int k4_ = 0; k4_ < n; k4_++)
    t3_ = t3_ && (b[k4_] == ref[k4_]);
  ok = t3_;
  printf("RESULT ran_on_host=%d check=%s\n", host_flag, ok ? "pass" : "fail");
  return 0;
}
