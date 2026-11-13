#include <stdio.h>
#include <stdbool.h>
#include <omp.h>

enum { n = 64 };

#pragma omp declare target
int cnt = 0;
int bump(void) {
  cnt = cnt + 1;
  return cnt;
}
#pragma omp end declare target

int main(void) {
  int a[n], b[n], ref[n];
  int host_flag = 1;
  for (int i = 0; i < n; i++) {
    a[i] = i + 1;
    b[i] = 0;
    ref[i] = i < 3 ? i + 1 : 0;
  }
  #pragma omp target map(tofrom: b, host_flag)
  {
    host_flag = omp_is_initial_device();
    b[0] = bump();
    b[1] = bump();
    b[2] = bump();
  }
  bool ok = true;
  for (int i = 0; i < n; i++)
    ok = ok && (b[i] == ref[i]);
  printf("RESULT ran_on_host=%d check=%s\n", host_flag, ok ? "pass" : "fail");
  return 0;
}
