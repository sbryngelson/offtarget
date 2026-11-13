#include <stdio.h>
#include <omp.h>
int main(void) {
  int on_host = 1;
  #pragma omp target map(tofrom: on_host)
  on_host = omp_is_initial_device();
  printf("on_host=%d\n", on_host);
  return 0;
}
