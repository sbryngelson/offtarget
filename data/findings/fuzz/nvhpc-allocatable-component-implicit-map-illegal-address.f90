! # Finding (parity-fuzz-s1): NVHPC: reading an allocatable component of a derived-type variable that the target construct maps
! # whole (implicitly or with map(to:)) ends in CUDA_ERROR_ILLEGAL_ADDRESS in separate memory; with the component itself in a
! # map clause the result is right
!
! - toolchains and modes that fail: nvhpc (NVHPC 25.11), nvhpc269 (NVHPC 26.9); modes: copy; -O2
! - build: nvfortran -mp=gpu -gpu=cc80 -gpu=mem:separate -O2
! - failure: run_error
! - observed: `Accelerator Fatal Error: call to cuMemcpyDtoHAsync returned error 700 (CUDA_ERROR_ILLEGAL_ADDRESS): Illegal
!   address during kernel execution`, exit status 1, and the same without OMP_TARGET_OFFLOAD=mandatory (the rows' stderr; the
!   harness's reason reads `exit_status: 1; without mandatory: exit_status: 1`); identical signature on 2 of 2 failing cells
!   (separate memory; in managed memory the program is correct)
! - expected: compiles and prints `sum= 1360` with `check=pass`
! - rule: "If a variable is not a scalar then it is treated as if it had appeared in a map clause with a map-type of tofrom."
!   (5.2 §5.8.1 p.149 l.4-5) maps dr whole, and "If a component of a derived type list item is a map clause list item that
!   results from the predefined default mapper for that derived type" (5.2 §5.8.3 p.151 l.29-30) names the components the
!   default mapper maps; the only latitude for an allocatable component applies when it "is present in the device data
!   environment when the construct is encountered" (5.2 §5.8.3 p.151 l.34-37), which dr%q is not: its storage is mapped with dr
!   and the kernel may read it
! - vendor: "The map clause is supported as described in 2.19.7" on the target construct (item 2.12.5) and "Data Mapping
!   Attribute Rules, Clauses, and Directives" (item 2.19.7) (NVIDIA HPC Compilers User's Guide 26.9, Using OpenMP;
!   data/index/claims/nvidia-hpc-26.9-user-guide-openmp.txt); the guide names no limit on allocatable components
! - same-compiler control: controls/nvhpc-allocatable-component-mapped-control.f90 (one change from this file; correct on nvhpc
!   (NVHPC 25.11), nvhpc269 (NVHPC 26.9); rows results/parity/nvs1/tuo.ac.jsonl, results/parity/nvs1/wt.ac.jsonl);
!   controls/nvhpc-allocatable-component-unreferenced-control.f90 (one change from this file; correct on nvhpc (NVHPC 25.11),
!   nvhpc269 (NVHPC 26.9); rows results/parity/nvs1/tuo.ac.jsonl, results/parity/nvs1/wt.ac.jsonl)
! - other families: afar (AFAR 24.3.0), cce19 (CCE 19.0.0), cce20 (CCE 20.0.2), cce21 (CCE 21.0.3), cce21_4 (CCE 21.0.4) run the
!   file correctly (rows results/parity/nvs1/tuo.ac.jsonl)
! - variants: files next to the reduction in results/parity/nvs1/red/, rows results/parity/nvs1/wt.ac.jsonl (both releases,
!   separate and managed memory) and results/parity/nvs1/tuo.ac.jsonl: dr in map(to: dr)
!   (nvhpc-allocatable-component-map-to-variant.f90), the loop as teams distribute
!   (nvhpc-allocatable-component-teams-distribute-variant.f90), the kernel in an internal procedure with dr an intent(inout)
!   dummy (nvhpc-allocatable-component-dummy-variant.f90, the seeds' shape) and the output a declare target module array read
!   back with target update (nvhpc-allocatable-component-declare-target-output-variant.f90, seed 6329's shape) all fail the same
!   way in separate memory and are correct in managed memory. Every program below reads dr%q in its kernel with dr mapped whole.
!   Seed 1994 carries the c1 depend finding's message (cuEventQuery error 700) but not its trigger: its depend list names only
!   variables present through target enter data (the shape that finding leaves uncounted), and once its depend clauses are
!   removed it fails this way, at cuMemcpyDtoHAsync (exploration); it is counted nowhere. Seed 6719, which maps dr%q itself and
!   crashes AFAR and CCE 21 too, is not counted either
! - gate and confirmer: 2 of 2 cells reproduce in all four environments (a-d; (c) on another node or GPU than (a); rows
!   results/parity/nvs1/gate_abd.ac.jsonl, results/parity/nvs1/gate_c.ac.jsonl, results/parity/nvs1/wt.ac.jsonl); campaign gate of
!   the programs below: 14 cells, 14 confirmed in the four environments (a-d; (c) on another node or GPU; rows
!   results/parity/wingtip/results/parity/gate/fuzz/reruns/wingtip.abd.2465893.jsonl,
!   results/parity/wingtip/results/parity/gate/fuzz/reruns/wingtip.abd.2476695.jsonl,
!   results/parity/wingtip/results/parity/gate/fuzz/reruns/wingtip.c.3354124.jsonl,
!   results/parity/wingtip/results/parity/gate/fuzz/reruns/wingtip.c.3482833.jsonl)
! - programs (7): par-s1-nvhpc-nvhpc269:2670, par-s1-nvhpc-nvhpc269:4516, par-s1-nvhpc-nvhpc269:4913, par-s1-nvhpc-nvhpc269:5351,
!   par-s1-nvhpc-nvhpc269:5538, par-s1-nvhpc-nvhpc269:6329, par-s1-nvhpc-nvhpc269:2004
! - legality: the rules (offload.engine.rules) and AFAR's flang front end accept this file, its controls and the variants above
!   (offload.engine.prerun.check on a Tuolumne compute node; results/parity/nvs1/prerun.ac.txt); AFAR 24.3.0 and CCE 19/20/21/21.0.4
!   compile and run all of them correctly with HSA_XNACK 0 and 1 (results/parity/nvs1/tuo.ac.jsonl). NVHPC is the compiler under
!   test and is not counted as a witness
program p
  implicit none
  type :: rec_t
    integer :: a(16)
    integer, allocatable :: q(:)
  end type rec_t
  type(rec_t) :: dr
  integer :: o(16), i
  allocate(dr%q(16))
  do i = 1, 16
    dr%a(i) = i
    dr%q(i) = 10 * i
  end do
  o = 0
  !$omp target map(from: o)
  do i = 1, 16
    o(i) = dr%q(i)
  end do
  !$omp end target
  print '(a,i0)', 'sum= ', sum(o)
  print '(a,a)', 'RESULT ran_on_host=0 check=', merge('pass', 'fail', sum(o) == 1360)
end program p

! site:
! title: allocatable component of a mapped structure: illegal address
! summary: nvfortran -mp=gpu appears to behave incorrectly when a target region reads an allocatable component of a derived-type
! + variable that is mapped whole, implicitly or with map(to:), in separate memory: the kernel ends in
! + CUDA_ERROR_ILLEGAL_ADDRESS. With the component itself in a map clause, when only a non-allocatable component is read, or in
! + managed memory, the result is right.
! control: fuzz/controls/nvhpc-allocatable-component-mapped-control.f90 one change from the finding; correct on nvhpc, nvhpc269
! control: fuzz/controls/nvhpc-allocatable-component-unreferenced-control.f90 one change from the finding; correct on nvhpc,
! + nvhpc269
! end site
