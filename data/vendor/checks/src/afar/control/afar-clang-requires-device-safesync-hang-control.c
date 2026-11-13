#pragma omp requires atomic_default_mem_order(seq_cst)
int main(void) { return 0; }
