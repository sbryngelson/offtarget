program t
  use omp_lib, only: omp_get_thread_num
  implicit none
  integer, parameter :: n = 64
  integer, allocatable :: a(:), b(:)
  integer :: ref(n), i, nbad
  allocate(a(n), b(n))
  do i = 1, n
    a(i) = i; b(i) = 0; ref(i) = 2*i + 1
  end do
  !$omp target parallel map(to: a) map(from: b) 
    !$omp single
      do i = 1, n
        b(i) = 2*a(i) + 1
      end do
    !$omp end single
  !$omp end target parallel
  nbad = count(b /= ref)
  print *, 'single bad=', nbad
end program
! site:
! title: ftn/craycc: constructs documented as unsupported in offload regions (single, masked, task, ordered, scan) give internal
! + compiler errors or device link failures instead of a diagnostic
! control: ../vendor/checks/src/cce/control/cce19-target-parallel-single-ice-control.f90 the single construct replaced by a
! + worksharing do
! + construct
! end site
! spec (requirement): A single construct in a parallel region is executed by exactly one thread of the team, with an
!   implicit barrier at its end.
! "The single construct specifies that the associated structured block is executed by only one of the threads in the
!   team" (5.2 §11.1 p.241 l.2-3)
! spec (requirement): The implicit barrier at the end of a single region applies unless nowait is specified.
! "An implicit barrier occurs at the end of a single region if the nowait clause is not specified." (5.2 §11.1 p.241
!   l.5-6)
! spec (this program): The program uses single inside target parallel without nowait. The nesting rules of OpenMP 5.2
!   list no restriction against single in a target region, so the program is legal; the vendor documentation that
!   lists single as unsupported in offload regions is a statement outside the spec, and the compiler gives an internal
!   error or link failure instead of a diagnostic.
