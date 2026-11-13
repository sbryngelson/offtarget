! # Finding (nested-data): AFAR flang, copy mode: a derived-type object reached through a pointer (the root, or a pointer
! # component) with an allocatable component, mapped by enter data, makes the kernel fault
!
! - toolchains and modes that fail: afar (AFAR 24.3.0); modes: copy; -O2
! - build: amdflang -fopenmp --offload-arch=gfx942 -O2
! - failure: crash
! - observed: `Warning: Queue error - HSA_STATUS_ERROR_MEMORY_FAULT` (killed by signal 6); identical signature on 1 of 1 failing
!   cells
! - expected: compiles and prints `tot= 828`, `sum= 884` with `check=pass`
! - rule: the structure is mapped by the target enter data directive and "If a variable is not a scalar then it is
!   treated as if it had appeared in a map clause with a map-type of tofrom" (5.2 §5.8.1 p.149 l.4-5), so a reference in
!   the later target region finds it present; an allocatable component of a mapped derived type is mapped with it by the
!   predefined default mapper (5.2 §5.8.2 p.150 l.2-4)
! - same-compiler control: controls/m2-ctl-variable-root.f90 (one change from this file; correct on afar (AFAR 24.3.0); rows
!   results/nested/red/tuo3.jsonl, results/nested/red/wgs.jsonl, results/nested/red/wnv.jsonl);
!   controls/m3-ctl-fixed-array-component.f90 (one change from this file; correct on afar (AFAR 24.3.0); rows
!   results/nested/red/tuo3.jsonl, results/nested/red/wgs.jsonl, results/nested/red/wnv.jsonl); controls/m5-ctl-no-enter-data.f90
!   (one change from this file; correct on afar (AFAR 24.3.0); rows results/nested/red/tuo3.jsonl, results/nested/red/wgs.jsonl,
!   results/nested/red/wnv.jsonl); controls/q2-ctl-fixed-array.f90 (one change from this file; correct on afar (AFAR 24.3.0); rows
!   results/nested/red/tuo11.jsonl, results/nested/red/wgs.jsonl, results/nested/red/wnv.jsonl);
!   controls/q3-ctl-allocatable-component-of-the-variable.f90 (one change from this file; correct on afar (AFAR 24.3.0); rows
!   results/nested/red/tuo11.jsonl, results/nested/red/wgs.jsonl, results/nested/red/wnv.jsonl)
! - other families: cce19 (CCE 19.0.0), cce20 (CCE 20.0.2), cce21 (CCE 21.0.3), cce21_4 (CCE 21.0.4), nvhpc (NVHPC 25.11), nvhpc269
!   (NVHPC 26.9), gcc_g90 (GCC 16.2.0), gcc_sm80 (GCC 16.2.0) run the file correctly in managed mode (rows
!   results/nested/red/red7.jsonl, results/nested/red/tuo2.jsonl, results/nested/red/tuo3.jsonl, results/nested/red/tuo6.jsonl,
!   results/nested/red/wgs.jsonl, results/nested/red/wnv.jsonl, site rows, check case
!   site-nested--afar-flang-pointer-root-allocatable-component-enter-data-fault); nvhpc (NVHPC 25.11), nvhpc269 (NVHPC 26.9) fail it
!   another way in copy mode, e.g. `Failing in Thread:1`
! - gate and confirmer: campaign gate of the programs below: 123 cells, 123 confirmed in the four environments (a-d; (c) on another
!   node or GPU; rows results/nested/big/gate_reruns.part.tuolumne1010.3222831.jsonl,
!   results/nested/big/gate_reruns.part.tuolumne1012.1040717.jsonl, results/nested/big/gate_reruns.part.tuolumne1176.1251749.jsonl,
!   results/nested/big/gate_reruns.part.tuolumne1246.1434668.jsonl, results/nested/big/rows.part.tuolumne1010.1956389.jsonl,
!   results/nested/big/rows.part.tuolumne1040.1523848.jsonl, results/nested/big/rows.part.tuolumne1624.1197409.jsonl,
!   results/nested/main/gate_reruns.part.tuolumne1095.961942.jsonl, results/nested/main/gate_reruns.part.tuolumne1789.919396.jsonl,
!   results/nested/main/gate_reruns.part.tuolumne1955.3910568.jsonl,
!   results/nested/main/gate_reruns.part.tuolumne1955.4072524.jsonl, results/nested/main/rows.part.tuolumne1955.994167.jsonl)
! - programs (123): nd-f-omp-always-chain-d2-0b79aaa6, nd-f-omp-always-chain-d2-5b08a1dd, nd-f-omp-always-chain-d2-75ca3965,
!   nd-f-omp-always-chain-d2-a1106ec3, nd-f-omp-always-chain-d2-af297865, nd-f-omp-always-chain-d2-b1ac0170,
!   nd-f-omp-always-chain-d2-c87159f0, nd-f-omp-always-chain-d2-c931e678, nd-f-omp-always-chain-d3-0a19c378,
!   nd-f-omp-always-chain-d3-23f3159f, nd-f-omp-always-chain-d3-6429d1f2, nd-f-omp-always-chain-d3-a2c50d15,
!   nd-f-omp-always-chain-d3-d619d8f3, nd-f-omp-always-chain-d3-e6c04585, nd-f-omp-always-list-d2-1a3866f8,
!   nd-f-omp-close-chain-d2-23d11b6c, nd-f-omp-close-chain-d2-53ab37a7, nd-f-omp-close-chain-d3-6805e4ee,
!   nd-f-omp-close-chain-d3-7d95925f, nd-f-omp-close-chain-d3-9c214397, nd-f-omp-close-tree-d2-77fe8f90,
!   nd-f-omp-enter-chain-d1-b2c324d9, nd-f-omp-enter-chain-d2-02ac29dd, nd-f-omp-enter-chain-d2-3197d0a8,
!   nd-f-omp-enter-chain-d2-3be528ec, nd-f-omp-enter-chain-d2-446a7bbe, nd-f-omp-enter-chain-d2-6f9da85d,
!   nd-f-omp-enter-chain-d2-a22671ae, nd-f-omp-enter-chain-d2-b1679c00, nd-f-omp-enter-chain-d2-b668ef1a,
!   nd-f-omp-enter-chain-d2-c4de674a, nd-f-omp-enter-chain-d2-c8d85554, nd-f-omp-enter-chain-d2-cee2a3ae,
!   nd-f-omp-enter-chain-d2-cf1e37c5, nd-f-omp-enter-chain-d2-ff520002, nd-f-omp-enter-chain-d3-0b3bdece,
!   nd-f-omp-enter-chain-d3-181eb7ae, nd-f-omp-enter-chain-d3-27fc4e52, nd-f-omp-enter-chain-d3-5f7d1cd9,
!   nd-f-omp-enter-chain-d3-6d18ea3c, nd-f-omp-enter-chain-d3-77e3bd5d, nd-f-omp-enter-chain-d3-8b826b39,
!   nd-f-omp-enter-chain-d3-a54517a7, nd-f-omp-enter-chain-d3-e0125bfa, nd-f-omp-enter-list-d3-9b3ce758,
!   nd-f-omp-enter-list-d4-880965d5, nd-f-omp-enter-tree-d2-15fff1f4, nd-f-omp-enter-tree-d2-c78514c5,
!   nd-f-omp-mapper-chain-d1-0d36f37d, nd-f-omp-mapper-chain-d2-15137215, nd-f-omp-mapper-chain-d2-90256a87,
!   nd-f-omp-mapper-chain-d2-b48755f6, nd-f-omp-mapper-chain-d2-c224f613, nd-f-omp-mapper-chain-d2-c26a1f3c,
!   nd-f-omp-mapper_enter-chain-d2-194e7b57, nd-f-omp-mapper_enter-chain-d2-42baa788, nd-f-omp-mapper_enter-chain-d2-58989314,
!   nd-f-omp-mapper_enter-chain-d2-843af8df, nd-f-omp-mapper_enter-chain-d2-a42fde14, nd-f-omp-mapper_enter-chain-d2-d66c239d,
!   nd-f-omp-one-chain-d2-195ea825, nd-f-omp-one-chain-d2-1a15b55c, nd-f-omp-one-chain-d2-2a889054, nd-f-omp-one-chain-d2-30e18d0f,
!   nd-f-omp-one-chain-d2-db9b2606, nd-f-omp-one-chain-d3-4df89a9f, nd-f-omp-one-chain-d3-7d0cf848, nd-f-omp-one-list-d2-1b67cb71,
!   nd-f-omp-one-tree-d2-fe998394, nd-f-omp-present-chain-d2-6b433240, nd-f-omp-present-chain-d2-8328294e,
!   nd-f-omp-present-chain-d2-98f96e52, nd-f-omp-present-chain-d2-9d7a0b6d, nd-f-omp-present-chain-d2-f3cf6eb5,
!   nd-f-omp-present-chain-d3-04d9e7d3, nd-f-omp-present-chain-d3-512ec550, nd-f-omp-present-chain-d3-c07b93ee,
!   nd-f-omp-present-chain-d3-d110420c, nd-f-omp-present-list-d2-865f5787, nd-f-omp-tdata-chain-d2-3ddce863,
!   nd-f-omp-tdata-chain-d2-d7b601da, nd-f-omp-tdata-chain-d3-2be49672, nd-f-omp-tdata-chain-d3-5a6fdac0,
!   nd-f-omp-tdata-chain-d3-85766a94, nd-f-omp-tdata-chain-d3-88f311be, nd-f-omp-tdata-chain-d3-8af496d0,
!   nd-f-omp-tdata-chain-d3-96349065, nd-f-omp-tdata-list-d2-c3abf961, nd-f-omp-tdata-tree-d2-a44b533c,
!   nd-f-omp-tdata-tree-d2-ba8e4a37, nd-f-omp-tdata_nested-chain-d2-ee52b5c1, nd-f-omp-tdata_nested-chain-d2-f63872c4,
!   nd-f-omp-tdata_nested-chain-d3-1d9ac350, nd-f-omp-tdata_nested-chain-d3-78ee2d27, nd-f-omp-tdata_nested-chain-d3-833d215e,
!   nd-f-omp-tdata_nested-chain-d3-9dd3b6ad, nd-f-omp-tdata_nested-chain-d3-cec76abb, nd-f-omp-tdata_nested-chain-d3-e0671608,
!   nd-f-omp-tdata_nested-chain-d3-e61550e7, nd-f-omp-tdata_nested-chain-d4-355811c0, nd-f-omp-update-chain-d2-018eb6d9,
!   nd-f-omp-update-chain-d2-0545e9b5, nd-f-omp-update-chain-d2-3daf06e5, nd-f-omp-update-chain-d2-75e83840,
!   nd-f-omp-update-chain-d2-9756b365, nd-f-omp-update-chain-d2-b9c06ba7, nd-f-omp-update-chain-d2-d90fc1ec,
!   nd-f-omp-update-chain-d2-eb4cf5ae, nd-f-omp-update-chain-d3-261315ff, nd-f-omp-update-chain-d3-3d5ca029,
!   nd-f-omp-update-chain-d3-5b69f0e6, nd-f-omp-update-chain-d3-64ea229b, nd-f-omp-update-chain-d3-74e122b9,
!   nd-f-omp-update-chain-d3-a40d2cc5, nd-f-omp-update-chain-d3-cf66ca90, nd-f-omp-update-chain-d3-d51553a5,
!   nd-f-omp-update-chain-d3-f84ee81c, nd-f-omp-update-chain-d3-fddf3ef0, nd-f-omp-update-chain-d3-fee48361,
!   nd-f-omp-update-chain-d4-0079ddfd, nd-f-omp-update-tree-d2-9a0f19f5, nd-f-omp-update-tree-d3-7d66722a,
!   nd-f-omp-update-tree-d3-cef9276d
! - legality: the rules (offload.engine.rules) accept it, AFAR's flang front end accepts it and CCE compiles and runs it
!   (the front ends of two other families)
program t
  use omp_lib
  implicit none
  type :: n0
    integer, allocatable :: a(:)
  end type n0
  type(n0), pointer :: r
  integer :: q, hf, tot
  logical :: ok
  hf = 1
  !$omp target map(from: hf)
  hf = merge(1, 0, omp_is_initial_device())
  !$omp end target
  allocate(r)
  allocate(r%a(8))
  do q = 1, 8
    r%a(q) = 100 + q - 1
  end do
  tot = 0
  !$omp target enter data map(to: r)
  !$omp target teams distribute parallel do reduction(+: tot)
  do q = 1, 8
    tot = tot + r%a(q)
    r%a(q) = r%a(q) + 7
  end do
  !$omp end target teams distribute parallel do
  !$omp target exit data map(from: r)
  ok = tot == 828 .and. sum(r%a) == 884
  print '(a,i0)', 'tot= ', tot
  print '(a,i0)', 'sum= ', sum(r%a)
  print '(a,i0,a,a)', 'RESULT ran_on_host=', hf, ' check=', merge('pass', 'fail', ok)
end program t

! site:
! title: AFAR: pointer-root derived type with allocatable component faults in copy mode
! summary: AFAR faults in copy mode on a Fortran pointer to a derived type with an allocatable component entered by enter data.
! control: nested/controls/m2-ctl-variable-root.f90 one change from the finding; correct on afar
! control: nested/controls/m3-ctl-fixed-array-component.f90 one change from the finding; correct on afar
! control: nested/controls/m5-ctl-no-enter-data.f90 one change from the finding; correct on afar
! control: nested/controls/q2-ctl-fixed-array.f90 one change from the finding; correct on afar
! control: nested/controls/q3-ctl-allocatable-component-of-the-variable.f90 one change from the finding; correct on afar
! end site
