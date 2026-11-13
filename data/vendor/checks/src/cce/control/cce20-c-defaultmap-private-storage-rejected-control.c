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
  int w[n];
  for (int i = 1; i <= n; i++) {
    a[i - 1] = i;
    b[i - 1] = 0;
    ref[i - 1] = 2 * i + 1;
  }
  host_flag = 1;
  c = 0;
  for (int k1_ = 0; k1_ < n; k1_++)
    w[k1_] = 0;
  #pragma omp target map(to: a) map(from: b) map(tofrom: host_flag) defaultmap(firstprivate)
  {
    host_flag = (omp_is_initial_device() ? 1 : 0);
    c = 1;
    for (int i = 1; i <= n; i++) {
      w[i - 1] = 2 * a[i - 1];
      b[i - 1] = w[i - 1] + c;
    }
  }
  bool wz = true;
  for (int k_ = 0; k_ < n; k_++)
    wz = wz && (w[k_] == 0);
  bool t2_ = true;
  for (int k3_ = 0; k3_ < n; k3_++)
    t2_ = t2_ && (b[k3_] == ref[k3_]);
  ok = t2_ && wz;
  printf("RESULT ran_on_host=%d check=%s\n", host_flag, ok ? "pass" : "fail");
  return 0;
}
