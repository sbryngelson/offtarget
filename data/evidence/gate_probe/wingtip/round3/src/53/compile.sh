ulimit -c 0
export TMPDIR=.
<site>/nvhpc/Linux_x86_64/26.9/compilers/bin/nvfortran -mp=gpu -gpu=cc80 -gpu=mem:separate -O2 -c fuzz_dmod.f90 -o fuzz_dmod.o && \
<site>/nvhpc/Linux_x86_64/26.9/compilers/bin/nvfortran -mp=gpu -gpu=cc80 -gpu=mem:separate -O2 -c fuzz_dfun.f90 -o fuzz_dfun.o && \
<site>/nvhpc/Linux_x86_64/26.9/compilers/bin/nvfortran -mp=gpu -gpu=cc80 -gpu=mem:separate -O2 -c fuzz_amod.f90 -o fuzz_amod.o && \
<site>/nvhpc/Linux_x86_64/26.9/compilers/bin/nvfortran -mp=gpu -gpu=cc80 -gpu=mem:separate -O2 -c fuzz_smod.f90 -o fuzz_smod.o && \
<site>/nvhpc/Linux_x86_64/26.9/compilers/bin/nvfortran -mp=gpu -gpu=cc80 -gpu=mem:separate -O2 -c fuzz_ssub.f90 -o fuzz_ssub.o && \
<site>/nvhpc/Linux_x86_64/26.9/compilers/bin/nvfortran -mp=gpu -gpu=cc80 -gpu=mem:separate -O2 -c fuzz_ext.f90 -o fuzz_ext.o && \
<site>/nvhpc/Linux_x86_64/26.9/compilers/bin/nvfortran -mp=gpu -gpu=cc80 -gpu=mem:separate -O2 -c fuzz_prog.f90 -o fuzz_prog.o && \
<site>/nvhpc/Linux_x86_64/26.9/compilers/bin/nvfortran -mp=gpu -gpu=cc80 -gpu=mem:separate -O2 fuzz_dmod.o fuzz_dfun.o fuzz_amod.o fuzz_smod.o fuzz_ssub.o fuzz_ext.o fuzz_prog.o -o prog.out
