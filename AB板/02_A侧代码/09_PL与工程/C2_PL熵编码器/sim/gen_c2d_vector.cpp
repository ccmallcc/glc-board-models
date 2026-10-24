//======================================================================
// gen_c2d_vector.cpp —— 为 C2d (rans_cdf.v) 生成黄金向量
//
// 自检设计（这是本工具可信的关键）：
//   ① 调官方 BoardEncoder::encode() 拿到 payload_gold       —— 真值
//   ② 在本文件里**重新展开**一遍并逐项 trace（start/range/bypass）
//      → 把 trace 出来的序列**倒序**喂给 Rans64EncPut → payload_mine
//   ③ 断言 payload_mine == payload_gold
//   若二者不等，直接报错退出 —— 说明 trace 与官方实现有偏差，向量不可用。
//
// 用法：
//   g++ -O2 -std=c++11 -o gen_c2d_vector gen_c2d_vector.cpp
//   ./gen_c2d_vector <sym.i32> <scales.f32> <out前缀>
//
// 产出：
//   <out>_logical.txt  每行 "k value"        —— RTL 的输入流
//   <out>_rans.txt     每行 "start range bypass last" —— RTL 的期望输出流
//   <out>_payload.hex  payload 十六进制
//   <out>_stats.txt    n_syms/n_escape/n_bypass_syms/max_raw/max_n_bypass/out_of_domain
//======================================================================
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>

#include "glc_board_encoder.h"

struct RSym {
    uint16_t start;
    uint16_t range;
    bool     bypass;
};

int main(int argc, char **argv) {
    if (argc < 4) {
        std::printf("usage: %s <sym.i32> <scales.f32> <outprefix>\n", argv[0]);
        return 2;
    }
    const char *psym = argv[1], *pscl = argv[2], *opre = argv[3];

    // ---- 读输入 ----
    std::vector<int32_t> symbols;
    std::vector<float>   scales;
    {
        FILE *f = std::fopen(psym, "rb");
        if (!f) { std::printf("cannot open %s\n", psym); return 2; }
        std::fseek(f, 0, SEEK_END); long n = std::ftell(f); std::fseek(f, 0, SEEK_SET);
        symbols.resize(n / 4);
        if (std::fread(symbols.data(), 4, symbols.size(), f) != symbols.size()) return 2;
        std::fclose(f);
    }
    {
        FILE *f = std::fopen(pscl, "rb");
        if (!f) { std::printf("cannot open %s\n", pscl); return 2; }
        std::fseek(f, 0, SEEK_END); long n = std::ftell(f); std::fseek(f, 0, SEEK_SET);
        scales.resize(n / 4);
        if (std::fread(scales.data(), 4, scales.size(), f) != scales.size()) return 2;
        std::fclose(f);
    }
    if (symbols.size() != scales.size()) {
        std::printf("size mismatch %zu vs %zu\n", symbols.size(), scales.size());
        return 2;
    }
    std::printf("输入: %zu 个符号\n", symbols.size());

    // ---- ① 官方真值 ----
    BoardEncoder enc;
    enc.encode(symbols, scales);
    const std::string &gold = enc.payload;
    std::printf("官方 encode(): payload %zu B, escape %zu, bypass %zu, "
                "max_raw %u, max_n_bypass %d, out_of_domain %d\n",
                gold.size(), enc.n_escape, enc.n_bypass_syms, enc.max_raw,
                enc.max_n_bypass, (int)enc.out_of_domain);

    // ---- ② 自己展开 + trace ----
    std::vector<RSym> seq;
    std::vector<std::pair<int, int> > logical;   // (k, value)
    seq.reserve(symbols.size() * 2);
    size_t n_esc = 0, n_by = 0;
    uint32_t mx_raw = 0; int mx_nby = 0; bool ood = false;

    for (size_t i = 0; i < symbols.size(); ++i) {
        const int k = glc_build_index(scales[i]);
        const uint32_t *cdf = glc_row_of(k);
        const int32_t max_value = (int32_t)GLC_CDF_LENGTH[k] - 2;
        int32_t value = symbols[i] - GLC_CDF_OFFSET[k];
        uint32_t raw_val = 0; bool escaped = false;
        if (value < 0) {
            raw_val = (uint32_t)(-2 * value - 1); value = max_value; escaped = true; ++n_esc;
        } else if (value >= max_value) {
            raw_val = (uint32_t)(2 * (value - max_value)); value = max_value; escaped = true; ++n_esc;
        }
        if (raw_val > mx_raw) mx_raw = raw_val;
        logical.push_back(std::make_pair(k, (int)symbols[i]));

        RSym s; s.start = (uint16_t)cdf[value];
        s.range = (uint16_t)(cdf[value + 1] - cdf[value]); s.bypass = false;
        seq.push_back(s);                                 // push 主符号（与 C++ 同序）

        if (escaped) {
            int32_t n_bypass = 0;
            for (uint64_t rv = raw_val; rv != 0; rv >>= GLC_BYPASS_PRECISION) ++n_bypass;
            if (n_bypass > 7) ood = true;
            if (n_bypass > mx_nby) mx_nby = n_bypass;
            int32_t val = n_bypass;
            while (val >= GLC_MAX_BYPASS_VAL) {
                RSym b; b.start = GLC_MAX_BYPASS_VAL; b.range = GLC_MAX_BYPASS_VAL + 1; b.bypass = true;
                seq.push_back(b); ++n_by; val -= GLC_MAX_BYPASS_VAL;
            }
            RSym b; b.start = (uint16_t)val; b.range = (uint16_t)(val + 1); b.bypass = true;
            seq.push_back(b); ++n_by;
            for (int32_t j = 0; j < n_bypass; ++j) {
                int32_t v = (int32_t)((raw_val >> (j * GLC_BYPASS_PRECISION)) & GLC_MAX_BYPASS_VAL);
                RSym r; r.start = (uint16_t)v; r.range = (uint16_t)(v + 1); r.bypass = true;
                seq.push_back(r); ++n_by;
            }
        }
    }

    // ---- ③ trace 序列倒序跑一遍，必须与真值相同 ----
    std::vector<uint32_t> pay_words;
    {
        Rans64State st; Rans64EncInit(&st);
        std::vector<uint32_t> out(seq.size() + 8, 0xCC);
        uint32_t *ptr = out.data() + out.size();
        for (size_t i = seq.size(); i-- > 0; ) {
            const RSym &s = seq[i];
            if (!s.bypass) Rans64EncPut(&st, &ptr, s.start, s.range, GLC_PRECISION);
            else           Rans64EncPutBits(&st, &ptr, s.start, GLC_BYPASS_PRECISION);
        }
        Rans64EncFlush(&st, &ptr);
        const size_t nw = (size_t)(out.data() + out.size() - ptr);
        std::string mine(reinterpret_cast<char *>(ptr), nw * 4);
        if (mine != gold) {
            std::printf("❌ 自检失败：我展开的序列跑出的 payload (%zu B) != 官方 (%zu B)\n",
                        mine.size(), gold.size());
            return 1;
        }
        pay_words.assign(ptr, ptr + nw);      // 内存顺序的 32 位字
        std::printf("✅ 自检通过：展开序列倒序重跑 == 官方 payload（%zu B = %zu 字）\n",
                    gold.size(), nw);
    }

    // ---- 与官方统计比对 ----
    std::printf("   统计比对: escape %zu/%zu  bypass %zu/%zu  max_raw %u/%u  "
                "max_n_bypass %d/%d  ood %d/%d\n",
                n_esc, enc.n_escape, n_by, enc.n_bypass_syms, mx_raw, enc.max_raw,
                mx_nby, enc.max_n_bypass, (int)ood, (int)enc.out_of_domain);
    if (n_esc != enc.n_escape || n_by != enc.n_bypass_syms ||
        mx_raw != enc.max_raw || mx_nby != enc.max_n_bypass) {
        std::printf("❌ 统计不一致\n"); return 1;
    }

    // ---- 落盘 ----
    // ⚠️ **顺序是本工具最容易搞错的地方，这里定死**：
    //   C++ 的 `syms` 是"每个逻辑符号 push [主, b_hi×m, b_last, r_0..r_{n-1}]"，
    //   然后 **pop_back 倒序编码** ⇒ 真正的**编码顺序 = reverse(syms)**。
    //   展开到逻辑符号层面就是：
    //       逻辑符号按 **i = n-1 → 0** 处理；
    //       每个逻辑符号内部按 **[r_{n-1} … r_0, b_last, b_hi×m, 主]** 发射。
    //   ⇒ 所以：
    //       `_rans.txt`    按 **reverse(seq)** 写 = RTL 的发射顺序（最后一行是 i=0 的主符号）
    //       `_logical.txt` 按 **i = n-1 → 0** 写 = RTL 的消费顺序
    //   `last` 只挂在两边的**最后一行**（即 i=0 的主符号）上。
    std::string f;

    f = std::string(opre) + "_rans.txt";
    { FILE *o = std::fopen(f.c_str(), "w");
      for (size_t i = seq.size(); i-- > 0; ) {
          std::fprintf(o, "%u %u %d %d\n", seq[i].start, seq[i].range,
                       seq[i].bypass ? 1 : 0, (i == 0) ? 1 : 0);
      }
      std::fclose(o); }

    f = std::string(opre) + "_logical.txt";
    { FILE *o = std::fopen(f.c_str(), "w");
      for (size_t i = logical.size(); i-- > 0; ) {
          std::fprintf(o, "%d %d %d\n", logical[i].first, logical[i].second,
                       (i == 0) ? 1 : 0);   // k value last
      }
      std::fclose(o); }

    f = std::string(opre) + "_payload.hex";
    { FILE *o = std::fopen(f.c_str(), "w");
      static const char *H = "0123456789abcdef";
      for (size_t i = 0; i < gold.size(); ++i) {
          unsigned char c = (unsigned char)gold[i];
          std::fputc(H[c >> 4], o); std::fputc(H[c & 15], o);
      }
      std::fputc('\n', o); std::fclose(o); }
    f = std::string(opre) + "_payload_words.txt";
    { FILE *o = std::fopen(f.c_str(), "w");
      for (size_t i = 0; i < pay_words.size(); ++i) std::fprintf(o, "%08x\n", pay_words[i]);
      std::fclose(o); }

    f = std::string(opre) + "_stats.txt";
    { FILE *o = std::fopen(f.c_str(), "w");
      std::fprintf(o, "n_logical %zu\nn_rans_syms %zu\nn_escape %zu\n"
                      "n_bypass_syms %zu\nmax_raw %u\nmax_n_bypass %d\n"
                      "out_of_domain %d\npayload_bytes %zu\n",
                   logical.size(), seq.size(), n_esc, n_by, mx_raw, mx_nby,
                   (int)ood, gold.size());
      std::fclose(o); }

    std::printf("产出: %s_{logical,rans}.txt %s_payload.hex %s_stats.txt\n", opre, opre, opre);
    return 0;
}
