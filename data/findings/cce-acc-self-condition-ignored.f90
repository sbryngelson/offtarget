! OpenACC 3.4 §2.5.7 (self clause): "When the condition evaluates to true,
! the region will execute on the local device." Legal. Expected output:
! on_host = T. Compile: ftn -h acc -O2.
program t
  use openacc
  implicit none
  logical :: on_host, use_host
  use_host = .true.
  on_host = .false.
  !$acc serial self(use_host) copy(on_host)
  on_host = acc_on_device(acc_device_host)
  !$acc end serial
  print *, 'on_host =', on_host
end program t
! site:
! disposition: out-of-scope out of scope (maintainer ruling 2026-10-21): the construct of interest runs on the host
! end site
