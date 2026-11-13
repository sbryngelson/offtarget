! control: the allocatable array in the variable, the pointer component holds a fixed array too
program t
  use omp_lib
  implicit none
  type :: n1
    integer :: s = 0
  end type n1
  type :: n0
    integer :: v = 0
    integer, allocatable :: a(:)
    type(n1), pointer :: nx => null()
  end type n0
  type(n0) :: r
  integer :: q, hf, tot
  logical :: ok
  hf = 1
  !$omp target map(from: hf)
  hf = merge(1, 0, omp_is_initial_device())
  !$omp end target
  allocate(r%nx)
  allocate(r%a(8))
  do q = 1, 8
    r%a(q) = 200 + q - 1
  end do
  tot = 0
  !$omp target enter data map(to: r)
  !$omp target enter data map(to: r%nx)
  !$omp target teams distribute parallel do reduction(+: tot)
  do q = 1, 8
    tot = tot + r%a(q)
  end do
  !$omp end target teams distribute parallel do
  !$omp target exit data map(release: r%nx)
  !$omp target exit data map(release: r)
  ok = tot == 1628
  print '(a,i0)', 'tot= ', tot
  print '(a,i0,a,a)', 'RESULT ran_on_host=', hf, ' check=', merge('pass', 'fail', ok)
end program t
