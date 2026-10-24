//======================================================================
// rans_top.v —— C2e：把 rANS 核接进官方自定义算子骨架
//
// 设计原则（**只换计算核，不动软件契约**）：
//   · `reg_ctrl.v`  **原样复用官方文件**（软件寄存器映射一字不改）
//       0x00 START(w[0])   0x01 {rsize,rbase}   0x02 {wsize,wbase}
//       0x20 DONE(读)      0x03-0x0c 写寄存器×10  0x21-0x2a 读寄存器×10
//       0x77 RESET(w[0])   0xff DEBUG
//   · `pulse_cross.v` 跨时钟域，用法与官方 `adder_top.v` 完全一致
//   · **只把计算核换掉**：`adder` → `rans_cdf` + `rans_enc_stream`
//
// ── §divergence：为什么数据通路自己写、不用官方 `dma.v` ──────────────
//   官方 demo 内部位宽**不自洽**：
//     · `ai7030_edif_top.v` 里 `User_Ddr_awwdata/rdata` 是 **512 位**
//       （且 `awwinfo[70:7]` 是 64 字节使能 —— 正好 512 bit，两处互相印证）
//     · 但 `adder_op/adder_top.v` 只声明 **64 位**，集成时靠位宽截断"碰巧能用"
//     · `dma.v` 的 `comp_data` 也是 64 位，而地址步进 `+64`（= 512bit 一拍）
//   ⇒ 本模块**按 512 位实现**（与真实顶层一致），并自带"一拍 → 16 个符号"的拆包
//     与"16 个字 → 一拍"的拼包 —— 这层是 `dma.v` 没有的。
//
// ── §data_format：PL DDR 里的数据布局（PS 侧须按此写/读）─────────────
//   输入：每拍 512 bit = **16 个 32 位字**，每字一个逻辑符号
//           word[5:0]   = k      （CDF 行号 = glc_build_index(scale)，**PS 算**）
//           word[31:16] = value  （**有符号 16 位** = sym）
//           word[15:6]  = 忽略
//         ⚠️ 位域**必须**与下面 `sym_k`/`sym_v` 的切片一致（bit[5:0] / bit[31:16]）。
//            踩坑记录：首版 TB 打成 `{10'd0, k[5:0], v[15:0]}`（k在[21:16]、v在[15:0]）
//            —— k 与 v 交换，PL 把 v 的低 6 位当 CDF 行号用，escape 数从 577 掉到 338、
//            max_n_bypass 从 4 掉到 2。**改这里必须同步改 TB 与 PS 侧打包。**
//         ⚠️ 符号必须按**编码顺序**（i = n-1 → 0）被消费。
//            `REVERSE_IN=1`（默认）时：**倒着读拍、倒着取字**，
//            于是 **PS 只要按图像自然顺序写进 DDR 即可**。
//   输出：每拍 512 bit = 16 个 32 位 payload 字（内存顺序，小端展开即字节流）
//         末拍不足 16 字 **高位补 0**；真实字数由 `pl_words` 决定
//         （读 `RFU_RADDR2`，见下）
//
// ── §addressing：为什么用 RFU 寄存器传地址（**官方 reg_ctrl 一字不改**）──
//   官方 `reg_ctrl.v` 的 `rbase/rsize/wbase/wsize` **都只有 16 位**
//   （`rbase<=awdata[15:0]`, `rsize<=awdata[31:16]`），配上 `dma.v` 的
//   `araddr <= arbase` + 每拍 `+64` 字节 ⇒ **寻址上限 64 KB**。
//   而我们真实数据：一个 phase 16384 个符号 = 16 字/拍 × 1024 拍 × 64 B
//   = **正好 64 KB**，再加 payload 区必然溢出。
//   ⇒ 解法：**地址走官方预留的 RFU 写寄存器**（`reg_ctrl` 照抄不改）：
//        RFU_W0 (0x03) = rbase[31:0]  字节地址
//        RFU_W1 (0x04) = rsize        拍数（512bit/拍）
//        RFU_W2 (0x05) = wbase[31:0]  字节地址
//        RFU_W5 (0x08) = nsym         真实符号数（见下方 §quirk）
//     ⛔ RFU_W3 (0x06) / RFU_W4 (0x07) **不可用** —— 见 §quirk。
//     标准寄存器（0x00 START / 0x20 DONE）**用法完全不变**。
//
// ── §quirk：官方 reg_ctrl.v 的 RFU_W3/W4 是**1 位**寄存器（实测，非推断）──
//   官方 `rtl/official/reg_ctrl.v` L170-182：
//        else if(ra_awevent && ra_awaddr==RFU_WADDR3)
//            rfu_wreg3 <= #0.1 ra_awdata[0];     // ⚠️ 只存 bit0
//        else if(ra_awevent && ra_awaddr==RFU_WADDR4)
//            rfu_wreg4 <= #0.1 ra_awdata[0];     // ⚠️ 只存 bit0
//   其余 RFU_W0/1/2/5/6/7/8/9 都是整字 `ra_awdata`。W3/W4 应该是照抄
//   `comp_start`（只需要 bit0）留下的复制粘贴痕迹。
//   踩坑记录：C2e 首跑 stress 报 nsym=1（705=0x2C1 的 bit0）、real 报 nsym=0
//   （16384=0x4000 的 bit0）—— 两个症状同一根因。**不要用 W3/W4 传数值。**
//   直接证明：`sim/reg_ctrl_quirk_tb.v`（写 0x2C1 → 观察 rfu_wreg3==1）。
//     ⚠️ RFU 写在 `ra_clk` 域、在 `clk` 域使用：本模块在 `comp_start_d`
//        （已同步的脉冲）当拍采样，此时值是静态的 —— 标准安全写法。
//
// ── §regs：读寄存器（`RFU_RADDR0..9`）────────────────────────────────
//   R0 版本(0x20260922)   R1 状态{ood,busy,done,running}
//   R2 payload 字数        R3 n_escape        R4 n_bypass_syms
//   R5 编码总拍数          R6 max_raw         R7 max_n_bypass
//   R8/R9 保留
//
// ── §clock：两个时钟域（与官方一致）──────────────────────────────────
//   `clk` = hp_clk（数据域 / DDR 侧）   `ra_clk` = gp_clk（寄存器域 / PS 侧）
//======================================================================
`timescale 1ns / 1ps

module rans_top #(
    parameter DEPTH      = 16384,
    parameter AW         = 14,
    parameter MEM_ROOT   = "mem",
    parameter REVERSE_IN = 1
)(
    //------------ 寄存器访问端口（与官方 adder_top 同名）------------
    input  wire [31:0]  itf_ra_awaddr,
    input  wire [31:0]  itf_ra_awdata,
    input  wire         itf_ra_awvalid,
    output wire         itf_ra_awready,
    input  wire [31:0]  itf_ra_araddr,
    input  wire         itf_ra_arvalid,
    output wire         itf_ra_arready,
    output wire [31:0]  itf_ra_rdata,
    output wire         itf_ra_rvalid,
    input  wire         itf_ra_rready,

    //------------ 数据访问端口（512 位，匹配 ai7030_edif_top）--------
    output reg  [31:0]  itf_awaddr,
    output reg  [511:0] itf_awdata,
    output reg          itf_awvalid,
    input  wire         itf_awready,

    output reg  [31:0]  itf_araddr,
    output reg          itf_arvalid,
    input  wire         itf_arready,

    input  wire [511:0] itf_rdata,
    input  wire         itf_rvalid,
    output reg          itf_rready,

    output reg          reset_reg,

    input  wire         clk, ra_clk, rst_n, ra_rst_n
);

    localparam RESET_ADDR = 16'h77;

    //==================================================================
    // 0. 复位寄存器 + 门控复位（改自官方 adder_top.v:187-195）
    //
    // ⚠️ 本地加固（2026-09-25）：官方原版只用 `negedge ra_rst_n` 一个异步复位源。
    //    但 `reset_reg` 是**用 `clk`(hp_clk) 打拍、却由 `ra_clk`(gp_clk) 域的
    //    复位异步清零** —— 两个域的复位脉冲长度不同。若 `ra_rst_n` 的低脉冲
    //    恰好落在 `clk` 还没起振（MIG ui_clk 要等 DDR 校准）的时候，
    //    `reset_reg` 就可能停在不确定值；而 `reset_reg` 会门控
    //    `reg_ctrl` 的复位 —— **reg_ctrl 一旦被按住，
    //    `ra_arready=(ra_rvalid==0)` 不为高，上游 AXI 读永不返回**，
    //    经 `gpx_ww_split` 直接把整块板子锁死（本项目实测踩过两次，都需断电）。
    //    ⇒ 这里把 **两个域的复位都接上**，任一为低都清零，消除这个窗口。
    //==================================================================
    wire rst_n_1, ra_rst_n_1;
    always @(posedge clk or negedge ra_rst_n or negedge rst_n) begin
        if (ra_rst_n == 1'b0 || rst_n == 1'b0) reset_reg <= 1'b0;
        else if (itf_ra_awvalid && itf_ra_awready && itf_ra_awaddr[17:2] == RESET_ADDR)
            reset_reg <= itf_ra_awdata[0];
    end
    assign rst_n_1    = (~reset_reg) && rst_n;
    assign ra_rst_n_1 = (~reset_reg) && ra_rst_n;

    //==================================================================
    // 1. 官方 reg_ctrl（原样复用）
    //==================================================================
    wire        comp_start;                          // reg_ctrl 输出
    reg         comp_done;                           // 本模块驱动 → 经 pulse_cross 回 reg_ctrl
    wire        comp_start_d, comp_done_cross;       // 跨域后的脉冲
    wire [15:0] rbase, rsize, wbase, wsize;
    wire [31:0] rfu_wreg0, rfu_wreg1, rfu_wreg2, rfu_wreg3, rfu_wreg4,
                rfu_wreg5, rfu_wreg6, rfu_wreg7, rfu_wreg8, rfu_wreg9;
    wire [31:0] rfu_rreg0, rfu_rreg1, rfu_rreg2, rfu_rreg3, rfu_rreg4,
                rfu_rreg5, rfu_rreg6, rfu_rreg7, rfu_rreg8, rfu_rreg9;

    reg_ctrl u_reg_ctrl (
        .ra_awaddr (itf_ra_awaddr[17:2]), .ra_awdata (itf_ra_awdata),
        .ra_awvalid(itf_ra_awvalid),      .ra_awready(itf_ra_awready),
        .ra_araddr (itf_ra_araddr[17:2]), .ra_arvalid(itf_ra_arvalid),
        .ra_arready(itf_ra_arready),
        .ra_rdata  (itf_ra_rdata),        .ra_rvalid (itf_ra_rvalid),
        .ra_rready (itf_ra_rready),
        .comp_start(comp_start),          .comp_done (comp_done_cross),
        .rbase(rbase), .rsize(rsize), .wbase(wbase), .wsize(wsize),
        .rfu_rreg0(rfu_rreg0), .rfu_rreg1(rfu_rreg1), .rfu_rreg2(rfu_rreg2),
        .rfu_rreg3(rfu_rreg3), .rfu_rreg4(rfu_rreg4), .rfu_rreg5(rfu_rreg5),
        .rfu_rreg6(rfu_rreg6), .rfu_rreg7(rfu_rreg7), .rfu_rreg8(rfu_rreg8),
        .rfu_rreg9(rfu_rreg9),
        .rfu_wreg0(rfu_wreg0), .rfu_wreg1(rfu_wreg1), .rfu_wreg2(rfu_wreg2),
        .rfu_wreg3(rfu_wreg3), .rfu_wreg4(rfu_wreg4), .rfu_wreg5(rfu_wreg5),
        .rfu_wreg6(rfu_wreg6), .rfu_wreg7(rfu_wreg7), .rfu_wreg8(rfu_wreg8),
        .rfu_wreg9(rfu_wreg9),
        .clk(ra_clk), .rst_n(ra_rst_n_1)
    );

    //==================================================================
    // 2. 跨时钟域脉冲（照抄官方 adder_top.v:165-185）
    //==================================================================
    pulse_cross U_start_cross (
        .a2(comp_start_d),    .clk2(clk),    .rst2(~rst_n_1),    .rdy1(),
        .a1(comp_start),      .clk1(ra_clk), .rst1(~ra_rst_n_1));
    pulse_cross U_done_cross (
        .a2(comp_done_cross), .clk2(ra_clk), .rst2(~ra_rst_n_1), .rdy1(),
        .a1(comp_done),       .clk1(clk),    .rst1(~rst_n_1));

    //==================================================================
    // 3. 计算核：rans_cdf + rans_enc_stream
    //==================================================================
    reg                sym_valid;
    wire               sym_ready;
    reg  [5:0]         sym_k;
    reg  signed [15:0] sym_v;
    reg                sym_last;

    wire        c_valid, c_last, c_bypass, c_ready;
    wire [15:0] c_start, c_freq;
    wire [63:0] c_rcp;
    wire [15:0] n_escape;
    wire [19:0] n_bypass_syms;
    wire [31:0] max_raw;
    wire [4:0]  max_n_bypass;
    wire        out_of_domain;

    rans_cdf #(.MEM_ROOT(MEM_ROOT)) u_cdf (
        .clk(clk), .rst_n(rst_n_1),
        .d_valid(sym_valid), .d_ready(sym_ready),
        .d_k(sym_k), .d_value(sym_v), .d_last(sym_last),
        .s_valid(c_valid), .s_ready(c_ready), .s_last(c_last),
        .s_start(c_start), .s_freq(c_freq), .s_rcp(c_rcp), .s_bypass(c_bypass),
        .n_escape(n_escape), .n_bypass_syms(n_bypass_syms),
        .max_raw(max_raw), .max_n_bypass(max_n_bypass), .out_of_domain(out_of_domain)
    );

    reg            enc_start;
    wire           enc_busy, enc_done;
    wire [31:0]    cyc_total;
    wire [7:0]     cyc_put;
    wire [AW-1:0]  pl_base, pl_words;
    reg  [AW-1:0]  rd_addr;
    wire [31:0]    rd_data;

    rans_enc_stream #(.XW(64), .DEPTH(DEPTH), .AW(AW)) u_stream (
        .clk(clk), .rst_n(rst_n_1), .start(enc_start),
        .s_valid(c_valid), .s_ready(c_ready), .s_last(c_last),
        .s_start(c_start), .s_freq(c_freq), .s_rcp(c_rcp), .s_bypass(c_bypass),
        .busy(enc_busy), .done(enc_done), .cyc_total(cyc_total), .cyc_put(cyc_put),
        .pl_base(pl_base), .pl_words(pl_words), .rd_addr(rd_addr), .rd_data(rd_data)
    );

    //==================================================================
    // 4. 数据通路 FSM
    //==================================================================
    localparam [3:0] T_IDLE = 4'd0,
                     T_AR   = 4'd1,
                     T_RD   = 4'd2,
                     T_FEED = 4'd3,
                     T_FIN  = 4'd4,
                     T_PRE  = 4'd8,   // §read_lat：等一拍读口
                     T_FILL = 4'd5,
                     T_SEND = 4'd6,
                     T_WAIT = 4'd7;

    reg [3:0]   tstate;
    reg [15:0]  nbeat, beat, fed, wbeat, wnbeat;
    reg [511:0] rbuf, wbuf;
    reg [4:0]   sidx, widx;
    reg [15:0]  pl_words_r;
    reg [AW-1:0] pl_base_r;

    // 取字/取拍下标（REVERSE_IN=1：倒序，PS 按自然顺序写即可）
    wire [4:0]  take_idx = REVERSE_IN ? (5'd15 - sidx) : sidx;
    wire [15:0] rd_beat  = REVERSE_IN ? (nbeat - 16'd1 - beat) : beat;
    // ⭐ 32 位地址来自 RFU 寄存器（见 §addressing）
    wire [31:0] rd_addr_beat = rbase32 + {16'd0, rd_beat} * 32'd64;
    wire [31:0] wr_addr_beat = wbase32 + {16'd0, wbeat}   * 32'd64;
    // ⚠️ 已放置的 payload 字序号必须是**线性**的 wbeat*16 + widx。
    //    首版写成 `{wbeat, widx}` —— widx 是 5 位，拼接等价于 wbeat*32+widx，
    //    于是 wbeat=17 时就误判 (558>=558) 提前收尾、wbeat>=18 整拍全 0：
    //    stress 向量只有前 18 拍被写出（word 286 起全 0）。real 只有 1 拍所以没暴露。
    wire [20:0] wpos = {5'd0, wbeat} * 21'd16 + {16'd0, widx};

    // 启动当拍采样 RFU（此时是静态值）
    reg [31:0] rbase32, wbase32;
    reg [15:0] nsym;                 // ⭐ 真实符号数（末拍补齐的 0 不算）
    always @(posedge clk or negedge rst_n_1) begin
        if (!rst_n_1) begin rbase32 <= 32'd0; wbase32 <= 32'd0; nsym <= 16'd0; end
        else if (comp_start_d) begin
            rbase32 <= rfu_wreg0;      // 字节地址
            wbase32 <= rfu_wreg2;      // 字节地址
            // ⭐ 必须走 W5：W3/W4 在官方 reg_ctrl 里只有 1 位（见文件头 §quirk）
            nsym    <= rfu_wreg5[15:0];// 符号数（必须给！否则末拍补齐的 0 会被误编）
        end
    end

    // 状态上报
    assign rfu_rreg0 = 32'h2026_0922;
    assign rfu_rreg1 = {26'd0, out_of_domain, enc_busy, (tstate == T_WAIT),
                        2'd0, (tstate != T_IDLE)};
    assign rfu_rreg2 = {16'd0, pl_words_r};
    assign rfu_rreg3 = {16'd0, n_escape};
    assign rfu_rreg4 = {12'd0, n_bypass_syms};
    assign rfu_rreg5 = cyc_total;
    assign rfu_rreg6 = max_raw;
    assign rfu_rreg7 = {27'd0, max_n_bypass};
    assign rfu_rreg8 = {16'd0, nsym};                       // 调试：启动时采到的符号数
    assign rfu_rreg9 = {12'd0, tstate, fed[15:0]};          // 调试：{tstate, 已喂符号数}

    always @(posedge clk or negedge rst_n_1) begin
        if (!rst_n_1) begin
            tstate <= T_IDLE; nbeat <= 16'd0; beat <= 16'd0; fed <= 16'd0;
            itf_araddr <= 32'd0; itf_arvalid <= 1'b0; itf_rready <= 1'b0;
            sym_valid <= 1'b0; sym_k <= 6'd0; sym_v <= 16'd0; sym_last <= 1'b0;
            enc_start <= 1'b0; sidx <= 5'd0;
            itf_awaddr <= 32'd0; itf_awdata <= 512'd0; itf_awvalid <= 1'b0;
            wbeat <= 16'd0; wnbeat <= 16'd0; wbuf <= 512'd0; widx <= 5'd0;
            pl_words_r <= 16'd0; pl_base_r <= {AW{1'b0}};
            comp_done <= 1'b0; rd_addr <= {AW{1'b0}};
        end else begin
            enc_start <= 1'b0;
            comp_done <= 1'b0;

            case (tstate)
            //-------------------------------------------------------
            T_IDLE: begin
                sym_valid <= 1'b0;
                if (comp_start_d) begin
                    nbeat     <= rfu_wreg1[15:0];   // ⭐ 拍数来自 RFU_W1
                    beat      <= 16'd0;
                    fed       <= 16'd0;
                    enc_start <= 1'b1;
                    tstate    <= T_AR;
                end
            end
            //-------------------------------------------------------
            T_AR: begin
                itf_araddr  <= rd_addr_beat;      // 此时 beat 已稳定
                itf_arvalid <= 1'b1;
                tstate      <= T_RD;
            end
            //-------------------------------------------------------
            T_RD: begin
                if (itf_arvalid && itf_arready) itf_arvalid <= 1'b0;
                itf_rready <= 1'b1;
                if (itf_rvalid && itf_rready) begin
                    rbuf       <= itf_rdata;
                    itf_rready <= 1'b0;
                    sidx       <= 5'd0;
                    tstate     <= T_FEED;
                end
            end
            //-------------------------------------------------------
            T_FEED: begin
                if (!sym_valid) begin
                    sym_valid <= 1'b1;
                    sym_k     <= rbuf[take_idx*32 +: 6];
                    sym_v     <= rbuf[take_idx*32 + 16 +: 16];
                    // ⭐ 最后一个符号由**符号数**决定，不是由拍边界决定
                    sym_last  <= (fed == nsym - 16'd1);
                end else if (sym_ready) begin
                    sym_valid <= 1'b0;
                    fed <= fed + 16'd1;
                    if (fed == nsym - 16'd1) begin
                        tstate <= T_FIN;                  // 收够了就收尾，不看拍
                    end else if (sidx == 5'd15) begin
                        if (beat == nbeat - 16'd1) tstate <= T_FIN;
                        else begin
                            beat   <= beat + 16'd1;
                            tstate <= T_AR;
                        end
                    end else begin
                        sidx <= sidx + 5'd1;
                    end
                end
            end
            //-------------------------------------------------------
            T_FIN: begin
                sym_valid <= 1'b0;
                if (enc_done) begin
                    pl_base_r  <= pl_base;
                    pl_words_r <= {2'd0, pl_words};
                    wnbeat     <= (pl_words + 16'd15) >> 4;
                    wbeat      <= 16'd0;
                    widx       <= 5'd0;
                    wbuf       <= 512'd0;
                    rd_addr    <= pl_base;
                    // §read_lat：rans_enc_stream 的 payload 读口是**寄存输出**
                    // （为了综合出 BRAM），rd_data 对应上一拍的 rd_addr。
                    // 所以先设好 rd_addr，等一拍 T_PRE，再进 T_FILL 取第一个字。
                    tstate     <= T_PRE;
                end
            end
            //-------------------------------------------------------
            T_PRE: begin
                // ⚠️ 寄存读口的时序：D(k) = mem[A(k-1)]，所以要取 mem[pl_base+w]
                //    必须让 A 提前一拍。T_FIN 已设 A=pl_base（→ T_FILL0 拿到
                //    mem[pl_base]），本拍把 A 预加到 pl_base+1。
                //    之后 T_FILL 每次 `rd_addr<=rd_addr+1` 正好保持"提前一拍"。
                //    踩坑记录：不预加会出现"首字重复、整体后移一字"——
                //    C2e payload 报 word[1]==期望的 word[0]。
                rd_addr <= rd_addr + 1'b1;
                tstate  <= T_FILL;
            end
            //-------------------------------------------------------
            T_FILL: begin
                // 逐字读 payload 缓冲，按 bit 位塞进这一拍
                if ((widx == 5'd16) || (wpos >= {5'd0, pl_words_r})) begin
                    tstate <= T_SEND;
                end else begin
                    wbuf[widx*32 +: 32] <= rd_data;
                    // ⚠️ 只在**本拍之后组内还要继续取字**时推进地址。
                    //    widx==15 时本组已取满，紧接着的 T_SEND 若干拍不取字，
                    //    地址必须**保持**；否则下一组恢复取字时会多前进一步。
                    //    踩坑记录（实测症状）：每个 beat 的**第 0 个字**错一字，
                    //    其余 15 个字全对 —— C2e stress 报 34 处错、real（只 1 拍）
                    //    却 PASS，就是这个"跨拍"路径没被覆盖到。
                    if (widx != 5'd15) rd_addr <= rd_addr + 1'b1;
                    widx    <= widx + 5'd1;
                end
            end
            //-------------------------------------------------------
            T_SEND: begin
                if (!itf_awvalid) begin
                    itf_awdata  <= wbuf;
                    itf_awaddr  <= wr_addr_beat;    // ⭐ 32 位地址
                    itf_awvalid <= 1'b1;
                end else if (itf_awready) begin
                    itf_awvalid <= 1'b0;
                    if (wbeat + 16'd1 >= wnbeat) tstate <= T_WAIT;
                    else begin
                        wbeat  <= wbeat + 16'd1;
                        wbuf   <= 512'd0;
                        widx   <= 5'd0;
                        // ⚠️ 关键一拍：进入下一组 T_FILL_0 之前，rd_addr 必须
                        //    已经等于 pl_base + 新组首字的缓冲下标 + 1。
                        //    因为寄存读口满足 D(k)=mem[A(k-1)]，A 要**提前两拍**
                        //    到位；本拍是 T_FILL_0 的前一拍，所以在这里预加。
                        //    配合：T_PRE 也预加一次（首组）；T_FILL 内只在
                        //    widx!=15 时推进（widx==15 时组已取满，地址要保持）。
                        rd_addr <= rd_addr + 1'b1;
                        tstate <= T_FILL;
                    end
                end
            end
            //-------------------------------------------------------
            T_WAIT: begin
                comp_done <= 1'b1;
                tstate    <= T_IDLE;
            end
            default: tstate <= T_IDLE;
            endcase
        end
    end

endmodule
