// Fresh-042 conforming form: requires dynamic_allocators (so the
// allocator argument of omp_aligned_alloc in a target region may be a
// variable, 5.2 §18.13.6 p.429), a const traits array with a valid trait, the
// size a multiple of the alignment. Expected: x=7 done
#include <omp.h>
#include <stdio.h>
#pragma omp requires dynamic_allocators
int main(void) {
  const omp_alloctrait_t traits[1] = {{omp_atk_alignment, 64}};
  omp_allocator_handle_t alloc = omp_null_allocator;
  int out = 0;
#pragma omp target uses_allocators(alloc(traits)) map(from: out)
  {
    int *x = (int *)omp_aligned_alloc(64, 64, alloc);
    x[0] = 7;
    out = x[0];
    omp_free(x, alloc);
  }
  printf("x=%d done\n", out);
  return 0;
}
