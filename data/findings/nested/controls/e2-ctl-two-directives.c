// control: the second parent and its pointer to the leaf in two directives
#include <stdio.h>
#include <stdlib.h>
#include <openacc.h>
struct leaf { int *a; };
struct mid { struct leaf *c; };
struct top { int v; struct mid *l; struct mid *r; };
int main(void)
{
  int hf = 1, i, tot = 0, ok;
  struct top t;
  t.v = 5;
  t.l = malloc(sizeof *t.l);
  t.r = malloc(sizeof *t.r);
  t.l->c = malloc(sizeof *t.l->c);
  t.r->c = t.l->c;                       /* one leaf, two parents */
  t.l->c->a = malloc(4 * sizeof(int));
  for (i = 0; i < 4; i++) t.l->c->a[i] = i + 1;
  #pragma acc serial copy(hf)
  hf = acc_on_device(acc_device_host) ? 1 : 0;
  #pragma acc enter data copyin(t)
  #pragma acc enter data copyin(t.l[0:1])
  #pragma acc enter data copyin(t.l->c[0:1])
  #pragma acc enter data copyin(t.l->c->a[0:4])
  #pragma acc enter data copyin(t.r[0:1])
  #pragma acc enter data copyin(t.r->c[0:1])
  #pragma acc serial copy(tot) present(t)
  {
    tot = t.v;
    for (int q = 0; q < 4; q++) tot += t.l->c->a[q] + t.r->c->a[q];
  }
  #pragma acc exit data delete(t.r->c[0:1])
  #pragma acc exit data delete(t.r[0:1])
  #pragma acc exit data delete(t.l->c->a[0:4])
  #pragma acc exit data delete(t.l->c[0:1])
  #pragma acc exit data delete(t.l[0:1])
  #pragma acc exit data delete(t)
  ok = tot == 25;
  printf("tot= %d\n", tot);
  printf("RESULT ran_on_host=%d check=%s\n", hf, ok ? "pass" : "fail");
  return 0;
}
