#include <stdio.h>
int main(void) {
  int x = 0;
  #pragma acc parallel loop copy(x)
  for (int v = 0; v < 64; v++) {
    #pragma acc atomic update
    x = x + v + 1;
  }
  printf("x=%d\n", x);
  return 0;
}
