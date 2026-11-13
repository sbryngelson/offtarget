program p
  implicit none
  integer :: a(10), i
  a = 0
  !$omp target parallel do thread_limit(8) map(from: a)
  do i = 1, 10
    a(i) = i
  end do
  print *, 'a(3) =', a(3)
end program p
! site:
! title: amdflang: thread_limit on target parallel do rejected
! control: ../vendor/checks/src/afar/control/afar-flang-thread-limit-target-parallel-do-control.f90 thread_limit(8) removed
! end site
! spec (requirement): The thread_limit clause is permitted on the target construct.
! "in_reduction, is_device_ptr, map, nowait, private, thread_limit," (5.2 §13.8 p.284 l.5)
! spec (requirement): On a combined construct the thread_limit clause applies to every leaf construct that permits it,
!   so it is accepted on target parallel do and takes effect on the target leaf.
! "The effect of the shared, default, thread_limit, or order clause is as if it is applied to all leaf constructs that
!   permit the clause." (5.2 §17.2 p.340 l.31-32)
! spec (this program): thread_limit(8) on target parallel do is applied to the target leaf construct, which permits
!   the clause; amdflang rejects the clause on the combined construct.
