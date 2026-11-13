// Control of harvest/gcc-c-same-item-two-maps-rejected.c: the variable in one map clause, map(tofrom: x) (compiles;
// correct on gcc_g90 and gcc_sm80).
#include <stdio.h>
#include <omp.h>

int main(void) {
  int x = 111, host_flag = 1;
  /* control: the list item in one map clause */
#pragma omp target map(tofrom: x) map(tofrom: host_flag)
  {
    host_flag = omp_is_initial_device();
    x = x + 1;
  }
  printf("x= %d\n", x);
  printf("RESULT ran_on_host=%d check=%s\n", host_flag, x == 112 ? "pass" : "fail");
  return 0;
}
