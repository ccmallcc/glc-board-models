//======================================================================
// rans_board.cpp —— 板端：把 GLC 的 (symbols, scales) 交给 PL 的 rANS 熵编码器
//                   编码，与 CPU 参考实现逐字节对拍，并分别计时。
//
// 硬件契约（全部来自官方 fpai_demo，不是猜的）：
//   · 自定义算子寄存器区（PS 侧 AXI）：BD ps_ai.bd 的
//       SEG_User_GP0_Reg -> /User_GP0/Reg @ offset 0x40080000, range 512K
//     见 fpai_demo_vivado.srcs/sources_1/bd/ps_ai/ps_ai.bd
//   · 寄存器地址换算：reg_ctrl 用 itf_ra_awaddr[17:2] 当**字**下标
//       => 字节偏移 = 字下标 * 4
//     对照官方 adder_demo.cpp：START=+0x00, {rsize,rbase}=+0x04, {wsize,wbase}=+0x08,
//       DONE=+0x80, version=+0xC0 —— 与 reg_ctrl 的 0x00/0x01/0x02/0x20/0x30 完全一致。
//   · 我们**不用**标准的 rbase/rsize/wbase（官方只有 16 位，寻址上限 64 KB），
//     而用 RFU 写寄存器（见 rtl/rans_top.v §addressing）：
//       RFU_W0 (0x03) = rbase[31:0]   字节地址
//       RFU_W1 (0x04) = rsize         拍数（512bit/拍 = 64 B）
//       RFU_W2 (0x05) = wbase[31:0]   字节地址
//       RFU_W5 (0x08) = nsym          真实符号数  ← 必须 W5！W3/W4 在官方
//                                     reg_ctrl 里只有 1 位（已由 reg_ctrl_quirk_tb 证明）
//
// 待定项（**必须实测**，不推断）：UserCustomOp_0 那条 AXI 通路在 AI_Mate（加密
//   EDIF）内部，通到 PS DDR 还是 PL DDR 不可见。所以 rbase 走候选地址搜索，
//   用一个已知输入跑一遍、拿 payload 与 CPU 参考对拍来判定。
//
// 数据布局（与 rtl/rans_top.v §data_format 一字不差）：
//   每拍 512 bit = 16 个 32 位字，每字一个逻辑符号（**图像自然顺序**写入）：
//       word[5:0]   = k      (CDF 行号)
//       word[31:16] = value  (有符号 16 位)
//   REVERSE_IN=1 让 PL 倒着读，所以 PS 按自然顺序写即可。
//
// 编译（FPAI-Ubuntu2004 里）：
//   aarch64-linux-gnu-g++ -O2 -std=c++17 -static -I<repo>/assets/板端代码 \
//       -o rans_board rans_board.cpp
//======================================================================
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cstdint>
#include <cerrno>
#include <string>
#include <vector>
#include <chrono>
#include <fcntl.h>
#include <unistd.h>
#include <sys/mman.h>
#include <sys/stat.h>

#include "glc_board_encoder.h"   // BoardEncoder / glc_build_index / GLC_* 表

//----------------------------------------------------------------------
// 寄存器字节偏移（字下标 × 4）
//
// ⭐ 寄存器**基址 = 0x400C0000**（不是 0x40080000！）
//   出处：官方 `rtl/gp/gp0_manager.sv` 的地址图 + 译码参数：
//       GP0_BASE = 0x4000_0000
//       gpx_ww_split #(.BASE(GP0_BASE),   .ASP(19))  -> m00_gpx / m04_gpx
//       gpx_ww_split #(.BASE(GP0_BASE),   .ASP(18))  -> host_ctrl / ai_ra
//       gpx_ww_split #(.BASE(0x40080000), .ASP(18))  -> m2_gpx   / m3_gpx
//       而 `m3_gpx` = `user_op.master`，`user_op` 就是喂给 `User_Reg_*` 的总线。
//     => 我们的自定义算子窗口 = **0x400C_0000 .. 0x400F_FFFF**。
//     => 与官方 adder_demo.cpp 里的 `reg_base = 0x400C0000` **完全一致**。
//   ⚠️ 踩坑：`ps_ai.bd` 的地址映射里写的是 `SEG_User_GP0_Reg @ 0x40080000`，
//      但那是**顶层 split 的边界**，不是一个算子窗口。照它去读 0x40080000
//      命中 `m2_gpx`（摄像头），于是版本号读回 0、统计量全是不相干的数。
//      **BD 的段映射与 RTL 里的译码不是一回事 —— 以 RTL 译码为准。**
//
// 地址换算：reg_ctrl 用 itf_ra_awaddr[17:2] 当**字**下标
//   => 字节偏移 = 字下标 * 4。PS 地址 0x400C0000+off 的 bit[17:2] 正好是 off/4。
//----------------------------------------------------------------------
static const uint32_t R_START   = 0x00;   // w[0]
static const uint32_t R_RSIZE_B = 0x04;   // w[1] 官方 16 位，不用
static const uint32_t R_WSIZE_B = 0x08;   // w[2] 官方 16 位，不用
static const uint32_t R_RBASE32 = 0x0C;   // RFU_W0
static const uint32_t R_RSIZE   = 0x10;   // RFU_W1
static const uint32_t R_WBASE32 = 0x14;   // RFU_W2
static const uint32_t R_NSYM    = 0x20;   // RFU_W5
static const uint32_t R_DONE    = 0x80;   // w[0x20]
static const uint32_t R_VER     = 0x84;   // RFU_R0 = 0x20260922
static const uint32_t R_STATUS  = 0x88;   // RFU_R1
static const uint32_t R_PLWORDS = 0x8C;   // RFU_R2
static const uint32_t R_NESC    = 0x90;   // RFU_R3
static const uint32_t R_NBYP     = 0x94;  // RFU_R4
static const uint32_t R_CYC     = 0x98;   // RFU_R5  实测拍数（hp_clk 域）
static const uint32_t R_MAXRAW  = 0x9C;   // RFU_R6
static const uint32_t R_MAXNB   = 0xA0;   // RFU_R7
static const uint32_t R_NSYM_R  = 0xA4;   // RFU_R8 回读
static const uint32_t R_TFED    = 0xA8;   // RFU_R9 {tstate, fed}

static const uint32_t VER_EXPECT = 0x20260922u;   // rans_top 的 rfu_rreg0
static const uint32_t ADD_VER    = 0x20230628u;   // 官方 reg_ctrl 的 ADD_VERSION

#define DIE(fmt, ...) do { fprintf(stderr, "FATAL: " fmt "\n", ##__VA_ARGS__); exit(1); } while (0)

//----------------------------------------------------------------------
// 小工具
//----------------------------------------------------------------------
static std::vector<uint8_t> slurp(const std::string &path) {
    FILE *f = fopen(path.c_str(), "rb");
    if (!f) DIE("cannot open %s", path.c_str());
    fseek(f, 0, SEEK_END); long n = ftell(f); fseek(f, 0, SEEK_SET);
    std::vector<uint8_t> v((size_t)n);
    if (n && fread(v.data(), 1, (size_t)n, f) != (size_t)n) DIE("short read %s", path.c_str());
    fclose(f);
    return v;
}

static double now_ms() {
    using namespace std::chrono;
    return duration_cast<duration<double, std::milli>>(
               steady_clock::now().time_since_epoch()).count();
}

//----------------------------------------------------------------------
// u-dma-buf：mmap + sysfs cache 同步（dma_coherent=0，所以同步是必须的）
//----------------------------------------------------------------------
class Udmabuf {
  public:
    void *va = nullptr;
    size_t size = 0;
    uint64_t phys = 0;
    std::string cls;

    bool open_dev(const std::string &name) {
        std::string dev = "/dev/" + name;
        cls = "/sys/class/u-dma-buf/" + name;
        phys = read_ull(cls + "/phys_addr");
        size = (size_t)read_ull(cls + "/size");
        int fd = ::open(dev.c_str(), O_RDWR | O_SYNC);
        if (fd < 0) { perror(("open " + dev).c_str()); return false; }
        va = mmap(nullptr, size, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
        if (va == MAP_FAILED) { perror("mmap udmabuf"); return false; }
        return true;
    }
    void sync_for_device(size_t off, size_t len) { sync(off, len, 1, "sync_for_device"); }
    void sync_for_cpu(size_t off, size_t len)    { sync(off, len, 2, "sync_for_cpu"); }

  private:
    static uint64_t read_ull(const std::string &p) {
        FILE *f = fopen(p.c_str(), "r");
        if (!f) DIE("cannot read %s", p.c_str());
        char buf[64] = {0};
        if (!fgets(buf, sizeof(buf), f)) DIE("empty %s", p.c_str());
        fclose(f);
        // ⚠️ 必须按 **0 基数** 解析：`phys_addr` 是 `0x0000000030100000`（带 0x 前缀），
        //    而 `size` 是十进制 `134217728`。用 `fscanf("%llu")` 会在 `0x` 处停下
        //    只得到 0 —— 实测踩过：程序打印 phys=0x0，等于操作了错误的物理地址。
        errno = 0;
        char *end = nullptr;
        unsigned long long v = strtoull(buf, &end, 0);
        if (end == buf || errno) DIE("bad value in %s: %s", p.c_str(), buf);
        return (uint64_t)v;
    }
    static void write_str(const std::string &p, const char *s) {
        int fd = ::open(p.c_str(), O_WRONLY);
        if (fd < 0) DIE("cannot open %s for write", p.c_str());
        if (::write(fd, s, strlen(s)) < 0) DIE("write %s failed", p.c_str());
        ::close(fd);
    }
    void sync(size_t off, size_t len, int dir, const char *forwhat) {
        char b[32];
        snprintf(b, sizeof(b), "%zu", off);       write_str(cls + "/sync_offset", b);
        snprintf(b, sizeof(b), "%zu", len);       write_str(cls + "/sync_size", b);
        snprintf(b, sizeof(b), "%d", dir);        write_str(cls + "/sync_direction", b);
        write_str(cls + "/" + forwhat, "1");
    }
};

//----------------------------------------------------------------------
// /dev/mem 映射的寄存器窗口
//----------------------------------------------------------------------
class RegWin {
  public:
    volatile uint32_t *p = nullptr;
    uint64_t base = 0;
    bool map(uint64_t phys, size_t len) {
        int fd = ::open("/dev/mem", O_RDWR | O_SYNC);
        if (fd < 0) { perror("open /dev/mem"); return false; }
        void *v = mmap(nullptr, len, PROT_READ | PROT_WRITE, MAP_SHARED, fd, (off_t)phys);
        close(fd);
        if (v == MAP_FAILED) { perror("mmap /dev/mem"); return false; }
        p = (volatile uint32_t *)v; base = phys; return true;
    }
    uint32_t rd(uint32_t off) const { return p[off / 4]; }
    void     wr(uint32_t off, uint32_t v) { p[off / 4] = v; __sync_synchronize(); }
};

//----------------------------------------------------------------------
// 一个 phase 的输入
//----------------------------------------------------------------------
struct Phase {
    std::vector<int32_t> sym;
    std::vector<float>   scale;
    bool load(const std::string &dir, int p) {
        char n[64];
        snprintf(n, sizeof(n), "/p%d_sym.i32", p);
        std::vector<uint8_t> a = slurp(dir + n);
        snprintf(n, sizeof(n), "/p%d_scales.f32", p);
        std::vector<uint8_t> b = slurp(dir + n);
        if (a.size() % 4 || b.size() % 4 || a.size() != b.size())
            DIE("bad sizes %zu / %zu", a.size(), b.size());
        size_t n_ = a.size() / 4;
        sym.resize(n_); scale.resize(n_);
        memcpy(sym.data(), a.data(), a.size());
        memcpy(scale.data(), b.data(), b.size());
        return true;
    }
};

//----------------------------------------------------------------------
// 把 (sym, scale) 打成 PL 要的 32 位字并写进 udmabuf
//----------------------------------------------------------------------
static size_t pack_words(const Phase &ph, uint32_t *dst) {
    for (size_t i = 0; i < ph.sym.size(); ++i) {
        uint32_t k = (uint32_t)glc_build_index(ph.scale[i]) & 0x3Fu;
        uint32_t v = (uint32_t)(int32_t)ph.sym[i] & 0xFFFFu;
        dst[i] = (v << 16) | k;
    }
    return ph.sym.size();
}

//----------------------------------------------------------------------
// 跑一次 PL 编码
//----------------------------------------------------------------------
struct PlResult {
    uint32_t pl_words = 0, n_escape = 0, n_bypass = 0, cyc_total = 0;
    uint32_t max_raw = 0, max_nb = 0, nsym_rb = 0, status = 0, tfed = 0;
    double   wall_ms = 0, poll_ms = 0;
    std::vector<uint32_t> words;
};

static bool run_pl(RegWin &reg, Udmabuf &ub, const Phase &ph, uint32_t rbase_phys,
                   PlResult &out, bool verbose) {
    const size_t   N     = ph.sym.size();
    const uint32_t nbeat = (uint32_t)((N + 15) / 16);
    const size_t   in_bytes = (size_t)nbeat * 64;
    const size_t   wbase_off = in_bytes;
    const size_t   out_max_bytes = 16384 * 4;   // payload 缓冲上限（= RTL DEPTH 字）

    if (in_bytes + out_max_bytes > ub.size) DIE("udmabuf too small");

    // 1. 打输入并刷 cache
    pack_words(ph, (uint32_t *)ub.va);
    ub.sync_for_device(0, wbase_off + out_max_bytes);

    // 2. 配置（顺序无所谓，START 之前写完即可）
    reg.wr(R_RBASE32, rbase_phys);
    reg.wr(R_RSIZE,   nbeat);
    reg.wr(R_WBASE32, rbase_phys + (uint32_t)wbase_off);
    reg.wr(R_NSYM,    (uint32_t)N);

    // 3. 启动 + 轮询
    double t0 = now_ms();
    reg.wr(R_START, 1);
    uint32_t done = 0; long polls = 0;
    while ((done & 1u) == 0 && polls < 20000000L) { done = reg.rd(R_DONE); ++polls; }
    double t1 = now_ms();
    out.wall_ms = t1 - t0;
    out.poll_ms = t1 - t0;

    out.status  = reg.rd(R_STATUS);
    out.pl_words= reg.rd(R_PLWORDS) & 0xFFFFu;
    out.n_escape= reg.rd(R_NESC);
    out.n_bypass= reg.rd(R_NBYP);
    out.cyc_total = reg.rd(R_CYC);
    out.max_raw = reg.rd(R_MAXRAW);
    out.max_nb  = reg.rd(R_MAXNB) & 0x1Fu;
    out.nsym_rb = reg.rd(R_NSYM_R) & 0xFFFFu;
    out.tfed    = reg.rd(R_TFED) & 0xFFFFFu;

    if (verbose) {
        printf("    polls=%ld done=%u status=%08x pl_words=%u nsym_rb=%u cyc=%u\n",
               polls, done & 1u, out.status, out.pl_words, out.nsym_rb, out.cyc_total);
        printf("    n_escape=%u n_bypass=%u max_raw=%u max_n_bypass=%u {tstate,fed}=%05x\n",
               out.n_escape, out.n_bypass, out.max_raw, out.max_nb, out.tfed);
    }
    if ((done & 1u) == 0) { fprintf(stderr, "  PL timeout (no DONE)\n"); return false; }

    // 4. 让 CPU 看到 PL 写的结果
    ub.sync_for_cpu(wbase_off, out_max_bytes);

    size_t nw = out.pl_words;
    if (nw > 16384) { fprintf(stderr, "  pl_words=%zu 超上限\n", nw); return false; }
    out.words.resize(nw);
    memcpy(out.words.data(), (uint8_t *)ub.va + wbase_off, nw * 4);
    return true;
}

static std::vector<uint8_t> words_to_bytes(const std::vector<uint32_t> &w) {
    std::vector<uint8_t> b(w.size() * 4);
    for (size_t i = 0; i < w.size(); ++i) {
        b[i*4+0] = (uint8_t)(w[i]      );
        b[i*4+1] = (uint8_t)(w[i] >>  8);
        b[i*4+2] = (uint8_t)(w[i] >> 16);
        b[i*4+3] = (uint8_t)(w[i] >> 24);
    }
    return b;
}

//----------------------------------------------------------------------
// GLC2 容器：取第 p 个 stage 的 payload
//
// ⚠️ 头长 = **76** 字节，不是 44。
//    `struct.Struct(">4sBBH17I")` 的实际大小 = 4+1+1+2+17*4 = **76**。
//    `工具/glc2_validate.py` 的文件头注释里写的是 "44 bytes" —— 那是**错的**
//    （仓库里"44 字节头"这一说法此前已被撤销）。用 76 才能对上实测的
//    board_img0.glc：76 + 28(z) + 60 + 60 + 52 + 48 = 324 ✓。
//    字段偏移（i>=4）：off(i) = 8 + (i-4)*4
//      z_bytes   = 字段 15 -> 52
//      stage_len = 字段 16..19 -> 56, 60, 64, 68
//      trailer   = 字段 20 -> 72
//----------------------------------------------------------------------
static const size_t GLC_HEADER_BYTES = 76;

struct GlcHeader {
    uint32_t stage_len[4]{}; uint32_t z_bytes = 0; uint64_t stage_off[4]{};
    uint32_t file_bytes = 0;
};
static GlcHeader parse_glc(const std::string &path, std::vector<uint8_t> &blob) {
    blob = slurp(path);
    if (blob.size() < GLC_HEADER_BYTES || memcmp(blob.data(), "GLC2", 4))
        DIE("not a GLC2 file: %s", path.c_str());
    auto be32 = [&](size_t o) {
        return ((uint32_t)blob[o] << 24) | ((uint32_t)blob[o+1] << 16) |
               ((uint32_t)blob[o+2] << 8) | (uint32_t)blob[o+3];
    };
    GlcHeader h;
    h.file_bytes = (uint32_t)blob.size();
    h.z_bytes = be32(52);
    for (int i = 0; i < 4; ++i) h.stage_len[i] = be32(56 + 4 * i);
    uint64_t off = GLC_HEADER_BYTES + h.z_bytes;
    for (int i = 0; i < 4; ++i) { h.stage_off[i] = off; off += h.stage_len[i]; }
    if (off != blob.size())
        fprintf(stderr, "  WARN: 容器长度不自洽: header+z+stages=%llu 但文件=%zu\n",
                (unsigned long long)off, blob.size());
    return h;
}

//----------------------------------------------------------------------
int main(int argc, char **argv) {
    // ⚠️ 必须**关掉 stdout 缓冲**：这个程序会去读一个"读不通就把整块板子锁死"
    //    的寄存器窗口。如果走的是管道（ssh），行缓冲不会自动刷，
    //    一旦挂死，缓冲区里的内容全部丢失 —— 我们就**不知道死在哪一步**。
    //    实测踩过：`probe` 一个字符都没收到，无法区分"连接断了"和"卡住了"。
    setvbuf(stdout, nullptr, _IONBF, 0);
    setvbuf(stderr, nullptr, _IONBF, 0);

    std::string mode = (argc > 1) ? argv[1] : "run";
    std::string ubm  = "udmabuf0";
    std::string dir  = "/root/glc/pack/img0";
    std::string glcp = "/root/glc/pack/img0.glc";
    uint64_t regbase = 0x400C0000ull;   // ⭐ 自定义算子窗口（gp0_manager 的 m3_gpx）
    uint32_t phases_mask = 0xF;
    int bench = 1;

    for (int i = 2; i < argc; ++i) {
        std::string a = argv[i];
        auto next = [&]() -> std::string { return (i + 1 < argc) ? argv[++i] : std::string(); };
        if      (a == "--ubm")    ubm = next();
        else if (a == "--dir")    dir = next();
        else if (a == "--glc")    glcp = next();
        else if (a == "--phase")  phases_mask = (uint32_t)strtoul(next().c_str(), nullptr, 0);
        else if (a == "--bench")  bench = atoi(next().c_str());
        else if (a == "--reg-base") regbase = strtoull(next().c_str(), nullptr, 0);
        else DIE("unknown arg %s", a.c_str());
    }

    Udmabuf ub;
    if (!ub.open_dev(ubm)) DIE("udmabuf open failed");
    printf("== udmabuf %s : phys=0x%llx size=%zu B (%.1f MB)\n",
           ubm.c_str(), (unsigned long long)ub.phys, ub.size, ub.size / 1048576.0);

    RegWin reg;
    if (!reg.map(regbase, 0x2000)) DIE("reg map failed");

    printf("== reg base 0x%llx\n", (unsigned long long)regbase);

    //==================================================================
    // 为什么读 `user_op`（0x400C0000）会把板子锁死 —— 机制已定位到具体信号
    //
    // 官方 `rtl/gp/gpx_ww_split.sv:48`：
    //     assign gpx.arready = rbase_match
    //            ? ( araddr[ASP] ? (~wait_rdata) && m01_gpx.arready
    //                            : (~wait_rdata) && m00_gpx.arready )
    //            : ~mxx_rvalid ;
    // `0x400C0000` 命中 `m01_gpx = user_op`，于是**上游 AXI 的 arready
    // 完全取决于我们 `reg_ctrl` 的 `ra_arready = (ra_rvalid==0)`**。
    // 只要 `ra_rvalid` 卡在 1，这次 AXI 读就**永远不返回** ⇒ 整块板子锁死。
    //
    // 佐证：官方位流下读 `0x80080000` 返回的正是顶层 split 的 `ERR` 参数
    // `0xB0AAAAAA` ⇒ GP0 通路本身是通的；挂死的只是 `user_op` 这一支。
    //
    // ⇒ 探测顺序**刻意**做成"先安全、后危险"，且每步先打印再读、立刻刷缓冲，
    //    这样 SSH 掉线时能知道**死在哪一步**。
    //==================================================================
    if (mode == "probe") {
        struct { uint64_t a; const char *why; uint32_t expect; } steps[] = {
            {0x80080000ull, "顶层 split 的 ERR 路径（上一轮实测 0xB0AAAAAA，证明 GP0 通路通）", 0},
            {0x40000000ull, "host_ctrl RFU（gpx_RFU ERR=0xA0AAAAAA）", 0xA0AAAAAAu},
            {0x40040000ull, "ai_ra RFU（gpx_RFU ERR=0xA0AAAAAA）",     0xA0AAAAAAu},
            {0x40080000ull, "m2_gpx -> cam（摄像头块）", 0},
            {0x400C0000ull, "m3_gpx -> user_op（**我们的算子**；若挂死就是这一支）", 0},
        };
        printf("\n== 分步探测（先安全、后危险；每步「先打印再读」）==\n");
        for (auto &s : steps) {
            printf("  [读] 0x%08llX  %s\n", (unsigned long long)s.a, s.why);
            fflush(stdout);
            RegWin r2;
            if (!r2.map(s.a, 0x2000)) { printf("       mmap 失败\n"); fflush(stdout); continue; }
            uint32_t vc0 = r2.rd(0xC0);
            printf("       +0xC0 = 0x%08X", vc0);
            if (vc0 == ADD_VER) printf("   *** 官方 reg_ctrl 在这里（ADD_VERSION）***");
            else if (s.expect && vc0 == s.expect) printf("   (与预期一致)");
            printf("\n"); fflush(stdout);
            uint32_t v84 = r2.rd(R_VER);
            printf("       +0x84 = 0x%08X", v84);
            if (v84 == VER_EXPECT) printf("   *** rans_top 在这里（我们的版本号）***");
            printf("\n"); fflush(stdout);
            munmap((void *)r2.p, 0x2000);
        }
        printf("== 探测结束（走完说明 0x400C0000 没挂死）==\n");
        return 0;
    }

    printf("   +0xC0 (reg_ctrl ADD_VERSION) = 0x%08X  (expect 0x%08X)\n",
           reg.rd(0xC0), ADD_VER);
    printf("   +0x84 (rans_top RFU_R0 ver)  = 0x%08X  (expect 0x%08X)\n",
           reg.rd(R_VER), VER_EXPECT);

    //==================================================================
    // ⚠️⚠️ 安全闸门：**只有**确认版本指纹正确，才允许写寄存器。
    //
    // 事故记录（2026-09-24，本项目真实踩过）：
    //   当时以为自定义算子窗口在 0x40080000（照 `ps_ai.bd` 的段映射），
    //   没先读版本号确认就直接 `addr` / `run`，
    //   而那个地址其实是 `gp0_manager` 的 `m2_gpx` -> **摄像头块**。
    //   盲写它的寄存器之后板子随即失联（PHY 有链路、Linux 不应答），
    //   基本可判定是误触发了不该触发的 DMA、破坏了内核内存。
    //   正确基址是 **0x400C0000**（`m3_gpx` -> `user_op`）。
    //
    // 规则：**发现阶段只读不写；写之前必须先用版本号指纹确认窗口身份。**
    //==================================================================
    {
        uint32_t v84 = reg.rd(R_VER);
        uint32_t vc0 = reg.rd(0xC0);
        if (v84 != VER_EXPECT && vc0 != ADD_VER) {
            fprintf(stderr,
                "\n*** 拒绝继续：寄存器窗口身份未确认，不允许写寄存器 ***\n"
                "  base 0x%08llX : +0x84 = 0x%08X (期望 0x%08X = rans_top 的 RFU_R0)\n"
                "                 +0xC0 = 0x%08X (期望 0x%08X = 官方 reg_ctrl 的 ADD_VERSION)\n"
                "  已知正确基址 = 0x400C0000（gp0_manager 的 m3_gpx -> user_op）。\n"
                "  先跑 `probe` 确认，再用 --reg-base 指定。\n",
                (unsigned long long)regbase, v84, VER_EXPECT, vc0, ADD_VER);
            return 3;
        }
        printf("== 指纹确认：窗口身份正确，允许写寄存器 ==\n");
    }

    Phase ph[4];
    for (int p = 0; p < 4; ++p)
        if (phases_mask & (1u << p)) ph[p].load(dir, p);

    std::vector<uint8_t> blob;
    GlcHeader gh = parse_glc(glcp, blob);

    // ---------------- addr：地址候选搜索 ----------------
    if (mode == "addr") {
        // ⚠️ 为什么候选里既有"物理地址"又有"偏移"：
        //    官方 rtl/adder_op/dma.v 把 `araddr`(32位) <= `arbase`(16位)，
        //    Verilog 会**高位补零** ⇒ demo 实际只送了低 16 位还能跑通。
        //    说明 `User_Ddr_araddr` 很可能是**某个 DMA 窗口内的偏移**（窗口基址
        //    由 AI_Mate/运行时配置），而不是 PS 的物理地址。
        //    两种解释都得试，所以候选同时覆盖。
        std::vector<uint64_t> cand;
        auto add = [&](uint64_t v) {
            for (uint64_t x : cand) if (x == v) return;
            cand.push_back(v);
        };
        add(0);                                       // 窗口内偏移 0（最可能）
        add(ub.phys);                                 // 直接物理地址 0x30100000
        add(ub.phys & 0xFFFFull);                     // 低 16 位
        add(ub.phys & 0xFFFFFFull);                   // 低 24 位
        add(ub.phys & 0xFFFFFFFull);                  // 低 28 位
        add(0x80000000ull);                           // NPU DMA 窗口基址
        add(0x80000000ull | (ub.phys & 0xFFFFull));
        add(0x80000000ull | (ub.phys & 0xFFFFFFull));
        add(0x80000000ull | (ub.phys & 0xFFFFFFFull));
        add(0x80000000ull + ub.phys);                 // 0xB0100000
        add(0x40000000ull + ub.phys);                 // 0x70100000
        add(ub.phys - 0x30000000ull);                 // 0x00100000
        add(ub.phys - 0x20000000ull);                 // 0x10100000
        add(0x10000000ull | (ub.phys & 0xFFFFFFull));
        add(0x8000000ull  | (ub.phys & 0xFFFFFFull));

        printf("\n== 地址候选搜索（判定用 phase 0 的前 8 字节）==\n");
        // CPU 参考
        BoardEncoder ref;
        ref.encode(ph[0].sym, ph[0].scale);
        const uint8_t *want = gh.stage_len[0] ?
            blob.data() + gh.stage_off[0] : (const uint8_t *)ref.payload.data();
        printf("  参考(%zu B) 前 8 字节: ", ref.payload.size());
        for (int i = 0; i < 8; ++i) printf("%02x", want[i]);
        printf("   glc stage0=%u B\n", gh.stage_len[0]);
        printf("  %-12s %-8s %-9s %-9s %s\n", "rbase", "pl_words", "n_escape", "cyc", "head8 / 判定");
        for (uint64_t c : cand) {
            PlResult r;
            printf("  0x%08llX  ", (unsigned long long)c); fflush(stdout);
            if (!run_pl(reg, ub, ph[0], (uint32_t)c, r, false)) { printf("timeout\n"); continue; }
            std::vector<uint8_t> b = words_to_bytes(r.words);
            bool ok = b.size() >= 8 && memcmp(b.data(), want, 8) == 0;
            printf("%-8u %-9u %-9u ", r.pl_words, r.n_escape, r.cyc_total);
            for (size_t i = 0; i < b.size() && i < 8; ++i) printf("%02x", b[i]);
            printf("  %s\n", ok ? "*** MATCH ***" : "");
        }
        return 0;
    }

    // ---------------- run：四相全跑 + 对拍 + 计时 ----------------
    printf("\n== 四相编码：PL vs CPU 参考 vs 容器 ==\n");
    printf("  .glc = %s (%u B); stage 长度 %u/%u/%u/%u\n\n", glcp.c_str(), gh.file_bytes,
           gh.stage_len[0], gh.stage_len[1], gh.stage_len[2], gh.stage_len[3]);

    uint64_t cpu_total_ns = 0, pl_cyc_total = 0;
    double   pl_wall_total = 0;
    int      n_ok = 0, n_ph = 0;

    for (int p = 0; p < 4; ++p) {
        if (!(phases_mask & (1u << p))) continue;
        ++n_ph;
        printf("---- phase %d : %zu 符号 ----\n", p, ph[p].sym.size());

        // CPU 参考（多次取最好）
        BoardEncoder ref;
        double best = 1e18;
        for (int b = 0; b < bench; ++b) {
            double t0 = now_ms();
            ref.encode(ph[p].sym, ph[p].scale);
            double t1 = now_ms();
            if (t1 - t0 < best) best = t1 - t0;
        }
        cpu_total_ns += (uint64_t)(best * 1e6);
        printf("  CPU  : %zu B, %zu rANS 符号, escape=%zu bypass=%zu, %.2f ms\n",
               ref.payload.size(), ref.n_syms, ref.n_escape, ref.n_bypass_syms, best);

        // 容器里的 stage 是否与 CPU 参考一致（先验：证明我们的工装没错）
        bool glc_ok = true;
        if (gh.stage_len[p] == ref.payload.size())
            glc_ok = memcmp(blob.data() + gh.stage_off[p], ref.payload.data(), ref.payload.size()) == 0;
        else glc_ok = false;
        printf("  容器 : stage%d %u B -> CPU 参考 %s\n", p, gh.stage_len[p],
               glc_ok ? "逐字节一致" : "** 不一致 / 长度不同 **");

        // PL
        PlResult r;
        if (!run_pl(reg, ub, ph[p], (uint32_t)ub.phys, r, true)) { printf("  PL   : 失败\n"); continue; }
        std::vector<uint8_t> pb = words_to_bytes(r.words);
        bool pl_ok = pb.size() == ref.payload.size() &&
                     memcmp(pb.data(), ref.payload.data(), pb.size()) == 0;
        printf("  PL   : %zu B, cyc_total=%u (=%.3f ms @200MHz), wall=%.3f ms, %s\n",
               pb.size(), r.cyc_total, r.cyc_total * 5.0 / 1e6, r.wall_ms,
               pl_ok ? "==== 与 CPU 参考逐字节一致 ====" : "** 不一致 **");
        if (!pl_ok) {
            size_t show = pb.size() < ref.payload.size() ? pb.size() : ref.payload.size();
            size_t i = 0; while (i < show && pb[i] == (uint8_t)ref.payload[i]) ++i;
            printf("       首个不同字节 @%zu : PL=%02x CPU=%02x\n", i,
                   i < pb.size() ? pb[i] : 0, i < ref.payload.size() ? (uint8_t)ref.payload[i] : 0);
        } else ++n_ok;

        pl_cyc_total += r.cyc_total;
        pl_wall_total += r.wall_ms;

        // PL payload 落盘
        char out[256];
        snprintf(out, sizeof(out), "/root/glc/pack/pl_p%d.bin", p);
        FILE *f = fopen(out, "wb"); if (f) { fwrite(pb.data(), 1, pb.size(), f); fclose(f); }
        printf("       -> %s\n", out);
        printf("\n");
    }

    printf("================ 汇总 ================\n");
    printf("  相位逐字节一致 : %d / %d\n", n_ok, n_ph);
    printf("  CPU 熵编码合计 : %.3f ms\n", cpu_total_ns / 1e6);
    printf("  PL  实测拍数   : %llu 拍 = %.3f ms @200MHz\n",
           (unsigned long long)pl_cyc_total, pl_cyc_total * 5.0 / 1e6);
    printf("  PL  墙钟合计   : %.3f ms\n", pl_wall_total);
    if (pl_cyc_total) printf("  PL/CPU 加速比  : %.2fx (按拍数) \n",
                             (cpu_total_ns / 1e6) / (pl_cyc_total * 5.0 / 1e6));
    long long enc_bytes = 0, stages = 0;
    for (int p = 0; p < 4; ++p) { enc_bytes += gh.stage_len[p]; stages += 1; }
    printf("  压缩比(payload): %lld B / (256*256) = %.6f bpp\n",
           enc_bytes, 8.0 * enc_bytes / (256.0 * 256.0));
    printf("  压缩比(整容器): %u B -> %.6f bpp\n", gh.file_bytes,
           8.0 * gh.file_bytes / (256.0 * 256.0));
    return n_ok == n_ph ? 0 : 1;
}
