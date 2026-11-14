/* (blueshell) Unlock everything: with unlock_everything=1 in hookshot_options.ini (the Insert menu's Unlock everything, the
   Builder's tick) or HOS_UNLOCK_ALL=1, the save the game opens (Play/account.sav) gets every driver and costume, vehicle and
   sticker, the Special Cup and Mirror, as a save editor does; everything the save had stays. Edited once a session, before
   nn_fs.c opens it; a copy of the save as it was goes to save-backup-unlock beside the saves first, once.
   Ported from adriadam10/mkw-recomp (MIT, runtime/core/hacks/unlock.c at c06721d), which is from
   Ca1nM/mario-kart-world-save-editor (MIT, mkw_core.py unlock_all / set_owned / reveal_special_cup at b12cbe6): each category is
   a length-prefixed list of owned ids, a parallel per-slot state array and, for drivers, one bit per owned slot; new items are
   appended with the state the game gives a new one. The arrays are found by key hash in the save's own table, so any game
   version; the offsets of game data Product.100 (1.0.0) are the fallback. */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include "hos_paths.h"
#include "mkw_unlock_ids.h"
void hos_log(const char *fmt, ...);   /* (hos.h's: this file stands alone, for tests/test_mkw_unlock.py) */

#define SAVE_MAGIC 0x01020304u
#define KEY_TABLE 0x20u
#define SAVE_SIZE_100 850928u
#define SPECIAL_CUP_SLOT 15u
#define MIRROR_OPEN_KEY 0x2F65471Cu   /* (a saved Int the class list offers Mirror by: its value sits in the table entry) */

typedef struct { uint32_t key_hash, offset_100; } Array;
typedef struct {
    const char *name;
    const uint32_t *ids;
    const int *n;
    Array list, state, mask;   /* (mask.key_hash 0: none) */
    uint32_t cap, new_state;
} Category;

static const Category cats[] = {
    {"drivers", unlock_driver_ids, &unlock_driver_ids_n, {0x44850554, 0x29800}, {0xED0C72BF, 0x683C}, {0xCE4D2DD9, 0x6A8}, 1000, 3},
    {"vehicles", unlock_vehicle_ids, &unlock_vehicle_ids_n, {0x1E849D5C, 0x63F28}, {0xF39B8041, 0x5704}, {0, 0}, 1000, 3},
    {"stickers", unlock_sticker_ids, &unlock_sticker_ids_n, {0xB8A3BA35, 0x2A7A4}, {0xE85996AD, 0x8E0}, {0, 0}, 5000, 1},
};
static const Array cup_progress = {0x55A6E00E, 0xF5B0};
static const Array cup_open_in_gp = {0x9A164573, 0x72C};

typedef struct { uint32_t list, state, mask, cap; } Located;

static uint32_t rd(const uint8_t *b, uint32_t off) {
    uint32_t v;
    memcpy(&v, b + off, 4);
    return v;
}
static void wr(uint8_t *b, uint32_t off, uint32_t v) { memcpy(b + off, &v, 4); }

static uint32_t locate_array(const uint8_t *b, uint64_t n, const Array *a, uint32_t *cap) {
    uint32_t count_at = 0;
    if (n >= KEY_TABLE + 8 && rd(b, 0) == SAVE_MAGIC) {
        const uint32_t table_end = rd(b, 8);
        if (table_end <= n && table_end % 8 == 0)
            for (uint32_t e = KEY_TABLE; e + 8 <= table_end && !count_at; e += 8)
                if (rd(b, e) == a->key_hash) count_at = rd(b, e + 4);
    }
    if (!count_at && n == SAVE_SIZE_100 && a->offset_100) count_at = a->offset_100 - 4;
    if (!count_at || count_at % 4 || (uint64_t)count_at + 4 > n) return 0;
    *cap = rd(b, count_at);
    if ((uint64_t)count_at + 4 + 4ull * *cap > n) return 0;
    return count_at + 4;
}

static int locate_category(const uint8_t *b, uint64_t n, const Category *c, Located *at) {
    uint32_t cap = 0;
    if (!(at->list = locate_array(b, n, &c->list, &cap)) || cap != c->cap) return 0;
    if (!(at->state = locate_array(b, n, &c->state, &cap)) || cap != c->cap) return 0;
    at->mask = 0;
    if (c->mask.key_hash && (!(at->mask = locate_array(b, n, &c->mask, &cap)) || cap != c->cap)) return 0;
    at->cap = c->cap;
    return 1;
}

static int own_all(uint8_t *b, const Category *c, const Located *at) {
    uint32_t have = 0;
    while (have < at->cap && rd(b, at->list + 4 * have)) have++;
    int added = 0;
    for (int i = 0; i < *c->n && have < at->cap; i++) {
        const uint32_t id = c->ids[i];
        uint32_t k = 0;
        while (k < have && rd(b, at->list + 4 * k) != id) k++;
        if (k < have) continue;
        wr(b, at->list + 4 * have, id);
        wr(b, at->state + 4 * have, c->new_state);
        if (at->mask) wr(b, at->mask + 4 * (have / 32), rd(b, at->mask + 4 * (have / 32)) | 1u << (have % 32));
        have++, added++;
    }
    return added;
}

/* Everything owned in the save image b (n bytes); how many things changed, 0 for a layout this does not know */
int hos_unlock_save(uint8_t *b, uint64_t n) {
    Located at[sizeof cats / sizeof *cats];
    uint32_t progress = 0, cup_slots = 0;
    int ok = n <= 0xffffffffu && (progress = locate_array(b, n, &cup_progress, &cup_slots)) && cup_slots > SPECIAL_CUP_SLOT;
    for (size_t k = 0; ok && k < sizeof cats / sizeof *cats; k++) ok = locate_category(b, n, &cats[k], &at[k]);
    if (!ok) {
        hos_log("unlock: account.sav (%llu bytes) is not a layout this knows: left as it is", (unsigned long long)n);
        return 0;
    }
    char note[160];
    int pos = 0, total = 0;
    for (size_t k = 0; k < sizeof cats / sizeof *cats; k++) {
        const int a = own_all(b, &cats[k], &at[k]);
        total += a;
        pos += snprintf(note + pos, sizeof note - (size_t)pos, "%s%s +%d", k ? "," : "", cats[k].name, a);
    }
    const uint32_t sc = progress + 4 * SPECIAL_CUP_SLOT;
    if (!rd(b, sc)) wr(b, sc, 2), total++;
    uint32_t flag_slots = 0;
    const uint32_t flags = locate_array(b, n, &cup_open_in_gp, &flag_slots);
    const uint32_t special_bit = 1u << SPECIAL_CUP_SLOT;
    if (flags && flag_slots > SPECIAL_CUP_SLOT && !(rd(b, flags) & special_bit)) wr(b, flags, rd(b, flags) | special_bit), total++;
    int mirror = 0;
    for (uint32_t e = KEY_TABLE, end = rd(b, 8); e + 8 <= end && e + 8 <= n; e += 8)
        if (rd(b, e) == MIRROR_OPEN_KEY) {
            mirror = 1;
            if (!rd(b, e + 4)) wr(b, e + 4, 1), total++;
            break;
        }
    hos_log("unlock: %s, Special Cup open, mirror %s", note, mirror ? "open" : "not in this save");
    return total;
}

static int unlock_wanted(void) {
    const char *e = getenv("HOS_UNLOCK_ALL");
    if (e && *e) return *e != '0';
    char path[1024];
    const DWORD n = hos_game_path_a(path, (DWORD)sizeof path);
    char *slash = n ? (strrchr(path, '\\') ? strrchr(path, '\\') : strrchr(path, '/')) : NULL;
    if (!slash) return 0;
    snprintf(slash + 1, (size_t)(path + sizeof path - slash - 1), "hookshot_options.ini");
    FILE *f = fopen(path, "r");
    int on = 0;
    char line[128];
    while (f && fgets(line, sizeof line, f))
        if (!strncmp(line, "unlock_everything=", 18)) on = atoi(line + 18) != 0;
    if (f) fclose(f);
    return on;
}

/* (nn_fs.c, before it opens a game file) the save, when it is Play/account.sav and Unlock everything is on: edited in place
   once a session, its first state kept in <saves>/save-backup-unlock (never written over) */
void hos_unlock_on_open(const char *host_path) {
    static int done;
    const size_t n = strlen(host_path);
    if (done || n < 16) return;
    const char *tail = host_path + n - 16;
    if (_stricmp(tail, "Play/account.sav") && _stricmp(tail, "Play\\account.sav")) return;
    done = 1;
    if (!unlock_wanted()) return;
    FILE *f = fopen(host_path, "rb");
    if (!f) return;
    fseek(f, 0, SEEK_END);
    const long size = ftell(f);
    fseek(f, 0, SEEK_SET);
    uint8_t *data = size > 0 ? (uint8_t *)malloc((size_t)size) : NULL;
    const int read_ok = data && fread(data, 1, (size_t)size, f) == (size_t)size;
    fclose(f);
    if (read_ok && hos_unlock_save(data, (uint64_t)size)) {
        /* (the backup: <saves>\save-backup-unlock\account.sav, beside the save folder's own save\ folder) */
        char backup[1024];
        snprintf(backup, sizeof backup, "%s", host_path);
        char *cut = NULL;   /* (up three: account.sav's Play, the user's folder, save: the saves' root) */
        for (int up = 0; up < 4; up++) {
            char *b = strrchr(backup, '\\'), *s = strrchr(backup, '/');
            cut = b > s ? b : s;
            if (!cut) break;
            if (up < 3) *cut = 0;
        }
        if (cut) {
            snprintf(cut + 1, sizeof backup - (size_t)(cut + 1 - backup), "save-backup-unlock");
            CreateDirectoryA(backup, NULL);
            strncat(backup, "\\account.sav", sizeof backup - strlen(backup) - 1);
            if (GetFileAttributesA(backup) == INVALID_FILE_ATTRIBUTES) CopyFileA(host_path, backup, TRUE);
        }
        char tmp[1024];
        snprintf(tmp, sizeof tmp, "%s.unlock", host_path);
        FILE *o = fopen(tmp, "wb");
        const int wrote = o && fwrite(data, 1, (size_t)size, o) == (size_t)size;
        if (o) fclose(o);
        if (wrote && MoveFileExA(tmp, host_path, MOVEFILE_REPLACE_EXISTING))
            hos_log("unlock: %s edited (Unlock everything)", host_path);
        else {
            DeleteFileA(tmp);
            hos_log("unlock: %s could not be written: left as it was", host_path);
        }
    }
    free(data);
}
