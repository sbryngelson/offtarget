ulimit -c 0
export TMPDIR=.
/opt/nvidia/hpc_sdk/Linux_x86_64/25.11/compilers/bin/nvc -mp=gpu -gpu=cc80 -gpu=mem:managed -O2 $PWD/omp52-c-w-ordered.c -o prog.out
