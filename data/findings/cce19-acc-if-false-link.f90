! OpenACC 3.4 §2.5.6 (if clause): with a false condition the local thread
! executes the region. Legal. Expected output: on_host = T.
! Compile: ftn -h acc -O2.
program t
  use openacc
  implicit none
  logical :: on_host, use_dev
  use_dev = .false.
  on_host = .false.
  !$acc serial if(use_dev) copy(on_host)
  on_host = acc_on_device(acc_device_host)
  !$acc end serial
  print *, 'on_host =', on_host
end program t
! site:
! disposition: out-of-scope out of scope (maintainer ruling 2026-10-21): the region with if(.false.) runs on the host
! end site
