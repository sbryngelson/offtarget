program p
  implicit none
  integer :: a(10), i, p1
  p1 = 3
  !$omp target firstprivate(p1) map(from: a)
    do i = 1, 10
      a(i) = p1
    end do
  !$omp end target
  !$omp target map(to: p1) map(tofrom: a)
    do i = 1, 10
      a(i) = a(i) + p1
    end do
  !$omp end target
  print *, 'a(3) =', a(3)
end program p
! site:
! title: amdflang: firstprivate(p1) on one target and map(to: p1) on a later target rejected as if on the same construct
! control: ../vendor/checks/src/afar/control/afar-flang-firstprivate-map-two-targets-control.f90 map(to: p1) instead of
! + firstprivate(p1)
! + on the
! + first target
! end site
! spec (requirement): The data environment of each target task is created from the data-sharing and data-mapping
!   clauses on that one target construct, so clauses on different target constructs do not interact.
! "The data environment of the target task is created according to the data-sharing and data-mapping attribute clauses
!   on the target construct" (5.2 §13.8 p.284 l.19-21)
! spec (requirement): A firstprivate list item on a target construct is initialized from the original list item that
!   exists before that construct.
! "In addition, the new list item is initialized from the original list item that exists before the construct." (5.2
!   §5.4.4 p.112 l.11-12)
! spec (this program): p1 is firstprivate on the first target construct and appears in map(to:) only on the second,
!   separate target construct, so no list item has two attributes on one construct; amdflang rejects the second target
!   as if both clauses were on the same construct.
