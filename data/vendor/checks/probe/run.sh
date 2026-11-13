#!/bin/bash
cd /tmp && rm -rf t44probe && mkdir t44probe && cd t44probe
cp <site>/compliant/vendor/checks/probe/ds.* .
A=<site>/afar/therock-afar-24.3.0-multiarch-10.1.0-592954c/bin
$A/amdflang -fopenmp --offload-arch=gfx942 -L/usr/lib/gcc/x86_64-redhat-linux/8 -O2 ds.f90 -o f && echo AFAR-F && OMP_TARGET_OFFLOAD=mandatory ./f
$A/amdclang -fopenmp --offload-arch=gfx942 -O2 ds.c -o c && echo AFAR-C && OMP_TARGET_OFFLOAD=mandatory ./c
. /etc/profile >/dev/null 2>&1; module load cce/21.0.4 craype-accel-amd-gfx942 rocm/7.2.0 >/dev/null 2>&1; module unload cray-mpich >/dev/null 2>&1
craycc -fopenmp -fopenmp-targets=amdgcn-amd-amdhsa -Xopenmp-target=amdgcn-amd-amdhsa -march=gfx942 -O2 ds.c -o cc && echo CCE-C && OMP_TARGET_OFFLOAD=mandatory ./cc
ftn -fopenmp -O2 ds.f90 -o ff && echo CCE-F && OMP_TARGET_OFFLOAD=mandatory ./ff
cd /tmp && rm -rf t44probe
