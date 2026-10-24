// ===========================================================================
// rans_oracle.cpp -- 给 PL（FPGA）实现用的参考模型 / 测试向量生成器
// ---------------------------------------------------------------------------
// 为什么要有它：
//   板端 C++（assets\板端代码\glc_board_encoder.h）已经与 compressai
//   **逐字节对拍一致**，所以它就是我们唯一的"正确答案"来源（oracle）。
//   但 RTL 验证需要的不只是"最终码流"，还需要**逐符号的中间量**
//   （每拍的 state、freq、是否吐出 32 位字），否则出错时无法定位。
//
//   本程序做两件事：
//     1. 用官方头文件里的 BoardEncoder 算出 payload（**标准答案**）；
//     2. 独立重实现一遍带 trace 的等价循环，并**断言两者 payload 完全相同**
//        —— 只有断言通过，trace 才可信。
//
// 不依赖任何第三方库（不用 compressai / torch），只需要 glc_cdf_table.h。
//
// 编译（在 WSL 里，从仓库根目录）：
//   g++ -O2 -std=c++11 -I "assets/板端代码" -o /tmp/rans_oracle 工具/rans_oracle.cpp
//
// 用法：
//   rans_oracle gen   --n 64 --seed 1 --out vec.txt
//   rans_oracle run   --in vec.txt
//   rans_oracle trace --in vec.txt
// ===========================================================================
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>

#include "glc_board_encoder.h"

// ---------------------------------------------------------------------------
// 向量文件格式（纯文本，人类可读，便于 RTL testbench 用 $readmemh 或手写解析）
//   GLC_RANS_VECTOR 1
//   N <个数>
//   SYMS <s0> <s1> ...            (十进制 int32，可跨行)
//   SCALES <h0> <h1> ...          (float32 的 16 进制位模式，不带 0x)
// ---------------------------------------------------------------------------

struct Vec {
  std::vector<int32_t> syms;
  std::vector<float> scales;
};

static uint32_t rng_state = 0x12345678u;
static uint32_t xorshift32() {
  uint32_t x = rng_state;
  x ^= x << 13; x ^= x >> 17; x ^= x << 5;
  rng_state = x;
  return x;
}
static float float_of_bits(uint32_t u) { float f; std::memcpy(&f, &u, 4); return f; }
static uint32_t bits_of_float(float f) { uint32_t u; std::memcpy(&u, &f, 4); return u; }

// ---- 生成向量：覆盖真实分布 + 边界 ----------------------------------------
// 真实统计（见报告）：y_q 里 99.3858% 是 0，|y_q|<=1 占 99.9615%；
// 逃逸（raw_val 分支）实测真实数据 0 次触发 —— 但硬件必须能处理，所以向量里
// 要**故意**造几个逃逸样本。
static Vec gen_vector(int n, uint32_t seed) {
  rng_state = seed ? seed : 1u;
  Vec v;
  for (int i = 0; i < n; ++i) {
    int32_t s;
    const uint32_t r = xorshift32() % 1000;
    if (r < 900)       s = 0;                       // 大多数是 0
    else if (r < 960)  s = (xorshift32() & 1) ? 1 : -1;
    else if (r < 990)  s = (int32_t)(xorshift32() % 7) - 3;
    else               s = (int32_t)(xorshift32() % 4001) - 2000;  // 偶发大值 -> 可能逃逸

    // scale 取真实的几个量级（GLCM 输出的尺度范围 0.11 ~ 256）
    static const float kScales[] = {0.11f, 0.35f, 1.0f, 3.7f, 12.0f, 48.0f, 200.0f, 256.0f};
    float sc = kScales[xorshift32() % 8];
    v.syms.push_back(s);
    v.scales.push_back(sc);
  }
  return v;
}

// ---- 带 trace 的等价实现 ---------------------------------------------------
struct TraceRow {
  int      idx;        // 编码顺序里的第几个（0 = 第一个被压入的）
  int      sym_idx;    // 对应原始符号下标（-1 表示 bypass 附加符号）
  bool     bypass;
  uint32_t start;
  uint32_t freq;
  uint64_t x_before;
  uint64_t x_after;
  int      renorm_words;   // 0 或 1（Rans64EncPut 用的是 if，不是 while）
  uint32_t emitted;        // renorm_words==1 时吐出的 32 位字
  int      q_bits;         // 商 (x/freq) 的有效位宽 —— 决定除法器要做多少位
  int      x_bits;         // **被除数**（重归一化之后的 x）的有效位宽 —— 这个才是除法器输入宽度
};

static int bit_width64(uint64_t v) { int b = 0; while (v) { ++b; v >>= 1; } return b; }

static void run_trace(const Vec &v, std::vector<TraceRow> *rows,
                      std::vector<uint32_t> *flush_words,
                      std::vector<RansSymbol> *syms_out) {
  // ---- 第一步：与头文件完全相同的正向建表 ----
  std::vector<RansSymbol> syms;
  syms.reserve(v.syms.size() + 16);
  for (size_t i = 0; i < v.syms.size(); ++i) {
    const int k = glc_build_index(v.scales[i]);
    const uint32_t *cdf = glc_row_of(k);
    const int32_t max_value = (int32_t)GLC_CDF_LENGTH[k] - 2;

    int32_t value = v.syms[i] - GLC_CDF_OFFSET[k];
    uint32_t raw_val = 0;
    bool escaped = false;
    if (value < 0) {
      raw_val = (uint32_t)(-2 * value - 1); value = max_value; escaped = true;
    } else if (value >= max_value) {
      raw_val = (uint32_t)(2 * (value - max_value)); value = max_value; escaped = true;
    }

    RansSymbol s;
    s.start = (uint16_t)cdf[value];
    s.range = (uint16_t)(cdf[value + 1] - cdf[value]);
    s.bypass = false;
    syms.push_back(s);

    if (escaped) {
      int32_t n_bypass = 0;
      for (uint64_t rv = raw_val; rv != 0; rv >>= GLC_BYPASS_PRECISION) ++n_bypass;
      int32_t val = n_bypass;
      while (val >= GLC_MAX_BYPASS_VAL) {
        RansSymbol b; b.start = GLC_MAX_BYPASS_VAL;
        b.range = GLC_MAX_BYPASS_VAL + 1; b.bypass = true;
        syms.push_back(b);
        val -= GLC_MAX_BYPASS_VAL;
      }
      RansSymbol b; b.start = (uint16_t)val; b.range = (uint16_t)(val + 1); b.bypass = true;
      syms.push_back(b);
      for (int32_t j = 0; j < n_bypass; ++j) {
        const int32_t t =
            (int32_t)((raw_val >> (j * GLC_BYPASS_PRECISION)) & GLC_MAX_BYPASS_VAL);
        RansSymbol r; r.start = (uint16_t)t; r.range = (uint16_t)(t + 1); r.bypass = true;
        syms.push_back(r);
      }
    }
  }
  *syms_out = syms;

  // ---- 第二步：反向遍历，逐符号记录（语义照抄头文件）----
  // 注意：头文件把 output 的指针从尾部往前走（*--ptr），所以这里也按
  // "从缓冲区末尾往前" 的模型记录；最终把 words 逆序即为内存顺序。
  Rans64State rans;
  Rans64EncInit(&rans);
  std::vector<uint32_t> words_rev;   // 压入顺序（最终码流是它的逆序）

  int enc_idx = 0;
  for (int i = (int)syms.size() - 1; i >= 0; --i) {
    const RansSymbol s = syms[i];
    TraceRow tr;
    tr.idx = enc_idx++;
    tr.sym_idx = -1;
    tr.bypass = s.bypass;
    tr.start = s.start;
    tr.freq = s.range;
    tr.x_before = rans;
    tr.renorm_words = 0;
    tr.emitted = 0;

    if (!s.bypass) {
      uint64_t x = rans;
      uint64_t x_max = ((RANS64_L >> GLC_PRECISION) << 32) * (uint64_t)s.range;
      if (x >= x_max) {
        tr.emitted = (uint32_t)x;
        tr.renorm_words = 1;
        words_rev.push_back((uint32_t)x);
        x >>= 32;
      }
      tr.q_bits = bit_width64(x / s.range);
      tr.x_bits = bit_width64(x);
      rans = ((x / s.range) << GLC_PRECISION) + (x % s.range) + s.start;
    } else {
      uint64_t x = rans;
      uint32_t freq = 1u << (GLC_PRECISION - GLC_BYPASS_PRECISION);
      uint64_t x_max = ((RANS64_L >> GLC_PRECISION) << 32) * (uint64_t)freq;
      if (x >= x_max) {
        tr.emitted = (uint32_t)x;
        tr.renorm_words = 1;
        words_rev.push_back((uint32_t)x);
        x >>= 32;
      }
      rans = (x << GLC_BYPASS_PRECISION) | s.start;
    }
    tr.x_after = rans;
    rows->push_back(tr);
  }

  // flush：先吐高 32 位，再吐低 32 位
  flush_words->clear();
  flush_words->push_back((uint32_t)(rans >> 32));
  flush_words->push_back((uint32_t)rans);
  words_rev.push_back((uint32_t)(rans >> 32));
  words_rev.push_back((uint32_t)rans);
  // 注意：words_rev 内的完整内存顺序由调用方用 payload_from_trace 重建；
  // 这里**不要**再用 mem.end()-2 之类去改写 flush_words —— 曾经这么写，
  // 把真正的 {hi, lo} 覆盖成了码流末尾两个字，导致自检报"不一致"。
}

// 把 trace 的中间量再走一遍，产出与头文件**同格式**的 payload 供断言
static std::string payload_from_trace(const Vec &v) {
  std::vector<TraceRow> rows;
  std::vector<uint32_t> flush;
  std::vector<RansSymbol> syms;
  run_trace(v, &rows, &flush, &syms);

  // 重建 words_rev：按 trace 顺序收集 emitted，再补 flush
  std::vector<uint32_t> words_rev;
  for (size_t i = 0; i < rows.size(); ++i)
    if (rows[i].renorm_words) words_rev.push_back(rows[i].emitted);
  words_rev.push_back(flush[0]);
  words_rev.push_back(flush[1]);

  std::vector<uint32_t> mem(words_rev.rbegin(), words_rev.rend());
  return std::string(reinterpret_cast<const char *>(mem.data()), mem.size() * 4);
}

// ---- 除法器专用向量 --------------------------------------------------------
// 输出 `x freq q r` 四列文本，供 RTL 的 rans_div 模块对拍。
// 来源有三部分：
//   ① 真实 trace 里每个非 bypass 符号的 (x_after_renorm, freq)  —— 最贴近实战
//   ② 边界：对每个出现过的 freq，q 取 0/1/max 及 x=q*freq+r 在 r=0,freq-1 处
//   ③ freq 扫描：1,2,3,255,256,65535 等 + 随机
static void emit_divvec(const Vec &v, FILE *out) {
  std::vector<TraceRow> rows; std::vector<uint32_t> flush; std::vector<RansSymbol> syms;
  run_trace(v, &rows, &flush, &syms);

  long n = 0;
  // ① 真实数据
  for (size_t i = 0; i < rows.size(); ++i) {
    if (rows[i].bypass) continue;
    // trace 里的 x_before 是重归一化**之前**的；除法器吃的是之后的值
    uint64_t x = rows[i].x_before;
    uint64_t x_max = ((RANS64_L >> GLC_PRECISION) << 32) * (uint64_t)rows[i].freq;
    if (x >= x_max) x >>= 32;
    uint32_t f = rows[i].freq;
    if (f == 0) continue;
    // ⚠️ 必须用**固定 16 位十六进制**：`%012llx` 只是最小宽度，x 超过 2^48 时会自动变宽，
    //    下游按固定列宽解析就会错位（C2a1 的 tb 就是这么误判的）。
    fprintf(out, "%016llx %04llx %016llx %04llx\n",
            (unsigned long long)x, (unsigned long long)f,
            (unsigned long long)(x / f), (unsigned long long)(x % f));
    ++n;
  }
  // ② 边界 + ③ freq 扫描（freq=0 不合法，跳过）
  static const uint32_t kFreqs[] = {1,2,3,4,5,7,8,15,16,17,31,32,63,64,127,128,255,256,
                                    257,511,512,1023,1024,4095,4096,16383,16384,32767,32768,
                                    65533,65534,65535};
  for (size_t i = 0; i < sizeof(kFreqs)/sizeof(kFreqs[0]); ++i) {
    const uint64_t f = kFreqs[i];
    static const uint64_t kQs[] = {0,1,2,3,0xFFFFull,0x10000ull,
                                   0x7FFFFFFFFFFFull / 2, 0x7FFFFFFFFFFFull};
    for (size_t j = 0; j < sizeof(kQs)/sizeof(kQs[0]); ++j) {
      const uint64_t q = kQs[j];
      if (q > 0xFFFFFFFFFFFFull / f) continue;      // 别溢出 48 位
      for (int r = 0; r < 2; ++r) {
        const uint64_t rr = (r == 0) ? 0 : (f - 1);
        const uint64_t x = q * f + rr;
        if (x > 0xFFFFFFFFFFFFull) continue;
        fprintf(out, "%016llx %04llx %016llx %04llx\n",
                (unsigned long long)x, (unsigned long long)f,
                (unsigned long long)(x / f), (unsigned long long)(x % f));
        ++n;
      }
    }
  }
  // 随机补一批
  for (int i = 0; i < 20000; ++i) {
    uint32_t f = 1 + (xorshift32() % 65535);
    uint64_t x = ((uint64_t)xorshift32() << 16) ^ xorshift32();
    x &= 0xFFFFFFFFFFFFull;
    fprintf(out, "%016llx %04llx %016llx %04llx\n",
            (unsigned long long)x, (unsigned long long)f,
            (unsigned long long)(x / f), (unsigned long long)(x % f));
    ++n;
  }
  fprintf(stderr, "divvec: 共 %ld 行（x 与 q 均为固定 16 位十六进制）\n", n);
}

// ---- 向量读写 --------------------------------------------------------------
static bool save_vector(const Vec &v, const char *path) {
  FILE *f = fopen(path, "w");
  if (!f) return false;
  fprintf(f, "GLC_RANS_VECTOR 1\n");
  fprintf(f, "N %d\n", (int)v.syms.size());
  fprintf(f, "SYMS");
  for (size_t i = 0; i < v.syms.size(); ++i) {
    if (i % 16 == 0) fprintf(f, "\n");
    fprintf(f, " %d", v.syms[i]);
  }
  fprintf(f, "\nSCALES");
  for (size_t i = 0; i < v.scales.size(); ++i) {
    if (i % 8 == 0) fprintf(f, "\n");
    fprintf(f, " %08x", bits_of_float(v.scales[i]));
  }
  fprintf(f, "\n");
  fclose(f);
  return true;
}

static bool load_vector(const char *path, Vec *v) {
  FILE *f = fopen(path, "r");
  if (!f) return false;
  char tok[256];
  if (fscanf(f, "%255s", tok) != 1 || strcmp(tok, "GLC_RANS_VECTOR") != 0) { fclose(f); return false; }
  int ver = 0; if (fscanf(f, "%d", &ver) != 1) { fclose(f); return false; }
  int n = 0;   if (fscanf(f, "%255s %d", tok, &n) != 2 || strcmp(tok, "N") != 0) { fclose(f); return false; }
  if (fscanf(f, "%255s", tok) != 1 || strcmp(tok, "SYMS") != 0) { fclose(f); return false; }
  v->syms.resize(n);
  for (int i = 0; i < n; ++i) if (fscanf(f, "%d", &v->syms[i]) != 1) { fclose(f); return false; }
  if (fscanf(f, "%255s", tok) != 1 || strcmp(tok, "SCALES") != 0) { fclose(f); return false; }
  v->scales.resize(n);
  for (int i = 0; i < n; ++i) {
    unsigned int u = 0;
    if (fscanf(f, "%x", &u) != 1) { fclose(f); return false; }
    v->scales[i] = float_of_bits((uint32_t)u);
  }
  fclose(f);
  return true;
}

// ---- main ------------------------------------------------------------------
int main(int argc, char **argv) {
  if (argc < 2) {
    fprintf(stderr,
            "用法:\n"
            "  rans_oracle gen   --n <个数> --seed <整数> --out <向量文件>\n"
            "  rans_oracle run   --in <向量文件>\n"
            "  rans_oracle trace --in <向量文件>\n");
    return 2;
  }
  const std::string mode = argv[1];
  int n = 64; uint32_t seed = 1; const char *inp = NULL; const char *outp = NULL;
  for (int i = 2; i < argc; ++i) {
    if (!strcmp(argv[i], "--n") && i + 1 < argc)         n = atoi(argv[++i]);
    else if (!strcmp(argv[i], "--seed") && i + 1 < argc) seed = (uint32_t)strtoul(argv[++i], NULL, 10);
    else if (!strcmp(argv[i], "--in") && i + 1 < argc)   inp = argv[++i];
    else if (!strcmp(argv[i], "--out") && i + 1 < argc)  outp = argv[++i];
  }

  if (mode == "gen") {
    if (!outp) { fprintf(stderr, "gen 需要 --out\n"); return 2; }
    Vec v = gen_vector(n, seed);
    if (!save_vector(v, outp)) { fprintf(stderr, "写不进去: %s\n", outp); return 1; }
    printf("已生成 %d 个符号 -> %s\n", n, outp);
    return 0;
  }

  if (!inp) { fprintf(stderr, "需要 --in\n"); return 2; }
  Vec v;
  if (!load_vector(inp, &v)) { fprintf(stderr, "读不了向量: %s\n", inp); return 1; }

  if (mode == "divvec") {
    if (!outp) { fprintf(stderr, "divvec 需要 --out\n"); return 2; }
    FILE *fo = fopen(outp, "w");
    if (!fo) { fprintf(stderr, "写不进去: %s\n", outp); return 1; }
    emit_divvec(v, fo);
    fclose(fo);
    printf("除法器向量已写入 %s\n", outp);
    return 0;
  }

  // 标准答案（官方头文件）
  BoardEncoder enc;
  enc.encode(v.syms, v.scales);
  const std::string golden = enc.payload;

  // 独立重实现（带 trace）
  const std::string from_trace = payload_from_trace(v);

  printf("=== 向量 ===\n");
  printf("符号数 %d ｜ 编码后符号数（含 bypass）%d ｜ 逃逸 %zu 次 ｜ max_raw %u ｜ max_n_bypass %d\n",
         (int)v.syms.size(), (int)enc.n_syms, enc.n_escape, enc.max_raw, enc.max_n_bypass);
  printf("payload = %zu 字节 (%zu 个 uint32)\n", golden.size(), golden.size() / 4);

  printf("\n=== 自检：trace 重实现 vs 官方头文件 ===\n");
  if (golden != from_trace) {
    printf("!! 不一致 —— trace 不可信，先修 oracle\n");
    return 1;
  }
  printf("逐字节一致 ✔  （trace 可信）\n");

  printf("\n=== payload（hex，内存顺序）===\n");
  for (size_t i = 0; i < golden.size(); ++i)
    printf("%02x%s", (unsigned char)golden[i], ((i + 1) % 32 == 0) ? "\n" : "");
  printf("\n");

  if (mode == "trace") {
    std::vector<TraceRow> rows; std::vector<uint32_t> flush; std::vector<RansSymbol> syms;
    run_trace(v, &rows, &flush, &syms);
    int n_renorm = 0;
    for (size_t i = 0; i < rows.size(); ++i) n_renorm += rows[i].renorm_words;

    printf("\n=== 逐符号 trace（编码顺序 = 符号表的逆序）===\n");
    printf("#idx bypass start  freq  x_before            x_after             renorm emitted\n");
    for (size_t i = 0; i < rows.size(); ++i) {
      const TraceRow &t = rows[i];
      printf("%4d  %d     %5u %5u  %016llx  %016llx  %d      %08x\n",
             t.idx, t.bypass ? 1 : 0, t.start, t.freq,
             (unsigned long long)t.x_before, (unsigned long long)t.x_after,
             t.renorm_words, t.emitted);
    }
    printf("flush: %08x %08x\n", flush[0], flush[1]);
    printf("\n=== 汇总（对硬件设计最要紧的几个数）===\n");
    printf("编码符号总数        : %d\n", (int)rows.size());
    printf("发生重归一化的符号数: %d  (%.1f%%)\n", n_renorm, 100.0 * n_renorm / (double)rows.size());
    printf("单符号最多重归一化  : %d  (Rans64EncPut 用 if 不用 while，理论上限 1)\n",
           [&]{ int m = 0; for (size_t i = 0; i < rows.size(); ++i) if (rows[i].renorm_words > m) m = rows[i].renorm_words; return m; }());
    uint32_t fmin = 0xFFFFFFFFu, fmax = 0;
    for (size_t i = 0; i < rows.size(); ++i) {
      if (!rows[i].bypass) { if (rows[i].freq < fmin) fmin = rows[i].freq; if (rows[i].freq > fmax) fmax = rows[i].freq; }
    }
    printf("非 bypass 的 freq 范围: %u ~ %u\n", fmin, fmax);
    // 除法器要多少位？—— rANS 状态跨符号串行依赖，无法流水线，
    // **除法延迟直接等于吞吐率上限**，所以这个分布是硬件设计的关键输入。
    int qmax = 0, qmin = 999;
    long qsum = 0; int qn = 0;
    for (size_t i = 0; i < rows.size(); ++i) {
      if (rows[i].bypass) continue;
      if (rows[i].q_bits > qmax) qmax = rows[i].q_bits;
      if (rows[i].q_bits < qmin) qmin = rows[i].q_bits;
      qsum += rows[i].q_bits; ++qn;
    }
    printf("商 x/freq 有效位宽    : %d ~ %d 位（均值 %.1f）\n", qmin, qmax, qn ? (double)qsum / qn : 0.0);
    printf("  -> 除法器按 %d 位做即可（不是 64 位）\n", qmax);
    // ⚠️ 2026-09-18 更正：上面那个"位宽"是**商**的，不是**被除数**的。
    // 被除数 x 是重归一化之后的 rANS state，最大可到 ~2^63 —— **除法器输入必须够宽**。
    // 曾经把两者混为一谈，写成"做 48 位即可"，导致 C2a1 的对拍出现 1284 条不匹配。
    int xbmax = 0, xbmin = 999;
    for (size_t i = 0; i < rows.size(); ++i) {
      if (rows[i].bypass) continue;
      if (rows[i].x_bits > xbmax) xbmax = rows[i].x_bits;
      if (rows[i].x_bits < xbmin) xbmin = rows[i].x_bits;
    }
    printf("被除数 x 有效位宽    : %d ~ %d 位  <-- **除法器输入要按这个宽度做**\n", xbmin, xbmax);
    uint64_t xmax_seen = 0, xmin_seen = ~0ull;
    for (size_t i = 0; i < rows.size(); ++i) {
      if (rows[i].x_before > xmax_seen) xmax_seen = rows[i].x_before;
      if (rows[i].x_before < xmin_seen) xmin_seen = rows[i].x_before;
    }
    printf("state 范围           : %016llx ~ %016llx\n",
           (unsigned long long)xmin_seen, (unsigned long long)xmax_seen);
    printf("flush 后 state      : 已全部吐出（%08x %08x）\n", flush[0], flush[1]);
  }
  return 0;
}
