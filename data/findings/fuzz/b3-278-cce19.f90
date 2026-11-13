! Minimized by compliance.fuzz_min from fuzz seed 278 (fuzz-3).
! toolchain: cce19 (-O2, HSA_XNACK=1, OMP_TARGET_OFFLOAD=mandatory)
! failure: run_error (crash: SIGABRT)
! expected: runs to completion (the host run does)
! observed: device: fail crash: SIGABRT; host reference (afar) checksum=144
! Legal OpenMP 5.2: offload.engine.prerun.check accepts it (rerun: offload.engine.rules with the
!   race rule and the restriction checks, and the AFAR flang front end, not under test here); no
!   compiler under test, gfortran or gcc is a legality witness.
! also failed on (before refinement): cce20
! : CCE 21.0.3 and 21.0.4 fail it too (hipErrorIllegalAddress, HSA_XNACK 0
!   and 1; reruns); it was recorded as correct on CCE 21.
program fuzz_prog
  use omp_lib, only: omp_is_initial_device
  implicit none
  integer, parameter :: n = 64, m = 5
  type :: rec_t
    integer, allocatable :: q(:)
  end type rec_t
  type(rec_t) :: dr
  integer, allocatable, target :: ib(:)
  integer :: ic(n, m)
  integer :: i, j, r1b
  integer(8) :: cs
  allocate(ib(n))
  allocate(dr%q(n))
  do i = 1, n
    ib(i) = mod(i * 42 + 15, 101) - 28
  end do
  do j = 1, m
    do i = 1, n
      ic(i, j) = mod((i + 6 * j) * 19 + 21, 97) - 20
    end do
  end do
  do i = 1, n
    dr%q(i) = mod(i * 17 + 13, 1009) - 449
  end do
  r1b = -13
  ! fuzz: kernels
    !$omp target teams reduction(max: r1b)
      !$omp distribute
      do i = n, 1, -1
        do j = 1, m
          r1b = max(r1b, max((dr%q(i) / 8), (ic(8, (6 - j)) + ib(i))))
        end do
      end do
      !$omp end distribute
    !$omp end target teams
  ! fuzz: checksum
  cs = 0
  cs = modulo(cs * 31_8 + int(r1b, 8), 2147483629_8)
  print '(a,i0,a,i0)', 'RESULT checksum=', cs, ' ran_on_host=', 0
end program fuzz_prog
! site:
! title: ftn: target teams with reduction(max) reading an allocatable component of an implicitly mapped structure ends in an illegal
! + memory access
! control: ../vendor/checks/src/fuzz/control/fuzz-b3-278-cce19-control.f90 the device loop reads ib(i) instead of the allocatable
! + component
! + dr%q(i) (dr is not referenced in the region)
! end site
! spec (requirement): a structure variable that a target region references, with no clause naming it, is mapped tofrom with each
!   structure element (an allocatable component included), and a reduction on a combined target teams construct is combined into
!   the original list item.
! "A structure type T has a predefined default mapper that is defined as if by a declare mapper directive that specifies v in a
!   map clause with the alloc map-type and each structure element of v in a map clause with the tofrom map-type." (5.2 §5.8.2
!   p.150 l.2-4)
! "If a variable is not a scalar then it is treated as if it had appeared in a map clause with a map-type of tofrom." (5.2
!   §5.8.1 p.149 l.4-5)
! spec (this program): target teams reduction(max: r1b) reads the allocatable component dr%q(i) of the implicitly mapped
!   structure dr in the distribute loop; the component is mapped with the structure, but CCE 19, 20 and 21 end in an illegal
!   memory access, and the program is correct when the loop reads ib(i) instead.
