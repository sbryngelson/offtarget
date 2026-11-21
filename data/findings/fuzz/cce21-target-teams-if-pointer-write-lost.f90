! # Finding (CCE 21): CCE 21 ftn: the writes of a target teams region with an if clause whose condition is true to a pointer array
!   never reach the host (the array stays 0)
!
! - toolchains and modes that fail: cce21 (CCE 21.0.3), cce21_4 (CCE 21.0.4); modes: unified, copy; -O2
! - build: ftn -fopenmp -O2
! - failure: wrong_answer (check=fail)
! - observed: `checksum= 0` with `check=fail`; identical signature on 4 of 4 failing cells
! - expected: compiles and prints `checksum= 1099183000` with `check=pass`
! - rule: o2 is not a scalar, so "it is treated as if it had appeared in a map clause with a map-type of tofrom" (OpenMP 5.2 §5.8.1
!   p.149 l.4-5); it is an associated pointer, and "If a list item in a map clause is an associated pointer and the pointer is not
!   the base pointer of another list item in a map clause on the same construct, then it is treated as if its pointer target is
!   implicitly mapped in the same clause" (OpenMP 5.2 §5.8.3 p.152 l.1-3), so the array o2 points to is mapped tofrom and copied
!   back at the end of the region; lt is .true., and only "When an if clause is present and the if clause expression evaluates to
!   false, the effect is as if a device clause that specifies omp_initial_device as the device number is present" (OpenMP 5.2 §13.8
!   p.284 l.31-32), so the region runs on the device
! - same-compiler control: controls/cce21-target-teams-if-pointer-write-lost-no-if-control.f90 (one change from this file: no if
!   clause; correct on cce21 (CCE 21.0.3), cce21_4 (CCE 21.0.4); site rows, check case
!   site-fuzz--cce21-target-teams-if-pointer-write-lost)
! - other families: afar (AFAR 24.3.0), afar244 (AFAR 24.4.0), cce19 (CCE 19.0.0), cce20 (CCE 20.0.2), gcc (GCC 16.2.0) run the file
!   correctly (site rows, check case site-fuzz--cce21-target-teams-if-pointer-write-lost)
! - legality: legal by reading: the loop construct, closely nested in the teams region, writes each o2(i) once with t2 private, so
!   there is no data race; o2 is an associated pointer (allocate) mapped implicitly tofrom, and hf1 is written only by thread 0 of
!   the first target region and mapped tofrom. The rules witness and AMD flang's front end accept the file and its control
!   (offload.engine.prerun.check on Tuolumne, 2026-11-21). Reduced from fuzz program def1 seed 7003 (generator fuzz-6), which CCE 19
!   and 20 run correctly and CCE 21 does not
! - releases: CCE 19.0.0 and 20.0.2 run it correctly; CCE 21.0.3 and 21.0.4 fail it the same way
program fuzz_prog
  use omp_lib, only: omp_get_thread_num, omp_is_initial_device
  implicit none
  integer, parameter :: n = 24, m = 5
  integer, pointer :: o2(:)
  real(8), pointer :: o1(:)
  integer :: i, j, hf1, t2
  logical :: lt
  integer(8) :: cs
  allocate(o1(n))
  allocate(o2(n))
  o1 = 0
  o2 = 0
  hf1 = 0
  lt = .true.
  ! fuzz: kernels
  !$omp target map(tofrom: hf1)
    if (omp_get_thread_num() == 0) hf1 = merge(1, 0, omp_is_initial_device())
  !$omp end target
  !$omp taskwait
  do i = 1, n
  end do
  !$omp target teams if(lt)
    do i = 1, n
      t2 = 0
      o2(i) = 255
    end do
  !$omp end target teams
  ! fuzz: checksum
  cs = 0
  do i = 1, n
    cs = modulo(cs * 31_8 + int(o1(i) * 64, 8), 2147483629_8)
  end do
  do i = 1, n
    cs = modulo(cs * 31_8 + int(o2(i), 8), 2147483629_8)
  end do
  print '(a,i0)', 'checksum= ', cs
  print '(a,i0,a,a)', 'RESULT ran_on_host=', max(hf1, 0), ' check=', merge('pass', 'fail', cs == &
      & 1099183000_8)
end program fuzz_prog

! site:
! title: CCE 21: target teams if(true) loses its pointer-array writes
! summary: CCE 21.0.3 and 21.0.4 lose a target teams region's writes to a pointer array when the construct has an if clause, even a
! + true one; without the if clause, and on CCE 19 and 20, the writes reach the host.
! control: fuzz/controls/cce21-target-teams-if-pointer-write-lost-no-if-control.f90 one change from the finding; correct on
! + cce21, cce21_4
! end site
