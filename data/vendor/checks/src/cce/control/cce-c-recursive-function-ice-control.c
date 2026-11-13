#include <stdio.h>
#include <stdbool.h>
#include <omp.h>

enum { n = 64 };

#pragma omp declare target
int sumto(int k) { return k * (k + 1) / 2; }
#pragma omp end declare target

int main(void) {
  int a[n], b[n], ref[n];
  int host_flag = 1;
  for (int i = 0; i < n; i++) {
    a[i] = i + 1;
    b[i] = 0;
    ref[i] = ((i + 1) % 8) * ((i + 1) % 8 + 1) / 2;
  }
  #pragma omp target teams distribute parallel for map(to: a) map(from: b) map(tofrom: \
      host_flag)
  for (int i = 0; i < n; i++) {
    b[i] = sumto(a[i] % 8);
    if (i == 0) host_flag = omp_is_initial_device();
  }
  bool ok = true;
  for (int i = 0; i < n; i++)
    ok = ok && (b[i] == ref[i]);
  printf("RESULT ran_on_host=%d check=%s\n", host_flag, ok ? "pass" : "fail");
  return 0;
}
