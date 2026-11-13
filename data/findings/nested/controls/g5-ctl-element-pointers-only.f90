! control: the element pointers only
program t
  use omp_lib
  implicit none
  type :: n1
    integer, pointer :: a(:) => null()
  end type n1
  type :: n0
    integer, pointer :: a(:) => null()
    type(n1), allocatable :: nx(:)
  end type n0
  type(n0) :: r
  integer :: q, hf, tot
  logical :: ok
  hf = 1
  !$omp target map(from: hf)
  hf = merge(1, 0, omp_is_initial_device())
  !$omp end target
  allocate(r%nx(2))
  allocate(r%a(4))
  allocate(r%nx(1)%a(4))
  allocate(r%nx(2)%a(4))
  r%a = 1
  r%nx(1)%a = 2
  r%nx(2)%a = 3
  !$omp target enter data map(to: r)
  !$omp target enter data map(to: r%nx(1)%a) map(to: r%nx(2)%a)
  !$omp target map(tofrom: tot)
    tot = sum(r%nx(1)%a) + sum(r%nx(2)%a)
  !$omp end target
  !$omp target exit data map(release: r%nx(1)%a) map(release: r%nx(2)%a)
  !$omp target exit data map(release: r)
  ok = tot == 20
  print '(a,i0)', 'tot= ', tot
  print '(a,i0,a,a)', 'RESULT ran_on_host=', hf, ' check=', merge('pass', 'fail', ok)
end program t
