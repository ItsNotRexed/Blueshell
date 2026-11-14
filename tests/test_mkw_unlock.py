"""host/mkw_unlock.c, Unlock everything: on a made-up save of the game's layout (a key table of hash -> offset, length-prefixed
arrays): every listed driver, vehicle and sticker owned once with its new-item state, the drivers' owned bits set, the
Special Cup and Mirror opened, what the save had kept, a second run changing nothing, and a save of another layout left as
it is. No game, no game data: the file and the arrays are built here.

Run with: python -I tests/test_mkw_unlock.py [--cc clang]
"""
import argparse
import os
import re
import struct
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN_ALL_ARGS = ["--cc", "{cc}"]

DRIVER = """
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
void hos_log(const char *fmt, ...) { va_list a; va_start(a, fmt); vprintf(fmt, a); va_end(a); putchar('\\n'); }
int hos_unlock_save(uint8_t *b, uint64_t n);
int main(int argc, char **argv) {
    (void)argc;
    FILE *f = fopen(argv[1], "rb");
    fseek(f, 0, SEEK_END);
    long n = ftell(f);
    fseek(f, 0, SEEK_SET);
    uint8_t *b = malloc((size_t)n);
    if (fread(b, 1, (size_t)n, f) != (size_t)n) return 9;
    fclose(f);
    int changed = hos_unlock_save(b, (uint64_t)n);
    f = fopen(argv[2], "wb");
    fwrite(b, 1, (size_t)n, f);
    fclose(f);
    printf("changed %d\\n", changed);
    return 0;
}
"""

# (key hash, slots): the arrays host/mkw_unlock.c looks up
ARRAYS = [(0x44850554, 1000), (0xED0C72BF, 1000), (0xCE4D2DD9, 1000),   # drivers: list, state, owned bits
          (0x1E849D5C, 1000), (0xF39B8041, 1000),                       # vehicles
          (0xB8A3BA35, 5000), (0xE85996AD, 5000),                       # stickers
          (0x55A6E00E, 50), (0x9A164573, 50)]                           # cup progress, cups open in Grand Prix
MIRROR = 0x2F65471C


def ids(name):
    src = (ROOT / "host" / "mkw_unlock_ids.h").read_text(encoding="utf-8")
    body = src[src.index("unlock_%s_ids[] = {" % name):]
    return [int(x, 16) for x in re.findall(r"0x[0-9a-fA-F]+", body[:body.index("};")])]


def make_save(have_driver):
    entries = len(ARRAYS) + 1
    table_end = 0x20 + 8 * entries
    b = bytearray(table_end)
    struct.pack_into("<III", b, 0, 0x01020304, 0, table_end)
    at = {}
    for i, (key, slots) in enumerate(ARRAYS):
        at[key] = len(b)
        struct.pack_into("<II", b, 0x20 + 8 * i, key, len(b))
        b += struct.pack("<I", slots) + bytes(4 * slots)
    struct.pack_into("<II", b, 0x20 + 8 * len(ARRAYS), MIRROR, 0)
    # (the save already has one driver, state 5, its owned bit set: kept as it is)
    struct.pack_into("<I", b, at[0x44850554] + 4, have_driver)
    struct.pack_into("<I", b, at[0xED0C72BF] + 4, 5)
    struct.pack_into("<I", b, at[0xCE4D2DD9] + 4, 1)
    return bytes(b), at


def read_list(b, off, n):
    return list(struct.unpack_from("<%dI" % n, b, off + 4))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cc", default="clang")
    a = p.parse_args()
    drivers, vehicles, stickers = ids("driver"), ids("vehicle"), ids("sticker")
    with tempfile.TemporaryDirectory(prefix="mkw-unlock-") as tmp:
        tmp = Path(tmp)
        (tmp / "driver.c").write_text(DRIVER, encoding="utf-8")
        exe = tmp / ("t.exe" if os.name == "nt" else "t")
        subprocess.run([a.cc, "-std=c11", "-Wall", "-Wextra", "-Werror", "-I", str(ROOT / "host"), str(ROOT / "host" / "mkw_unlock.c"),
                        str(tmp / "driver.c"), "-o", str(exe)], check=True)
        save, at = make_save(drivers[3])
        (tmp / "in.sav").write_bytes(save)
        out = subprocess.run([str(exe), str(tmp / "in.sav"), str(tmp / "out.sav")], capture_output=True, text=True, check=True).stdout
        b = (tmp / "out.sav").read_bytes()
        assert len(b) == len(save), "the save changed size"
        dl = read_list(b, at[0x44850554], 1000)
        assert dl[0] == drivers[3] and read_list(b, at[0xED0C72BF], 1)[0] == 5, "the driver the save had was not kept"
        assert sorted(x for x in dl if x) == sorted(set(drivers)), "not every driver owned once"
        n = len(set(drivers))
        assert all(s == 3 for s in read_list(b, at[0xED0C72BF], n)[1:]), "a new driver's state is not 3"
        bits = read_list(b, at[0xCE4D2DD9], (n + 31) // 32)
        assert all(bits[i // 32] >> (i % 32) & 1 for i in range(n)), "a driver's owned bit is not set"
        assert sorted(x for x in read_list(b, at[0x1E849D5C], 1000) if x) == sorted(set(vehicles)), "not every vehicle"
        assert sorted(x for x in read_list(b, at[0xB8A3BA35], 5000) if x) == sorted(set(stickers)), "not every sticker"
        assert read_list(b, at[0x55A6E00E], 16)[15] == 2, "the Special Cup is not revealed"
        assert read_list(b, at[0x9A164573], 1)[0] >> 15 & 1, "the Special Cup is not open in Grand Prix"
        assert struct.unpack_from("<I", b, 0x20 + 8 * len(ARRAYS) + 4)[0] == 1, "Mirror is not open"
        assert "mirror open" in out, out
        # (a second run: nothing more to change)
        (tmp / "in.sav").write_bytes(b)
        out = subprocess.run([str(exe), str(tmp / "in.sav"), str(tmp / "out2.sav")], capture_output=True, text=True, check=True).stdout
        assert "changed 0" in out and (tmp / "out2.sav").read_bytes() == b, out
        # (another layout: left as it is)
        other = bytes(4096)
        (tmp / "in.sav").write_bytes(other)
        out = subprocess.run([str(exe), str(tmp / "in.sav"), str(tmp / "out3.sav")], capture_output=True, text=True, check=True).stdout
        assert "changed 0" in out and "not a layout this knows" in out and (tmp / "out3.sav").read_bytes() == other, out
    print("PASS: Unlock everything owns every driver, vehicle and sticker once, opens the Special Cup and Mirror, keeps the save's own")


if __name__ == "__main__":
    main()
