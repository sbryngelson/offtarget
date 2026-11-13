/* GCC smoke: OpenACC C offload */
#include <openacc.h>
#include <stdio.h>
int main(void) {
  enum { N = 1000 };
  static float a[N];
  int dev = 0;
  for (int i = 0; i < N; i++) a[i] = 1.0f;
#pragma acc parallel loop copy(a, dev)
  for (int i = 0; i < N; i++) {
    a[i] += i + 1;
    if (i == 0) dev = !acc_on_device(acc_device_host);
  }
  double s = 0;
  for (int i = 0; i < N; i++) s += a[i];
  int ok = s == N + N * (N + 1) / 2.0 && dev;
  printf("acc.c sum=%.1f on_device=%d %s\n", s, dev, ok ? "PASS" : "FAIL");
  return !ok;
}
