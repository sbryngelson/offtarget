// (copy mode for the whole catalog): CCE craycc keeps an array
// present after map(delete: a) on target exit data when its reference
// count is two.
// a is entered twice (reference count 2), b once; target exit data
// map(from: b) map(delete: a) sets a's reference count to zero and
// removes it, and decrements b's to zero (5.2 §5.8.3 p.154: "If the
// map-type is delete and the reference count of the corresponding
// storage block is finite then the reference count is set to zero";
// "If the reference count ... is zero, all storage ... is removed").
// Expected: bad= 0 a_present= 0 b_present= 0
// Observed (tuolumne, MI300A, 2026-10-22, 3 runs each, -O2,
// OMP_TARGET_OFFLOAD=mandatory):
// - CCE craycc 19.0.0, 20.0.2, 21.0.3: bad= 0 a_present= 1 b_present= 0,
//   at HSA_XNACK 0 and 1 (delete acts like release).
// - AFAR amdclang 24.0.0git: expected output in both modes.
// The Fortran form passes on CCE (the catalog's Fortran map.delete
// programs). The catalog's C map.delete programs (5.2, 6.0) check the
// presence only in copy mode (copy_mode_only evidence: under unified
// memory the presence checks are skipped), so CCE reads correct at
// HSA_XNACK=1 and wrong at HSA_XNACK=0; with its presence checks run at
// HSA_XNACK=1 (tools/campaigns/presence_x1.py) it fails there too. Not a copy-mode
// failure: the class is x1_oracle_blind.
// CCE: craycc -fopenmp -fopenmp-targets=amdgcn-amd-amdhsa
//      -Xopenmp-target=amdgcn-amd-amdhsa -march=gfx942 -fopenmp-version=52 -O2
//      (module load cce/<v> craype-accel-amd-gfx942 rocm)
// Run:  OMP_TARGET_OFFLOAD=mandatory HSA_XNACK=0 ./a.out
#include <stdio.h>
#include <omp.h>
enum { n = 64 };
int main(void) {
  int a[n], b[n], d = omp_get_default_device();
  for (int i = 0; i < n; i++) { a[i] = i; b[i] = 0; }
  #pragma omp target enter data map(to: a) map(alloc: b)
  #pragma omp target enter data map(to: a)
  #pragma omp target map(alloc: a, b)
  for (int i = 0; i < n; i++) b[i] = 2 * a[i] + 1;
  #pragma omp target exit data map(from: b) map(delete: a)
  int bad = 0;
  for (int i = 0; i < n; i++) bad += b[i] != 2 * i + 1;
  printf("bad= %d a_present= %d b_present= %d\n", bad,
         omp_target_is_present(a, d), omp_target_is_present(b, d));
  return 0;
}
// site:
// title: craycc: map(delete:) on target exit data acts as release for an array entered twice (still present)
// control: ../vendor/checks/src/cce/control/cce-c-map-delete-refcount-control.c a entered once (reference count 1) instead of twice
// end site
