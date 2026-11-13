ulimit -c 0
export TMPDIR=.
<site>/nvhpc/Linux_x86_64/26.9/compilers/bin/nvc -mp=gpu -gpu=cc80 -gpu=mem:separate -O2 prog.c -o prog.out
