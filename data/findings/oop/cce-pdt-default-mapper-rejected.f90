! # Finding (fortran-oop): a derived type with a length type parameter in a map clause is rejected (ftn-1853 in the default mapper)
!
! - toolchains and modes that fail: cce19 (CCE 19.0.0: copy, unified), cce20 (CCE 20.0.2: copy, unified), cce21 (CCE 21.0.3: copy,
!   unified), cce21_4 (CCE 21.0.4: copy, unified); -O2
! - build: ftn -fopenmp -O2 (module load cce/<v> craype-accel-amd-gfx942 rocm/<r>; OpenACC: ftn -h acc)
! - failure: rejected (diagnostic); OMP_TARGET_OFFLOAD=mandatory
! - observed: `ftn-1853 ftn: ERROR default$mapper$lv$oop_m_ ... Missing type parameter value for type` at the type definition,
!   every CCE release: the compiler-generated default mapper of the type lacks the length parameter
! - expected: compiles; `r1= 16 r2= 1496`
! - rule: 5.2 §5.8.3 p.155 l.5-7 (the new list item has the type parameters of the original); a parameterized derived type is
!   mappable (5.2 §1.2.6 p.18-19)
! - same-compiler control: the same program with the type's length parameter replaced by a fixed size
!   (controls/pdt-len-unparameterized.f90, one change): correct (check=pass) on CCE 19, 20, 21.0.3 and 21.0.4 in both modes in the
!   stored run and the gate's four environments a-d, (c) on another node or GPU
!   (results/oop/probe/ctl2.*.pdt-len-unparameterized.*.jsonl); a kind type parameter alone (controls/pdt-kind.f90) is correct too
!   (results/oop/main/rows.part*.jsonl)
! - other families: AFAR: 'not yet implemented' for length parameters (afar-pdt-length-parameter-not-implemented.f90); GCC 16.2
!   compiles them and aborts (gcc-pdt-length-parameter-abort.f90)
! - gate and confirmer: 32 cells, 32 confirmed in the gate's four environments (a-d; results/oop/main/gate_reruns*.jsonl);
!   confirmer (results/oop/main/confirm.jsonl): compiler_bug (R11-compile-rejection) 16, unsupported_everywhere
!   (R12-every-family-rejects) 16
! - programs (4): oop-pdt-len, oop-pdt-deferred, oop-pdt-array, oop-pdt-kindlen (offload/engine/oop_gen.py; this file is the first
!   one)
! - legality: for the cce cells: the rules (offload.engine.rules, with the fortran-oop restrictions) and AFAR's flang front end
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
! title: a derived type with a length type parameter cannot be mapped
! summary: Mapping a variable of a parameterized derived type with a length type parameter (type(lv(16)) :: x; map(tofrom: x)) is
! + rejected by CCE 19, 20 and 21 with ftn-1853 'Missing type parameter value' in the compiler's generated default mapper. The same
! + program with a fixed size in place of the length parameter works.
! control: oop/controls/pdt-len-unparameterized.f90 the same program; the type has no length parameter (a fixed size instead)
! end site
