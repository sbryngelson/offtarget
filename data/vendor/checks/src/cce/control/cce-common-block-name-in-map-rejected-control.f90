program main
   integer :: A(2), C, r
   real :: B
   common /mycommon/ A, B, C
   A = [1, 2]; B = 2.0; C = 7
   r = 0
   !$omp target map(to: A, B, C) map(from: r)
     if (A(1) == 1 .and. A(2) == 2 .and. B == 2.0 .and. C == 7) r = 1
   !$omp end target
   if (r == 1) then
     print *, 'wild-check: pass'
   else
     print *, 'wild-check: fail'
   end if
end program main
