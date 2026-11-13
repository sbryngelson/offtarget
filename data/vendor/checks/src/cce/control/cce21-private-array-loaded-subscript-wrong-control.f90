module pas_m
  implicit none
  integer :: d(3)
  !$omp declare target (d)
end module pas_m
program private_array_loaded_subscript
  use pas_m
  implicit none
  integer, parameter :: n = 64
  integer :: zb(n), zc(n), zt(n), za(n), zd(n), zn(n), zw(n), v(3), w(3), s(3), k, r
  k = 3
  s = [1, 2, 3]
  d = [1, 2, 3]
  !$omp target update to(d)
  zb = -1; zc = -1; zt = -1; za = -1; zd = -1; zn = -1; zw = -1
  w = [10, 20, 30]
  !$omp target parallel do map(from: zb) map(to: s) private(v)
  do r = 1, n
    v(1) = 10; v(2) = 20; v(3) = 30
    zb(r) = v(3)
  end do
  !$omp target parallel do map(from: zc) private(v)
  do r = 1, n
    v(1) = 10; v(2) = 20; v(3) = 30
    zc(r) = v(d(3))
  end do
  !$omp target teams distribute parallel do map(from: zt) map(to: s) private(v)
  do r = 1, n
    v(1) = 10; v(2) = 20; v(3) = 30
    zt(r) = v(s(3))
  end do
  !$omp target parallel do map(from: za) private(v)
  do r = 1, n
    v(1) = 10; v(2) = 20; v(3) = 30
    za(r) = v(k)
  end do
  !$omp target parallel do map(from: zd) private(v)
  do r = 1, n
    v(1) = 10; v(2) = 20; v(3) = 30
    zd(r) = v(mod(r - 1, 3) + 1)
  end do
  !$omp target teams distribute map(from: zn) map(to: s) private(v)
  do r = 1, n
    v(1) = 10; v(2) = 20; v(3) = 30
    zn(r) = v(s(3))
  end do
  !$omp target parallel do map(from: zw) map(to: s, w)
  do r = 1, n
    zw(r) = w(s(3))
  end do
  print '(a,i0,a,i0,a,i0,a,i0)', 'bad: mapped-subscript ', count(zb /= 30), ' declare-target-subscript ', &
    count(zc /= 30), ' teams-distribute-parallel-do ', count(zt /= 30), ' teams-distribute ', count(zn /= 30)
  print '(a,i0,a,i0,a,i0)', 'control-bad: firstprivate-subscript ', count(za /= 30), ' computed-subscript ', &
    count([(zd(r) /= 10*(mod(r - 1, 3) + 1), r = 1, n)]), ' mapped-array ', count(zw /= 30)
end program private_array_loaded_subscript
