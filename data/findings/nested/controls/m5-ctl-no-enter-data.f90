! control: no enter/exit data, the map clause on the construct
program t
  use omp_lib
  implicit none
  type :: n0
    integer, allocatable :: a(:)
  end type n0
  type(n0), pointer :: r
  integer :: q, hf, tot
  logical :: ok
  hf = 1
  !$omp target map(from: hf)
  hf = merge(1, 0, omp_is_initial_device())
  !$omp end target
  allocate(r)
  allocate(r%a(8))
  do q = 1, 8
    r%a(q) = 100 + q - 1
  end do
  tot = 0

  !$omp target teams distribute parallel do reduction(+: tot) map(tofrom: r)
  do q = 1, 8
    tot = tot + r%a(q)
    r%a(q) = r%a(q) + 7
  end do
  !$omp end target teams distribute parallel do

  ok = tot == 828 .and. sum(r%a) == 884
  print '(a,i0)', 'tot= ', tot
  print '(a,i0)', 'sum= ', sum(r%a)
  print '(a,i0,a,a)', 'RESULT ran_on_host=', hf, ' check=', merge('pass', 'fail', ok)
end program t
