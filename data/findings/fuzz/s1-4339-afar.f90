! Finding: AFAR at HSA_XNACK=1 aborts (SIGABRT; in
! the campaign "OFFLOAD ERROR: memory access fault by GPU ... Write access
! to a read-only page") on a target construct with map(close, tofrom: ia)
! for an allocatable dummy ia that the region does not even reference,
! while the region reads another assumed-shape dummy (dsi, implicitly
! mapped tofrom). AFAR at HSA_XNACK=0 and CCE 19/20/21 in both modes print
! "RESULT check=pass".
!
! Legal OpenMP 5.2: close is a map-type modifier that is a hint ("The close
! map-type-modifier is a hint to the runtime to allocate memory close to
! the target device", 5.2 §5.8.3 p.155 l.12); an
! assumed-shape dummy referenced in the region is mapped tofrom implicitly
! (5.2 §5.8.1).
!
! Observed (tuolumne, MI300A, -O2, 2026-10-23, results/t28_probe/close/
! c4339_*.f90.*.json): this program (c4339_c) aborts on AFAR at
! HSA_XNACK=1 on every run and passes at HSA_XNACK=0; without close
! (c4339_b) it passes; with an explicit-shape ia (c4339_d) it passes; with
! the region reading ia instead of the other dummy (c4339_e) it passes; the
! derived-type dummy of the reduction (c4339_a) aborts the same way. The
! close + present abort of fuzz/158-afar.f90 is another symptom of AFAR's
! close handling at HSA_XNACK=1 (no present modifier here).
! From s1 seed 4339 (the smallest program of the s1 group "AFAR memory
! access fault", 59 compiler_bug cells): tools/campaigns/fuzz.py minimize-one,
! 141 -> 91 lines (data/evidence/dataenv_probe/rt/4339-afar.f90), then by hand.
! Expected: "RESULT check=pass".
!
! amdflang -fopenmp --offload-arch=gfx942 -O2 (afar recipe, offload/engine/toolchains.py)
module mm
  implicit none
  integer, parameter :: n = 128
  type :: el_t
    integer :: u
  end type el_t
contains
  subroutine kp1(ia, o1, dsi)
    integer, allocatable, intent(inout) :: ia(:)
    integer, intent(inout) :: o1(:)
    integer, intent(in) :: dsi(:)
    integer :: i
    !$omp target map(close, tofrom: ia) map(tofrom: o1)
      do i = 1, n
        o1(i) = dsi(i)
      end do
    !$omp end target
  end subroutine kp1
end module mm
program p
  use mm
  implicit none
  type(el_t) :: ds(n)
  integer :: dsi(n)
  integer, allocatable :: ia(:)
  integer, pointer :: o1(:)
  integer :: i
  logical :: ok
  allocate(ia(n))
  ia = 1
  allocate(o1(n))
  do i = 1, n
    dsi(i) = mod(i * 26 + 31, 97) - 21
  end do
  o1 = 0
  call kp1(ia, o1, dsi)
  ok = .true.
  do i = 1, n
    ok = ok .and. o1(i) == mod(i * 26 + 31, 97) - 21
  end do
  if (ok) then
    print '(a)', 'RESULT check=pass'
  else
    print '(a)', 'RESULT check=fail'
  end if
end program p
! site:
! title: AFAR offload runtime at HSA_XNACK=1: map(close, ...) breaks presence lookup and device access (abort, memory fault)
! control: ../vendor/checks/src/other/control/s1-4339-afar-control.f90 map(tofrom: ia) without the close modifier
! same_as: fuzz/s1-9443-afar
! end site
