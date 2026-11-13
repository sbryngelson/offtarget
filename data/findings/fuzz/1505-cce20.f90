! Minimized by compliance.fuzz_min from fuzz seed 1505 (fuzz-1).
! toolchain: cce20 (-O2, HSA_XNACK=1, OMP_TARGET_OFFLOAD=mandatory)
! failure: run_error (crash: SIGABRT)
! expected: runs to completion (the host run does)
! : not reproducible on the current install (CCE 20.0.2; reruns,
!   data/vendor/README.md: held, not reproducible); kept as a record.
! observed: device: fail crash: SIGSEGV; host reference (cce20/afar) checksum=1148569567
! Legal OpenMP 5.2: offload.engine.prerun.check accepts it (rerun: offload.engine.rules with the
!   race rule and the restriction checks, and the AFAR flang front end, not under test here); no
!   compiler under test, gfortran or gcc is a legality witness.
module fuzz_mod
  implicit none
contains
  integer function g1(x, y)
    !$omp declare target
    integer, intent(in) :: x, y
    g1 = mod(iand(max(7, x), y), 1009)
  end function g1
end module fuzz_mod
program fuzz_prog
  use omp_lib, only: omp_is_initial_device
  use fuzz_mod, only: g1
  implicit none
  integer, parameter :: n = 24, m = 2
  integer, allocatable :: ia(:)
  integer, allocatable :: o1(:)
  integer, allocatable :: o2(:, :)
  integer, allocatable :: o3(:, :)
  integer :: i, j, p1, r3b
  logical :: lpar
  integer(8) :: cs
  allocate(ia(n))
  allocate(o1(n))
  allocate(o2(n, m))
  allocate(o3(n, m))
  do i = 1, n
    ia(i) = mod(i * 24 + 3, 211) - 93
  end do
  o1 = 0
  o2 = 0
  o3 = 0
  p1 = -5
  r3b = 78
  lpar = .false.
  ! fuzz: kernels
  !$omp target map(tofrom: r3b)
    !$omp parallel if(parallel: lpar)
      !$omp do reduction(min: r3b)
      do i = n, 1, -1
        do j = m, 1, -1
          o3(i, j) = o2(i, j)
          r3b = min(r3b, g1(o2(i, (mod(((j * 7) + 6), m) + 1)), p1))
        end do
      end do
    !$omp end parallel
  !$omp end target
  ! fuzz: checksum
  cs = 0
  do i = 1, n
    cs = modulo(cs * 31_8 + int(o1(i), 8), 2147483629_8)
  end do
  do j = 1, m
    do i = 1, n
      cs = modulo(cs * 31_8 + int(o2(i, j), 8), 2147483629_8)
    end do
  end do
  cs = modulo(cs * 31_8 + int(r3b, 8), 2147483629_8)
  do j = 1, m
    do i = 1, n
      cs = modulo(cs * 31_8 + int(o3(i, j), 8), 2147483629_8)
    end do
  end do
  print '(a,i0,a,i0)', 'RESULT checksum=', cs, ' ran_on_host=', 0
end program fuzz_prog
! spec (requirement): a parallel construct whose if clause evaluates to false is executed by a team of one thread, and a
!   reduction clause on a worksharing loop in that region gives each thread a private copy that is combined into the original list
!   item at the end of the region, so the target region runs to completion with the host's result.
! "if (IfClauseValue = false) then number of threads = 1;" (5.2 §10.1.1 p.226 l.27-28)
! "At the end of a region that corresponds to a construct for which the reduction clause was specified, the original list item
!   is updated by combining its original value with the final value of each of the private copies, using the combiner of the
!   specified reduction-identifier." (5.2 §5.5.8 p.135 l.7-10)
! spec (this program): the target region runs a worksharing do loop with reduction(min: r3b) inside parallel if(parallel: lpar)
!   with lpar false (a team of one thread) and calls a declare target function; the host run completes, CCE 20 crashed on the
!   device (the finding is kept as a record, not reproducible on the current install).
! site:
! title: ftn 20: a reduction(min) loop in parallel if(false) calling a declare target function crashed on the device (not
! + reproducible now)
! end site
