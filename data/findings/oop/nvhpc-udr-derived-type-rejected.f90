! # Finding (fortran-oop): declare reduction on a derived type: 'Unimplemented feature - DECLARE REDUCTION'
!
! - toolchains and modes that fail: nvhpc (NVHPC 25.11: managed, separate), nvhpc269 (NVHPC 26.9: managed, separate); -O2
! - build: nvfortran -mp=gpu -gpu=cc80 -O2 (managed: -gpu=mem:managed)
! - failure: rejected (diagnostic); OMP_TARGET_OFFLOAD=mandatory
! - observed: `NVFORTRAN-W-0155-Unimplemented feature - DECLARE REDUCTION` and then `NVFORTRAN-S-0155-The reduction intrinsic must
!   be MAX, MIN, ...`, NVHPC 25.11 and 26.9
! - expected: compiles; `r1= 2080 r2= 4160`
! - rule: 5.2 §5.5.11 p.139-140; NVHPC documents the gap by omission: the NVIDIA HPC Compilers User's Guide §7.4 "OpenMP Subset"
!   (the OpenMP 5.0 features the compilers support) does not list declare reduction
! - other families: AFAR and GCC 16.2 correct; CCE rejects them (cce-udr-derived-type-unsupported.f90)
! - gate and confirmer: 24 cells, 24 confirmed in the gate's four environments (a-d; results/oop/main/gate_reruns*.jsonl);
!   confirmer (results/oop/main/confirm.jsonl): compiler_bug (R11-compile-rejection) 12, needs_human (R12b-compile-undecided) 12
! - programs (6): oop-dreduce-function, oop-dreduce-subroutine, oop-dreduce-operator, oop-dreduce-default-init,
!   oop-dreduce-argmax, oop-dreduce-nested (offload/engine/oop_gen.py; this file is the first one)
! - legality: for the nvhpc cells: the rules (offload.engine.rules, with the fortran-oop restrictions) and AFAR's flang front end
!   (-fsyntax-only) (tools/campaigns/oop.py legality, results/oop/main/legality.json)
module oop_m
  implicit none
  integer, parameter :: n = 64
  type v2
    integer :: x = 0, y = 0
  end type v2
contains
  function vadd(a, b) result(c)
    !$omp declare target
    type(v2), intent(in) :: a, b
    type(v2) :: c
    c%x = a%x + b%x
    c%y = a%y + b%y
  end function vadd
end module oop_m

program oop
  use omp_lib
  use oop_m
  implicit none
  integer :: host_flag
  logical :: ok
  integer :: r1, r2
  type(v2) :: acc
  integer :: i
  !$omp declare reduction(vsum: v2: omp_out = vadd(omp_out, omp_in)) initializer(omp_priv = v2(0, 0))
  host_flag = 1
  !$omp target map(from: host_flag)
  host_flag = merge(1, 0, omp_is_initial_device())
  !$omp end target
  acc = v2(0, 0)
  !$omp target teams distribute parallel do reduction(vsum: acc)
  do i = 1, n
    acc = vadd(acc, v2(i, 2 * i))
  end do
  r1 = acc%x
  r2 = acc%y
  ok = .true.
  ok = ok .and. (r1 == 2080)
  ok = ok .and. (r2 == 4160)
  print '(a,i0)', 'r1= ', r1
  print '(a,i0)', 'r2= ', r2
  print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, ' check=', merge('pass', 'fail', ok)
end program oop
! site:
! title: declare reduction on a derived type is not implemented
! summary: A user-defined reduction (declare reduction) on a derived type, used on a target teams distribute parallel do, is
! + rejected by NVHPC 25.11 and 26.9 ('Unimplemented feature - DECLARE REDUCTION'); the NVHPC user guide's OpenMP subset does not
! + list declare reduction. AFAR and GCC run all six forms correctly.
! end site
