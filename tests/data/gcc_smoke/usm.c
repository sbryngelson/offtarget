/* GCC smoke: what does requires unified_shared_memory do on this GPU and
   memory setting? libgomp keeps a device only if it supports USM (AMD:
   HSA_AMD_SYSTEM_INFO_SVM_ACCESSIBLE_BY_DEFAULT; NVIDIA: pageableMemoryAccess),
   else host fallback, which OMP_TARGET_OFFLOAD=mandatory turns into an error. */
#include <omp.h>
#include <stdio.h>
#include <stdlib.h>
#pragma omp requires unified_shared_memory
int main(void) {
  int n = 1024, bad = 0, dev = -1;
  int *x = malloc(n * sizeof *x);
  for (int i = 0; i < n; i++) x[i] = i;
#pragma omp target teams distribute parallel for map(tofrom: dev)
  for (int i = 0; i < n; i++) { x[i] += 1; if (i == 0) dev = omp_is_initial_device(); }
  for (int i = 0; i < n; i++) bad += x[i] != i + 1;
  printf("usm.c ndev=%d bad=%d on_host=%d %s\n", omp_get_num_devices(), bad,
         dev, (!bad && !dev) ? "PASS" : "FAIL");
  return bad != 0;
}
