! OpenACC 3.4 §2.14.1 (init; with no clause all devices are initialized)
! and §2.14.3 (set default_async). Legal. Expected output: ok 2 then
! ok 2 2. Compile: ftn -h acc -O2. Variants that abort the same way:
! `!$acc set device_num(0)`, `!$acc shutdown device_type(radeon)` (device-
! number assertion); `!$acc init device_type(radeon)` works.
! The catalog's acc34-directive-init, -set and -shutdown programs
! (no clauses) abort on CCE 19, 20 and 21 in both memory modes and on
! MI250X: "_cray_acc_init_device ... Incorrect device type set" and, for
! a plain `!$acc shutdown`, "_cray_acc_shutdown_device ... Shutting down
! incorrect device type" (results/acc_matrix.jsonl).
program t
  use openacc
  implicit none
  integer :: a(8), i
  a = 1
  !$acc init
  !$acc parallel loop copy(a)
  do i = 1, 8
    a(i) = 2
  end do
  print *, 'ok', a(1)
  !$acc set default_async(2)
  !$acc parallel loop copy(a) async
  do i = 1, 8
    a(i) = 2
  end do
  !$acc wait(2)
  print *, 'ok', a(1), acc_get_default_async()
end program t
! site:
! title: ftn -h acc: !$acc init and !$acc set default_async abort in the runtime ("Incorrect device type set")
! control: ../vendor/checks/src/cce/control/cce-acc-init-set-runtime-assert-control.f90 device_type(radeon) added to the init and
! + set
! + directives
! end site
