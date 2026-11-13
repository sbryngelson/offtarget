! # Finding (nested-data): GCC: a pointer component mapped alloc and written on the device comes back with the wrong values
! # (bounds of the attached descriptor not set)
!
! - toolchains and modes that fail: gcc_g90 (GCC 16.2.0), gcc_sm80 (GCC 16.2.0); modes: copy; -O2
! - build: gfortran -fopenmp -foffload=amdgcn-amdhsa -foffload-options=amdgcn-amdhsa=-march=gfx90a -O2 (gcc_g90); gfortran -fopenmp
!   -foffload=nvptx-none -foffload-options=nvptx-none=-march=sm_80 -foffload-options=nvptx-none=-latomic -O2 (gcc_sm80)
! - failure: wrong_answer (check=fail)
! - observed: `tot= 504`, `s= 900` with `check=fail`
! - expected: compiles and prints `tot= 4028`, `s= 900` with `check=pass` (the model of the program: the sum of the
!   written values)
! - rule: on entry the corresponding pointer "is associated with a pointer target that has the same rank and bounds as
!   the pointer target of the original pointer, such that the corresponding list item can be accessed through the
!   pointer in a target region" (5.2 §5.8.3 p.152 l.11-13); the structure is entered with map(alloc:), so its descriptor
!   is not initialized by a transfer and has to be set by the attach
! - same-compiler control: controls/g2-ctl-entered-to.f90 (one change from this file; correct on gcc_g90 (GCC 16.2.0), gcc_sm80 (GCC
!   16.2.0); rows results/nested/red/red1.jsonl, results/nested/red/tuo2.jsonl, results/nested/red/wgs.jsonl,
!   results/nested/red/wnv.jsonl); controls/g2-ctl-allocatable.f90 (one change from this file; correct on gcc_g90 (GCC 16.2.0),
!   gcc_sm80 (GCC 16.2.0); rows results/nested/red/red1.jsonl, results/nested/red/wgs.jsonl, results/nested/red/wnv.jsonl)
! - other families: afar (AFAR 24.3.0), cce19 (CCE 19.0.0), cce20 (CCE 20.0.2), cce21 (CCE 21.0.3), cce21_4 (CCE 21.0.4), nvhpc
!   (NVHPC 25.11), nvhpc269 (NVHPC 26.9) run the file correctly (rows results/nested/red/tuo2.jsonl, results/nested/red/wnv.jsonl,
!   site rows, check case site-nested--gcc-fortran-pointer-component-alloc-bounds-lost)
! - legality: the rules (offload.engine.rules) accept it, AFAR's flang front end accepts it
program t
  use omp_lib
  implicit none
  type :: n0
    integer :: s = 0
    integer, pointer :: a(:) => null()
  end type n0
  type(n0) :: r
  integer :: q, hf, tot
  logical :: ok
  hf = 1
  !$omp target map(from: hf)
  hf = merge(1, 0, omp_is_initial_device())
  !$omp end target
  allocate(r%a(8))
  r%s = -1
  r%a = -1
  !$omp target enter data map(alloc: r)
  !$omp target enter data map(alloc: r%a)
  !$omp target
    do q = 1, 8
      r%a(q) = 500 + q - 1
    end do
    r%s = 900
  !$omp end target
  !$omp target exit data map(from: r%a)
  !$omp target exit data map(from: r)
  tot = sum(r%a)
  ok = tot == 4028 .and. r%s == 900
  print '(a,i0)', 'tot= ', tot
  print '(a,i0)', 's= ', r%s
  print '(a,i0,a,a)', 'RESULT ran_on_host=', hf, ' check=', merge('pass', 'fail', ok)
end program t

! site:
! title: GCC Fortran: pointer component entered with alloc comes back with wrong values
! summary: GCC returns wrong values for a Fortran pointer component entered with map(alloc:).
! control: nested/controls/g2-ctl-entered-to.f90 one change from the finding; correct on gcc_g90, gcc_sm80
! control: nested/controls/g2-ctl-allocatable.f90 one change from the finding; correct on gcc_g90, gcc_sm80
! end site
