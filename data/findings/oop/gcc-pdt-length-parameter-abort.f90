! # Finding (fortran-oop): mapping a derived type with a length type parameter aborts at run time
!
! - toolchains and modes that fail: gcc_g90 (GCC 16.2 (gfx90a): copy), gcc_sm80 (GCC 16.2 (sm_80): copy); -O2
! - build: gfortran -fopenmp -foffload=amdgcn-amdhsa -foffload-options=amdgcn-amdhsa=-march=gfx90a -O2 (gcc_g90);
!   -foffload=nvptx-none -foffload-options=nvptx-none=-march=sm_80 -foffload-options=nvptx-none=-latomic (gcc_sm80)
! - failure: crash (SIGABRT); OMP_TARGET_OFFLOAD=mandatory
! - observed: compiles; aborts (SIGABRT) in every run; the deferred-length allocatable form (oop-pdt-deferred) aborts in some runs
!   only (nondeterministic in the gate, not counted)
! - expected: `r1= 16 r2= 1496`
! - rule: 5.2 §5.8.3 p.155 l.5-7
! - same-compiler control: the same program without the target construct (controls/pdt-len-host.f90, one change: the PDT work runs
!   on the host): `r1= 16 r2= 1496`, check=pass in the stored run and the gate's four environments on both machines
!   (results/oop/probe/ctl2.*.pdt-len-host.gcc.jsonl, results/oop/probe/ctl2.*.pdt-len-host.wt-gcc_sm80.jsonl), so the abort is
!   the offload's; a
!   kind type parameter only (controls/pdt-kind.f90) is correct too (results/oop/main/rows.part*.jsonl)
! - other families: AFAR (not implemented) and CCE (ftn-1853) reject the programs
! - gate and confirmer: 6 cells, 6 confirmed in the gate's four environments (a-d; results/oop/main/gate_reruns*.jsonl); confirmer
!   (results/oop/main/confirm.jsonl): needs_human (R22-expected-weak) 6; R22-expected-weak means the expected value has one
!   source, the generator's Python model; the values follow from the program's arithmetic (checked by hand), and NVHPC 25.11,
!   NVHPC 26.9 print them on this program
! - programs (3): oop-pdt-len, oop-pdt-array, oop-pdt-kindlen (offload/engine/oop_gen.py; this file is the first one)
! - legality: for the gcc cells: the rules (offload.engine.rules, with the fortran-oop restrictions) and AFAR's flang front end
!   (-fsyntax-only) and NVHPC 26.9 nvfortran (compile only) (tools/campaigns/oop.py legality, results/oop/main/legality.json)
module oop_m
  implicit none
  integer, parameter :: n = 64
  type lv(m)
  integer, len :: m
  integer :: a(m)
  end type lv
end module oop_m

program oop
  use omp_lib
  use oop_m
  implicit none
  integer :: host_flag
  logical :: ok
  integer :: r1, r2
  type(lv(16)) :: x
  integer :: i
  host_flag = 1
  !$omp target map(from: host_flag)
  host_flag = merge(1, 0, omp_is_initial_device())
  !$omp end target
  do i = 1, 16
    x%a(i) = i
  end do
  !$omp target map(tofrom: x) map(from: r1)
  r1 = x%m
  do i = 1, x%m
    x%a(i) = x%a(i) * x%a(i)
  end do
  !$omp end target
  r2 = sum(x%a)
  ok = .true.
  ok = ok .and. (r1 == 16)
  ok = ok .and. (r2 == 1496)
  print '(a,i0)', 'r1= ', r1
  print '(a,i0)', 'r2= ', r2
  print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, ' check=', merge('pass', 'fail', ok)
end program oop
! site:
! title: mapping a derived type with a length type parameter aborts
! summary: A variable of a parameterized derived type with a length type parameter, mapped tofrom, makes the program abort at run
! + time with GCC 16.2. A kind type parameter works.
! control: oop/controls/pdt-len-host.f90 the same program without the target construct (host only)
! end site
