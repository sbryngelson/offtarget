! Minimized by compliance.fuzz_min from fuzz seed 68 (fuzz-3).
! toolchain: afar (-O2, HSA_XNACK=1, OMP_TARGET_OFFLOAD=mandatory)
! failure: wrong_code
! expected: the host reference checksum (host reference (cce19) checksum=17631)
! observed: device checksum=70431 ran_on_host=0
! Legal OpenMP 5.2: offload.engine.rules accepts it (offload.engine.prerun.check, rerun: with the
!   race rule and the restriction checks); NVHPC is no witness: it rejects it (NVFORTRAN-F-1243-GPU
!   target doesn't support 'if' clauses for managing
!   parallel region.); the check's other witness, the AFAR flang front end, is the compiler under
!   test and is not counted; no gfortran or gcc is a legality witness.
program fuzz_prog
  use omp_lib, only: omp_get_default_device, omp_is_initial_device
  implicit none
  integer, parameter :: n = 200, m = 8
  type :: rec_t
  end type rec_t
  type(rec_t) :: dr
  integer :: i, j, r3a, hf3
  logical :: lpar
  integer(8) :: cs
  r3a = 31
  hf3 = 0
  lpar = .false.
  ! fuzz: kernels
  !$omp target map(tofrom: hf3) map(tofrom: r3a)
    hf3 = merge(1, 0, omp_is_initial_device())
    !$omp parallel if(parallel: lpar)
      !$omp loop reduction(+: r3a)
      do i = 1, n
        do j = m, 1, -1
          r3a = r3a + 11
        end do
      end do
      !$omp end loop
    !$omp end parallel
  !$omp end target
  ! fuzz: checksum
  cs = 0
  cs = modulo(cs * 31_8 + int(r3a, 8), 2147483629_8)
  print '(a,i0,a,i0)', 'RESULT checksum=', cs, ' ran_on_host=', max(hf3, 0)
end program fuzz_prog
! site:
! title: amdflang: loop reduction inside parallel if(.false.) in a target region counts the contribution more than once
! control: ../vendor/checks/src/fuzz/control/fuzz-b2-68-afar-control.f90 lpar = .true. (the parallel region is active)
! end site
! spec (requirement): a parallel region whose if clause evaluates to false is executed by a team of one thread, and a reduction
!   on the loop construct bound to it combines the threads' private copies with the original value once.
! "if (IfClauseValue = false) then number of threads = 1;" (5.2 §10.1.1 p.226 l.27-28)
! "At the end of a region that corresponds to a construct for which the reduction clause was specified, the original list item
!   is updated by combining its original value with the final value of each of the private copies, using the combiner of the
!   specified reduction-identifier." (5.2 §5.5.8 p.135 l.7-10)
! spec (this program): parallel if(parallel: lpar) with lpar false (one thread) around loop reduction(+: r3a) in a target region
!   adds each of the 1600 contributions once (r3a = 31 + 1600 * 11); AFAR counts the contributions four times (checksum 70431
!   instead of 17631), and is correct with lpar true.
