//======================================================================
// rans_div.v  ——  rANS 用 64 位被除数除法器（radix-2 restoring 基线版）
//----------------------------------------------------------------------
// 出处：设计规格.md §四 难点 1（除法器=吞吐上限；本批只求对、不求快）
//      任务书 C2a1 §3（radix-2 restoring 伪码）
//
// 算法：逐位移位-减（shift-and-subtract），商从 MSB 到 LSB 依次生成。
//   rem = 0;
//   for (i = XW-1; i >= 0; i--) begin
//     sh = {rem[15:0], x[i]};            // 17 位（因为 freq<=65535, rem<=65534）
//     if (sh >= freq) { rem = sh - freq; q[i] = 1; }
//     else            { rem = sh; }
//   end
//   r = rem;
//
// 每操作数固定 XW+2 拍（=50 @ XW=48）：
//   1 拍锁存 → XW 拍逐位算 → 1 拍 done 输出。
//
// busy 语义：IDLE 且 start=1 时接受一次除法；busy=1 期间 start 被忽略
//   （不做流水、不做队列）。done 是单拍脉冲，q/r/cycles 同拍稳定可读。
//
// 本批不追求性能；radix-4 / 倒数表 / 流水留到下一批。
//======================================================================
`timescale 1ns / 1ps

module rans_div #(
    parameter XW = 64
)(
    input  wire            clk,
    input  wire            rst_n,
    input  wire            start,     // 单拍脉冲；busy 期间被忽略
    input  wire [XW-1:0]   x,
    input  wire [15:0]     freq,      // 保证 1..65535（rANS 的 f 下界=1）
    output reg  [XW-1:0]   q,
    output reg  [15:0]     r,
    output reg             busy,
    output reg             done,      // 单拍脉冲
    output reg  [7:0]      cycles     // start 被采到 done 拉起的拍数（含首尾）
);

    localparam [1:0] S_IDLE = 2'd0,
                     S_RUN  = 2'd1,
                     S_DONE = 2'd2;

    reg [1:0]    state;
    reg [XW-1:0] x_r;
    reg [15:0]   freq_r;
    reg [16:0]   rem;        // 17 位：rem<<1|bit <= 2*65534+1 = 131069
    reg [XW-1:0] q_r;
    reg [5:0]    i;          // 位指针：XW-1 downto 0，XW<=64 都放得下

    // 组合：本拍要做的一次 shift-subtract
    wire [16:0] sh  = {rem[15:0], x_r[i]};
    wire        sub = (sh >= {1'b0, freq_r});
    wire [16:0] nr  = sub ? (sh - {1'b0, freq_r}) : sh;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state   <= S_IDLE;
            x_r     <= {XW{1'b0}};
            freq_r  <= 16'd0;
            rem     <= 17'd0;
            q_r     <= {XW{1'b0}};
            i       <= 6'd0;
            q       <= {XW{1'b0}};
            r       <= 16'd0;
            busy    <= 1'b0;
            done    <= 1'b0;
            cycles  <= 8'd0;
        end else begin
            // done 是单拍脉冲：默认拉低，S_DONE 里再拉高
            done <= 1'b0;
            case (state)
                S_IDLE: begin
                    if (start) begin
                        x_r    <= x;
                        freq_r <= freq;
                        rem    <= 17'd0;
                        q_r    <= {XW{1'b0}};
                        i      <= XW - 1;
                        cycles <= 8'd1;   // 把 start 那一拍算进去
                        busy   <= 1'b1;
                        state  <= S_RUN;
                    end
                end
                S_RUN: begin
                    cycles <= cycles + 8'd1;
                    rem    <= nr;
                    q_r    <= {q_r[XW-2:0], sub};  // 商逐位左推，MSB 先进
                    if (i == 6'd0)
                        state <= S_DONE;
                    else
                        i <= i - 6'd1;
                end
                S_DONE: begin
                    q      <= q_r;
                    r      <= rem[15:0];      // 上一拍 S_RUN 已经把最后一次 nr 写进 rem
                    cycles <= cycles + 8'd1;  // 把 done 那一拍也算进去
                    busy   <= 1'b0;
                    done   <= 1'b1;
                    state  <= S_IDLE;
                end
                default: state <= S_IDLE;
            endcase
        end
    end

endmodule
