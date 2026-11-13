int main(void) {
  int x = 0, b[8];
  #pragma omp parallel for linear(x: step(2))
  for (int i = 0; i < 8; i++) { b[i] = x; x += 2; }
  return b[1];
}
