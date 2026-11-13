! CCE 21: with a defaultmap clause on a target construct, the scalar x named
! in map(tofrom: x) is not copied back (a correction: the header
! this file did not have).
! Spec: x is explicitly mapped tofrom, which defaultmap does not change
! ("The defaultmap clause determines the implicit data-mapping or
! data-sharing attribute of certain variables that are referenced in a
! target construct", 5.2 §5.8.7 p.161 l.14-16), and on exit the original is
! updated "if the map-type is from or tofrom" (5.2 §5.8.3 p.154 l.2-5).
! Expected: A 0, B 0, C 0 (x = 0 from omp_is_initial_device() on the device).
! Observed: CCE 21.0.3 and 21.0.4: A 1, B 0, C 1, at HSA_XNACK 0 and 1, -O0
! and -O2. The region runs on the device: CRAY_ACC_DEBUG shows the kernel,
! and an array flag mapped from in the same region comes back 0 (vendor
! case cce21-defaultmap-device-probe); what is lost is the copy-back of x.
! Control: region B, the same construct without defaultmap: 0. CCE 19.0.0
! and 20.0.2: all zeros. The catalog's defaultmap programs read their
! ran_on_host flag through such a map(tofrom) scalar, so on CCE 21 they
! read ran_on_host=1 although they ran on the device (decided as this wrong
! answer: catalog/rulings.yaml RUL-MAPPED-FLAG-NOT-COPIED-BACK).
! CCE: ftn -fopenmp -O2 (module load cce/21.0.4 craype-accel-amd-gfx942
!      rocm/7.2.0; module unload cray-mpich)
program h
  use omp_lib
  implicit none
  integer :: x, i
  integer, allocatable :: a(:)
  allocate(a(8)); a=1
  x=1
  !$omp target map(tofrom:x) map(to:a) defaultmap(to: aggregate)
  x = merge(1,0,omp_is_initial_device())
  !$omp end target
  print *, 'A', x
  x=1
  !$omp target map(tofrom:x) map(to:a)
  x = merge(1,0,omp_is_initial_device())
  !$omp end target
  print *, 'B', x
  x=1
  !$omp target map(tofrom:x) map(to:a) defaultmap(to: aggregate)
  x = merge(1,0,omp_is_initial_device())
  do i=1,8
    a(i)=2
  end do
  !$omp end target
  print *, 'C', x
end
! site:
! title: ftn: with a defaultmap clause on target, an explicitly mapped map(tofrom) scalar is not copied back, and with
! + defaultmap(tofrom) an array in map(alloc) or map(to) is copied back
! control: ../vendor/checks/src/cce/control/cce21-defaultmap-aggregate-flag-control.f90 defaultmap(to: aggregate) removed from
! + regions A
! + and C
! end site
