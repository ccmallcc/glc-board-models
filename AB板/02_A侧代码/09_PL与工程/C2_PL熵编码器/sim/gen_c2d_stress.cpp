//======================================================================
// gen_c2d_stress.cpp —— 构造**会触发 escape/bypass** 的向量
//
// 为什么需要它：真实板端数据实测 **escape = 0 次**（V16），
// 所以 rans_cdf.v 的 escape/bypass 展开通路**根本不会被真实数据走到**。
// 必须人工构造越界符号，否则那部分 RTL 等于没测。
//
// ⚠️ 输入按 int16 有符号：`d_value` 是 16 位（见 rans_cdf.v）。
//    因此 raw_val 上限受 sym ∈ [-32768, 32767] 约束：
//      v<0 侧 : raw = -2v-1, v = sym - OFFSET  =>  最大 raw ≈ 2*(32768+1565) ≈ 68665
//      v>=mx 侧: raw = 2(v-mx)                  =>  最大 raw ≈ 2*(32767+1565) ≈ 68664
//    → n_bypass 最大 = 4（2^16=65536 < raw < 2^20）。
//    ⇒ **n_bypass > 7（out_of_domain）在本位宽下不可能发生**，那段逻辑是安全网。
//
// 用法：
//   g++ -O2 -std=c++11 -o gen_c2d_stress gen_c2d_stress.cpp
//   ./gen_c2d_stress <out_sym.i32> <out_scales.f32>
//======================================================================
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cmath>
#include <vector>

#include "glc_board_encoder.h"

// 找一个能把 glc_build_index 映到 k 的 scale。
// 可证：SCALE_TABLE 单调递增且无重复 ⇒ scale = SCALE_TABLE[k] 恰好给出 idx = k：
//   idx = 63 - #{i∈[0,62] : TABLE[i] >= scale}
//   scale ∈ (TABLE[k-1], TABLE[k]] ⇒ TABLE[i] >= scale ⟺ i >= k ⇒ idx = k
static float scale_for_row(int k) {
    float s = GLC_SCALE_TABLE[k];
    if (glc_build_index(s) == k) return s;
    // 兜底：在相邻表值之间细扫（理论上不会走到）
    const float lo = (k == 0) ? 0.10f : GLC_SCALE_TABLE[k - 1];
    const float hi = (k + 1 < GLC_NUM_CDFS) ? GLC_SCALE_TABLE[k + 1] : 300.0f;
    for (int t = 0; t <= 200000; ++t) {
        float c = lo + (hi - lo) * (float)t / 200000.0f;
        if (glc_build_index(c) == k) return c;
    }
    std::printf("找不到映射到 k=%d 的 scale（TABLE[%d]=%.6f）\n", k, k, GLC_SCALE_TABLE[k]);
    std::exit(1);
}

int main(int argc, char **argv) {
    if (argc < 3) { std::printf("usage: %s <out_sym.i32> <out_scales.f32>\n", argv[0]); return 2; }

    std::vector<int32_t> syms;
    std::vector<float>   scls;

    // 每个 (k, 构造式) 一组；构造式覆盖 in-range 与两侧 escape
    for (int k = 0; k < GLC_NUM_CDFS; ++k) {
        const float sc = scale_for_row(k);
        const int32_t off = GLC_CDF_OFFSET[k];
        const int32_t mx  = (int32_t)GLC_CDF_LENGTH[k] - 2;

        int32_t cand[11];
        int nc = 0;
        cand[nc++] = off;                    // v = 0            （in range）
        cand[nc++] = off + mx - 1;           // v = mx-1         （in range，顶部）
        cand[nc++] = off - 1;                // v = -1 -> raw=1  （负 escape，nbyp=1）
        cand[nc++] = off - 2;                // v = -2 -> raw=3  （nbyp=1）
        cand[nc++] = off - 15;               // raw=29           （nbyp=2）
        cand[nc++] = off - 4095;             // raw=8191         （nbyp=4）
        cand[nc++] = off - 16000;            // raw=31999        （nbyp=4）
        cand[nc++] = off + mx;               // v = mx -> raw=0  （escape 但 nbyp=0！）
        cand[nc++] = off + mx + 1;           // raw=2            （nbyp=1）
        cand[nc++] = off + mx + 4095;        // raw=8190         （nbyp=4）
        cand[nc++] = off + mx + 16000;       // raw=32000        （nbyp=4）

        for (int i = 0; i < nc; ++i) {
            if (cand[i] < -32768 || cand[i] > 32767) {
                std::printf("⚠️ k=%d cand[%d]=%d 超出 int16，跳过\n", k, i, cand[i]);
                continue;
            }
            syms.push_back(cand[i]);
            scls.push_back(sc);
        }
    }

    // ⭐ 让**最后一个**逻辑符号也是 escape 的（检验 s_last 落在主符号上）
    {
        const int k = 63;
        syms.push_back(GLC_CDF_OFFSET[k] - 7);   // raw=13, nbyp=1
        scls.push_back(scale_for_row(k));
    }

    FILE *f = std::fopen(argv[1], "wb");
    if (!f) { std::printf("cannot write %s\n", argv[1]); return 2; }
    std::fwrite(syms.data(), 4, syms.size(), f); std::fclose(f);
    f = std::fopen(argv[2], "wb");
    if (!f) { std::printf("cannot write %s\n", argv[2]); return 2; }
    std::fwrite(scls.data(), 4, scls.size(), f); std::fclose(f);

    std::printf("压力向量: %zu 个逻辑符号（64 行 x 最多 11 式 + 1）\n", syms.size());
    std::printf("  scale 范围 [%.4f, %.4f]\n", scls.front(), scls.back());

    // 自检：统计会触发多少 escape
    {
        BoardEncoder e; e.encode(syms, scls);
        std::printf("  官方 encode(): payload %zu B, escape %zu, bypass符号 %zu, "
                    "max_raw %u, max_n_bypass %d, out_of_domain %d\n",
                    e.payload.size(), e.n_escape, e.n_bypass_syms, e.max_raw,
                    e.max_n_bypass, (int)e.out_of_domain);
        if (e.n_escape == 0) { std::printf("❌ 一个 escape 都没触发，向量无效\n"); return 1; }
        if (e.max_n_bypass < 4) std::printf("⚠️ max_n_bypass 只有 %d，期望 4\n", e.max_n_bypass);
    }
    std::printf("-> %s / %s\n", argv[1], argv[2]);
    return 0;
}
