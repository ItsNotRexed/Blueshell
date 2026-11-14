"""(blueshell) Arms a dump when a whole-screen flash shows in a live frame log (RX_VK_FRAMELOG): MKW's exploded draws come back on
a cycle in some scenes (every 4th frame in a desert attract scene), so the frames after the first catch one. The run sets
RX_VK_DUMP_FILE=<trigger> and RX_VK_DUMP_MOD=1,0,<n> (the next n frames after the trigger appears).

    python -I scripts/flash_watch.py <frames.bin> <trigger file> [--times 3] [--blocks 100] [--gap 20]

Polls the log's newest three records twice a second with framelog.py's test (a block brighter or darker than both
neighbours by more than they differ); --gap seconds between triggers. Ends when the log stops growing for 30 s.
"""
import argparse
import time
from pathlib import Path

import numpy as np

W, H = 320, 180
SIZE = 16 + W * H * 4


def blocks(a):
    l = a[..., 0] * 0.3 + a[..., 1] * 0.6 + a[..., 2] * 0.1
    return l[:H // 20 * 20, :].reshape(H // 20, 20, W // 20, 20).mean(axis=(1, 3))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("log", type=Path)
    p.add_argument("trigger", type=Path)
    p.add_argument("--times", type=int, default=3)
    p.add_argument("--blocks", type=int, default=100)
    p.add_argument("--gap", type=float, default=20)
    a = p.parse_args()
    last_size, still_since, fired, last_fire, seen = -1, time.time(), 0, 0.0, -1
    while fired < a.times:
        time.sleep(0.5)
        try:
            size = a.log.stat().st_size
        except OSError:
            size = 0
        if size != last_size:
            last_size, still_since = size, time.time()
        elif time.time() - still_since > 30 and size:
            break
        n = size // SIZE
        if n < 3 or n - 2 == seen:
            continue
        seen = n - 2
        with open(a.log, "rb") as f:
            f.seek((n - 3) * SIZE)
            raw = f.read(3 * SIZE)
        fr = [blocks(np.frombuffer(raw[i * SIZE + 16:(i + 1) * SIZE], np.uint8).reshape(H, W, 4)[..., :3].astype(np.float32))
              for i in range(3)]
        prev, cur, nxt = fr
        span = np.abs(prev - nxt)
        hit = 0
        for jump in (np.minimum(cur - prev, cur - nxt), np.minimum(prev - cur, nxt - cur)):
            hit = max(hit, int(((jump > 12) & (jump > span * 1.5)).sum()))
        if hit >= a.blocks and time.time() - last_fire > a.gap:
            a.trigger.touch()
            fired += 1
            last_fire = time.time()
            print("record %d: %d blocks: dump armed (%d of %d)" % (n - 2, hit, fired, a.times), flush=True)
    print("watch done: %d dumps armed" % fired)


if __name__ == "__main__":
    main()
