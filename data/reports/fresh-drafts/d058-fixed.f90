! Fresh-058 control: A a fixed-size module array, one iteration.
! Expected: 7.
MODULE GLOBALS
   IMPLICIT NONE
   REAL :: Z
   REAL, DIMENSION(10)::A

END MODULE GLOBALS

MODULE RECON
   USE GLOBALS

   IMPLICIT NONE

CONTAINS

   SUBROUTINE CRASH_REPRO()

      IMPLICIT NONE
      INTEGER::II

      Z = 7

      !$OMP target teams loop
      DO II = 1, 1
         A = Z;
      END DO
      !$OMP end target teams loop

      PRINT *, A(1)

   END SUBROUTINE CRASH_REPRO

END MODULE RECON

PROGRAM compilerCrashTest

   USE RECON
   IMPLICIT NONE

   CALL CRASH_REPRO()

END PROGRAM compilerCrashTest
