! scope: host+device: multi-threaded offload (host threads each offload their part of an array)
! Host+device pattern (found while making the multi-threaded
! offload programs conforming): b is mapped whole by target enter data and
! written on the device; then four host threads (parallel do,
! num_threads(4)) each copy their quarter back with
! target update from(b(lo:hi)). The sections are disjoint and present
! (5.2 §5.9.2: each list item is updated from its corresponding list
! item), so every element comes back. Expected: bad= 0.
! Observed (tuolumne, MI300A, 2026-10-21, 5 runs each, -O2,
! OMP_TARGET_OFFLOAD=mandatory), at HSA_XNACK=0 only (correct at 1):
! - CCE 19.0.0, 20.0.2, 21.0.3: bad= 64 on every run: no update inside the
!   parallel region moves data; the same with num_threads(1) and with
!   fixed-size arrays. Without the parallel region the updates work. A
!   program with target update to(a(lo:hi)) in the parallel region and b
!   copied back by target exit data fails the same way (bad= 64), so the
!   to direction is affected as well.
! - AFAR 24.0.0git: bad= 16 in 3 of 5 runs (one quarter lost); correct
!   with num_threads(1) and with fixed-size arrays (concurrent updates of
!   disjoint sections of one allocatable).
! AFAR: amdflang -fopenmp --offload-arch=gfx942 -O2
! CCE:  ftn -fopenmp -O2 (module load cce/<v> craype-accel-amd-gfx942 rocm)
! Run:  OMP_TARGET_OFFLOAD=mandatory HSA_XNACK=0 ./a.out
program p
  implicit none
  integer, parameter :: n = 64
  integer, allocatable :: b(:)
  integer :: i, c, lo, hi, bad
  allocate(b(n))
  b = 0
  !$omp target enter data map(to: b)
  !$omp target
    do i = 1, n
      b(i) = 2*i + 1
    end do
  !$omp end target
  !$omp parallel do num_threads(4) private(lo, hi)
  do c = 1, 4
    lo = (c - 1)*16 + 1
    hi = c*16
    !$omp target update from(b(lo:hi))
  end do
  !$omp end parallel do
  !$omp target exit data map(release: b)
  bad = count(b /= [(2*i + 1, i = 1, n)])
  print *, 'bad=', bad
end program p
! site:
! title: ftn: target update from(b(lo:hi)) inside a host parallel region moves no data in copy mode (HSA_XNACK=0)
! control: ../vendor/checks/src/other/control/target-update-sections-in-parallel-control.f90 the parallel do directive removed
! + (the four
! + updates
! + run one after another)
! end site
