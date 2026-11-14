"""(blueshell) The Builder's save options (nx2/make_game.py --save-folder, --full-save):

- save_folder(out, folder): the game keeps its saves in <folder> (hookshot_options.ini's save_folder=, which host/hos_main.c
  reads at start; the Insert menu keeps the line). None or "": beside the game, the folder's user\\ as before.
- full_save(save_root): a player-made 100% save, downloaded from GameBanana on this PC (it is not BlueShell's to ship:
  CC BY-NC-ND 4.0, "Download and install" allowed): "Great Mario Kart Save File (1.0.0)" by hydro sucks,
  https://gamebanana.com/mods/735334: every character, kart, outfit and sticker, the Peach Medallions and P Switches.
  Checked by its SHA-256 before use. A save already there is moved to save-backup-<date time> beside it first, never deleted.

The saves' place in either root: save/5a3c9e1f0b7d24680000000000000001/Play/account.sav (host/nn_applet.c's one user).
"""
import datetime
import hashlib
import io
import os
import shutil
import urllib.request
import zipfile

USER = "5a3c9e1f0b7d24680000000000000001"
FULL_SAVE_URL = "https://gamebanana.com/dl/1873422"
FULL_SAVE_SHA256 = "6673e6f6bdf47fd49481566a41fcac955ea54ce41b5d91191dea27f65b46fbee"
FULL_SAVE_MEMBER = "Complete 100% Save File (1.0)/0400C3F00006E000/Play/account.sav"
FULL_SAVE_PAGE = "https://gamebanana.com/mods/735334"
TIMEOUT = 60


def save_folder(out, folder):
    """save_folder=<folder> in <out>/hookshot_options.ini (taken out when folder is empty)"""
    ini = os.path.join(out, "hookshot_options.ini")
    lines = []
    if os.path.isfile(ini):
        with open(ini, encoding="utf-8", errors="replace") as f:
            lines = [l for l in f.read().splitlines() if not l.startswith("save_folder=")]
    if folder:
        folder = os.path.abspath(folder)
        os.makedirs(folder, exist_ok=True)
        lines.append("save_folder=" + folder)
    with open(ini, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + ("\n" if lines else ""))
    return folder or os.path.join(out, "user")


def set_option(out, key, value):
    """<key>=<value> in <out>/hookshot_options.ini, in place of the line the file had (the Insert menu keeps it)"""
    ini = os.path.join(out, "hookshot_options.ini")
    lines = []
    if os.path.isfile(ini):
        with open(ini, encoding="utf-8", errors="replace") as f:
            lines = [l for l in f.read().splitlines() if not l.startswith(key + "=")]
    lines.append("%s=%s" % (key, value))
    with open(ini, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")


def fetch(url=FULL_SAVE_URL, opener=urllib.request.urlopen):
    req = urllib.request.Request(url, headers={"User-Agent": "BlueShellBuilder"})
    with opener(req, timeout=TIMEOUT) as r:
        return r.read()


def full_save(save_root, data=None, say=print, now=None):
    """The 100% save into <save_root>; the save there before kept in a backup folder. Returns the backup's path or None"""
    if data is None:
        say("downloading the 100%% save from %s" % FULL_SAVE_PAGE)
        data = fetch()
    if hashlib.sha256(data).hexdigest() != FULL_SAVE_SHA256:
        raise ValueError("the 100%% save downloaded from %s is not the file expected (SHA-256): not used" % FULL_SAVE_PAGE)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        sav = z.read(FULL_SAVE_MEMBER)
    play = os.path.join(save_root, "save", USER, "Play")
    backup = None
    if os.path.isdir(play) and os.listdir(play):
        stamp = (now or datetime.datetime.now()).strftime("%Y-%m-%d %H%M%S")
        backup = os.path.join(save_root, "save-backup-" + stamp)
        shutil.copytree(play, os.path.join(backup, "Play"))
        say("your save before was kept in %s" % backup)
    os.makedirs(play, exist_ok=True)
    tmp = os.path.join(play, "account.sav.part")
    with open(tmp, "wb") as f:
        f.write(sav)
    os.replace(tmp, os.path.join(play, "account.sav"))
    say("the 100%% save is in %s" % play)
    return backup
