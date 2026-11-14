"""(blueshell) Code mods, in the layout emulators use: a mod's exefs folder with .pchtxt or .ips patches, applied to the game's
code before it is translated (nx2/make_game.py), so the patched instructions are what the game folder runs.

    python -I nx2/exefs_mods.py <mods dir> <exefs dir> [--list]

<mods dir> is the game folder's "mods" folder, the one host/mods.c reads RomFS mods from: any folder in it (at any depth, as
emulators keep them: <mods>/contents/<title id>/<name>/exefs) holding an exefs folder is a mod. Folders whose names start
with '-' or '_' are off. Mods apply in the order of their paths (name them 01-..., 02-... to order them), later ones over
earlier ones, as an emulator's load folder does. A patch applies to the module whose build id it names (a .pchtxt's
@nsobid-, an .ips file's name); one for another build is skipped and said, as on an emulator.

<exefs dir> holds plain (uncompressed) NSOs: nx2/unpack.py's. Patches are by memory offset: a .pchtxt's offsets plus its
@flag offset_shift, less the 0x100 header an .ips file's offsets count. A patch outside the module's segments is refused.
The original exefs the game folder keeps (.hookshot_exefs) is never patched: a build without mods is the game as it was.

.pchtxt (IPSwitch): @nsobid-<id>, @flag offset_shift <n>, @enabled / @disabled (the lines after it apply or not), @stop
(the rest is ignored), and patch lines "<hex offset> <hex bytes>" or "<hex offset> \"text\"". Comments: //, #, [ ]-titles.
"""
import os
import re
import struct
import sys

HEADER = 0x100


def mod_folders(mods):
    """The mods' exefs folders, in path order; those under a folder named -x or _x left out"""
    out = []
    for root, dirs, _ in os.walk(mods):
        dirs[:] = sorted(d for d in dirs if not d.startswith(("-", "_")))
        for d in list(dirs):
            if d.lower() == "exefs":
                out.append(os.path.join(root, d))
                dirs.remove(d)
    # (by the mod's folder, as an emulator orders its load folder: "Pack" before "Pack HUD" before "Pack HUD Edges")
    return sorted(out, key=lambda p: os.path.relpath(os.path.dirname(p), mods).lower().split(os.sep))


def parse_pchtxt(text):
    """(build id or None, [(memory offset, bytes)])"""
    bid, shift, on, patches = None, 0, False, []
    for raw in text.splitlines():
        line = raw.split("//")[0].strip()
        if not line or line.startswith("#") or line.startswith("["):
            continue
        low = line.lower()
        if low.startswith("@nsobid-"):
            bid = low[8:].strip()
        elif low.startswith("@flag offset_shift"):
            shift = int(line.split()[-1], 0)
        elif low == "@enabled":
            on = True
        elif low == "@disabled":
            on = False
        elif low == "@stop":
            break
        elif low.startswith("@"):
            continue
        elif on:
            m = re.match(r'^([0-9A-Fa-f]+)\s+(?:"((?:[^"\\]|\\.)*)"|([0-9A-Fa-f]+))$', line)
            if not m:
                raise ValueError("a line this tool cannot read: %r" % raw)
            off = int(m.group(1), 16) + shift - HEADER
            if m.group(2) is not None:
                data = m.group(2).encode("utf-8").decode("unicode_escape").encode("latin-1")
            else:
                if len(m.group(3)) % 2:
                    raise ValueError("an odd number of hex digits: %r" % raw)
                data = bytes.fromhex(m.group(3))
            patches.append((off, data))
    return bid, patches


def parse_ips(raw):
    """[(memory offset, bytes)] of an IPS or IPS32 file"""
    if raw[:5] == b"PATCH":
        width, end = 3, b"EOF"
    elif raw[:5] == b"IPS32":
        width, end = 4, b"EEOF"
    else:
        raise ValueError("not an IPS file")
    i, out = 5, []
    while raw[i:i + len(end)] != end:
        off = int.from_bytes(raw[i:i + width], "big")
        i += width
        size = int.from_bytes(raw[i:i + 2], "big")
        i += 2
        if size:
            data = raw[i:i + size]
            i += size
        else:   # (RLE)
            n = int.from_bytes(raw[i:i + 2], "big")
            data = raw[i + 2:i + 3] * n
            i += 3
        if len(data) != (size or len(data)):
            raise ValueError("cut short")
        out.append((off - HEADER, data))
        if i >= len(raw):
            raise ValueError("no end marker")
    return out


class Module:
    def __init__(self, path):
        self.path = path
        self.raw = bytearray(open(path, "rb").read())
        if self.raw[:4] != b"NSO0":
            raise ValueError("not an NSO")
        flags = struct.unpack_from("<I", self.raw, 0xC)[0]
        if flags & 0x80:
            raise ValueError("ZBIC-compressed (nx2/unpack.py first)")
        if flags & 7:   # (LZ4 segments, as nx2/unpack.py leaves them: made plain, as it does ZBIC's)
            import lz4.block
            segs = [struct.unpack_from("<III", self.raw, 0x10 + 0x10 * i) for i in range(3)]
            csize = struct.unpack_from("<III", self.raw, 0x60)
            body = bytearray(self.raw[0x100:min(s[0] for s in segs)])
            hdr = bytearray(self.raw[:0x100])
            for i, ((foff, _, size), cs) in enumerate(zip(segs, csize)):
                d = bytes(self.raw[foff:foff + cs])
                if flags & (1 << i):
                    d = lz4.block.decompress(d, uncompressed_size=size)
                struct.pack_into("<I", hdr, 0x10 + 0x10 * i, 0x100 + len(body))
                struct.pack_into("<I", hdr, 0x60 + 4 * i, len(d))
                body += d
            struct.pack_into("<I", hdr, 0xC, flags & ~7)
            self.raw = hdr + body
        segs = [struct.unpack_from("<III", self.raw, 0x10 + 0x10 * i) for i in range(3)]
        self.moff = [s[1] for s in segs]
        self.datas = [bytearray(self.raw[f:f + size]) for f, _, size in segs]
        self.name_bytes = bytes(self.raw[0x100:min(s[0] for s in segs)])   # (the module name the header points at)
        self.build_id = self.raw[0x40:0x60].hex()

    def patch(self, mem, data):
        for i, d in enumerate(self.datas):
            start = self.moff[i]
            # (a segment's room: up to the next one's start, the page padding a console maps as zeros and an emulator's patch
            # writes in. Mods put new code there (code caves past .text's end): the segment grows to hold it. .data: its own size)
            room = self.moff[i + 1] - start if i < 2 else len(d)
            if start <= mem and mem + len(data) <= start + room:
                at = mem - start
                if at + len(data) > len(d):
                    d.extend(b"\0" * (at + len(data) - len(d)))
                d[at:at + len(data)] = data
                return
        raise ValueError("offset %#x (%d bytes) is outside the module's segments" % (mem, len(data)))

    def save(self):
        hdr = bytearray(self.raw[:0x100])
        body = bytearray(self.name_bytes)
        for i, d in enumerate(self.datas):
            struct.pack_into("<III", hdr, 0x10 + 0x10 * i, 0x100 + len(body), self.moff[i], len(d))
            struct.pack_into("<I", hdr, 0x60 + 4 * i, len(d))
            body += d
        # (plain, and the segment hashes are of the original bytes: their check flags off, as an emulator's patched module has them)
        flags = struct.unpack_from("<I", hdr, 0xC)[0] & ~(0x38 | 7)
        struct.pack_into("<I", hdr, 0xC, flags)
        with open(self.path, "wb") as f:
            f.write(hdr + body)


def same_build(a, b):
    a, b = a.lower().rstrip("0"), b.lower().rstrip("0")
    n = max(min(len(a), len(b)), 16)
    return a[:n] == b[:n]


def apply(mods, exefs, log=print, dry=False):
    """Every code mod in <mods> onto the modules of <exefs>; (patches applied, files used). Raises ValueError on a broken mod"""
    if not os.path.isdir(mods):
        return 0, 0
    modules = {}
    for name in sorted(os.listdir(exefs)):
        p = os.path.join(exefs, name)
        if name != "main.npdm" and os.path.isfile(p):
            try:
                modules[name] = Module(p)
            except ValueError:
                continue
    applied = used = 0
    for folder in mod_folders(mods):
        mod = os.path.relpath(os.path.dirname(folder), mods)
        for f in sorted(os.listdir(folder)):
            path = os.path.join(folder, f)
            ext = os.path.splitext(f)[1].lower()
            if ext not in (".pchtxt", ".ips"):
                if os.path.isfile(path):
                    log("exefs mod %s: %s left out (only .pchtxt and .ips patches apply to translated code)" % (mod, f))
                continue
            try:
                if ext == ".pchtxt":
                    bid, patches = parse_pchtxt(open(path, encoding="utf-8-sig").read())
                else:
                    bid, patches = os.path.splitext(f)[0], parse_ips(open(path, "rb").read())
            except (ValueError, UnicodeDecodeError) as e:
                raise ValueError("the code mod %s, %s: %s" % (mod, f, e))
            target = next((m for m in modules.values() if bid and same_build(m.build_id, bid)), None)
            if target is None:
                log("exefs mod %s: %s is for build %s, which this game is not: left out" % (mod, f, (bid or "?")[:16]))
                continue
            for mem, data in patches:
                try:
                    target.patch(mem, data)
                except ValueError as e:
                    raise ValueError("the code mod %s, %s: %s" % (mod, f, e))
            applied += len(patches)
            used += 1
            log("exefs mod %s: %s, %d patches on %s" % (mod, f, len(patches), os.path.basename(target.path)))
    if not dry:
        for m in modules.values():
            m.save()
    return applied, used


def main():
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    try:
        applied, used = apply(sys.argv[1], sys.argv[2], dry="--list" in sys.argv)
    except ValueError as e:
        raise SystemExit(str(e))
    print("exefs mods: %d patches from %d files" % (applied, used))


if __name__ == "__main__":
    main()
