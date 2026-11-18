/*
 * mem_probe.c - Native C Linux ZRAM, MGLRU, PSI & Per-Process RSS/Swap Probe
 */
#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include <ctype.h>
#include <dirent.h>
#include <fcntl.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

typedef struct {
    int pid;
    char name[32];
    double rss_mb;
    double swap_mb;
} MemProc;

static int cmp_mem_desc(const void *a, const void *b) {
    const MemProc *pa = (const MemProc *)a;
    const MemProc *pb = (const MemProc *)b;
    double sa = pa->rss_mb + pa->swap_mb;
    double sb = pb->rss_mb + pb->swap_mb;
    return (sb > sa) ? 1 : (sb < sa ? -1 : 0);
}

static bool read_line(const char *path, char *out, size_t sz) {
    int fd = open(path, O_RDONLY);
    if (fd < 0) return false;
    ssize_t n = read(fd, out, sz - 1);
    close(fd);
    if (n <= 0) return false;
    out[n] = '\0';
    while (n > 0 && (out[n - 1] == '\n' || out[n - 1] == ' ')) out[--n] = '\0';
    return true;
}

static void json_esc(const char *s, char *out, size_t sz) {
    size_t j = 0;
    for (size_t i = 0; s && s[i] && j + 2 < sz; i++) {
        unsigned char c = (unsigned char)s[i];
        if (c == '"' || c == '\\') {
            if (j + 2 >= sz) break;
            out[j++] = '\\'; out[j++] = (char)c;
        } else if (c >= 0x20) out[j++] = (char)c;
    }
    out[j] = '\0';
}

int main(int argc, char *argv[]) {
    bool as_json = false;
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--json") == 0 || strcmp(argv[i], "-j") == 0) as_json = true;
    }

    double mem_tot = 0, mem_avail = 0, buffers = 0, cached = 0, swap_tot = 0, swap_free = 0;
    FILE *mf = fopen("/proc/meminfo", "r");
    if (mf) {
        char line[256];
        unsigned long long kb = 0;
        while (fgets(line, sizeof(line), mf)) {
            if (sscanf(line, "MemTotal: %llu kB", &kb) == 1) mem_tot = kb / 1024.0;
            else if (sscanf(line, "MemAvailable: %llu kB", &kb) == 1) mem_avail = kb / 1024.0;
            else if (sscanf(line, "Buffers: %llu kB", &kb) == 1) buffers = kb / 1024.0;
            else if (sscanf(line, "Cached: %llu kB", &kb) == 1) cached = kb / 1024.0;
            else if (sscanf(line, "SwapTotal: %llu kB", &kb) == 0 ? false : (sscanf(line, "SwapTotal: %llu kB", &kb) == 1)) swap_tot = kb / 1024.0;
            else if (sscanf(line, "SwapFree: %llu kB", &kb) == 1) swap_free = kb / 1024.0;
        }
        fclose(mf);
    }

    double psi_some = 0.0, psi_full = 0.0;
    FILE *pf = fopen("/proc/pressure/memory", "r");
    if (pf) {
        char line[256];
        while (fgets(line, sizeof(line), pf)) {
            if (strncmp(line, "some ", 5) == 0) sscanf(line, "some avg10=%lf", &psi_some);
            else if (strncmp(line, "full ", 5) == 0) sscanf(line, "full avg10=%lf", &psi_full);
        }
        fclose(pf);
    }

    char mglru_hex[32] = "disabled";
    read_line("/sys/kernel/mm/lru_gen/enabled", mglru_hex, sizeof(mglru_hex));

    unsigned long long z_orig = 0, z_compr = 0, z_used = 0;
    char z_alg[64] = "zstd";
    FILE *zf = fopen("/sys/block/zram0/mm_stat", "r");
    if (zf) {
        if (fscanf(zf, "%llu %llu %llu", &z_orig, &z_compr, &z_used) != 3) { z_orig = z_compr = z_used = 0; }
        fclose(zf);
    }
    read_line("/sys/block/zram0/comp_algorithm", z_alg, sizeof(z_alg));

    double z_orig_mb = (double)z_orig / (1024.0 * 1024.0);
    double z_compr_mb = (double)z_compr / (1024.0 * 1024.0);
    double z_ratio = (z_compr > 0) ? ((double)z_orig / (double)z_compr) : 1.0;

    MemProc procs[1024];
    size_t nproc = 0;
    DIR *pd = opendir("/proc");
    if (pd) {
        struct dirent *de;
        while ((de = readdir(pd)) != NULL && nproc < 1024) {
            if (!isdigit((unsigned char)de->d_name[0])) continue;
            int pid = atoi(de->d_name);
            char sp[128], line[256], name[32] = "";
            snprintf(sp, sizeof(sp), "/proc/%d/status", pid);
            FILE *sf = fopen(sp, "r");
            if (!sf) continue;
            double rss = 0, sw = 0;
            while (fgets(line, sizeof(line), sf)) {
                unsigned long long kb = 0;
                if (strncmp(line, "Name:", 5) == 0) sscanf(line, "Name:%31s", name);
                else if (sscanf(line, "VmRSS: %llu kB", &kb) == 1) rss = kb / 1024.0;
                else if (sscanf(line, "VmSwap: %llu kB", &kb) == 1) sw = kb / 1024.0;
            }
            fclose(sf);
            if (rss < 10.0 && sw < 1.0) continue;
            procs[nproc].pid = pid;
            snprintf(procs[nproc].name, sizeof(procs[nproc].name), "%.31s", name[0] ? name : "proc");
            procs[nproc].rss_mb = rss;
            procs[nproc].swap_mb = sw;
            nproc++;
        }
        closedir(pd);
    }
    qsort(procs, nproc, sizeof(MemProc), cmp_mem_desc);

    if (as_json) {
        char mglru_e[48], alg_e[96];
        json_esc(mglru_hex, mglru_e, sizeof(mglru_e));
        json_esc(z_alg, alg_e, sizeof(alg_e));
        printf("{\n"
               "  \"ram\": {\"total_mb\": %.1f, \"used_mb\": %.1f, \"avail_mb\": %.1f, \"cache_mb\": %.1f},\n"
               "  \"swap\": {\"total_mb\": %.1f, \"used_mb\": %.1f},\n"
               "  \"psi\": {\"some_avg10\": %.2f, \"full_avg10\": %.2f},\n"
               "  \"mglru\": \"%s\",\n"
               "  \"zram\": {\"orig_mb\": %.2f, \"compr_mb\": %.2f, \"ratio\": %.2f, \"algo\": \"%s\"},\n"
               "  \"top_procs\": [",
               mem_tot, mem_tot - mem_avail, mem_avail, buffers + cached,
               swap_tot, swap_tot - swap_free, psi_some, psi_full,
               mglru_e, z_orig_mb, z_compr_mb, z_ratio, alg_e);
        size_t tp = nproc < 6 ? nproc : 6;
        for (size_t i = 0; i < tp; i++) {
            char ne[64];
            json_esc(procs[i].name, ne, sizeof(ne));
            printf("%s\n    {\"pid\": %d, \"name\": \"%s\", \"rss_mb\": %.1f, \"swap_mb\": %.1f}",
                   i == 0 ? "" : ",", procs[i].pid, ne, procs[i].rss_mb, procs[i].swap_mb);
        }
        printf("\n  ]\n}\n");
    } else {
        printf("=== MemPulse MGLRU & ZRAM Telemetry ===\n");
        printf("  RAM   : %.1f / %.1f GB used (Cache: %.1f GB)\n",
               (mem_tot - mem_avail) / 1024.0, mem_tot / 1024.0, (buffers + cached) / 1024.0);
        printf("  MGLRU : %s | PSI some=%.2f%% full=%.2f%%\n", mglru_hex, psi_some, psi_full);
        printf("  ZRAM  : %.1f MB -> %.1f MB (%.2fx %s)\n", z_orig_mb, z_compr_mb, z_ratio, z_alg);
    }
    return 0;
}
