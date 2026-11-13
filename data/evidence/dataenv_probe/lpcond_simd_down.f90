! probe: lastprivate(conditional:) on target simd, a loop with a
! negative step. The value at the end is the one assigned in the
! sequentially last iteration that assigns it (5.2 §5.4.5 p.115): the
! loop runs i = n, n-1, ..., 1, so the last assigning iteration is the
! smallest i with mod(i, 4) == 1, i = 1: lp = v(1).
! expected: check=pass
program p
  use omp_lib
  implicit none
  integer, parameter :: n = 64
  integer :: v(n), lp, i, want
  do i = 1, n
    v(i) = 100 + i
  end do
  want = -1
  do i = n, 1, -1
    if (mod(i, 4) == 1) want = v(i)
  end do
  lp = 0
  !$omp target simd map(to: v) lastprivate(conditional: lp)
  do i = n, 1, -1
    if (mod(i, 4) == 1) lp = v(i)
  end do
  !$omp end target simd
  if (lp == want) then
    print '(a)', 'RESULT check=pass'
  else
    print '(a,i0,a,i0)', 'RESULT check=fail lp=', lp, ' want=', want
  end if
end program p
