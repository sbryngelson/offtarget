ulimit -c 0
export TMPDIR=.
/opt/nvidia/hpc_sdk/Linux_x86_64/25.11/compilers/bin/nvfortran -acc=gpu -gpu=cc80 -gpu=mem:separate -O2 $PWD/acc34-clause-gang-dim.f90 -o prog.out
