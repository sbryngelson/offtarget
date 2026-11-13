! # Finding (nested-data): GCC ICE in gimplify_adjust_omp_clauses: a pointer component of the root and the pointer components
! # of the elements of an allocatable component array in one map list
!
! - toolchains and modes that fail: gcc_g90 (GCC 16.2.0), gcc_sm80 (GCC 16.2.0); modes: copy; -O2
! - build: gfortran -fopenmp -foffload=amdgcn-amdhsa -foffload-options=amdgcn-amdhsa=-march=gfx90a -O2 (gcc_g90); gfortran -fopenmp
!   -foffload=nvptx-none -foffload-options=nvptx-none=-march=sm_80 -foffload-options=nvptx-none=-latomic -O2 (gcc_sm80)
! - failure: ice
! - observed: `Please submit a full bug report, with preprocessed source (by using -freport-bug).`; identical signature on 2 of 2
!   failing cells
! - expected: compiles and prints `tot= 24` with `check=pass`
! - rule: pointer components are list items when they appear in a map clause ("The list items that appear in a map
!   clause may include array sections and structure elements", 5.2 §5.8.3 p.151 l.13); the construct names a pointer
!   component of the root and the pointer components of the elements of an allocatable array component, none of them the
!   base pointer of another item (5.2 §5.8.3 p.152 l.1-3)
! - same-compiler control: controls/g5-ctl-element-pointers-only.f90 (one change from this file; correct on gcc_g90 (GCC 16.2.0),
!   gcc_sm80 (GCC 16.2.0); rows results/nested/red/gate_abd.jsonl, results/nested/red/gate_c.jsonl, results/nested/red/red3.jsonl,
!   results/nested/red/tuo7.jsonl, results/nested/red/wgs.jsonl, results/nested/red/wnv.jsonl);
!   controls/g5-ctl-root-pointer-only.f90 (one change from this file; correct on gcc_g90 (GCC 16.2.0), gcc_sm80 (GCC 16.2.0); rows
!   results/nested/red/gate_abd.jsonl, results/nested/red/gate_c.jsonl, results/nested/red/red3.jsonl,
!   results/nested/red/tuo7.jsonl, results/nested/red/wgs.jsonl, results/nested/red/wnv.jsonl)
! - other families: afar (AFAR 24.3.0), cce19 (CCE 19.0.0), cce20 (CCE 20.0.2), cce21 (CCE 21.0.3), cce21_4 (CCE 21.0.4), nvhpc
!   (NVHPC 25.11), nvhpc269 (NVHPC 26.9) run the file correctly in managed mode (rows results/nested/red/tuo7.jsonl,
!   results/nested/red/wnv.jsonl, site rows, check case site-nested--gcc-fortran-root-and-element-pointer-components-ice); nvhpc
!   (NVHPC 25.11), nvhpc269 (NVHPC 26.9) fail it another way in copy mode, e.g. `Failing in Thread:1`
! - gate and confirmer: campaign gate of the programs below: 4 cells, 4 confirmed in the four environments (a-d; (c) on another node
!   or GPU; rows results/nested/main/gate_reruns.part.tioga37.2711328.jsonl,
!   results/nested/main/gate_reruns.part.tioga39.351539.jsonl,
!   results/nested/main/gate_reruns.part.wingtip.3374144.jsonl,
!   results/nested/main/gate_reruns.part.wingtip.3386107.jsonl,
!   results/nested/main/gate_reruns.part.wingtip.3582436.jsonl,
!   results/nested/main/gate_reruns.part.wingtip.3637854.jsonl,
!   results/nested/main/rows.part.tioga37.2691037.jsonl, results/nested/main/rows.part.wingtip.3363229.jsonl,
!   results/nested/main/rows.part.wingtip.3363230.jsonl)
! - programs (2): nd-f-omp-tdata_nested-chain-d3-0fae50d2, nd-f-omp-tdata_nested-chain-d3-b0edb43f
! - legality: the rules (offload.engine.rules) accept it and AFAR's flang front end accepts it
program t
  use omp_lib
  implicit none
  type :: n1
    integer, pointer :: a(:) => null()
  end type n1
  type :: n0
    integer, pointer :: a(:) => null()
    type(n1), allocatable :: nx(:)
  end type n0
  type(n0) :: r
  integer :: q, hf, tot
  logical :: ok
  hf = 1
  !$omp target map(from: hf)
  hf = merge(1, 0, omp_is_initial_device())
  !$omp end target
  allocate(r%nx(2))
  allocate(r%a(4))
  allocate(r%nx(1)%a(4))
  allocate(r%nx(2)%a(4))
  r%a = 1
  r%nx(1)%a = 2
  r%nx(2)%a = 3
  !$omp target enter data map(to: r)
  !$omp target enter data map(to: r%a) map(to: r%nx(1)%a) map(to: r%nx(2)%a)
  !$omp target map(tofrom: tot)
    tot = sum(r%nx(1)%a) + sum(r%nx(2)%a) + sum(r%a)
  !$omp end target
  !$omp target exit data map(release: r%a) map(release: r%nx(1)%a) map(release: r%nx(2)%a)
  !$omp target exit data map(release: r)
  ok = tot == 24
  print '(a,i0)', 'tot= ', tot
  print '(a,i0,a,a)', 'RESULT ran_on_host=', hf, ' check=', merge('pass', 'fail', ok)
end program t

! site:
! title: GCC Fortran: compiler crash on root and element pointer components in one map list
! summary: GCC crashes in gimplify_adjust_omp_clauses on a root pointer component and element pointer components in one map list.
! control: nested/controls/g5-ctl-element-pointers-only.f90 one change from the finding; correct on gcc_g90, gcc_sm80
! control: nested/controls/g5-ctl-root-pointer-only.f90 one change from the finding; correct on gcc_g90, gcc_sm80
! end site
