! control: enter data map(to: r) in place of map(alloc: r) and the update
program t
  use omp_lib
  implicit none
  type :: n1
    integer :: s = 0
  end type n1
  type :: n0
    integer :: s = 0
    integer :: a(8) = 0
    type(n1), allocatable :: nx
  end type n0
  type(n0), pointer :: r
  integer :: q, hf, tot
  logical :: ok
  hf = 1
  !$omp target map(from: hf)
  hf = merge(1, 0, omp_is_initial_device())
  !$omp end target
  allocate(r)
  allocate(r%nx)
  do q = 1, 8
    r%a(q) = 100 + q - 1
  end do
  r%nx%s = 21
  tot = 0
  !$omp target enter data map(to: r)
  !$omp target teams distribute parallel do reduction(+: tot)
  do q = 1, 8
    tot = tot + r%a(q) + r%nx%s
  end do
  !$omp end target teams distribute parallel do
  !$omp target exit data map(delete: r)
  ok = tot == 996
  print '(a,i0)', 'tot= ', tot
  print '(a,i0,a,a)', 'RESULT ran_on_host=', hf, ' check=', merge('pass', 'fail', ok)
end program t
