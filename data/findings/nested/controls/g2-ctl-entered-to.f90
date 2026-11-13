! control: entered with to
program t
  use omp_lib
  implicit none
  type :: n0
    integer :: s = 0
    integer, pointer :: a(:) => null()
  end type n0
  type(n0) :: r
  integer :: q, hf, tot
  logical :: ok
  hf = 1
  !$omp target map(from: hf)
  hf = merge(1, 0, omp_is_initial_device())
  !$omp end target
  allocate(r%a(8))
  r%s = -1
  r%a = -1
  !$omp target enter data map(to: r)
  !$omp target enter data map(to: r%a)
  !$omp target
    do q = 1, 8
      r%a(q) = 500 + q - 1
    end do
    r%s = 900
  !$omp end target
  !$omp target exit data map(from: r%a)
  !$omp target exit data map(from: r)
  tot = sum(r%a)
  ok = tot == 4028 .and. r%s == 900
  print '(a,i0)', 'tot= ', tot
  print '(a,i0)', 's= ', r%s
  print '(a,i0,a,a)', 'RESULT ran_on_host=', hf, ' check=', merge('pass', 'fail', ok)
end program t
