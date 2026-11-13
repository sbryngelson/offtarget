! # Finding (nested-data): CCE, both modes: a variable with a pointer component to a derived type that has an allocatable
! # scalar component of derived type fails at enter data with "unsupported flags for typed transfer"
!
! - toolchains and modes that fail: cce19 (CCE 19.0.0), cce21_4 (CCE 21.0.4); modes: unified, copy; -O2
! - build: ftn -fopenmp -O2
! - failure: run_error
! - observed: `exit_status: 1; without mandatory: exit_status: 1`; identical signature on 4 of 4 failing cells
! - expected: compiles and prints `ha= 4028` with `check=pass`
! - rule: a structure type has a predefined default mapper that maps its elements (OpenMP 5.2 §5.8.2 p.150 l.2-4: "A
!   structure type T has a predefined default mapper that is defined as if by a declare mapper directive that specifies
!   v in a map clause with the alloc map-type"); the variable r is entered with map(alloc: r) and left with map(from:
!   r), its pointer component is not associated, and the target region touches only r%a and r%s
! - same-compiler control: controls/ta2-ctl-no-allocatable-component.f90 (one change from this file; correct on cce19 (CCE 19.0.0),
!   cce21_4 (CCE 21.0.4); rows results/nested/red/red15.jsonl, results/nested/red/tuo20.jsonl, results/nested/red/wgs2.jsonl,
!   results/nested/red/wnv2.jsonl); controls/ta3-ctl-allocatable-scalar-in-the-variable.f90 (one change from this file; correct on
!   cce19 (CCE 19.0.0), cce21_4 (CCE 21.0.4); rows results/nested/red/red15.jsonl, results/nested/red/tuo21.jsonl,
!   results/nested/red/wgs2.jsonl, results/nested/red/wnv2.jsonl); controls/ta4-ctl-pointer-component-only.f90 (one change from this
!   file; correct on cce19 (CCE 19.0.0), cce21_4 (CCE 21.0.4); rows results/nested/red/red15.jsonl, results/nested/red/tuo21.jsonl,
!   results/nested/red/wgs2.jsonl, results/nested/red/wnv2.jsonl)
! - other families: afar (AFAR 24.3.0), nvhpc (NVHPC 25.11), nvhpc269 (NVHPC 26.9), gcc_g90 (GCC 16.2.0), gcc_sm80 (GCC 16.2.0) run
!   the file correctly (rows results/nested/red/red15.jsonl, results/nested/red/tuo20.jsonl, results/nested/red/wgs2.jsonl,
!   results/nested/red/wnv2.jsonl)
! - gate and confirmer: campaign gate of the programs below: 112 cells, 112 confirmed in the four environments (a-d; (c) on another
!   node or GPU; rows results/nested/big/gate_reruns.part.tuolumne1010.3222831.jsonl,
!   results/nested/big/gate_reruns.part.tuolumne1012.1040717.jsonl, results/nested/big/gate_reruns.part.tuolumne1030.1284552.jsonl,
!   results/nested/big/gate_reruns.part.tuolumne1176.1251749.jsonl, results/nested/big/gate_reruns.part.tuolumne1245.1517583.jsonl,
!   results/nested/big/gate_reruns.part.tuolumne1246.1434668.jsonl, results/nested/big/rows.part.tuolumne1010.1956389.jsonl,
!   results/nested/big/rows.part.tuolumne1040.1523848.jsonl, results/nested/big/rows.part.tuolumne1604.1239313.jsonl,
!   results/nested/big/rows.part.tuolumne1624.1197409.jsonl, results/nested/big/rows.part.tuolumne1797.1146311.jsonl,
!   results/nested/main/gate_reruns.part.tuolumne1095.961942.jsonl, results/nested/main/gate_reruns.part.tuolumne1789.919396.jsonl,
!   results/nested/main/gate_reruns.part.tuolumne1955.3910568.jsonl,
!   results/nested/main/gate_reruns.part.tuolumne1955.4072524.jsonl, results/nested/main/rows.part.tuolumne1955.994167.jsonl)
! - programs (28): nd-f-omp-close-chain-d2-23d11b6c, nd-f-omp-enter-chain-d1-21883845, nd-f-omp-enter-chain-d1-64c59390,
!   nd-f-omp-enter-chain-d1-b856f444, nd-f-omp-enter-chain-d2-3197d0a8, nd-f-omp-enter-chain-d2-b668ef1a,
!   nd-f-omp-enter-chain-d3-0b3bdece, nd-f-omp-enter-chain-d3-27fc4e52, nd-f-omp-enter-chain-d3-6d18ea3c,
!   nd-f-omp-enter-chain-d3-a54517a7, nd-f-omp-enter-chain-d3-dc18b074, nd-f-omp-enter-chain-d3-e0125bfa,
!   nd-f-omp-present-chain-d1-e4cdb6d0, nd-f-omp-present-chain-d2-365941e2, nd-f-omp-present-chain-d2-9d7a0b6d,
!   nd-f-omp-present-chain-d3-04d9e7d3, nd-f-omp-present-chain-d3-c07b93ee, nd-f-omp-present-chain-d3-d110420c,
!   nd-f-omp-update-chain-d1-58f7d58c, nd-f-omp-update-chain-d1-f1a9957f, nd-f-omp-update-chain-d2-0545e9b5,
!   nd-f-omp-update-chain-d3-261315ff, nd-f-omp-update-chain-d3-5b69f0e6, nd-f-omp-update-chain-d3-64ea229b,
!   nd-f-omp-update-chain-d3-a40d2cc5, nd-f-omp-update-chain-d3-d51553a5, nd-f-omp-update-chain-d3-fee48361,
!   nd-f-omp-update-chain-d4-0079ddfd
! - legality: the rules (offload.engine.rules) accept it; AFAR's flang front end and NVHPC accept it and run it correctly
!   (front ends of two other families)
program t
  use omp_lib
  implicit none
  type :: n2
    integer :: s = 0
  end type n2
  type :: n1
    integer :: s = 0
    type(n2), allocatable :: nx
  end type n1
  type :: n0
    integer :: s = 0
    integer :: a(8) = 0
    type(n1), pointer :: nx => null()
  end type n0
  type(n0) :: r
  integer :: q, hf, ha, hs
  logical :: ok
  hf = 1
  !$omp target map(from: hf)
  hf = merge(1, 0, omp_is_initial_device())
  !$omp end target

  r%s = -1
  do q = 1, 8
    r%a(q) = -1
  end do
  !$omp target enter data map(alloc: r)
  !$omp target
  do q = 1, 8
    r%a(q) = 500 + q - 1
  end do
  r%s = 900
  !$omp end target
  !$omp target exit data map(from: r)
  ha = sum(r%a)
  hs = r%s
  ok = ha == 4028 .and. hs == 900
  print '(a,i0)', 'ha= ', ha
  print '(a,i0,a,a)', 'RESULT ran_on_host=', hf, ' check=', merge('pass', 'fail', ok)
end program t

! site:
! title: CCE: "unsupported flags for typed transfer" for a nested allocatable scalar component
! summary: CCE aborts enter data of a variable whose pointer component points to a type with an allocatable scalar component.
! control: nested/controls/ta2-ctl-no-allocatable-component.f90 one change from the finding; correct on cce19, cce21_4
! control: nested/controls/ta3-ctl-allocatable-scalar-in-the-variable.f90 one change from the finding; correct on cce19, cce21_4
! control: nested/controls/ta4-ctl-pointer-component-only.f90 one change from the finding; correct on cce19, cce21_4
! end site
