// The C form of afar-xnack1-target-is-present.f90.
// After target enter data map(to: a), omp_target_is_present must return
// true (5.2 §18.8.3 p.389; the enter data creates a corresponding storage
// block, which may share storage with the original, 5.2 §5.8.3 p.153).
// Expected: after enter data: present= 1, after exit data: present= 0
// Observed (tuolumne, MI300A, 2026-10-22, 3 runs each, -O2,
// OMP_TARGET_OFFLOAD=mandatory):
// - AFAR amdclang 24.0.0git at HSA_XNACK=1: present= 0 after enter data;
//   at HSA_XNACK=0: present= 1.
// - CCE craycc 19.0.0: present= 1 / 0 in both modes.
// AFAR: amdclang -fopenmp --offload-arch=gfx942 -fopenmp-version=52 -O2
// CCE:  craycc -fopenmp -fopenmp-targets=amdgcn-amd-amdhsa
//       -Xopenmp-target=amdgcn-amd-amdhsa -march=gfx942 -fopenmp-version=52 -O2
// Run:  OMP_TARGET_OFFLOAD=mandatory HSA_XNACK=1 ./a.out
#include <stdio.h>
#include <omp.h>
int main(void) {
  int a[64], d = omp_get_default_device();
  for (int i = 0; i < 64; i++) a[i] = 1;
  #pragma omp target enter data map(to: a)
  printf("after enter data: present= %d\n", omp_target_is_present(a, d));
  #pragma omp target exit data map(release: a)
  printf("after exit data: present= %d\n", omp_target_is_present(a, d));
  return 0;
}
// site:
// title: AFAR offload runtime at HSA_XNACK=1: omp_target_is_present returns false after target enter data, and map(present) of an
// + absent item does not terminate
// control: ../vendor/checks/src/afar/control/afar-c-xnack1-target-is-present-control.c run at HSA_XNACK=0
// same_as: afar-xnack1-target-is-present
// end site
