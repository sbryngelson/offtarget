#include <hip/hip_runtime.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
/* The loop of thresh.c in HIP with OpenMP's shape: one thread per element, a grid of n/256 blocks of 256 threads (no
   grid-stride loop), every thread mallocs 12 bytes, stores a tag, copies it into its own record of a host-allocated
   (calloc) array that the GPU reaches directly (XNACK), frees. */
typedef struct { int loc[3]; int ib; } gp_t;
__global__ void k(gp_t *gps, long n) {
  long cc = blockIdx.x * (long)blockDim.x + threadIdx.x;
  if (cc < n) {
    int *tmp = (int *)malloc(3 * sizeof(int));
    tmp[0] = (int)cc; tmp[1] = (int)(cc >> 8); tmp[2] = (int)(cc ^ 1234);
    memcpy(gps[cc].loc, tmp, 3 * sizeof(int));
    free(tmp);
    gps[cc].ib = 1;
  }
}
int main(int argc, char **argv) {
  long n = atol(argv[1]);
  gp_t *gps = (gp_t *)calloc(n, sizeof(gp_t));
  k<<<(unsigned)((n + 255) / 256), 256>>>(gps, n);
  hipError_t e = hipDeviceSynchronize();
  if (e != hipSuccess) { printf("hip error %s\n", hipGetErrorString(e)); return 1; }
  long bad = 0;
  for (long cc = 0; cc < n; cc++)
    if (gps[cc].loc[0] != (int)cc || gps[cc].loc[1] != (int)(cc >> 8) || gps[cc].loc[2] != (int)(cc ^ 1234) || gps[cc].ib != 1) bad++;
  printf("n %ld bad %ld\n", n, bad);
  return 0;
}
