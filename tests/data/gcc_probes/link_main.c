/* Message probe (not a catalog program): a target region calls a function
   of another translation unit that is not a declare-target function, so the
   offload compiler has no device code for it. Captures GCC's offload link
   failure message (link_main.c link_ext.c compiled and linked together). */
#include <stdio.h>
int ext_fn(int);
int main(void) {
  int x = 0;
#pragma omp target map(tofrom: x)
  x = ext_fn(1);
  printf("x=%d\n", x);
  return 0;
}
