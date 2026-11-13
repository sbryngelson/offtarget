// # Finding (known-issues harvest): NVHPC gives use_device_ptr a garbage pointer
//   when the target data construct's if clause is false
//
// - source: UoB-HPC/TeaLeaf commit c35c0e57f6 (pack_halos.cpp: "#pragma omp target data if
//   (!settings.staging_buffer && settings.is_offload) use_device_ptr(...)", hoisted for an AOMP
//   bug, aomp#601); data/bench/harvest-known hk-018. The conjunction is not the trigger here: the
//   literal if(0) fails the same way (data/reports/harvest-known/v018-data-if-false.c is the
//   struct-member form)
// - compilers: NVHPC nvc 25.11 and 26.9, -mp=gpu -gpu=cc80 (separate and managed memory)
// - expected: seen == the host address of buf, RESULT ... check=pass. "When an if clause is
//   present and the if clause expression evaluates to false, the target device is the host"
//   (OpenMP 5.2 §13.5 p.279 l.12-13); on the host device buf's corresponding storage is buf
//   itself, so the use_device_ptr conversion refers to the host address (§5.4.8 p.121 l.15-21)
// - actual: p inside the region is 0xc (both releases, both memory modes; "host 0x7ffe... seen
//   0xc"), RESULT ... check=fail
// - control (same compiler): with the if clause true the region sees the device address that
//   omp_get_mapped_ptr returns (data/reports/harvest-known/c018-data-if-true.c); TeaLeaf's other
//   use, target update if(<conjunction>), behaves (v018-update-if.c)
// - other families: AFAR and CCE 19/20/21 give the host address (gfx90a and gfx942)
// - legality: buf is mapped by target enter data before the construct and p points to it
//   (§5.4.8 p.121 l.15-18); the if clause takes any scalar expression; the pre-run check
//   (rules and the AFAR front end) accepts the program
// - evidence: results/harvest-known/main.wingtip (hk-018, gate: confirmed), results/harvest-known/probes.wingtip.jsonl,
//   the MI250X probe runs' output for AFAR and CCE (results/harvest-known/logs/tioga/probe.f656gDkdAd9R.log; its rows
//   file probes.tioga.jsonl was not kept)
#include <omp.h>
#include <stdbool.h>
#include <stdio.h>
struct settings { bool staging_buffer; bool is_offload; };
int main(void) {
  enum { N = 512 };
  double buf[N];
  double *p = buf, *seen = NULL;
  struct settings s = {true, true};
#pragma omp target enter data map(to: buf[:N])
#pragma omp target data if (0) use_device_ptr(p)
  { seen = p; }
  printf("host %p seen %p\n", (void *)buf, (void *)seen);
  int ok = (seen == buf);
#pragma omp target exit data map(delete: buf[:N])
  int hk_host = 1;
#pragma omp target map(tofrom: hk_host)
  hk_host = omp_is_initial_device();
  printf("RESULT ran_on_host=%d check=%s\n", hk_host, ok ? "pass" : "fail");
  return 0;
}
// site:
// title: nvc: use_device_ptr gives a garbage pointer when the if clause of target data is false
// end site
