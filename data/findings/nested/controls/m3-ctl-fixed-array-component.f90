! control: a fixed-size array component
program t
  use omp_lib
  implicit none
  type :: n0
    integer :: a(8)
  end type n0
  type(n0), pointer :: r
  integer :: q, hf, tot
  logical :: ok
  hf = 1
  !$omp target map(from: hf)
  hf = merge(1, 0, omp_is_initial_device())
  !$omp end target
  allocate(r)
  do q = 1, 8
    r%a(q) = 100 + q - 1
  end do
  tot = 0
  !$omp target enter data map(to: r)
  !$omp target teams distribute parallel do reduction(+: tot)
  do q = 1, 8
    tot = tot + r%a(q)
    r%a(q) = r%a(q) + 7
  end do
  !$omp end target teams distribute parallel do
  !$omp target exit data map(from: r)
  ok = tot == 828 .and. sum(r%a) == 884
  print '(a,i0)', 'tot= ', tot
  print '(a,i0)', 'sum= ', sum(r%a)
  print '(a,i0,a,a)', 'RESULT ran_on_host=', hf, ' check=', merge('pass', 'fail', ok)
end program t
