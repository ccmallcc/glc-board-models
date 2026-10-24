/* rans_fast.c —— GLC 解码端 rANS 熵解码 C 加速（A 侧 2026-10-12）
 *
 * 目的：板上 rans_ad_np.decode_symbols 是纯 Python 逐符号循环，实测 4 相位合计
 *       3.497 s（65536 个符号 ⇒ 约 53 us/符号）。瓶颈在 row[s+1] 的 numpy 标量
 *       索引（每次都要 numpy -> Python 转换）+ 线性扫描。
 *       本文件把那一段原样搬到 C，语义**逐位对齐** rans_ad_np.decode_symbols：
 *         x = LE64(buf[0:8]); ptr = 8
 *         每符号： m = x & 0xFFFF
 *                  s = 最小使 cdf[ci][s+1] > m 的 s（cdf[ci][0] == 0）
 *                  out = s + offset[ci]
 *                  x = freq*(x>>16) + (m - cdf[ci][s])
 *                  while x < 2^31: x = (x<<32) | LE32(buf[ptr:]); ptr += 4
 *                  越界则补 0（"流尾补零"）
 *
 * 编译（板上）：
 *     gcc -O2 -fPIC -shared -o rans_fast.so rans_fast.c
 * 用 ctypes 加载，不依赖 Python.h（避免 Python 版本耦合）。
 *
 * 接口：
 *     int rans_decode(const uint8_t *buf, long buflen,
 *                     const int32_t *idx, long n,
 *                     const int32_t *cdf, long stride,
 *                     const int32_t *cdf_len, const int32_t *offset,
 *                     int32_t *out)
 *     返回 0 成功；<0 失败（-1 参数非法 / -2 重归一化不收敛）
 */
#include <stdint.h>
#include <stddef.h>

#define PRECISION      16
#define PRECISION_MASK 0xFFFFu
#define RANS64_L       0x80000000ULL

static inline uint32_t rd32le(const uint8_t *p)
{
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) |
           ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

static inline uint64_t rd64le(const uint8_t *p)
{
    return (uint64_t)rd32le(p) | ((uint64_t)rd32le(p + 4) << 32);
}

int rans_decode(const uint8_t *buf, long buflen,
                const int32_t *idx, long n,
                const int32_t *cdf, long stride,
                const int32_t *cdf_len,
                const int32_t *offset,
                int32_t *out)
{
    long i, ptr;
    uint64_t x;

    if (!buf || !idx || !cdf || !cdf_len || !offset || !out) return -1;
    if (n <= 0) return 0;
    if (buflen < 8) return -1;

    x   = rd64le(buf);
    ptr = 8;

    for (i = 0; i < n; i++) {
        int32_t        ci  = idx[i];
        const int32_t *row = cdf + (size_t)ci * (size_t)stride;
        int32_t        L   = cdf_len[ci];
        uint32_t       m   = (uint32_t)(x & PRECISION_MASK);
        int32_t        s   = 0;
        uint32_t       start, freq;
        int            guard = 0;

        /* cdf 单调不减，线性扫描（row[0] == 0 <= m 恒成立） */
        while (s + 1 < L && (uint32_t)row[s + 1] <= m) s++;

        out[i] = s + offset[ci];

        start = (uint32_t)row[s];
        freq  = (uint32_t)row[s + 1] - start;
        x     = (uint64_t)freq * (x >> PRECISION) + (uint64_t)(m - start);

        /* 合法数据最多重归一化 1 次（x>=1 时 x<<32 >= 2^32 > 2^31）；
           guard 只用于防御损坏码流导致的死循环 */
        while (x < RANS64_L) {
            uint32_t v = 0;
            if (ptr + 4 <= buflen) v = rd32le(buf + ptr);
            x = (x << 32) | (uint64_t)v;
            ptr += 4;
            if (++guard > 8) return -2;
        }
    }
    return 0;
}

/* 供 Python 侧确认库真的被加载了 */
const char *rans_fast_version(void) { return "rans_fast 2026-10-12"; }
