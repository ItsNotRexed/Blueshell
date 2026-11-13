"""Finalized NVN pools and the capture buffers' spares (gpu/vk/vk_memory.cpp; no game/GPU required).

1. retire_finalized_pools retires an import only when no pool of the game's is over it, in the GPU mappings (guest_pools,
   overlapping entries included) or among the pools the game made and has not finalized (memory_pool_created /
   memory_pool_finalized, so a live pool whose mapping entry an older pool's finalize took is kept); not while a queue is
   stopped at a wait (looked at again at the next submission) nor with RX_VK_ASYNC; and RX_VK_KEEP_FINALIZED_POOLS=1 keeps
   them. It retires them as a pool remade larger is, its mirror inherited by the pool made over its range next.
2. finalized_settle keeps a finalized range's textures while it waits: a pool made over it (the scene load's case) ends the
   wait with its textures kept; none within kIdleEpochs submissions, and its textures, GPU-owned ranges and capture spans go.
   Both are cut from vk_memory.cpp, compiled and run here.
3. mirrors_give_back runs on its own cadence (every 64 submissions, or for room), not on every submission once a pool was
   retired.
4. The capture buffers: spares of 32, 64 and 128 MB made ahead (the AMD scene-load stutter fix), and the startup line says
   so; spares capped at 256 MB above a 6.5 GB allowance (32 MB below), RX_VK_CAP_SPARE_MB read with env_int; the oldest
   capture unused for 120 submissions retired past 96 MB.

python -I -B tests/test_finalized_pools.py [--cxx g++]
"""
import argparse
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]


def block(text, marker):
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


def need(where, text, needles):
    for needle in needles:
        if needle not in text:
            raise SystemExit(where + " no longer has: " + needle)


def check_source():
    mem = (ROOT / "gpu/vk/vk_memory.cpp").read_text(encoding="utf-8")
    retire = block(mem, "void retire_pool(std::map<uint64_t, Pool>::iterator it, bool finalized) {")
    # (the inheritance is not switched off for a finalized pool: the foliage records a scene load's GPU work wrote)
    need("vk_memory.cpp: retire_pool", retire,
         ["if (old->mstate == Pool::MIRROR_ON && !no_inherit) old->inherit_pending = true, old->retired_epoch = mirror_epoch;"])
    fin = block(mem, "void retire_finalized_pools() {")
    need("vk_memory.cpp: retire_finalized_pools", fin,
         ["keep_finalized_pools()", "if (replay_may_run_older_work()) return;", "game_pool_over(lo, hi)",
          "retire_pool(cur, true);", "finalized_waiting.push_back("])
    if "texture_pool_finalized" in fin or "shadow_drop_range" in fin:
        raise SystemExit("retire_finalized_pools lets the range's textures go at once: a pool made over it next lost them")
    need("vk_memory.cpp: keep_finalized_pools", block(mem, "bool keep_finalized_pools() {"),
         ['static const bool v = env_on("RX_VK_KEEP_FINALIZED_POOLS");'])
    need("vk_memory.cpp: memory_pool_created", block(mem, "void memory_pool_created(uint64_t gpu, uint64_t size) {"),
         ["live_pool_count(gpu, size, 1);"])
    begin = block(mem, "void memory_begin_submission() {")
    need("vk_memory.cpp: memory_begin_submission", begin, ["retire_finalized_pools();", "finalized_settle();"])
    if begin.index("finalized_settle();") > begin.index("retired_imports_give_back();"):
        raise SystemExit("memory_begin_submission: finalized_settle after retired_imports_give_back")
    if "retired_pools.empty()" in begin:
        raise SystemExit("memory_begin_submission runs mirrors_give_back on every submission once any pool was retired")
    need("vk_memory.cpp: memory_begin_submission", begin,
         ["if (mirror_epoch % 64 == 0 || mirror_bytes + want > mirror_budget()) mirrors_give_back(want);"])

    replay = (ROOT / "gpu/vk/vk_replay.cpp").read_text(encoding="utf-8")
    need("vk_replay.cpp", replay, ["t.nvn_pool_finalized = memory_pool_finalized;",
                                   "return async_on() || blocked_n.load(std::memory_order_relaxed) > 0;"])
    need("vk_memory.cpp: finalized_settle", block(mem, "void finalized_settle() {"), ["replay_may_run_older_work()"])
    api = (ROOT / "gpu/vk/vk_api.h").read_text(encoding="utf-8")
    need("vk_api.h", api, ["void (*nvn_pool_finalized)(uint64_t gpu, uint64_t size);"])
    host = (ROOT / "host/nvn_native.c").read_text(encoding="utf-8")
    fz = block(host, "NV(nvnMemoryPoolFinalize) {")
    need("host/nvn_native.c: nvnMemoryPoolFinalize", fz, ["rx_nvn_pool_finalized(o->gpu, o->size);"])
    if fz.index("rx_nvn_pool_finalized") < fz.index("} else if (o->mem) {"):
        raise SystemExit("nvnMemoryPoolFinalize: a virtual pool's finalize counted against the pools made (they are not)")
    need("host/rx_backend.c", (ROOT / "host/rx_backend.c").read_text(encoding="utf-8"),
         ["if (vk && vk->nvn_pool_finalized) vk->nvn_pool_finalized(gpu, size);"])

    tex = (ROOT / "gpu/vk/vk_texture.cpp").read_text(encoding="utf-8")
    tf = block(tex, "void texture_pool_finalized(uint64_t lo, uint64_t hi) {")
    need("vk_texture.cpp: texture_pool_finalized", tf, ["gpu_owned.erase(it)", "t->released = true;"])
    if "env_on(" in tf:
        raise SystemExit("texture_pool_finalized reads the environment on every call")

    spare = block(mem, "uint64_t cap_spare_max() {")
    need("vk_memory.cpp: cap_spare_max", spare, ['env_int("RX_VK_CAP_SPARE_MB", -1)', "32ull << 20 : 256ull << 20"])
    if "getenv(" in spare or "atoll(" in spare:
        raise SystemExit("cap_spare_max reads RX_VK_CAP_SPARE_MB with getenv/atoll again (hookshot_env.h: env_int)")
    need("vk_memory.cpp: cap_buf_get", block(mem, "bool cap_buf_get("),
         ["for (uint64_t c : {32ull << 20, 64ull << 20, 128ull << 20}) cap_prewarm_class(c);"])
    need("vk_memory.cpp: cap_prewarm_on", block(mem, "bool cap_prewarm_on() {"), ["(32, 64, 128 MB spares made on a worker)"])
    need("vk_memory.cpp: take_capture", block(mem, "bool take_capture("),
         ["cap_bytes > (96ull << 20) && last_val + 120 <= completed"])


RETIRE_TEST = r"""
#include <algorithm>
#include <atomic>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <map>
#include <mutex>
#include <utility>
#include <vector>
#define CHECK(x) do { if (!(x)) { std::printf("FAIL line %d: %s\n", __LINE__, #x); std::exit(1); } } while (0)
bool env_on(const char*) { return false; }
void logf(const char*, ...) {}
struct Pool { uint64_t lo = 0, hi = 0; };
struct GuestPool { uint64_t lo = 0, hi = 0; };
std::vector<GuestPool> guest_pools;
std::atomic<uint64_t> guest_pools_gen{1};
std::map<uint64_t, Pool> imported;
std::vector<Pool> retired;
uint64_t align = 4096, mirror_epoch = 0;
constexpr uint64_t kIdleEpochs = 600;
void retire_pool(std::map<uint64_t, Pool>::iterator it, bool finalized) {
    if (!finalized) std::exit(2);
    retired.push_back(it->second);
    imported.erase(it);
}
std::mutex shadow_mu;
std::map<uint64_t, std::pair<uint64_t, uint64_t>> tex_spans;
bool tex_spans_changed = false;
std::vector<std::pair<uint64_t, uint64_t>> dropped, released;
void shadow_drop_range(uint64_t lo, uint64_t hi) { dropped.push_back({lo, hi}); }
void texture_pool_finalized(uint64_t lo, uint64_t hi) { released.push_back({lo, hi}); }
bool async = false, stopped = false;
bool replay_may_run_older_work() { return async || stopped; }
/*CUT*/
/*SETTLE*/
const uint64_t MB = 1ull << 20, A = 0x10000000;
void table(std::vector<GuestPool> v) {
    guest_pools = std::move(v);
    guest_pools_gen++;
}
void imp(uint64_t lo, uint64_t hi) {
    Pool p;
    p.lo = lo, p.hi = hi;
    imported[lo] = p;
}
void reset() {
    imported.clear(), retired.clear(), live_pools.clear(), finalized_waiting.clear(), dropped.clear(), released.clear();
    tex_spans.clear();
    guest_pools.clear(), guest_pools_gen++;
    async = stopped = false;
}
int main() {
    {   // finalized, nothing over it: retired, its textures kept for now
        reset();
        imp(A, A + 4 * MB);
        imp(A + 8 * MB, A + 12 * MB);
        table({{A + 8 * MB, A + 10 * MB}});
        retire_finalized_pools();
        CHECK(retired.size() == 1 && retired[0].lo == A && imported.count(A + 8 * MB));
        CHECK(finalized_waiting.size() == 1 && released.empty() && dropped.empty());
        retire_finalized_pools();   // (the table unchanged: not looked at again)
        CHECK(retired.size() == 1);
    }
    {   // inside a large pool, past a smaller one that starts after it (overlapping entries): kept
        reset();
        imp(A + 8 * MB, A + 12 * MB);
        table({{A, A + 64 * MB}, {A + 1 * MB, A + 2 * MB}});
        retire_finalized_pools();
        CHECK(retired.empty());
    }
    {   // live, its mapping entry gone (an older pool's finalize took it): kept, until the game finalizes it
        reset();
        imp(A, A + 4 * MB);
        memory_pool_created(A, 2 * MB);
        memory_pool_created(A, 2 * MB);   // (made again over the same memory, the first not finalized yet)
        table({});
        retire_finalized_pools();
        CHECK(retired.empty());
        memory_pool_finalized(A, 2 * MB);   // (the older one's finalize: the newer one is still live)
        retire_finalized_pools();
        CHECK(retired.empty());
        memory_pool_finalized(A, 2 * MB);
        retire_finalized_pools();
        CHECK(retired.size() == 1 && live_pools.empty());
    }
    {   // a queue stopped at a wait: not now, and looked at again once it went on, the table unchanged
        reset();
        imp(A, A + 4 * MB);
        table({});
        stopped = true;
        retire_finalized_pools();
        CHECK(retired.empty());
        stopped = false;
        retire_finalized_pools();
        CHECK(retired.size() == 1);
    }
    {   // the replay on its own thread (RX_VK_ASYNC): never
        reset();
        imp(A, A + 4 * MB);
        table({});
        async = true;
        retire_finalized_pools();
        CHECK(retired.empty());
    }
    {   // a scene load: finalized, then a pool made over the same memory a submission later. Its textures stay
        reset();
        imp(A, A + 4 * MB);
        tex_spans[A] = {A + MB, 0};
        table({});
        retire_finalized_pools();
        CHECK(retired.size() == 1);
        mirror_epoch++;
        finalized_settle();
        CHECK(finalized_waiting.size() == 1 && released.empty());
        memory_pool_created(A, 3 * MB);
        mirror_epoch++;
        finalized_settle();
        CHECK(finalized_waiting.empty() && released.empty() && dropped.empty() && tex_spans.count(A));
    }
    {   // none made over it: its textures, GPU-owned ranges and capture spans go after kIdleEpochs submissions, not before
        reset();
        imp(A, A + 4 * MB);
        tex_spans[A] = {A + MB, 0};
        tex_spans[A + 8 * MB] = {A + 9 * MB, 0};
        table({});
        retire_finalized_pools();
        const uint64_t at = mirror_epoch;
        mirror_epoch = at + kIdleEpochs;
        finalized_settle();
        CHECK(released.empty() && finalized_waiting.size() == 1);
        stopped = true;   // (a queue stopped: not now)
        mirror_epoch = at + kIdleEpochs + 1;
        finalized_settle();
        CHECK(released.empty());
        stopped = false;
        finalized_settle();
        CHECK(released.size() == 1 && released[0] == std::make_pair(A, A + 4 * MB) && dropped.size() == 1);
        CHECK(!tex_spans.count(A) && tex_spans.count(A + 8 * MB) && finalized_waiting.empty());
    }
    std::printf("finalized pools: ok\n");
    return 0;
}
"""


def retire_test(cxx, tmp):
    mem = (ROOT / "gpu/vk/vk_memory.cpp").read_text(encoding="utf-8")
    a = mem.index("std::mutex live_pools_mu;")
    b = mem.index("\n}\n", mem.index("void retire_finalized_pools() {")) + 3
    cut = mem[a:b]
    created = block(mem, "void memory_pool_created(uint64_t gpu, uint64_t size) {")
    created = created[:created.index("\n") + 1] + "    live_pool_count(gpu, size, 1);\n}\n"
    created += block(mem, "void memory_pool_finalized(uint64_t gpu, uint64_t size) {") + "\n"
    src = RETIRE_TEST.replace("/*CUT*/", cut + "\n" + created).replace("/*SETTLE*/", block(mem, "void finalized_settle() {"))
    cpp = Path(tmp) / "finalized_pools.cpp"
    cpp.write_text(src, encoding="utf-8")
    exe = Path(tmp) / "finalized-pools"
    subprocess.run([cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror", "-Wno-unused-function", str(cpp), "-o", str(exe)], check=True)
    subprocess.run([str(exe)], check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="g++")
    args = parser.parse_args()
    check_source()
    with tempfile.TemporaryDirectory(prefix="finalized-pools-") as tmp:
        retire_test(args.cxx, tmp)
    print("test_finalized_pools: ok")


if __name__ == "__main__":
    main()
