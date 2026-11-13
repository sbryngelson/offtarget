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
  int cnt;
  int seq[n];
  for (int i = 1; i <= n; i++) {
    a[i - 1] = i;
    b[i - 1] = 0;
    ref[i - 1] = 2 * i + 1;
  }
  host_flag = 1;
  cnt = 0;
  for (int k1_ = 0; k1_ < n; k1_++)
    seq[k1_] = -1;
  #pragma omp target map(to: a) map(from: b) map(tofrom: cnt) map(from: seq) \
      map(tofrom: host_flag)
  {
    host_flag = (omp_is_initial_device() ? 1 : 0);
    #pragma omp parallel for default(none) shared(a, b, cnt, seq) ordered
    for (int i = 1; i <= n; i++) {
      b[i - 1] = 2 * a[i - 1] + 1;
      #pragma omp ordered
      {
        cnt = cnt + 1;
        seq[i - 1] = cnt;
      }
    }
  }
  bool t2_ = true;
  for (int k3_ = 0; k3_ < n; k3_++)
    t2_ = t2_ && (b[k3_] == ref[k3_]);
  bool t4_ = true;
  for (int k5_ = 0; k5_ < n; k5_++)
    t4_ = t4_ && (2 * seq[k5_] + 1 == ref[k5_]);
  ok = t2_ && t4_;
  printf("RESULT ran_on_host=%d check=%s\n", host_flag, ok ? "pass" : "fail");
  return 0;
}
