! probe: target update of a strided array section, legal since
! OpenMP 5.0 ("The target update construct (see Section 13.9) was modified
! to allow array sections that specify discontiguous storage", 5.2 §B.4
! p.634); the map clause keeps its contiguity restriction (5.2 §5.8.3
! p.156), the motion clauses have none. The odd elements are updated on
! the device, the region doubles every element, the host copies back;
! the odd elements are 2 * i in both memory modes.
! expected: check=pass
program p
  implicit none
  integer, parameter :: n = 16
  integer :: a(n), i
  logical :: ok
  a = 0
  !$omp target enter data map(to: a)
  do i = 1, n
    a(i) = i
  end do
  !$omp target update to(a(1:n:2))
  !$omp target
  do i = 1, n
    a(i) = 2 * a(i)
  end do
  !$omp end target
  !$omp target exit data map(from: a)
  ok = .true.
  do i = 1, n
    ! the even elements are 0 with separate memory and 2 * i with
    ! shared memory: only the updated ones are checked
    if (mod(i, 2) == 1) ok = ok .and. a(i) == 2 * i
  end do
  if (ok) then
    print '(a)', 'RESULT check=pass'
  else
    print '(a)', 'RESULT check=fail'
  end if
end program p
