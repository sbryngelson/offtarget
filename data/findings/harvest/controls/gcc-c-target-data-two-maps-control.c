// Control of harvest/gcc-c-target-data-two-maps-ice.c: the variable in one map clause (compiles; correct on gcc_g90 and
// gcc_sm80).
#include <stdio.h>
#include <omp.h>

int main(void) {
  int x = 111, host_flag = 1;
  /* control: the list item in one map clause */
#pragma omp target data map(from: x)
  {
#pragma omp target map(present, alloc: x) map(tofrom: host_flag)
    {
      host_flag = omp_is_initial_device();
      x = 222;
    }
  }
  printf("x= %d\n", x);
  printf("RESULT ran_on_host=%d check=%s\n", host_flag, x == 222 ? "pass" : "fail");
  return 0;
}
