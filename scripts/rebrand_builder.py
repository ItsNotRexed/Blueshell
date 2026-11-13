"""(blueshell) Hookshot's builder and setup made BlueShell's: the app's names, the game's names, the build it supports.

    python -I scripts/rebrand_builder.py

Run again after merging Hookshot's builder changes: it is idempotent. Files the game and make_game.py share with the builder by
name (hookshot_version.txt, .hookshot_exefs, hookshot_pieces.prof, ...) keep their names; only what the player sees and the game's
own binaries change. The setup's GitHub feed is left in the text but never reached: BlueShell is installed locally
(scripts/install_builder_local.py).
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
B = os.path.join(ROOT, "builder")

# (internal names shared with nx2/make_game.py, host/ and gpu/vk: unchanged)
KEEP = ["hookshot_version.txt", ".hookshot_exefs", ".hookshot_fsr", ".hookshot_romfs", "hookshot_pieces.prof", "hookshot.res",
        ".hookshot-portable", "hookshot-setup.txt", "hookshot.png", "hookshot.ico", "hookshot_options.ini", "hookshot_shaders.bin",
        "HOOKSHOT_"]

RULES = [
    ("THE LEGEND OF ZELDA", "BLUESHELL"),
    ("The Legend of Zelda: Ocarina of Time, built by Hookshot", "Mario Kart World, built by BlueShell"),
    ("Ocarina of Time", "Mario Kart World"),
    ("d'Mario Kart World", "de Mario Kart World"),
    ("e0f3ccfa", "d00e4f39"),
    ("hookshot.exe", "blueshell.exe"),
    ("HookshotBuilder", "BlueShellBuilder"),
    ("HookshotSetup", "BlueShellSetup"),
    ("Hookshot.BuilderSetup", "BlueShell.BuilderSetup"),
    ("Hookshot", "BlueShell"),
]


def rebrand(text):
    held = {}
    for i, k in enumerate(KEEP):
        token = "\x00%d\x00" % i
        held[token] = k
        text = text.replace(k, token)
    for a, b in RULES:
        text = text.replace(a, b)
    for token, k in held.items():
        text = text.replace(token, k)
    return text


def main():
    old, new = os.path.join(B, "HookshotBuilder"), os.path.join(B, "BlueShellBuilder")
    if os.path.isdir(old) and not os.path.isdir(new):
        os.rename(old, new)
    proj = os.path.join(new, "HookshotBuilder.csproj")
    if os.path.exists(proj):
        os.rename(proj, os.path.join(new, "BlueShellBuilder.csproj"))
    changed = 0
    for folder in (new, os.path.join(B, "setup")):
        for name in os.listdir(folder):
            if not re.search(r"\.(cs|xaml|csproj|manifest|c|h|rc)$", name):
                continue
            p = os.path.join(folder, name)
            with open(p, encoding="utf-8", newline="") as f:
                s = f.read()
            t = rebrand(s)
            if t != s:
                with open(p, "w", encoding="utf-8", newline="") as f:
                    f.write(t)
                changed += 1
    print("rebranded %d files" % changed)


if __name__ == "__main__":
    sys.exit(main())
