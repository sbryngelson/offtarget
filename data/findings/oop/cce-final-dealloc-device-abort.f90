! # Finding (fortran-oop): DEALLOCATE of an allocatable finalizable object in device code aborts
!
! - toolchains and modes that fail: cce19 (CCE 19.0.0: copy, unified), cce20 (CCE 20.0.2: copy, unified), cce21 (CCE 21.0.3: copy,
!   unified), cce21_4 (CCE 21.0.4: copy, unified); -O2
! - build: ftn -fopenmp -O2 (module load cce/<v> craype-accel-amd-gfx942 rocm/<r>; OpenACC: ftn -h acc)
! - failure: crash / run_error; OMP_TARGET_OFFLOAD=mandatory
! - observed: CCE 19 and 20: `Thread execution stopped at ... LINE 29 due to a Fortran allocate/deallocate statement` (SIGABRT);
!   CCE 21.0.3 and 21.0.4: a queue error dump, exit 1; both modes
! - expected: `r1= 64 r2= 2144`
! - rule: Fortran 2018 7.5.6.3 para 2 (DEALLOCATE finalizes the object); the final subroutine is declare target (5.2 §1.2.6 p.19)
! - same-compiler control: a non-allocatable local of the same type (controls/final-local.f90, the family program
!   oop-assignfinal-final-local): correct on every CCE release and AFAR in both modes, stored run and gate environments a-d
!   (results/oop/probe/ctl2.*.final-local.*.jsonl)
! - other families: AFAR fails at the device link (afar-final-dealloc-device-link.f90); GCC 16.2 correct
! - gate and confirmer: 8 cells, 8 confirmed in the gate's four environments (a-d; results/oop/main/gate_reruns*.jsonl); confirmer
!   (results/oop/main/confirm.jsonl): needs_human (R22-expected-weak) 8; R22-expected-weak means the expected value has one
!   source, the generator's Python model; the values follow from the program's arithmetic (checked by hand), and GCC 16.2
!   (gfx90a), GCC 16.2 (sm_80) print them on this program
! - programs (1): oop-assignfinal-final-dealloc (offload/engine/oop_gen.py; this file is the first one)
! - legality: for the cce cells: the rules (offload.engine.rules, with the fortran-oop restrictions) and AFAR's flang front end
!   (-fsyntax-only) (tools/campaigns/oop.py legality, results/oop/main/legality.json)
module oop_m
  implicit none
  integer, parameter :: n = 64
  type ft
    integer :: v = 0
  contains
    final :: ft_fin
  end type ft
  integer :: fin_count = 0
  !$omp declare target to(fin_count)
contains
  subroutine ft_fin(o)
    !$omp declare target
    type(ft), intent(inout) :: o
    !$omp atomic update
    fin_count = fin_count + 1
  end subroutine ft_fin
  subroutine alloc_work(k, r)
    !$omp declare target
    integer, intent(in) :: k
    integer, intent(out) :: r
    type(ft), allocatable :: o
    allocate(o)
    o%v = k
    r = o%v + 1
    deallocate(o)
  end subroutine alloc_work
end module oop_m

program oop
  use omp_lib
  use oop_m
  implicit none
  integer :: host_flag
  logical :: ok
  integer :: r1, r2
  integer :: res(n), i
  host_flag = 1
  !$omp target map(from: host_flag)
  host_flag = merge(1, 0, omp_is_initial_device())
  !$omp end target
  fin_count = 0
  !$omp target update to(fin_count)
  !$omp target teams distribute parallel do map(tofrom: res)
  do i = 1, n
    call alloc_work(i, res(i))
  end do
  !$omp target update from(fin_count)
  r1 = fin_count
  r2 = sum(res)
  ok = .true.
  ok = ok .and. (r1 == 64)
  ok = ok .and. (r2 == 2144)
  print '(a,i0)', 'r1= ', r1
  print '(a,i0)', 'r2= ', r2
  print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, ' check=', merge('pass', 'fail', ok)
end program oop
! site:
! title: deallocating a finalizable object in device code aborts
! summary: A declare target subroutine allocates and deallocates a local allocatable object of a type with a final subroutine. CCE
! + 19 and 20 stop the device thread at the DEALLOCATE; CCE 21 aborts with a queue error. The same type as a non-allocatable local
! + is finalized correctly. GCC runs it correctly.
! control: oop/controls/final-local.f90 a non-allocatable local of the same finalizable type (no DEALLOCATE)
! end site
