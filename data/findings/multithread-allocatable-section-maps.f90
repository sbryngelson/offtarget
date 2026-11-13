! scope: host+device: multi-threaded offload (host threads each offload their part of an array)
! Host+device pattern (minimized and re-verified): two
! host threads (parallel do, num_threads(2)) each offload one half of an
! allocatable array b with map(to: a(lo:hi)) map(from: b(lo:hi)).
!
! Conformance (OpenMP 5.2). The target region references b (and a), so b
! also has an implicit data-mapping attribute (5.2 §5.8.1, p.148:
! "References to structure elements or array elements are treated as
! references to the structure or array, respectively, for the purposes of
! determining implicit data-mapping or data-sharing attributes"). When the
! other thread's half is not yet on the device, 5.2 §5.8.3 p.154: "If a
! list item with an implicit data-mapping attribute does not have any
! corresponding storage in the device data environment prior to a task
! encountering the construct associated with the map clause, and one or
! more contiguous parts of the original storage are either list items or
! base pointers to list items that are explicitly mapped on the
! construct, only those parts of the original storage will have
! corresponding storage in the device data environment as a result of the
! map clauses on the construct." When it is, p.154: "If a single
! contiguous part of the original storage of a list item with an implicit
! data-mapping attribute has corresponding storage in the device data
! environment prior to a task encountering the construct on which the map
! clause appears, only that part of the original storage will have
! corresponding storage in the device data environment as a result of the
! map clause." Each explicit half is a distinct mappable storage block
! (p.152: "The storage for each other map clause list item becomes a
! distinct mappable storage block") that no earlier construct created, so
! no restriction of p.156 applies ("If any part of the original storage
! of a list item with an explicit data-mapping attribute has corresponding
! storage ... all of the original storage must have corresponding
! storage": no part of the other half is mapped). Every interleaving is
! defined and every half comes back. Expected: bad= 0.
!
! With three or more threads (the program: four quarters) the
! program is NOT conforming: when a construct is encountered while the
! sections of two other threads are present, p.156: "If an array appears
! as a list item in a map clause, multiple parts of the array have
! corresponding storage in the device data environment prior to a task
! encountering the construct associated with the map clause, and the
! corresponding storage for those parts was created by maps from more
! than one earlier construct, the behavior is unspecified." (5.1 §2.21.7.1
! p.354 has the same sentence; 6.0 §7.9.6 p.287 makes it a restriction:
! "If a list item in a map clause has corresponding storage in the device
! data environment, all corresponding storage must correspond to a single
! mappable storage block that was previously mapped", which this
! two-thread program also violates under 6.0 when the constructs overlap.)
! The catalog's multi-threaded programs now map the arrays whole once.
!
! Observed (tuolumne, MI300A, 2026-10-21, 5 runs each, -O2,
! OMP_TARGET_OFFLOAD=mandatory): AFAR 24.0.0git bad= 32 at HSA_XNACK=0
! (correct at 1, zero-copy); CCE 19.0.0, 20.0.2, 21.0.3 bad= 32 at both.
! Correct on every toolchain with num_threads(1) and with fixed-size
! arrays (integer :: a(n), b(n)). With target nowait: AFAR bad= 32 at
! HSA_XNACK=0; CCE 19 intermittently bad= 32 or aborts (hipFree returned
! hipErrorInvalidValue), CCE 21 aborts at HSA_XNACK=1 (Present_table::
! release failed).
! AFAR: amdflang -fopenmp --offload-arch=gfx942 -O2
! CCE:  ftn -fopenmp -O2 (module load cce/<v> craype-accel-amd-gfx942 rocm)
! Run:  OMP_TARGET_OFFLOAD=mandatory HSA_XNACK=0 ./a.out
program p
  implicit none
  integer, parameter :: n = 64
  integer, allocatable :: a(:), b(:)
  integer :: i, c, lo, hi, bad
  allocate(a(n), b(n))
  do i = 1, n
    a(i) = i
    b(i) = 0
  end do
  !$omp parallel do num_threads(2) private(lo, hi)
  do c = 1, 2
    lo = (c - 1)*32 + 1
    hi = c*32
    !$omp target map(to: a(lo:hi)) map(from: b(lo:hi))
      do i = lo, hi
        b(i) = 2*a(i) + 1
      end do
    !$omp end target
  end do
  !$omp end parallel do
  bad = 0
  do i = 1, n
    if (b(i) /= 2*i + 1) bad = bad + 1
  end do
  print *, 'bad=', bad
end program p
! site:
! title: ftn: two host threads mapping disjoint halves of an allocatable array lose one half
! control: ../vendor/checks/src/other/control/multithread-allocatable-section-maps-control.f90 num_threads(1) instead of
! + num_threads(2)
! end site
