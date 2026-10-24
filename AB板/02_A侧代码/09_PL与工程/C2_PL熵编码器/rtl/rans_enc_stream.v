//======================================================================
// rans_enc_stream.v  ——  rANS 符号流 + 逆序缓冲 + flush
//----------------------------------------------------------------------
// 出处：任务书 C2c1 §2 算法（照 assets/板端代码/glc_board_encoder.h 的 encode() 尾部）、
//       §3 接口（端口名/顺序不许改）、§4 建议控制流。
//       本模块**例化** C2b 已验收的 rans_enc_put（4 拍/符号），不重实现其逻辑。
//
// 关键事实（均已读到、指到出处）：
//   RANS64_L = (1ull<<31)                glc_board_encoder.h:27
//   Rans64EncInit -> *r = RANS64_L       glc_board_encoder.h:32
//     => x 初值 64'h0000000080000000（tb 与 §3 均按此闭式给出）
//   encode 尾部：ptr=缓冲区末尾；逐符号 put/putbits；再 flush；
//     payload = [ptr, 末尾)              glc_board_encoder.h:165-174
//   flush 字序（最容易搞反）：
//     *--ptr = (uint32_t)(x>>32);   // 先写**高**字 -> 落在 ptr-1（高地址）
//     *--ptr = (uint32_t)(x);       // 再写**低**字 -> 落在 ptr-2（低地址）
//     glc_board_encoder.h:47-48
//   => 最终内存顺序 = [flush低, flush高, emit_{n-1}, ..., emit_0]（任务书 §2 一致）
//
// 为什么比字就够（任务书 §1）：逐字节正确性已由 工具/verify_payload.py 独立证明
//   （黄金字节流 == 字序列小端展开），故 tb 只比 32 位字。本模块只产字，不碰字节。
//
// 吐字（emit=1，emit_word 来自 rans_enc_put）：ptr 递减，先发射的字落在高地址：
//     mem[ptr-1] <= put_emit_word; ptr <= ptr - 1;   // 对应 C 的 *--ptr = x
//
// ── §synth：为**综合出 BRAM** 而做的三处结构调整（2026-09-24）────────────
//   现象（Vivado 2018.3 前置综合，实测报错原文）：
//     ERROR: [Synth 8-3391] Unable to infer a block/distributed RAM for
//       'mem_reg' ... Failed to dissolve the memory into bits because the
//       number of bits (524288) is too large
//     WARNING: [Synth 8-4767] Trying to implement RAM 'mem_reg' in registers.
//       Reason: 1: RAM has multiple writes via different ports in same process.
//   三个原因，逐个消除：
//     ① 写口不唯一 —— 原先把 `mem[...]` 直接写在**带异步复位的 FSM 块**里，
//        且 S_FLUSH 一拍写两个字、S_RUN 又另写一个地址 ⇒ 综合器看到"同一进程
//        多个写口"。现在把 RAM 抽成**独立 always 块**，只留一组
//        `mem_we/mem_wa/mem_wd`，**单写口**。
//     ② 读口是组合读（`assign rd_data = mem[rd_addr]`）—— BRAM 要求**寄存读**。
//        现在 `rd_data_r <= mem[rd_addr]`，`rd_data` 为寄存输出。
//        ⇒ rans_top 侧同步加了 T_PRE 一拍（见 rans_top.v §read_lat）。
//     ③ flush 原本同一拍写 ptr-1 / ptr-2 —— 单写口做不到，拆成
//        S_FLUSH(高字) + S_FLUSH2(低字) 两拍。**字节序不变**。
//   ⚠️ 这三处都只改**时序结构**、不改**功能**：改完重跑 C2e，real/stress
//      两向量的 payload 仍与官方 encode() 逐字一致（这是验收判据）。
//======================================================================
`timescale 1ns / 1ps

module rans_enc_stream #(
    parameter XW    = 64,
    parameter DEPTH = 16384,       // 输出缓冲深度（字数）
    parameter AW    = 14           // 须满足 2**AW == DEPTH
)(
    input  wire            clk,
    input  wire            rst_n,
    input  wire            start,     // 单拍脉冲：开始一帧
    // 符号输入流（已经是编码顺序，即符号表的逆序）
    input  wire            s_valid,
    output wire            s_ready,   // 能收下一个符号时拉高
    input  wire            s_last,    // 与 s_valid 同拍：本符号是本帧最后一个
    input  wire [15:0]     s_start,   // CDF start（bypass 时低 4 位是 val）
    input  wire [15:0]     s_freq,    // CDF range（bypass 时忽略）
    input  wire [63:0]     s_rcp,     // (2^64-1)/freq（bypass 时忽略）
    input  wire            s_bypass,
    // 状态
    output reg             busy,
    output reg             done,      // 一帧（含 flush）完成，单拍脉冲
    output reg  [31:0]     cyc_total, // 本帧从 start 到 done 的总拍数
    output reg  [7:0]      cyc_put,   // 最近一个符号的拍数（来自 rans_enc_put）
    // payload 读出（内存顺序，从 pl_base 起 pl_words 个字）
    output reg  [AW-1:0]   pl_base,
    output reg  [AW-1:0]   pl_words,
    input  wire [AW-1:0]   rd_addr,
    output wire [31:0]     rd_data    // **寄存读**：rd_data 对应上一拍的 rd_addr
);

    localparam [2:0] S_IDLE   = 3'd0,
                     S_RUN    = 3'd1,
                     S_FLUSH  = 3'd2,   // flush 高字
                     S_FLUSH2 = 3'd3,   // flush 低字
                     S_DONE   = 3'd4;

    localparam [XW-1:0] RANS64_L_INIT = 64'h0000000080000000; // = RANS64_L (glc_board_encoder.h:27,32)

    //------------------------------------------------------------------
    // §synth① 逆序缓冲：独立 always 块、单写口、无异步复位（BRAM 规范写法）
    //------------------------------------------------------------------
    reg  [31:0]        mem [0:DEPTH-1];
    reg                mem_we;
    reg  [AW-1:0]      mem_wa;
    reg  [31:0]        mem_wd;

    always @(posedge clk) begin           // ⚠️ 故意**没有** rst_n：BRAM 不能有异步复位
        if (mem_we) mem[mem_wa] <= mem_wd;
    end

    //------------------------------------------------------------------
    // §synth② 寄存读口（BRAM 要求）。rans_top 用 T_PRE 一拍对齐。
    //------------------------------------------------------------------
    reg  [31:0]        rd_data_r;
    always @(posedge clk) begin
        rd_data_r <= mem[rd_addr];
    end
    assign rd_data = rd_data_r;

    //--- 闭环 state / 符号锁存寄存器（喂 rans_enc_put 与 tb 端口名一致）---
    reg  [2:0]         state;
    reg  [AW:0]        ptr;              // 1 位余量以容纳初值 DEPTH
    // 写地址：取低 AW 位正好是 ptr-1 / ptr-2（ptr<=DEPTH=2^AW，故模 2^AW 下正确）
    wire [AW:0]        wa1 = ptr - 1'b1;
    wire [AW:0]        wa2 = ptr - 2'd2;
    reg  [XW-1:0]      x_state;
    reg  [15:0]        s_start_r, s_freq_r;
    reg  [63:0]        s_rcp_r;
    reg                s_byp_r, s_last_r;
    reg                launch;           // 单拍：下一拍 put_start 拉起
    reg  [31:0]        cyc_cnt;          // 帧内拍数计数

    //--- rans_enc_put 连线 ---
    wire               put_start = launch;
    wire [XW-1:0]      put_x_out;
    wire               put_emit;
    wire [31:0]        put_emit_word;
    wire               put_busy, put_done;
    wire [7:0]         put_cycles;

    // 能收下一个符号 = 正在跑帧、put 不忙、且没在拉起 put_start
    assign s_ready = (state == S_RUN) && !put_busy && !launch;

    rans_enc_put #(.XW(XW), .BYPASS_BITS(4)) u_put (
        .clk(clk), .rst_n(rst_n), .start(put_start),
        .x_in(x_state), .freq(s_freq_r), .sym_start(s_start_r), .rcp(s_rcp_r), .bypass(s_byp_r),
        .x_out(put_x_out), .emit(put_emit), .emit_word(put_emit_word),
        .busy(put_busy), .done(put_done), .cycles(put_cycles));

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state     <= S_IDLE;
            ptr       <= {(AW+1){1'b0}};
            x_state   <= {XW{1'b0}};
            s_start_r <= 16'd0;  s_freq_r  <= 16'd0;
            s_rcp_r   <= 64'd0;
            s_byp_r   <= 1'b0;   s_last_r  <= 1'b0;
            launch    <= 1'b0;
            busy      <= 1'b0;
            done      <= 1'b0;
            cyc_total <= 32'd0;
            cyc_put   <= 8'd0;
            cyc_cnt   <= 32'd0;
            pl_base   <= {AW{1'b0}};
            pl_words  <= {AW{1'b0}};
            mem_we    <= 1'b0;
            mem_wa    <= {AW{1'b0}};
            mem_wd    <= 32'd0;
        end else begin
            done   <= 1'b0;              // done 单拍脉冲
            launch <= 1'b0;              // put_start 单拍
            mem_we <= 1'b0;              // 写使能单拍（默认关）

            if (busy)                    // 帧内计数（start 到 done）
                cyc_cnt <= cyc_cnt + 32'd1;

            case (state)
                S_IDLE: begin
                    if (start) begin
                        ptr     <= DEPTH;              // ptr 是 AW+1 位，恰好容纳 DEPTH=2^AW
                        x_state <= RANS64_L_INIT;
                        cyc_cnt <= 32'd0;
                        busy    <= 1'b1;
                        state   <= S_RUN;
                    end
                end

                S_RUN: begin
                    // 提交一个刚完成的 put（done 单拍，同拍 x_out/emit/emit_word 有效）
                    if (put_done) begin
                        x_state <= put_x_out;
                        cyc_put <= put_cycles;
                        if (put_emit) begin
                            mem_we <= 1'b1;
                            mem_wa <= wa1[AW-1:0];
                            mem_wd <= put_emit_word;
                            ptr    <= ptr - 1;
                        end
                        if (s_last_r)
                            state <= S_FLUSH;
                    end
                    // 收下一个符号（done 拍且非最后：同拍即可接；否则等空闲拍）
                    if (s_valid && s_ready && !(put_done && s_last_r)) begin
                        s_start_r <= s_start;
                        s_freq_r  <= s_freq;
                        s_rcp_r   <= s_rcp;
                        s_byp_r   <= s_bypass;
                        s_last_r  <= s_last;
                        launch    <= 1'b1;
                    end
                end

                // §synth③ flush 拆两拍：先高字（高地址），再低字（低地址）。
                //          内存顺序最终仍是 [flush低, flush高, ...]，与 C 一致。
                S_FLUSH: begin
                    mem_we <= 1'b1;
                    mem_wa <= wa1[AW-1:0];          // ptr-1 = 高地址
                    mem_wd <= x_state[63:32];
                    state  <= S_FLUSH2;
                end

                S_FLUSH2: begin
                    mem_we <= 1'b1;
                    mem_wa <= wa2[AW-1:0];          // ptr-2 = 低地址
                    mem_wd <= x_state[31:0];
                    ptr    <= ptr - 2;
                    state  <= S_DONE;
                end

                S_DONE: begin
                    pl_base   <= ptr[AW-1:0];
                    pl_words  <= DEPTH - ptr[AW:0];    // = DEPTH - ptr，真实 payload 远小于 DEPTH
                    cyc_total <= cyc_cnt;
                    busy      <= 1'b0;
                    done      <= 1'b1;
                    state     <= S_IDLE;
                end

                default: state <= S_IDLE;
            endcase
        end
    end

endmodule
