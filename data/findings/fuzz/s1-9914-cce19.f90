! Finding: CCE 19 does not finish compiling this program (killed
! after 300 s; the campaign's limit was 600 s), while CCE 20, CCE 21 and
! AFAR compile it in seconds. The kernels: target constructs with
! map(always, tofrom:) of a structure component and thread_limit, and a
! target with a depend(out: go2(:)) on a declare target module array, in a
! bundle with a default declare mapper and a submodule.
!
! A compile that does not finish is the compiler's defect whatever the
! program (RUL-COMPILE-TIME); the program passed the fuzz legality checks
! (offload.engine.rules, gfortran -std=f2008, AFAR flang's front end).
!
! Observed (tuolumne, -O2, 2026-10-23, results/t28_probe/hangv.log): CCE
! 19.0.0 compile timeout; CCE 20.0.2, 21.0.3 and AFAR compile. Fuzz
! campaign s1: the CCE 19 compile timeouts (93 cells in s1 and s1x0; every
! one of those programs has target nowait with depend). Representative s1
! seed 9914, reduced by deleting while the CCE 19 compile still ran after
! 60 s (data/evidence/dataenv_probe/min_hang.py; 191 -> 99 lines).
!
! Fix: reduced further by line, clause and
! list-item deletion while the CCE 19 compile still ran after 90 s
! (data/evidence/dataenv_probe/min_ice.py with the compile-timeout oracle, 83 -> 34
! lines, results/t28_probe/short/; each kept candidate timed out). What
! remains: an empty target with thread_limit(1), an empty target with
! depend(out: go2(:)) on a declare target module array, and a module
! procedure in a submodule; CCE 20 compiles it in 5 s, CCE 21 in 10 s,
! AFAR in 2 s. (The reduction's empty fuzz_ext.f90, a translation unit of
! its own, is left out here.)
!
! ftn -fopenmp -O2 (a bundle: !@file marks start the files)
!@file fuzz_dmod.f90
module fuzz_dmod
  implicit none
  integer, parameter :: nm = 48
  integer :: go2(nm)
  !$omp declare target to(go2)
end module fuzz_dmod
!@file fuzz_smod.f90
module fuzz_smod
  implicit none
  interface
    module integer function gs1(x)
      integer, intent(in) :: x
    end function gs1
  end interface
end module fuzz_smod
!@file fuzz_ssub.f90
submodule (fuzz_smod) fuzz_ssub
  implicit none
contains
  module integer function gs1(x)
    integer, intent(in) :: x
  end function gs1
end submodule fuzz_ssub
!@file fuzz_prog.f90
program fuzz_prog
  use fuzz_dmod
  implicit none
  !$omp target thread_limit(1)
  !$omp end target
  !$omp target depend(out: go2(:))
  !$omp end target
end program fuzz_prog
! spec (requirement): a target construct accepts a depend clause (with an array section as list item) that is associated with
!   the target task, and a thread_limit clause that bounds the threads of the contention group; the specification says nothing
!   about compile time, so the requirement that these constructs are compiled at all is only implied.
! "The target construct generates a target task. The generated task region encloses the target region. If a depend clause is
!   present, it is associated with the target task. The device clause determines the device on which the target region executes.
!   If the nowait clause is present," (5.2 §13.8 p.284 l.14-16)
! "If the thread_limit clause is specified, the number of threads will be less than or equal to threadlim. Otherwise, if the"
!   (5.2 §13.3 p.277 l.19-20)
! spec (this program): an empty target with thread_limit(1) and an empty target with depend(out: go2(:)) on a declare target
!   module array are legal constructs; CCE 19 does not finish compiling the program (killed after 300 s), CCE 20, CCE 21 and AFAR
!   compile it in seconds.
! site:
! title: ftn 19 does not finish compiling target regions with map(always, tofrom:) of a structure component and a depend on a
! + declare target array
! control: ../vendor/checks/src/other/control/s1-9914-cce19-control.f90 thread_limit(1) removed from the first target
! end site
