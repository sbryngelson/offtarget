// 8 int64 sum reductions on one combined target
// construct (the kernel k0012 of the stress program scalars-c-64, alone).
// Each s_k starts at 100 + k and adds k in each of 4 iterations, so it ends
// at 100 + 5k (OpenMP 5.2 §5.5.8; §17.2 p.340: on a combined target
// construct a reduction list item is also map(tofrom)). Expected: bad= 0
#include <stdio.h>
#include <stdint.h>
int main(void) {
  int64_t s1, s2, s3, s4, s5, s6, s7, s8;
  s1 = 101;
  s2 = 102;
  s3 = 103;
  s4 = 104;
  s5 = 105;
  s6 = 106;
  s7 = 107;
  s8 = 108;
  #pragma omp target teams distribute parallel for reduction(+: s1, s2, s3, s4, s5, s6, s7, s8)
  for (int ii = 0; ii < 4; ii++) {
    s1 += 1;
    s2 += 2;
    s3 += 3;
    s4 += 4;
    s5 += 5;
    s6 += 6;
    s7 += 7;
    s8 += 8;
  }
  int bad = 0, first = -1;
  long fv = 0;
  if (s1 != 105) { bad++; if (first < 0) { first = 1; fv = (long) s1; } }
  if (s2 != 110) { bad++; if (first < 0) { first = 2; fv = (long) s2; } }
  if (s3 != 115) { bad++; if (first < 0) { first = 3; fv = (long) s3; } }
  if (s4 != 120) { bad++; if (first < 0) { first = 4; fv = (long) s4; } }
  if (s5 != 125) { bad++; if (first < 0) { first = 5; fv = (long) s5; } }
  if (s6 != 130) { bad++; if (first < 0) { first = 6; fv = (long) s6; } }
  if (s7 != 135) { bad++; if (first < 0) { first = 7; fv = (long) s7; } }
  if (s8 != 140) { bad++; if (first < 0) { first = 8; fv = (long) s8; } }
  printf("bad= %d first= %d (value %ld, expected %ld) s1= %ld s8= %ld\n", bad, first, fv,
         first < 0 ? 0L : 100L + 5L * first, (long) s1, (long) s8);
  return 0;
}
