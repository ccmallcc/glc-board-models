//======================================================================
// rans_enc_put.v  ——  rANS 单符号状态更新 + renorm（把整条环闭上）
//----------------------------------------------------------------------
// 出处：任务书 C2b §3 接口、§4 算法（逐字照做）、§5 三个位宽坑、
//       §6 renorm 全宽比较可便宜化、§7 流水结构。
//       除法算法搬自 rtl/rans_div_rcp.v（C2a2，已 270,121/270,121 通过），
//       本文件是**新模块**，不改 rans_div*.v。
//
// 常量出处：assets/板端代码/glc_board_encoder.h
//   RANS64_L = 1<<31 (glc_board_encoder.h:27)  -> (RANS64_L>>16)<<32 = 2^47
//   GLC_BYPASS_PRECISION = 4 (glc_board_encoder.h:29)
//   x_max = ((RANS64_L>>16)<<32)*freq (glc_board_encoder.h:37,56) = 2^47*freq
//   bypass: freq_bypass = 1<<(16-BYPASS_BITS)=1<<12=4096 -> x_max=2^47*4096=2^59
//
// 两条路（§4）：
//   1) renorm：x_in >= x_max ? 吐低 32 位、xr=x_in>>32 : 不吐、xr=x_in
//      normal: x_max=2^47*freq  <=> x_in[63:47] >= freq（17 位比较，§6）
//      bypass: x_max=2^59       <=> x_in[63:59] != 0
//   2) 状态更新：
//      bypass: x_out = (xr<<BYPASS_BITS) | sym_start[3:0]        (Rans64EncPutBits)
//      normal: q=xr/freq, r=xr%freq;  x_out=(q<<16)+r+sym_start  (Rans64EncPut)
//      除法用倒数法（rcp 外部给）：q0=(xr*rcp)>>64, r0c=(xr-q0*freq)mod2^17,
//                                  r0c>=freq 则 q=q0+1,r=r0c-freq 否则 q=q0,r=r0c。
//      freq=1 不开特例（rcp=2^64-1, q0=xr-1, 修正后得 xr、余 0）。
//
// busy 语义（§7，本模块自定义并写进注释）：**不流水**（rANS 跨符号串行依赖）。
//   busy=1 期间再给 start 一律**忽略**（不排队、不丢当前运算），与 rans_div_rcp 一致。
//   done 单拍脉冲；x_out/emit/emit_word 同拍稳定并保持到下次运算。
//
//----------------------------------------------------------------------
// ⭐ 拍数：**6 拍/符号**（原为 4 拍；2026-09-26 为修时序而拆拍）
//
// 为什么拆（**上板实测的根因，不是猜的**）：
//   路由后时序报告里最差路径唯一，就是本模块第 1 拍：
//     Source      U_rans_top/u_stream/x_state_reg[47]/C
//     Destination U_rans_top/u_stream/u_put/pp2c__0/PCIN[0..16]
//     Requirement 5.000ns (clk_pll_i 200MHz)  Data Path Delay **5.615ns**  Slack −1.653ns
//   ⇒ 同一条组合路径里串了「17 位比较 → 32 位宽 mux → 32x32 偏积 → DSP PCIN」。
//   1366 个失败端点几乎全在这一条上，于是 PL 的计数器算出
//   `n_escape=20770 > nsym=16384` 这种数学上不可能的值 —— 结果全不可信。
//
//   ⚠️ **只在最前面加一个寄存器把 x_in 存一拍是没用的**：
//      `mux → 乘法 → 寄存器` 这一段本身就占满了 5ns。**必须把比较/mux 与乘法分到不同拍。**
//
// 拆分后每拍的最长路径：
//   拍1 S_IDLE：比较 + 2:1 mux（按 bypass 选）→ 寄存 emit_r0        ≈ 1ns
//   拍2 S_P1  ：由寄存后的 emit_r0/x_in_r 算 c_xr（纯 mux）→ 寄存    ≈ 0.5ns
//   拍3 S_P2  ：**乘法独占一拍**：xr_r 与 rcp_r 的 4 个偏积 → 寄存    ≈ 3.5~4ns
//   拍4 S_Q0  ：q0
//   拍5 S_R0C ：r0c / cor
//   拍6 S_OUT ：x_out / done
//
// 代价：吞吐 4→6 拍/符号（−33%，仍约 15x 于 A53 CPU 的 ~9ms/相位）。
// 改动后必须重跑 C2e（2/2）与 C2d（15/15、558/558）做功能回归。
//======================================================================
`timescale 1ns / 1ps

module rans_enc_put #(
    parameter XW = 64,
    parameter BYPASS_BITS = 4        // = GLC_BYPASS_PRECISION
)(
    input  wire            clk,
    input  wire            rst_n,
    input  wire            start,      // 单拍脉冲
    input  wire [XW-1:0]   x_in,       // 当前 state（**renorm 之前**）
    input  wire [15:0]     freq,       // CDF range；bypass=1 时忽略
    input  wire [15:0]     sym_start,  // CDF start；bypass=1 时低 4 位是 val
    input  wire [63:0]     rcp,        // = (2^64-1)/freq；bypass=1 时忽略
    input  wire            bypass,     // 1 = 走 Rans64EncPutBits
    output reg  [XW-1:0]   x_out,      // 新 state
    output reg             emit,       // 本符号是否吐出一个 32 位字
    output reg  [31:0]     emit_word,  // emit=0 时必须为 0（与 oracle 一致）
    output reg             busy,
    output reg             done,       // 单拍脉冲；x_out/emit/emit_word 同拍稳定
    output reg  [7:0]      cycles      // start 被采到 done 拉起的拍数（含首尾）
);

    localparam [2:0] S_IDLE = 3'd0,   // 拍1：算 renorm 触发 + 寄存输入
                     S_P1   = 3'd1,   // 拍2：由寄存输入算 c_xr + 寄存上下文
                     S_P2   = 3'd2,   // 拍3：乘法独占一拍 -> 偏积
                     S_Q0   = 3'd3,   // 拍4：算 q0
                     S_R0C  = 3'd4,   // 拍5：算 r0c,cor
                     S_OUT  = 3'd5;   // 拍6：算 x_out,done

    reg  [2:0]     state;

    //--- 拍1 组合：renorm 触发（§4 第一步，§6 便宜比较）---
    wire        emit_n = (x_in[63:47] >= {1'b0, freq});   // x_in >= freq<<47
    wire        emit_b = (|x_in[63:59]);                   // x_in >= 2^59
    wire        c_emit = bypass ? emit_b : emit_n;         // 拍1 最长：17 位比较 + 2:1 mux

    //--- 拍1（S_IDLE 且 start）锁存：原始输入与 renorm 触发 ---
    reg  [XW-1:0]  x_in_r;
    reg  [15:0]    freq_r0;
    reg  [15:0]    sym_start_r0;
    reg            bypass_r0;
    reg            emit_r0;
    reg  [63:0]    rcp_r;

    //--- 拍2 组合：由**已寄存**的 emit_r0/x_in_r 做 renorm 移位（纯 mux）---
    wire [63:0] c_xr2 = emit_r0 ? {32'd0, x_in_r[63:32]} : x_in_r;   // x_in>>32 只是接线

    //--- 拍2（S_P1）锁存：xr 与后续各拍要用的上下文 ---
    reg  [XW-1:0]  xr_r;
    reg  [15:0]    freq_r;
    reg  [15:0]    sym_start_r;
    reg            bypass_r;

    //--- 拍3（S_P2）：乘法独占一拍（§5 坑1：LHS 64 位 -> 完整积，不被截成 32 位）---
    wire [31:0] xr_hi = xr_r[63:32], xr_lo = xr_r[31:0];
    wire [31:0] r1 = rcp_r[63:32],    r0 = rcp_r[31:0];
    (* use_dsp = "yes" *) wire [63:0] pp0c = xr_lo * r0;
    (* use_dsp = "yes" *) wire [63:0] pp1c = xr_hi * r0;
    (* use_dsp = "yes" *) wire [63:0] pp2c = xr_lo * r1;
    (* use_dsp = "yes" *) wire [63:0] pp3c = xr_hi * r1;
    reg  [63:0] pp0, pp1, pp2, pp3;

    // 拍4 组合：q0 = pp3 + (mid>>32)（§5 坑2：mid 是 65 位）
    wire [64:0] mid2 = {1'b0, pp1} + {1'b0, pp2} + {1'b0, pp0[63:32]};
    wire [63:0] q0_c2 = pp3 + {31'd0, mid2[64:32]};
    reg  [63:0] q0_r;

    // 拍5 组合：r0c=(xr - q0*freq) mod 2^17（§5 坑3：qf 左边 33 位）
    wire [32:0] qf3    = q0_r[16:0] * freq_r;
    wire [16:0] r0c_c3 = xr_r[16:0] - qf3[16:0];
    wire        cor_c3 = (r0c_c3 >= {1'b0, freq_r});
    reg  [16:0] r0c_r;
    reg         cor_r;

    // 拍6 组合：出 q,r -> x_out；bypass 路并行算好再 mux
    wire [63:0] q4 = cor_r ? (q0_r + 64'd1) : q0_r;
    wire [16:0] r_sub = r0c_r - {1'b0, freq_r};
    wire [15:0] r4 = cor_r ? r_sub[15:0] : r0c_r[15:0];
    wire [63:0] x_norm = (q4 << 16) + {48'd0, r4} + {48'd0, sym_start_r};  // Rans64EncPut
    wire [63:0] x_byp  = (xr_r << BYPASS_BITS) | {12'd0, sym_start_r[3:0]}; // Rans64EncPutBits
    wire [63:0] x_out_c4 = bypass_r ? x_byp : x_norm;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state        <= S_IDLE;
            x_in_r       <= {XW{1'b0}};
            freq_r0      <= 16'd0;
            sym_start_r0 <= 16'd0;
            bypass_r0    <= 1'b0;
            emit_r0      <= 1'b0;
            rcp_r        <= 64'd0;
            xr_r         <= {XW{1'b0}};
            freq_r       <= 16'd0;
            sym_start_r  <= 16'd0;
            bypass_r     <= 1'b0;
            pp0 <= 64'd0; pp1 <= 64'd0; pp2 <= 64'd0; pp3 <= 64'd0;
            q0_r   <= 64'd0;
            r0c_r  <= 17'd0;
            cor_r  <= 1'b0;
            x_out  <= {XW{1'b0}};
            emit   <= 1'b0;
            emit_word <= 32'd0;
            busy   <= 1'b0;
            done   <= 1'b0;
            cycles <= 8'd0;
        end else begin
            done <= 1'b0;                    // done 单拍脉冲：默认拉低
            case (state)
                S_IDLE: begin
                    if (start) begin         // 拍1：算 renorm 触发，寄存输入
                        x_in_r       <= x_in;
                        freq_r0      <= freq;
                        sym_start_r0 <= sym_start;
                        bypass_r0    <= bypass;
                        rcp_r        <= rcp;
                        emit_r0      <= c_emit;
                        cycles       <= 8'd1;
                        busy         <= 1'b1;
                        state        <= S_P1;
                    end
                end
                S_P1: begin                  // 拍2：renorm 移位（纯 mux）+ 上下文
                    xr_r         <= c_xr2;
                    freq_r       <= freq_r0;
                    sym_start_r  <= sym_start_r0;
                    bypass_r     <= bypass_r0;
                    emit         <= emit_r0;
                    emit_word    <= emit_r0 ? x_in_r[31:0] : 32'd0;  // emit=0 时恒 0
                    cycles       <= cycles + 8'd1;
                    state        <= S_P2;
                end
                S_P2: begin                  // 拍3：乘法独占一拍
                    pp0    <= pp0c;
                    pp1    <= pp1c;
                    pp2    <= pp2c;
                    pp3    <= pp3c;
                    cycles <= cycles + 8'd1;
                    state  <= S_Q0;
                end
                S_Q0: begin                  // 拍4
                    q0_r   <= q0_c2;
                    cycles <= cycles + 8'd1;
                    state  <= S_R0C;
                end
                S_R0C: begin                 // 拍5
                    r0c_r  <= r0c_c3;
                    cor_r  <= cor_c3;
                    cycles <= cycles + 8'd1;
                    state  <= S_OUT;
                end
                S_OUT: begin                 // 拍6
                    x_out  <= x_out_c4;
                    cycles <= cycles + 8'd1;   // = 6
                    busy   <= 1'b0;
                    done   <= 1'b1;
                    state  <= S_IDLE;
                end
                default: state <= S_IDLE;
            endcase
        end
    end

endmodule
