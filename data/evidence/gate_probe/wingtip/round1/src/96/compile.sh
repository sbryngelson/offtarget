ulimit -c 0
export TMPDIR=.
/opt/nvidia/hpc_sdk/Linux_x86_64/25.11/compilers/bin/nvc -mp=gpu -gpu=cc80 -gpu=mem:managed -O2 prog.c -o prog.out
