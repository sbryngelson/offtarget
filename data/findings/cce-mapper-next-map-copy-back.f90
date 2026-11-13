! (copy mode for the whole catalog): CCE 19 and 20 lose the
! copy-back of the map list item that FOLLOWS a map clause with a mapper
! modifier, at HSA_XNACK=0 only (separate host and device memory).
! s is mapped through the user-defined mapper mm (map(to: q%v)); the
! final map type is to (5.2 §5.8.8 p.163, Table 5.3: mapper to, clause
! tofrom -> to), so s%v keeps its host value 1 in copy mode. host_flag is
! map(tofrom:) and is set to 0 on the device; it must come back (5.2 §5.8.3
! p.151: "the map-type is replaced with a final map type ... according to
! the rules of map-type decay" applies to the mapper's list item only).
! Expected (copy mode): host_flag= 0  b1= 3  sv= 1
! Observed (tuolumne, MI300A, 2026-10-22, 3 runs each, -O2,
! OMP_TARGET_OFFLOAD=mandatory):
! - CCE 19.0.0, 20.0.2 at HSA_XNACK=0: host_flag= 1  b1= 3  sv= 1 on every
!   run: the region ran on the device (b came back, s%v was not copied
!   back) but host_flag's copy-back is lost. With the host_flag clause
!   BEFORE the mapper clause, host_flag= 0 (correct); without the mapper
!   modifier correct. At HSA_XNACK=1 correct (host_flag= 0, sv= 7).
! - CCE 21.0.3 and AFAR 24.0.0git: correct in both modes.
! The catalog's map.mapper programs (5.0, 5.2) put host_flag after the
! mapper clause, so CCE 19/20 report them as "fell back to host"
! (ran_on_host=1) at HSA_XNACK=0.
! AFAR: amdflang -fopenmp --offload-arch=gfx942 -O2
! CCE:  ftn -fopenmp -O2 (module load cce/<v> craype-accel-amd-gfx942 rocm)
! Run:  OMP_TARGET_OFFLOAD=mandatory HSA_XNACK=0 ./a.out
program p
  use omp_lib, only: omp_is_initial_device
  implicit none
  type :: dt
    integer :: v
  end type dt
  !$omp declare mapper(mm: dt :: q) map(to: q%v)
  integer :: host_flag, b(4)
  type(dt) :: s
  s%v = 1
  host_flag = 1
  b = 0
  !$omp target map(from: b) map(mapper(mm), tofrom: s) map(tofrom: host_flag)
    host_flag = merge(1, 0, omp_is_initial_device())
    b = 2 + s%v
    s%v = 7
  !$omp end target
  print *, 'host_flag=', host_flag, ' b1=', b(1), ' sv=', s%v
end program p
! site:
! title: ftn in copy mode: the map list item after a map clause with a mapper modifier is not copied back
! control: ../vendor/checks/src/cce/control/cce-mapper-next-map-copy-back-control.f90 the map(tofrom: host_flag) clause written
! + before the mapper clause
! end site
