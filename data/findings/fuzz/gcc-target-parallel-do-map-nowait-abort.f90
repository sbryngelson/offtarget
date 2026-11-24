! # Finding (leads): GCC 16.2 aborts at run time on a Fortran OpenMP program with a target parallel do construct, a map clause and a
!   nowait clause
!
! - toolchains and modes that fail: gcc (GCC 16.2.0); modes: copy; -O2
! - build: gfortran -fopenmp -foffload=amdgcn-amdhsa -foffload-options=amdgcn-amdhsa=-march=gfx942 -O2
! - failure: crash
! - observed: `Memory access fault by GPU node-4 (Agent handle: 0x59bb10) on address 0xfffff000. Reason: Unknown.` (killed by signal
!   6); identical signature on 1 of 1 failing cells
! - expected: compiles and prints `checksum= 804692072` with `check=pass`
! - rule: a conforming program runs to completion: "The target construct provides a superset of the functionality provided by the
!   target data directive, except for the use_device_ptr and use_device_addr clauses." (OpenMP 5.2 §13.8 p.284 l.11-12); "When a
!   thread encounters a parallel construct, a team of threads is created to execute the parallel region (see Section 10.1.1 for more
!   information about how the number of threads in the team is determined, including the evaluation of the if and num_threads
!   clauses)." (OpenMP 5.2 §10.1 p.223 l.12-14); "Separating directives scan Clauses allocate, collapse, firstprivate, lastprivate,
!   linear, nowait, order, ordered, private, reduction, schedule Semantics The do construct is a worksharing-loop construct."
!   (OpenMP 5.2 §11.5.2 p.251 l.2-9); "The map clause specifies how an original list item is mapped from the current task’s data
!   environment to a corresponding list item in the device data environment of the device identified by the construct." (OpenMP 5.2
!   §5.8.3 p.151 l.8-10); "The nowait clause overrides any synchronization that would otherwise occur at the end of a construct."
!   (OpenMP 5.2 §15.6 p.308 l.15-16)
! - same-compiler control: controls/lead-g1x0-o3-1867-gcc-delete-clause-map-to-dr-a-control.f90 (one change from this file; correct
!   on gcc (GCC 16.2.0); rows results/leads/reduce/lead-g1x0-o3-1867-gcc/rows.jsonl);
!   controls/lead-g1x0-o3-1867-gcc-delete-clause-nowait-control.f90 (one change from this file; correct on gcc (GCC 16.2.0); rows
!   results/leads/reduce/lead-g1x0-o3-1867-gcc/rows.jsonl); controls/lead-g1x0-o3-1867-gcc-unwrap-target-parallel-do-control.f90
!   (one change from this file; correct on gcc (GCC 16.2.0); rows results/leads/reduce/lead-g1x0-o3-1867-gcc/rows.jsonl)
! - other families: afar (AFAR 24.3.0) run the file correctly (site rows, check case
!   site-fuzz--gcc-target-parallel-do-map-nowait-abort); afar244 (AFAR 24.4.0), cce19 (CCE 19.0.0), cce20 (CCE 20.0.2), cce21 (CCE
!   21.0.3), cce21_4 (CCE 21.0.4) fail it another way, e.g. `site-fuzz--gcc-target-parallel-do-map-nowait-abort.f90:93:9: error:
!   This compound directive does not allow NOWAIT clause`
! - programs (1): g1x0-o3:1867
! - legality: the rules engine accepts it (offload.engine.prerun.rules_witness); afar run it correctly in the confirmer's runs
!   (tools/confirm.py case); the legality verdict is computed (tools/review/review.py mechanical)
module fuzz_smod
  implicit none
  interface
    module integer function gs1(x)
      !$omp declare target
      integer, intent(in) :: x
    end function gs1
  end interface
end module fuzz_smod
!@file fuzz_ssub.f90
submodule (fuzz_smod) fuzz_ssub
  implicit none
contains
  module integer function gs1(x)
    !$omp declare target
    integer, intent(in) :: x
    gs1 = 0
  end function gs1
end submodule fuzz_ssub
!@file fuzz_ext.f90
integer function ge1(x)
  implicit none
  integer, intent(in) :: x
  !$omp declare target
  ge1 = 0
end function ge1
!@file fuzz_prog.f90
program fuzz_prog
  use omp_lib, only: omp_is_initial_device
  use fuzz_smod, only: gs1
  implicit none
  interface
    integer function ge1(x)
      !$omp declare target
      integer, intent(in) :: x
    end function ge1
  end interface
  integer, parameter :: n = 48, m = 5
  type :: rec_t
    integer :: a(n)
    integer, allocatable :: q(:)
  end type rec_t
  type :: el_t
  end type el_t
  type(rec_t) :: dr
  type(el_t) :: ds(n)
  integer, pointer :: o2(:)
  integer, allocatable :: o4(:)
  integer :: i, j, lp2, hf2, hf4
  integer(8) :: cs
  allocate(o4(n))
  allocate(dr%q(n))
  allocate(o2(n))
  do i = 1, n
    dr%a(i) = mod(i * 7 + 44, 1009) - 458
    dr%q(i) = mod(i * 38 + 19, 211) - 5
  end do
  o2 = 0
  o4 = 0
  lp2 = 0
  hf2 = 0
  hf4 = 0
  ! fuzz: kernels
  !$omp target parallel do map(to: dr%a) lastprivate(lp2) nowait depend(in: dr) &
  !$omp& depend(out: ds, hf2, lp2, o2)
  do i = 1, n
    lp2 = dr%a((49 - i))
  end do
  !$omp end target parallel do
  !$omp target map(tofrom: hf4)
    hf4 = merge(1, 0, omp_is_initial_device())
    do i = 1, n
      o4(i) = mod(dr%q(i), 97)
    end do
  !$omp end target
  !$omp taskwait
  ! fuzz: checksum
  cs = 0
  cs = modulo(cs * 31_8 + int(lp2, 8), 2147483629_8)
  do i = 1, n
    cs = modulo(cs * 31_8 + int(o2(i), 8), 2147483629_8)
  end do
  do i = 1, n
    cs = modulo(cs * 31_8 + int(o4(i), 8), 2147483629_8)
  end do
  print '(a,i0)', 'checksum= ', cs
  print '(a,i0,a,a)', 'RESULT ran_on_host=', max(hf2, hf4, 0), ' check=', 'pass'
end program fuzz_prog

! site:
! title: GCC: abort with target parallel do, map and nowait
! summary: GCC 16.2 aborts at run time on a Fortran OpenMP program with a target parallel do construct, a map clause and a nowait
! + clause.
! control: fuzz/controls/lead-g1x0-o3-1867-gcc-delete-clause-map-to-dr-a-control.f90 one change from the finding; correct on gcc
! control: fuzz/controls/lead-g1x0-o3-1867-gcc-delete-clause-nowait-control.f90 one change from the finding; correct on gcc
! control: fuzz/controls/lead-g1x0-o3-1867-gcc-unwrap-target-parallel-do-control.f90 one change from the finding; correct on gcc
! end site
