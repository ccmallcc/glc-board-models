//======================================================================
// rans_chain_tb.v —— C2d + C2c1 **联调对拍**（这才是 C2d 的最终判据）
//
//   rans_cdf.v (C2d: 查表/映射/escape 展开)
//        │  s_start/s_freq/s_rcp/s_bypass/s_last
//        ▼
//   rans_enc_stream.v (C2c1: 状态机 + 逆序缓冲 + flush)
//        │  pl_base / pl_words / rd_addr / rd_data
//        ▼
//   payload 字序列  ←→  期望 `_payload_words.txt`（由 gen_c2d_vector 从**官方 encode()** 导出）
//
// 判据：**逐字完全相同**，且 pl_words == 期望字数。
//
// 运行（在 C2_PL熵编码器 目录下）：
//   iverilog -g2012 -o /tmp/c2d_chain rtl/rans_cdf.v rtl/rans_enc_put.v rtl/rans_enc_stream.v sim/rans_chain_tb.v
//   vvp /tmp/c2d_chain +VEC=sim/vec/real
//======================================================================
`timescale 1ns / 1ps

module rans_chain_tb;

    localparam MAXN = 70000;
    localparam DEPTH = 16384, AW = 14;

    reg clk = 0;
    reg rst_n = 0;
    always #5 clk = ~clk;

    //---- C2d ----
    reg               d_valid;
    wire              d_ready;
    reg  [5:0]        d_k;
    reg  signed [15:0] d_value;
    reg               d_last;
    wire              c_valid, c_last, c_bypass;
    wire [15:0]       c_start, c_freq;
    wire [63:0]       c_rcp;
    wire [15:0]       n_escape;
    wire [19:0]       n_bypass_syms;
    wire [31:0]       max_raw;
    wire [4:0]        max_n_bypass;
    wire              out_of_domain;

    rans_cdf #(.MEM_ROOT("mem")) u_cdf (
        .clk(clk), .rst_n(rst_n),
        .d_valid(d_valid), .d_ready(d_ready), .d_k(d_k), .d_value(d_value), .d_last(d_last),
        .s_valid(c_valid), .s_ready(c_ready), .s_last(c_last),
        .s_start(c_start), .s_freq(c_freq), .s_rcp(c_rcp), .s_bypass(c_bypass),
        .n_escape(n_escape), .n_bypass_syms(n_bypass_syms),
        .max_raw(max_raw), .max_n_bypass(max_n_bypass), .out_of_domain(out_of_domain)
    );

    //---- C2c1 ----
    wire              c_ready;
    wire              busy, done;
    wire [31:0]       cyc_total;
    wire [7:0]        cyc_put;
    wire [AW-1:0]     pl_base, pl_words;
    reg  [AW-1:0]     rd_addr;
    wire [31:0]       rd_data;
    reg               start_pulse;

    rans_enc_stream #(.XW(64), .DEPTH(DEPTH), .AW(AW)) u_stream (
        .clk(clk), .rst_n(rst_n), .start(start_pulse),
        .s_valid(c_valid), .s_ready(c_ready), .s_last(c_last),
        .s_start(c_start), .s_freq(c_freq), .s_rcp(c_rcp), .s_bypass(c_bypass),
        .busy(busy), .done(done), .cyc_total(cyc_total), .cyc_put(cyc_put),
        .pl_base(pl_base), .pl_words(pl_words), .rd_addr(rd_addr), .rd_data(rd_data)
    );

    //---- 向量 ----
    integer lg_k[0:MAXN-1], lg_v[0:MAXN-1], lg_last[0:MAXN-1];
    reg [31:0] ex_w[0:MAXN-1];
    integer n_lg = 0, n_ex = 0, errs = 0, li, i, r, fd;
    reg [8*512-1:0] vecp, path;

    initial begin
        if (!$value$plusargs("VEC=%s", vecp)) begin $display("需要 +VEC="); $finish; end
        $sformat(path, "%0s_logical.txt", vecp);
        fd = $fopen(path, "r");
        if (fd == 0) begin $display("❌ 打不开 %0s", path); $finish; end
        while (!$feof(fd)) begin
            r = $fscanf(fd, "%d %d %d\n", lg_k[n_lg], lg_v[n_lg], lg_last[n_lg]);
            if (r == 3) n_lg = n_lg + 1;
        end
        $fclose(fd);

        $sformat(path, "%0s_payload_words.txt", vecp);
        fd = $fopen(path, "r");
        if (fd == 0) begin $display("❌ 打不开 %0s", path); $finish; end
        while (!$feof(fd)) begin
            r = $fscanf(fd, "%h\n", ex_w[n_ex]);
            if (r == 1) n_ex = n_ex + 1;
        end
        $fclose(fd);
        $display("向量 %0s : 逻辑符号 %0d 个, 期望 payload %0d 字", vecp, n_lg, n_ex);
    end

    //---- 驱动 ----
    initial begin
        d_valid = 0; d_k = 0; d_value = 0; d_last = 0; start_pulse = 0; rd_addr = 0;
        repeat (4) @(negedge clk);
        rst_n = 1;
        @(negedge clk);
        wait (n_lg > 0);

        // 起一帧
        @(negedge clk); start_pulse <= 1'b1;
        @(negedge clk); start_pulse <= 1'b0;

        for (li = 0; li < n_lg; li = li + 1) begin
            while (!d_ready) @(negedge clk);
            @(negedge clk);
            d_valid <= 1'b1;
            d_k     <= lg_k[li][5:0];
            d_value <= lg_v[li][15:0];
            d_last  <= lg_last[li][0];
            @(negedge clk);
            d_valid <= 1'b0;
            d_last  <= 1'b0;
        end

        // 等 done
        i = 0;
        while (!done && i < 400000) begin @(negedge clk); i = i + 1; end
        if (!done) begin
            $display("❌ 超时未 done（busy=%0d, 已发射到 %0d）", busy, li);
        end
        @(negedge clk);

        $display("---------------------------------------------");
        $display("payload: 实测 %0d 字 / 期望 %0d 字   pl_base=%0d  cyc_total=%0d",
                 pl_words, n_ex, pl_base, cyc_total);
        if (pl_words !== n_ex[AW-1:0]) begin
            $display("❌ payload 字数不符");
            errs = errs + 1;
        end
        // ⚠️ rans_enc_stream 的 payload 读口现在是**寄存输出**（`rd_data_r <= mem[rd_addr]`），
        //    这是为了能综合出 BRAM（见 rans_enc_stream.v §synth②）。
        //    因此 `rd_data` 对应的是**上一拍**的 `rd_addr`：必须
        //      ① 在 negedge 设地址；② 等一个 posedge 让寄存器采样；③ 再比较。
        //    旧版是「设完地址 `#1` 就比」—— 那是**组合读**的假设，
        //    改寄存后会整体错位一字（实测报 495 处不一致，首字重复）。
        //    注意：这只是**工装**要跟着接口改；功能正确性由 C2e 全路径验收保证。
        for (i = 0; i < n_ex; i = i + 1) begin
            @(negedge clk);
            rd_addr = pl_base + i[AW-1:0];
            @(posedge clk);
            #1;
            if (rd_data !== ex_w[i]) begin
                if (errs < 10)
                    $display("❌ 字[%0d] 实测 %08x 期望 %08x", i, rd_data, ex_w[i]);
                errs = errs + 1;
            end
        end

        $display("C2d 统计: n_escape=%0d n_bypass_syms=%0d max_raw=%0d max_n_bypass=%0d ood=%0d",
                 n_escape, n_bypass_syms, max_raw, max_n_bypass, out_of_domain);
        if (errs == 0)
            $display("==== 结论: rans_cdf + rans_enc_stream 产出 payload 与官方 encode() **逐字一致** ✅ ====");
        else
            $display("==== 结论: 有 %0d 处不一致 ❌ ====", errs);
        $finish;
    end

endmodule
