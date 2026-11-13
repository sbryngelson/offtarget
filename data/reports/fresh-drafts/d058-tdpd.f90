! Fresh-058 variant: target teams distribute parallel do instead of
! target teams loop, one iteration. Expected: 7.
MODULE GLOBALS
   IMPLICIT NONE
   REAL :: Z
   REAL, ALLOCATABLE, DIMENSION(:)::A

END MODULE GLOBALS

MODULE RECON
   USE GLOBALS

   IMPLICIT NONE

CONTAINS

   SUBROUTINE CRASH_REPRO()

      IMPLICIT NONE
      INTEGER::II

      ALLOCATE (A(10))
      Z = 7

      !$OMP target teams distribute parallel do
      DO II = 1, 1
         A = Z;
      END DO
      !$OMP end target teams distribute parallel do

      PRINT *, A(1)

   END SUBROUTINE CRASH_REPRO

END MODULE RECON

PROGRAM compilerCrashTest

   USE RECON
   IMPLICIT NONE

   CALL CRASH_REPRO()

END PROGRAM compilerCrashTest
