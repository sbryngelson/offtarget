#include <stdio.h>
#include <omp.h>

int main(void) {
  int b[64];
  int host_flag = 1;
  #pragma omp target map(from: b) map(tofrom: host_flag)
  {
    #pragma omp error at(compilation) severity(warning) message("probe")
    host_flag = omp_is_initial_device();
    for (int i = 0; i < 64; i++) b[i] = 2 * i + 1;
  }
  int ok = 1;
  for (int i = 0; i < 64; i++) ok = ok && b[i] == 2 * i + 1;
  printf("RESULT ran_on_host=%d check=%s\n", host_flag, ok ? "pass" : "fail");
  return 0;
}
