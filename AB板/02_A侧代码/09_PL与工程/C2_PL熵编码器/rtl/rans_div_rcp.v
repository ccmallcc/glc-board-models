//======================================================================
// rans_div_rcp.v  ——  rANS 用 64 位被除数除法器（倒数 + 乘法 + 一次修正）
//----------------------------------------------------------------------
// 出处：任务书 C2a2 §2 算法、§3 接口、§4 三个位宽坑、§5 流水结构
//
// 算法（x 被除数 64 位, freq 1..65535, rcp = (2^64-1)/freq）：
//   q0  = (x * rcp) >> 64                 // 128 位乘积取高 64 位
//   r0c = (x - q0 * freq) mod 2^17        // 只保留低 17 位
//   if (r0c >= freq) { q = q0 + 1; r = r0c - freq; }
//   else             { q = q0;      r = r0c;      }
//
// 为什么对（任务书 C2a2 §2）：设 2^64-1 = rcp*freq + e, 0<=e<freq，则
//   x*rcp/2^64 = x/freq - x*(e+1)/(freq*2^64)，误差项 < x/2^64 < 1（实测 x<2^63）。
//   所以 q0 只可能是「真商」或「真商减一」，一次修正即够，不需要 while。
//   修正后 x-q0*freq < 2*freq <= 131070 < 2^17，故只需 17 位模减，
//   第二次乘积仅 17 位 x 16 位。
//   freq=1 时 rcp=2^64-1, q0 正好 x-1, 修正后得 x、余 0 —— 无需为 freq==1 开特例。
//
// busy 语义（任务书 C2a2 §5）：本模块**不流水**（rANS 状态跨符号串行依赖），
//   一次只处理一个除法。busy=1 期间再给 start 会被**忽略**（与 rans_div 基线一致），
//   不排队、不丢弃当前运算。done 是单拍脉冲，q/r/cycles 同拍稳定可读、并保持到下次运算。
//
// 拍数：5 拍（1 锁存输入 / 2 锁存偏积 / 3 锁存 q0 / 4 锁存 r0c,cor / 5 出 q,r,done）。
//======================================================================
`timescale 1ns / 1ps

module rans_div_rcp #(
    parameter XW = 64
)(
    input  wire            clk,
    input  wire            rst_n,
    input  wire            start,     // 单拍脉冲；busy 期间被忽略
    input  wire [XW-1:0]   x,         // 被除数（已过 renorm）
    input  wire [15:0]     freq,      // 1..65535（CDF 表实测上界；tb 扫到 65535）
    input  wire [63:0]     rcp,       // = (2^64-1)/freq
    output reg  [XW-1:0]   q,
    output reg  [15:0]     r,
    output reg             busy,
    output reg             done,      // 单拍脉冲
    output reg  [7:0]      cycles     // start 被采到 done 拉起的拍数（含首尾）
);

    localparam [2:0] S_IDLE = 3'd0,   // 等 start
                     S_PP   = 3'd1,   // 拍2：锁存四个 32x32 偏积
                     S_Q0   = 3'd2,   // 拍3：锁存 q0
                     S_R0C  = 3'd3,   // 拍4：锁存 r0c, cor
                     S_OUT  = 3'd4;   // 拍5：出 q,r, done

    reg  [2:0]     state;

    // 拍1 锁存的输入
    reg  [XW-1:0]  x_r;
    reg  [15:0]    freq_r;
    reg  [63:0]    rcp_r;

    // 拍2 锁存的偏积
    reg  [63:0]    pp0, pp1, pp2, pp3;
    // 拍3 锁存的商近似
    reg  [63:0]    q0_r;
    // 拍4 锁存的余数低 17 位与修正标志
    reg  [16:0]    r0c_r;
    reg            cor_r;

    //--------------------------------------------------------------
    // 拍2 组合：拆 32 位肢体求 128 位乘积的高 64 位（§4 坑 1、坑 2）
    //   x*rcp = pp3*2^64 + mid*2^32 + pp0[31:0]，故
    //   q0 = (x*rcp)>>64 = pp3 + (mid>>32)，精确（pp0[31:0]<2^32 不影响 >>64）。
    //--------------------------------------------------------------
    wire [31:0] x1 = x_r[63:32], x0 = x_r[31:0];
    wire [31:0] r1 = rcp_r[63:32], r0 = rcp_r[31:0];
    wire [63:0] c_pp0 = x0 * r0;      // LHS 64 位 -> 完整积，不被截成 32 位
    wire [63:0] c_pp1 = x1 * r0;
    wire [63:0] c_pp2 = x0 * r1;
    wire [63:0] c_pp3 = x1 * r1;

    // mid 是 65 位：pp1、pp2 各 ~2^64，相加会溢出 64 位（§4 坑 2）
    wire [64:0] c_mid = {1'b0, pp1} + {1'b0, pp2} + {1'b0, pp0[63:32]};

    //--------------------------------------------------------------
    // 拍3 组合：q0 = pp3 + (mid>>32)，取低 64 位（真商 <= 2^64-1，放得下）
    //--------------------------------------------------------------
    wire [63:0] c_q0 = pp3 + {31'd0, c_mid[64:32]};

    //--------------------------------------------------------------
    // 拍4 组合：r0c=(x - q0*freq) mod 2^17，一次修正判据（§4 坑 3）
    //   qf 左边必须 33 位，否则又被截成 17 位。
    //--------------------------------------------------------------
    wire [32:0] qf    = q0_r[16:0] * freq_r;               // 33 位完整积
    wire [16:0] c_r0c = x_r[16:0] - qf[16:0];              // 模 2^17
    wire        c_cor = (c_r0c >= {1'b0, freq_r});

    // 拍5 用的修正余数（r0c>=freq 时才有效）：具名 wire 才能做位选
    wire [16:0] r0c_sub = r0c_r - {1'b0, freq_r};

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state   <= S_IDLE;
            x_r     <= {XW{1'b0}};
            freq_r  <= 16'd0;
            rcp_r   <= 64'd0;
            pp0     <= 64'd0; pp1 <= 64'd0; pp2 <= 64'd0; pp3 <= 64'd0;
            q0_r    <= 64'd0;
            r0c_r   <= 17'd0;
            cor_r   <= 1'b0;
            q       <= {XW{1'b0}};
            r       <= 16'd0;
            busy    <= 1'b0;
            done    <= 1'b0;
            cycles  <= 8'd0;
        end else begin
            done <= 1'b0;                    // done 单拍脉冲：默认拉低
            case (state)
                S_IDLE: begin
                    if (start) begin         // 拍1：锁存输入（start 当拍算第 1 拍）
                        x_r    <= x;
                        freq_r <= freq;
                        rcp_r  <= rcp;
                        cycles <= 8'd1;
                        busy   <= 1'b1;
                        state  <= S_PP;
                    end
                end
                S_PP: begin                  // 拍2
                    pp0    <= c_pp0;
                    pp1    <= c_pp1;
                    pp2    <= c_pp2;
                    pp3    <= c_pp3;
                    cycles <= cycles + 8'd1;
                    state  <= S_Q0;
                end
                S_Q0: begin                   // 拍3
                    q0_r   <= c_q0;
                    cycles <= cycles + 8'd1;
                    state  <= S_R0C;
                end
                S_R0C: begin                  // 拍4
                    r0c_r  <= c_r0c;
                    cor_r  <= c_cor;
                    cycles <= cycles + 8'd1;
                    state  <= S_OUT;
                end
                S_OUT: begin                   // 拍5：出结果
                    q      <= cor_r ? (q0_r + 64'd1) : q0_r;
                    r      <= cor_r ? r0c_sub[15:0] : r0c_r[15:0];
                    cycles <= cycles + 8'd1;   // = 5
                    busy   <= 1'b0;
                    done   <= 1'b1;
                    state  <= S_IDLE;
                end
                default: state <= S_IDLE;
            endcase
        end
    end

endmodule
