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
  int k;
  int w[n];
  bool pres;
  bool shared_mem;
  int zc[1];
  for (int i = 1; i <= n; i++) {
    a[i - 1] = i;
    b[i - 1] = 0;
    ref[i - 1] = 2 * i + 1;
  }
  host_flag = 1;
  for (int k1_ = 0; k1_ < n; k1_++)
    w[k1_] = 0;
  #pragma omp target enter data map(iterator(k = 1:2), to: w[k:n / 2 - (k + 1) + 1])
  pres = true;
  for (int k2_ = 0; k2_ < 1; k2_++)
    zc[k2_] = 0;
  #pragma omp target map(to: zc)
  {
    zc[0] = 1;
  }
  shared_mem = zc[0] == 1;
  #pragma omp target map(to: a) map(from: b) map(tofrom: host_flag)
  {
    host_flag = (omp_is_initial_device() ? 1 : 0);
    for (int i = 1; i <= n; i++) {
      b[i - 1] = 2 * a[i - 1] + 1;
    }
  }
  if (!shared_mem) pres = pres && (omp_target_is_present(&w[1], omp_get_default_device()) != 0);
  if (!shared_mem) pres = pres && (omp_target_is_present(&w[n / 2 - 1], omp_get_default_device()) != 0);
  if (!shared_mem) pres = pres && (omp_target_is_present(&w[0], omp_get_default_device()) == 0);
  if (!shared_mem) pres = pres && (omp_target_is_present(&w[n / 2], omp_get_default_device()) == 0);
  #pragma omp target exit data map(iterator(k = 1:2), release: w[k:n / 2 - (k + 1) + 1])
  bool t3_ = true;
  for (int k4_ = 0; k4_ < n; k4_++)
    t3_ = t3_ && (b[k4_] == ref[k4_]);
  ok = t3_ && pres;
  printf("RESULT ran_on_host=%d check=%s\n", host_flag, ok ? "pass" : "fail");
  return 0;
}
