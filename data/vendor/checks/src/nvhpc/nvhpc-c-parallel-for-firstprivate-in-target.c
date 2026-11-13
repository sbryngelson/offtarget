#include <stdio.h>
int main(void) {
  int b[64];
  int c = 1;
  #pragma omp target map(from: b) map(tofrom: c)
  {
    #pragma omp parallel for default(none) shared(b) firstprivate(c)
    for (int i = 0; i < 64; i++) {
      b[i] = c;
      c = c + 100;
    }
  }
  int ok = (c == 1);
  for (int i = 0; i < 64; i++)
    ok = ok && (b[i] % 100 == 1);
  printf("c=%d every b[i] %% 100 == 1: %s\n", c, ok ? "yes" : "no");
  return ok ? 0 : 1;
}
