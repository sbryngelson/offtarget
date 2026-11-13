#include <stdio.h>
#include <stdbool.h>
#include <omp.h>

enum { n = 64 };

#pragma omp declare target
int tw(int x) { return 2 * x + 1; }
int th(int x) { return 3 * x; }
#pragma omp end declare target

int main(void) {
  int a[n], b[n], ref[n];
  int host_flag = 1;
  for (int i = 0; i < n; i++) {
    a[i] = i + 1;
    b[i] = 0;
    ref[i] = (i % 2) ? 2 * (i + 1) + 1 : 3 * (i + 1);
  }
  #pragma omp target teams distribute parallel for map(to: a) map(from: b) map(tofrom: \
      host_flag)
  for (int i = 0; i < n; i++) {
    int (*f)(int) = (i % 2) ? tw : th;
    b[i] = f(a[i]);
    if (i == 0) host_flag = omp_is_initial_device();
  }
  bool ok = true;
  for (int i = 0; i < n; i++)
    ok = ok && (b[i] == ref[i]);
  printf("RESULT ran_on_host=%d check=%s\n", host_flag, ok ? "pass" : "fail");
  return 0;
}
