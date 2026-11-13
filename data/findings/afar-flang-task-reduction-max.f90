program p
  implicit none
  integer :: r, i
  r = 0
  !$omp taskgroup task_reduction(max: r)
    !$omp target in_reduction(max: r)
      do i = 1, 10
        r = max(r, i)
      end do
    !$omp end target
  !$omp end taskgroup
  print *, 'r =', r
end program p
! site:
! title: amdflang: task_reduction(max: r) / in_reduction(max: r) rejected ("Internal: no symbol found for 'max'")
! control: ../vendor/checks/src/afar/control/afar-flang-task-reduction-max-control.f90 the reduction identifier + instead of max
! + (r = r + i)
! end site
! spec (requirement): In Fortran the intrinsic procedure names max and min are OpenMP reduction identifiers, usable
!   wherever a reduction identifier is.
! "following intrinsic procedure names: max, min, iand, ior, ieor." (5.2 §5.5.1 p.124 l.24)
! spec (requirement): The task_reduction clause on a taskgroup specifies a reduction among tasks.
! "The task_reduction clause is a reduction scoping clause, as described in Section 5.5.6, that specifies a reduction
!   among tasks." (5.2 §5.5.9 p.137 l.14-15)
! spec (requirement): An in_reduction clause makes a task a participant in a task reduction defined by an enclosing
!   task_reduction clause with the same reduction identifier.
! "defines a task to be a participant in a task reduction that is defined by an enclosing region for a matching list
!   item that appears in a task_reduction clause" (5.2 §5.5.10 p.138 l.11-13)
! spec (this program): task_reduction(max: r) on a taskgroup and in_reduction(max: r) on the enclosed target use the
!   intrinsic max as reduction identifier for an integer; amdflang rejects both clauses with Internal: no symbol found
!   for max.
