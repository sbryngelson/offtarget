! # Finding (nested-data): CCE: target update to() of a pointer to a derived type with an allocatable scalar component, entered
! # with map(alloc:), fails: "host object does not appear to have an associated accelerator object"
!
! - toolchains and modes that fail: cce19 (CCE 19.0.0), cce21_4 (CCE 21.0.4); modes: unified, copy; -O2
! - build: ftn -fopenmp -O2
! - failure: run_error
! - observed: `exit_status: 1; without mandatory: exit_status: 1`; identical signature on 4 of 4 failing cells
! - expected: compiles and prints `tot= 996` with `check=pass`
! - rule: a list item with an allocatable subobject is updated only if the subobject is allocated (OpenMP 5.2 §5.9 p.165
!   l.28-29: "If a list item or a subobject of a list item has the ALLOCATABLE attribute, its assignment is performed
!   only if its allocation status is allocated"); the structure was entered with map(alloc: r), whose default mapper
!   maps the allocated component (§5.8.2 p.150 l.2-4), so the update has a device copy to write
! - same-compiler control: controls/ua2-ctl-variable-root.f90 (one change from this file; correct on cce19 (CCE 19.0.0), cce21_4
!   (CCE 21.0.4); rows results/nested/red/tuo21.jsonl, results/nested/red/wgs5.jsonl, results/nested/red/wnv5.jsonl);
!   controls/ua4-ctl-to-in-place-of-alloc-and-update.f90 (one change from this file; correct on cce19 (CCE 19.0.0), cce21_4 (CCE
!   21.0.4); rows results/nested/red/tuo21.jsonl, results/nested/red/wgs5.jsonl, results/nested/red/wnv5.jsonl)
! - other families: nvhpc (NVHPC 25.11), nvhpc269 (NVHPC 26.9), gcc_sm80 (GCC 16.2.0) run the file correctly in managed mode (rows
!   results/nested/red/wgs5.jsonl, results/nested/red/wnv5.jsonl); nvhpc (NVHPC 25.11), nvhpc269 (NVHPC 26.9) fail the controls too,
!   so a failure with this signature is not claimed to be this one; afar (AFAR 24.3.0) fail it another way, e.g. `crash: SIGABRT;
!   without mandatory: crash: SIGABRT` (killed by signal ABRT)
! - gate and confirmer: campaign gate of the programs below: 48 cells, 47 confirmed in the four environments (a-d; (c) on another
!   node or GPU; rows results/nested/big/gate_reruns.part.tuolumne1010.3222831.jsonl,
!   results/nested/big/gate_reruns.part.tuolumne1012.1040717.jsonl, results/nested/big/gate_reruns.part.tuolumne1030.1284552.jsonl,
!   results/nested/big/gate_reruns.part.tuolumne1176.1251749.jsonl, results/nested/big/gate_reruns.part.tuolumne1245.1517583.jsonl,
!   results/nested/big/gate_reruns.part.tuolumne1246.1434668.jsonl, results/nested/big/rows.part.tuolumne1010.1956389.jsonl,
!   results/nested/big/rows.part.tuolumne1040.1523848.jsonl, results/nested/big/rows.part.tuolumne1604.1239313.jsonl,
!   results/nested/big/rows.part.tuolumne1624.1197409.jsonl, results/nested/big/rows.part.tuolumne1797.1146311.jsonl,
!   results/nested/main/gate_reruns.part.tuolumne1095.961942.jsonl, results/nested/main/gate_reruns.part.tuolumne1789.919396.jsonl,
!   results/nested/main/gate_reruns.part.tuolumne1955.3910568.jsonl,
!   results/nested/main/gate_reruns.part.tuolumne1955.4072524.jsonl, results/nested/main/rows.part.tuolumne1955.994167.jsonl)
! - programs (12): nd-f-omp-update-chain-d1-222d392b, nd-f-omp-update-chain-d1-eb999367, nd-f-omp-update-chain-d2-018eb6d9,
!   nd-f-omp-update-chain-d2-3daf06e5, nd-f-omp-update-chain-d2-75e83840, nd-f-omp-update-chain-d2-9756b365,
!   nd-f-omp-update-chain-d2-d90fc1ec, nd-f-omp-update-chain-d2-eb4cf5ae, nd-f-omp-update-chain-d3-3d5ca029,
!   nd-f-omp-update-chain-d3-cf66ca90, nd-f-omp-update-chain-d3-f84ee81c, nd-f-omp-update-tree-d3-cef9276d
! - legality: the rules (offload.engine.rules) accept it; AFAR compiles it (a front end of another family; AFAR fails the
!   pointer-root shape at run time for its own reason, which its map(to:) control shares)
program t
  use omp_lib
  implicit none
  type :: n1
    integer :: s = 0
  end type n1
  type :: n0
    integer :: s = 0
    integer :: a(8) = 0
    type(n1), allocatable :: nx
  end type n0
  type(n0), pointer :: r
  integer :: q, hf, tot
  logical :: ok
  hf = 1
  !$omp target map(from: hf)
  hf = merge(1, 0, omp_is_initial_device())
  !$omp end target
  allocate(r)
  allocate(r%nx)
  do q = 1, 8
    r%a(q) = 100 + q - 1
  end do
  r%nx%s = 21
  tot = 0
  !$omp target enter data map(alloc: r)
  !$omp target update to(r)
  !$omp target teams distribute parallel do reduction(+: tot)
  do q = 1, 8
    tot = tot + r%a(q) + r%nx%s
  end do
  !$omp end target teams distribute parallel do
  !$omp target exit data map(delete: r)
  ok = tot == 996
  print '(a,i0)', 'tot= ', tot
  print '(a,i0,a,a)', 'RESULT ran_on_host=', hf, ' check=', merge('pass', 'fail', ok)
end program t

! site:
! title: CCE: update to of a pointer root with an allocatable scalar component fails
! summary: CCE stops at target update to() of a pointer root with an allocatable scalar component.
! control: nested/controls/ua2-ctl-variable-root.f90 one change from the finding; correct on cce19, cce21_4
! control: nested/controls/ua4-ctl-to-in-place-of-alloc-and-update.f90 one change from the finding; correct on cce19, cce21_4
! end site
