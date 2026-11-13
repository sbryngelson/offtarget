#include <stdio.h>
#include <stdbool.h>
#include <omp.h>

enum { n = 64 };

int main(void) {
  int a[n], b[n], ref[n];
  int host_flag = 1;
  int s = 0;
  for (int i = 0; i < n; i++) {
    a[i] = i + 1;
    b[i] = 0;
    ref[i] = 0;
  }
  #pragma omp target parallel for map(to: a) map(tofrom: s, host_flag)
  for (int i = 0; i < n; i++) {
    #pragma omp critical(wsum) hint(omp_sync_hint_contended)
    {
      int t = s;
      s = t + a[i];
    }
    if (i == 0) host_flag = omp_is_initial_device();
  }
  bool ok = true;
  for (int i = 0; i < n; i++)
    ok = ok && (b[i] == ref[i]);
  ok = ok && (s == n * (n + 1) / 2);
  printf("RESULT ran_on_host=%d check=%s\n", host_flag, ok ? "pass" : "fail");
  return 0;
}
