//======================================================================
// rans_cdf.v  ——  C2d：CDF 查表 + 符号映射 + 倒数表 + escape/bypass 展开
//----------------------------------------------------------------------
// 算法基线：assets/板端代码/glc_board_encoder.h:97-175（BoardEncoder::encode）
// 表结构  ：C2_PL熵编码器/设计规格.md §五（由 工具/gen_c2d_tables.py 生成）
// 下游接口：rtl/rans_enc_stream.v —— 吃 (s_start, s_freq, s_rcp, s_bypass, s_last)
//
// 本模块只做一件事：把 PS 送来的**逻辑符号流** (k, value)
//   展开成 rans_enc_stream 需要的 **rANS 符号流**。
// 它**不碰** rANS 状态机与输出缓冲（那是 C2c1 的活）。
//
// ── key 1：为什么需要"展开" ─────────────────────────────────────────
//   C++ 把一个越界符号编码成**多个** rANS 符号：
//       主符号（落在 cdf 的 max_value 桶）+ 若干个 4bit bypass 符号 + n_bypass 的 unary 编码
//   而且 C++ 是 push_back 进 vector、**再 pop_back 倒序编码**（rANS 是栈）。
//   => 硬件必须按倒序发射。本模块不建栈：倒序是**可确定的**，用"阶段 + 向下计数器"直接生成。
//
// ── key 2：符号映射（必须与 compressai 的 rans_interface.cpp 一致）──
//     max_value = CDF_LENGTH[k] - 2
//     v = value - CDF_OFFSET[k]
//     v < 0          -> raw_val = -2*v - 1,      v = max_value, escaped
//     v >= max_value -> raw_val =  2*(v - max_value), v = max_value, escaped
//     start = cdf[row_start[k] + v]
//     freq  = cdf[row_start[k] + v + 1] - start
//   glc_board_encoder.h:124-125 把 start/freq 转 uint16，本模块同样取低 16 位。
//
// ── key 3：倒序展开的确定顺序 ───────────────────────────────────────
//   C++ push 顺序： [主, b_hi × m, b_last, r_0, r_1, …, r_{n-1}]
//   C++ pop  顺序：  r_{n-1}, …, r_1, r_0, b_last, b_hi × m, 主
//   => 硬件发射顺序：
//        ① j = n_bypass-1 downto 0 的 4bit 组   （MSB 组先发！）
//        ② b_last : start = n_bypass % 15, freq = start+1
//        ③ b_hi × m : start = 15,           freq = 16      （m = n_bypass / 15）
//        ④ 主符号
//   ⚠️ **每个逻辑符号的最后一次发射永远是主符号** ⇒ s_last 只挂在主符号上。
//
// ── key 4：bypass 走 Rans64EncPutBits，不用 rcp ──────────────────────
//   见 glc_board_encoder.h:169 ⇒ s_bypass=1 时 s_rcp 无所谓（本模块送 0）。
//
// ⚠️ n_bypass > 7 时 C++ 置 out_of_domain（glc_board_encoder.h:134）。
//    本模块照样展开（不截断），并同样上报，保持可对拍。
//
//======================================================================
// ── V6：拆流水（2026-09-26）──────────────────────────────────────────
// 动机（实测）：V4/V5 时序收敛到 WNS −0.119 ns、14 个失败端点，
//   最差路径起点 `U_rans_top/sym_k_reg[*]_replica` → `u_cdf/max_raw_reg[*]/CE`，
//   数据路径 4.864 ns、逻辑 15 级（CARRY4=9）。根因是**原来全挤在一个周期里**：
//
//     d_k → LUTRAM 查 cdf_len/off/row_start → 有符号减(v-off) → 比较(max)
//         → mux(v_c) → 32bit 加(rd_addr) / 再两次 32bit 运算(raw_val)
//         → 优先级编码(nbyp) → 与 max_raw 比较 → 寄存器 CE
//
// 做法：把这条链切成 4 段，段间插寄存器（**只加流水，不改算法**）：
//
//     S_IDLE : d_k → cdf_len/off/row_start 查表     → len_r / off_r / row_r
//              d_value / d_last                    → val_r / last_r
//     S_MAP  : val_r − off_r → vraw_r；len_r − 2 → mx_r；neg_r
//     S_ESC  : esc_r ← neg_r || (vraw_r ≥ mx_r)；v_r ← esc ? mx : vraw
//     S_ARITH: raw_r ← raw_val；rd_addr ← row_r3 + v_r
//     S_RD   : BRAM 读 cdf/rcp + nbyp 优先级编码 + 统计(max_raw/…) + 发射相位
//     S_EMIT : 与改前**逐字相同**
//
// 关键点：`rv_c` 的负分支 `−2v−1` 用的是 `~(v<<1)`（补码恒等式，**不需要加法器**），
//   所以 S_ARITH 那一段只剩一次 32bit 减法；`vraw_r`/`mx_r` 一直留到 S_ARITH 用。
//
// 代价（估算，需上板实测）：每个逻辑符号多 3 拍。
//   改前板端 8.64 拍/符号 → 估算约 11.6 拍/符号；
//   熵编码占整帧 0.79% → 约 1.06%，对整帧影响约 +0.25%。
//
// 纪律：改完**必须**重跑 C2e / C2d 回归（real + stress 两向量，逐符号 + 逐字对拍），
//   通过才许建 V6 位流上板。
//======================================================================
`timescale 1ns / 1ps

module rans_cdf #(
    parameter CDF_ENTRIES = 27256,
    parameter NUM_CDFS    = 64,
    parameter AW          = 15,          // 2**15 = 32768 >= CDF_ENTRIES
    parameter MEM_ROOT    = "mem"
)(
    input  wire            clk,
    input  wire            rst_n,

    // ── 逻辑符号输入流（PS/DMA 送，**已经是编码顺序**）──
    input  wire            d_valid,
    output wire            d_ready,
    input  wire [5:0]      d_k,
    // ⚠️ **有符号**！实测真实符号范围 = [-2, 3]（见 sim/vec 的统计），
    //    而 CDF_OFFSET 全为负（[-1565, -1]），v = sym - OFFSET 必须按有符号算。
    input  wire signed [15:0] d_value,
    input  wire            d_last,

    // ── rANS 符号输出流（接 rans_enc_stream）──
    output reg             s_valid,
    input  wire            s_ready,
    output reg             s_last,
    output reg  [15:0]     s_start,
    output reg  [15:0]     s_freq,
    output reg  [63:0]     s_rcp,
    output reg             s_bypass,

    // ── 统计（与 C++ 的 n_escape / n_bypass_syms / max_raw / max_n_bypass 对拍）──
    output reg  [15:0]     n_escape,
    output reg  [19:0]     n_bypass_syms,
    output reg  [31:0]     max_raw,
    output reg  [4:0]      max_n_bypass,
    output reg             out_of_domain
);

    //------------------------------------------------------------------
    // ROM —— 全部由 工具/gen_c2d_tables.py 从官方 glc_cdf_table.h 生成
    //------------------------------------------------------------------
    reg [31:0] cdf_flat  [0:CDF_ENTRIES-1];
    reg [63:0] rcp_arr   [0:CDF_ENTRIES-1];
    reg [31:0] cdf_len   [0:NUM_CDFS-1];
    reg [31:0] cdf_off   [0:NUM_CDFS-1];
    reg [31:0] row_start [0:NUM_CDFS-1];

    initial begin
        $readmemh({MEM_ROOT, "/cdf_flat.hex"},  cdf_flat);
        $readmemh({MEM_ROOT, "/rcp_arr.hex"},   rcp_arr);
        $readmemh({MEM_ROOT, "/cdf_len.hex"},   cdf_len);
        $readmemh({MEM_ROOT, "/cdf_off.hex"},   cdf_off);
        $readmemh({MEM_ROOT, "/row_start.hex"}, row_start);
    end

    //------------------------------------------------------------------
    // V6 流水寄存器
    //------------------------------------------------------------------
    // S_IDLE → S_MAP
    reg signed [31:0] val_r;
    reg        [31:0] len_r, off_r, row_r;
    reg               last_r;
    // S_MAP → S_ESC
    reg signed [31:0] vraw_r, mx_r;
    reg               neg_r;
    reg        [31:0] row_r2;
    // S_ESC → S_ARITH
    reg               esc_r;
    reg signed [31:0] v_r;
    reg        [31:0] row_r3;
    // S_ARITH → S_RD
    reg        [31:0] raw_r;

    //------------------------------------------------------------------
    // 组合：符号映射（key 2）—— 已按流水段拆开
    //------------------------------------------------------------------
    wire signed [31:0] vraw_c = $signed(val_r) - $signed(off_r);   // ⚠️ 有符号
    wire signed [31:0] mx_c   = $signed(len_r) - 32'sd2;
    wire               esc_c  = neg_r || (vraw_r >= mx_r);
    wire signed [31:0] v_c    = esc_c ? mx_r : vraw_r;
    //  raw_val：负分支 -2v-1 == ~(v<<1)（补码恒等式，无加法器）
    //           正分支  2*(v-max)
    wire        [31:0] rv_c   = esc_r ? (neg_r ? (~(vraw_r << 1))
                                               : ((vraw_r - mx_r) << 1))
                                      : 32'd0;

    // raw_val 的 4bit 组数 = 最高非零组下标 + 1（等价于 C++ 的 while(rv){++n; rv>>=4;}）
    // ⚠️ 综合纪律：原写法是 `while (q != 32'd0) ... q = q >> 4;`。
    //    Vivado 对**数据相关终止条件**的 while 循环不保证可综合
    //    （可能报 Synth 8-27 / 无法静态展开）。入参只有 32 位 ⇒ 最多 8 个
    //    4bit 组，因此改写成**等价的优先级编码**（纯组合、静态展开）。
    //    等价性不是推理出来的：改完重跑 C2e，real/stress 两向量 payload
    //    仍与官方 encode() 逐字一致。
    function [4:0] nbyp_of;
        input [31:0] rv;
        begin
            if      (rv[31:28] != 4'd0) nbyp_of = 5'd8;
            else if (rv[27:24] != 4'd0) nbyp_of = 5'd7;
            else if (rv[23:20] != 4'd0) nbyp_of = 5'd6;
            else if (rv[19:16] != 4'd0) nbyp_of = 5'd5;
            else if (rv[15:12] != 4'd0) nbyp_of = 5'd4;
            else if (rv[11: 8] != 4'd0) nbyp_of = 5'd3;
            else if (rv[ 7: 4] != 4'd0) nbyp_of = 5'd2;
            else if (rv[ 3: 0] != 4'd0) nbyp_of = 5'd1;
            else                        nbyp_of = 5'd0;
        end
    endfunction

    // ⚠️ V6：nbyp 现在从**已寄存的** raw_r 算（S_RD 那一段），不再直接挂在长链末端
    wire [4:0] nbyp_c = nbyp_of(raw_r);
    wire [4:0] m_c    = nbyp_c / 5'd15;
    wire [4:0] vrem_c = nbyp_c % 5'd15;

    //---------------------------------------------------------------//
    // BRAM 同步读（cdf[v] / cdf[v+1] / rcp[v] 同址）
    //---------------------------------------------------------------//
    reg  [AW-1:0] rd_addr;
    reg  [31:0]   cdf_v0, cdf_v1;
    reg  [63:0]   rcp_v0;
    always @(posedge clk) begin
        cdf_v0 <= cdf_flat[rd_addr];
        cdf_v1 <= cdf_flat[rd_addr + 1'b1];
        rcp_v0 <= rcp_arr [rd_addr];
    end
    wire [15:0] main_start = cdf_v0[15:0];
    wire [15:0] main_freq  = cdf_v1[15:0] - cdf_v0[15:0];

    //---------------------------------------------------------------//
    // FSM
    //---------------------------------------------------------------//
    localparam [2:0] S_IDLE = 3'd0, S_MAP = 3'd1, S_ESC = 3'd2,
                     S_ARITH= 3'd3, S_RD  = 3'd4, S_EMIT= 3'd5;
    localparam [1:0] PH_R = 2'd0, PH_BL = 2'd1, PH_BH = 2'd2, PH_MAIN = 2'd3;

    reg [2:0]  state;
    reg [1:0]  phase;
    reg [3:0]  m_r, vrem_r, jcnt, bcnt;

    assign d_ready = (state == S_IDLE) && !s_valid;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= S_IDLE; phase <= PH_MAIN; s_valid <= 1'b0;
            s_start <= 16'd0; s_freq <= 16'd0; s_rcp <= 64'd0;
            s_bypass <= 1'b0; s_last <= 1'b0;
            val_r <= 32'sd0; len_r <= 32'd0; off_r <= 32'd0; row_r <= 32'd0;
            last_r <= 1'b0;
            vraw_r <= 32'sd0; mx_r <= 32'sd0; neg_r <= 1'b0; row_r2 <= 32'd0;
            esc_r <= 1'b0; v_r <= 32'sd0; row_r3 <= 32'd0;
            raw_r <= 32'd0;
            m_r <= 4'd0; vrem_r <= 4'd0; jcnt <= 4'd0; bcnt <= 4'd0;
            rd_addr <= {AW{1'b0}};
            n_escape <= 16'd0; n_bypass_syms <= 20'd0;
            max_raw <= 32'd0; max_n_bypass <= 5'd0; out_of_domain <= 1'b0;
        end else begin
            case (state)

            //-------------------------------------------------------
            // 段 1：查元数据（d_k → len/off/row），并锁存符号本身
            //-------------------------------------------------------
            S_IDLE: begin
                if (d_valid && d_ready) begin
                    len_r  <= cdf_len  [d_k];
                    off_r  <= cdf_off  [d_k];
                    row_r  <= row_start[d_k];
                    val_r  <= d_value;
                    last_r <= d_last;
                    state  <= S_MAP;
                end
            end

            //-------------------------------------------------------
            // 段 2：两次有符号减（v-off、len-2）
            //-------------------------------------------------------
            S_MAP: begin
                vraw_r <= vraw_c;
                mx_r   <= mx_c;
                neg_r  <= (vraw_c < 0);
                row_r2 <= row_r;
                state  <= S_ESC;
            end

            //-------------------------------------------------------
            // 段 3：越界判断 + 取桶下标 v_c
            //-------------------------------------------------------
            S_ESC: begin
                esc_r  <= esc_c;
                v_r    <= v_c;
                row_r3 <= row_r2;
                state  <= S_ARITH;
            end

            //-------------------------------------------------------
            // 段 4：算 raw_val + 算 BRAM 地址
            //-------------------------------------------------------
            S_ARITH: begin
                raw_r   <= rv_c;
                rd_addr <= row_r3[AW-1:0] + v_r[AW-1:0];
                state   <= S_RD;
            end

            //-------------------------------------------------------
            // S_RD：cdf/rcp 本拍末有效；用已寄存的 raw_r 做 nbyp 与统计；
            //        并把 r 组的起点装载好（MSB 组先发）
            //-------------------------------------------------------
            S_RD: begin
                jcnt   <= (nbyp_c == 5'd0) ? 4'd0 : (nbyp_c[3:0] - 4'd1);
                bcnt   <= 4'd0;
                m_r    <= m_c[3:0];
                vrem_r <= vrem_c[3:0];
                phase  <= esc_r ? ((nbyp_c == 5'd0) ? PH_BL : PH_R) : PH_MAIN;
                // 统计（V6 前放在 S_IDLE，值不变，只是晚 3 拍）
                if (esc_r)                 n_escape     <= n_escape + 16'd1;
                if (raw_r > max_raw)       max_raw      <= raw_r;
                if (nbyp_c > max_n_bypass) max_n_bypass <= nbyp_c;
                if (nbyp_c > 5'd7)         out_of_domain<= 1'b1;
                state  <= S_EMIT;
            end

            //-------------------------------------------------------
            // S_EMIT：与 V6 前**逐字相同**
            //-------------------------------------------------------
            S_EMIT: begin
                if (!s_valid) begin
                    // 发起一个符号
                    s_valid <= 1'b1;
                    s_last  <= 1'b0;
                    case (phase)
                    PH_MAIN: begin
                        s_start  <= main_start;
                        s_freq   <= main_freq;
                        s_rcp    <= rcp_v0;
                        s_bypass <= 1'b0;
                        s_last   <= last_r;            // ⭐ 只有主符号能是 last
                    end
                    PH_R: begin
                        s_start  <= {12'd0, raw_r[jcnt*4 +: 4]};
                        s_freq   <= {12'd0, raw_r[jcnt*4 +: 4]} + 16'd1;
                        s_rcp    <= 64'd0;
                        s_bypass <= 1'b1;
                    end
                    PH_BL: begin
                        s_start  <= {12'd0, vrem_r};
                        s_freq   <= {12'd0, vrem_r} + 16'd1;
                        s_rcp    <= 64'd0;
                        s_bypass <= 1'b1;
                    end
                    default: begin // PH_BH
                        s_start  <= 16'd15;
                        s_freq   <= 16'd16;
                        s_rcp    <= 64'd0;
                        s_bypass <= 1'b1;
                    end
                    endcase
                end else if (s_ready) begin
                    // 被下游接收 → 推进
                    s_valid <= 1'b0;
                    if (s_bypass) n_bypass_syms <= n_bypass_syms + 20'd1;
                    case (phase)
                    PH_MAIN: state <= S_IDLE;
                    PH_R: begin
                        if (jcnt == 4'd0) phase <= PH_BL;
                        else              jcnt  <= jcnt - 4'd1;
                    end
                    PH_BL: begin
                        if (m_r == 4'd0) phase <= PH_MAIN;
                        else             phase <= PH_BH;
                    end
                    default: begin // PH_BH
                        if (bcnt + 4'd1 >= m_r) phase <= PH_MAIN;
                        else                    bcnt  <= bcnt + 4'd1;
                    end
                    endcase
                end
            end

            default: state <= S_IDLE;
            endcase
        end
    end

endmodule
