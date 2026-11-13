! Minimized by compliance.fuzz_min from fuzz seed 54 (fuzz-3).
! toolchain: afar (-O2, HSA_XNACK=1, OMP_TARGET_OFFLOAD=mandatory)
! failure: run_error (crash: SIGSEGV)
! expected: runs to completion (the host run does)
! observed: device: fail crash: SIGSEGV; host reference (elision) checksum=0
! Legal OpenMP 5.2: offload.engine.rules accepts it (offload.engine.prerun.check, rerun: with the
!   race rule and the restriction checks); nvfortran/nvc 26.9 and 25.11 (NVHPC, not under test
!   here) compile it; the check's other witness, the AFAR flang front end, is the compiler under
!   test and is not counted; no gfortran or gcc is a legality witness.
module fuzz_mod
  implicit none
contains
end module fuzz_mod
program fuzz_prog
  use omp_lib, only: omp_get_thread_num, omp_is_initial_device
  implicit none
  integer, parameter :: n = 32, m = 5
  type :: rec_t
    integer, allocatable :: q(:)
  end type rec_t
  type(rec_t) :: dr
  integer, allocatable, target :: ic(:, :)
  integer, pointer :: o1(:)
  integer :: i, j, p1, hf1
  integer(8) :: cs
  allocate(ic(n, m))
  allocate(dr%q(n))
  allocate(o1(n))
  do j = 1, m
    do i = 1, n
      ic(i, j) = mod((i + 8 * j) * 26 + 35, 97) - 30
    end do
  end do
  do i = 1, n
    dr%q(i) = mod(i * 6 + 6, 1009) - 171
  end do
  o1 = 0
  p1 = -3
  hf1 = 0
  ! fuzz: kernels
  !$omp target nowait depend(in: p1) depend(inout: dr, hf1, ic, o1)
  !$omp end target
  !$omp taskwait
  ! fuzz: checksum
  cs = 0
  do i = 1, n
    cs = modulo(cs * 31_8 + int(o1(i), 8), 2147483629_8)
  end do
  print '(a,i0,a,i0)', 'RESULT checksum=', cs, ' ran_on_host=', max(hf1, 0)
end program fuzz_prog
! site:
! title: amdflang: an empty target nowait with depend(inout:) on a derived-type variable with an allocatable component crashes
! + (SIGSEGV)
! control: ../vendor/checks/src/fuzz/control/fuzz-b3-54-afar-control.f90 dr removed from the depend clause
! end site
! spec (requirement): a depend clause on a target construct is associated with the target task and derives its dependences from
!   the storage locations of its list items; a variable of derived type with an allocated allocatable component is a legal list
!   item.
! "The target construct generates a target task. The generated task region encloses the target region. If a depend clause is
!   present, it is associated with the target task. The device clause determines the device on which the target region executes.
!   If the nowait clause is present," (5.2 §13.8 p.284 l.14-16)
! "The depend clause enforces additional constraints on the scheduling of tasks. These constraints establish dependences only
!   between sibling tasks. Task dependences are derived from the task-dependence-type and the list items." (5.2 §15.9.5 p.323
!   l.16-18)
! spec (this program): target nowait depend(inout: dr, hf1, ic, o1) with an empty body followed by taskwait is legal, dr being a
!   derived-type variable with an allocated allocatable component; AFAR crashes (SIGSEGV), and the program is correct when dr is
!   removed from the depend clause.
