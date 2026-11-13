! control: the pointed-to type has no allocatable component
program t
  use omp_lib
  implicit none
  type :: n2
    integer :: s = 0
  end type n2
  type :: n1
    integer :: s = 0
    type(n2) :: nx
  end type n1
  type :: n0
    integer :: s = 0
    integer :: a(8) = 0
    type(n1), pointer :: nx => null()
  end type n0
  type(n0) :: r
  integer :: q, hf, ha, hs
  logical :: ok
  hf = 1
  !$omp target map(from: hf)
  hf = merge(1, 0, omp_is_initial_device())
  !$omp end target

  r%s = -1
  do q = 1, 8
    r%a(q) = -1
  end do
  !$omp target enter data map(alloc: r)
  !$omp target
  do q = 1, 8
    r%a(q) = 500 + q - 1
  end do
  r%s = 900
  !$omp end target
  !$omp target exit data map(from: r)
  ha = sum(r%a)
  hs = r%s
  ok = ha == 4028 .and. hs == 900
  print '(a,i0)', 'ha= ', ha
  print '(a,i0,a,a)', 'RESULT ran_on_host=', hf, ' check=', merge('pass', 'fail', ok)
end program t
