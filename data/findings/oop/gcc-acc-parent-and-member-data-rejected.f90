! # Finding (fortran-oop): OpenACC data copyin(x) copy(x%a): 'Symbol x has mixed component and non-component accesses'
!
! - toolchains and modes that fail: gcc_g90 (GCC 16.2 (gfx90a): copy), gcc_sm80 (GCC 16.2 (sm_80): copy); -O2
! - build: gfortran -fopenacc -foffload=amdgcn-amdhsa -foffload-options=amdgcn-amdhsa=-march=gfx90a -O2 (gcc_g90); -fopenacc
!   -foffload=nvptx-none -foffload-options=nvptx-none=-march=sm_80 (gcc_sm80)
! - failure: rejected (diagnostic)
! - observed: `Error: Symbol 'x' has mixed component and non-component accesses`
! - expected: compiles; `r1= 4160`
! - rule: OpenACC 3.4 §2.7.1 p.50 l.1711-1713 (a derived-type variable's allocatable members' data are not copied with it) and
!   §2.6.4 p.43 l.1449-1458 (a member in a data clause is attached): the manual deep copy the specification describes
! - same-compiler control: the same deep copy by enter data copyin(x) then copyin(x%a) (oop-acc-deep-enterexit): correct
! - other families: CCE 19, 20, 21 correct in both modes
! - gate and confirmer: 2 cells, 2 confirmed in the gate's four environments (a-d; results/oop/main/gate_reruns*.jsonl); confirmer
!   (results/oop/main/confirm.jsonl): compiler_bug (R11-compile-rejection) 2
! - programs (1): oop-acc-deep-data (offload/engine/oop_gen.py; this file is the first one)
! - legality: for the gcc cells: the rules (offload.engine.rules, with the fortran-oop restrictions) and AFAR's flang front end
!   (-fsyntax-only) and a CCE compile and NVHPC 26.9 nvfortran (compile only) (tools/campaigns/oop.py legality,
!   results/oop/main/legality.json)
module oop_m
  implicit none
  integer, parameter :: n = 64
  type vec
    integer :: n = 0
    integer, allocatable :: a(:)
  end type vec
end module oop_m

program oop
  use openacc
  use oop_m
  implicit none
  integer :: host_flag
  logical :: ok
  integer :: r1
  type(vec) :: x
  integer :: i
  host_flag = 1
  !$acc serial copy(host_flag)
  host_flag = merge(1, 0, acc_on_device(acc_device_host))
  !$acc end serial
  allocate(x%a(n))
  x%n = n
  do i = 1, n
    x%a(i) = i
  end do
  !$acc data copyin(x) copy(x%a)
  !$acc parallel loop
  do i = 1, n
    x%a(i) = 2 * x%a(i)
  end do
  !$acc end data
  r1 = sum(x%a)
  ok = .true.
  ok = ok .and. (r1 == 4160)
  print '(a,i0)', 'r1= ', r1
  print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, ' check=', merge('pass', 'fail', ok)
end program oop
! site:
! title: OpenACC: a structure and its member in one data construct are rejected
! summary: An OpenACC data construct with copyin(x) copy(x%a), the specification's manual deep copy of an allocatable member, is
! + rejected by GCC 16.2 ('mixed component and non-component accesses'). The same deep copy with two enter data directives works.
! + CCE is correct.
! end site
