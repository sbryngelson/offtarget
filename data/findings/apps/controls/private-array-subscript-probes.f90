! Docs/findings/apps/cce21-private-array-loaded-subscript-wrong.f90: PROBES. z1: private v, subscript from a
! mapped array; z2: mapped w, subscript from a declare target array; z3: private v, subscript copied from the declare
! target array to a private scalar; z4: private v in a target region without a loop construct. Expected z1= 50 z2= 50
! z3= 30 z4= 50 (each of 4). AFAR, CCE 19/20 (MI300A both modes): as expected. CCE 21: z1= 20, z3= 10 (wrong), z2= 50,
! z4= 50 (correct).
module g7
  implicit none
  integer :: d(3)
  !$omp declare target (d)
end module g7
program dt7
  use g7
  implicit none
  integer :: z1(4), z2(4), z3(4), z4(4), r, k
  integer :: v(3), s(3), w(3)
  d = [1, 2, 3]
  s = [1, 2, 3]
  w = [10, 20, 30]
  !$omp target update to(d)
  z1 = -1; z2 = -1; z3 = -1; z4 = -1
  ! 1: private v, subscript from a mapped (not declare target) array
  !$omp target parallel do map(from: z1) map(to: s) private(v)
  do r = 1, 4
    v = [10, 20, 30]
    z1(r) = v(s(2)) + v(s(3))
  end do
  ! 2: mapped (shared) w, subscript from the declare target array
  !$omp target parallel do map(from: z2) map(to: w)
  do r = 1, 4
    z2(r) = w(d(2)) + w(d(3))
  end do
  ! 3: private v, the declare target element first copied to a local scalar
  !$omp target parallel do map(from: z3) private(v, k)
  do r = 1, 4
    v = [10, 20, 30]
    k = d(3)
    z3(r) = v(k)
  end do
  ! 4: private v, declare target subscript, in a target region without parallel do
  !$omp target map(from: z4) private(v)
    v = [10, 20, 30]
    z4 = v(d(2)) + v(d(3))
  !$omp end target
  print '(a,4i4,a,4i4,a,4i4,a,4i4)', 'z1=', z1, ' z2=', z2, ' z3=', z3, ' z4=', z4
end program dt7
