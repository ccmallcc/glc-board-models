//======================================================================
// rans_cdf_tb.v —— C2d 的 testbench
//
// 判据（与 C2a/b/c 一致的标准）：**与 C++ 参考实现逐字节等价**
//   本 tb 验的是"展开层"：把 (k, value) 逻辑符号流喂进去，
//   发射出来的 (start, freq, bypass) 序列必须与 gen_c2d_vector 导出的
//   `_rans.txt` **逐行完全相同**，且 `last` 落在正确的位置。
//
// 向量由 工具/gen_c2d_vector.cpp 生成（它自己也会自检：
//   把导出的展开序列倒序喂给官方 Rans64EncPut，必须得到与官方 encode() 相同的 payload）。
//
// 运行（在 C2_PL熵编码器 目录下，$readmemh 用相对路径 mem/）：
//   iverilog -g2012 -o /tmp/c2d rtl/rans_cdf.v sim/rans_cdf_tb.v
//   vvp /tmp/c2d +VEC=sim/vec/real
//   vvp /tmp/c2d +VEC=sim/vec/stress
//======================================================================
`timescale 1ns / 1ps

module rans_cdf_tb;

    localparam MAXN = 70000;

    reg clk = 0;
    reg rst_n = 0;
    always #5 clk = ~clk;

    // ---- DUT ----
    reg               d_valid;
    wire              d_ready;
    reg  [5:0]        d_k;
    reg  signed [15:0] d_value;
    reg               d_last;
    wire              s_valid, s_last, s_bypass;
    wire [15:0]       s_start, s_freq;
    wire [63:0]       s_rcp;
    reg               s_ready = 1'b1;
    wire [15:0]       n_escape;
    wire [19:0]       n_bypass_syms;
    wire [31:0]       max_raw;
    wire [4:0]        max_n_bypass;
    wire              out_of_domain;

    rans_cdf #(.MEM_ROOT("mem")) dut (
        .clk(clk), .rst_n(rst_n),
        .d_valid(d_valid), .d_ready(d_ready), .d_k(d_k), .d_value(d_value), .d_last(d_last),
        .s_valid(s_valid), .s_ready(s_ready), .s_last(s_last),
        .s_start(s_start), .s_freq(s_freq), .s_rcp(s_rcp), .s_bypass(s_bypass),
        .n_escape(n_escape), .n_bypass_syms(n_bypass_syms),
        .max_raw(max_raw), .max_n_bypass(max_n_bypass), .out_of_domain(out_of_domain)
    );

    // ---- 向量 ----
    integer lg_k   [0:MAXN-1];
    integer lg_v   [0:MAXN-1];
    integer lg_last[0:MAXN-1];
    integer ex_st  [0:MAXN-1];
    integer ex_fr  [0:MAXN-1];
    integer ex_by  [0:MAXN-1];
    integer ex_ls  [0:MAXN-1];

    integer n_lg = 0, n_ex = 0, cap = 0, errs = 0, li, ci, r, fd;
    reg [8*512-1:0] vecp, path;

    initial begin
        if (!$value$plusargs("VEC=%s", vecp)) begin
            $display("用法: vvp <sim> +VEC=<向量前缀>"); $finish;
        end

        $sformat(path, "%0s_logical.txt", vecp);
        fd = $fopen(path, "r");
        if (fd == 0) begin $display("❌ 打不开 %0s", path); $finish; end
        while (!$feof(fd)) begin
            r = $fscanf(fd, "%d %d %d\n", lg_k[n_lg], lg_v[n_lg], lg_last[n_lg]);
            if (r == 3) n_lg = n_lg + 1;
        end
        $fclose(fd);

        $sformat(path, "%0s_rans.txt", vecp);
        fd = $fopen(path, "r");
        if (fd == 0) begin $display("❌ 打不开 %0s", path); $finish; end
        while (!$feof(fd)) begin
            r = $fscanf(fd, "%d %d %d %d\n", ex_st[n_ex], ex_fr[n_ex], ex_by[n_ex], ex_ls[n_ex]);
            if (r == 4) n_ex = n_ex + 1;
        end
        $fclose(fd);

        $display("向量 %0s : 逻辑符号 %0d 个, 期望 rANS 符号 %0d 个", vecp, n_lg, n_ex);
    end

    // ---- 采集 + 比对 ----
    always @(posedge clk) begin
        if (rst_n && s_valid && s_ready) begin
            if (cap >= n_ex) begin
                $display("❌ [%0d] 多发射了（期望只有 %0d 个）", cap, n_ex);
                errs = errs + 1;
            end else begin
                if (s_start !== ex_st[cap][15:0] || s_freq !== ex_fr[cap][15:0] ||
                    s_bypass !== ex_by[cap][0] || s_last !== ex_ls[cap][0]) begin
                    if (errs < 12)
                        $display("❌ [%0d] 实测 start=%0d freq=%0d byp=%0d last=%0d  |  期望 start=%0d freq=%0d byp=%0d last=%0d",
                                 cap, s_start, s_freq, s_bypass, s_last,
                                 ex_st[cap], ex_fr[cap], ex_by[cap], ex_ls[cap]);
                    errs = errs + 1;
                end
            end
            cap = cap + 1;
        end
    end

    // ---- 驱动 ----
    initial begin
        d_valid = 0; d_k = 0; d_value = 0; d_last = 0;
        repeat (4) @(negedge clk);
        rst_n = 1;
        @(negedge clk);
        wait (n_lg > 0);

        for (li = 0; li < n_lg; li = li + 1) begin
            // 等到 DUT 能收
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

        // 等发射完
        ci = 0;
        while (ci < 40000) begin
            @(negedge clk);
            ci = ci + 1;
            if (cap >= n_ex && !s_valid) ci = 40000;
        end
        repeat (20) @(negedge clk);

        $display("---------------------------------------------");
        $display("发射数量: 实测 %0d / 期望 %0d", cap, n_ex);
        $display("DUT 统计: n_escape=%0d  n_bypass_syms=%0d  max_raw=%0d  max_n_bypass=%0d  ood=%0d",
                 n_escape, n_bypass_syms, max_raw, max_n_bypass, out_of_domain);
        if (cap != n_ex) begin
            $display("❌ 数量不符");
            errs = errs + 1;
        end
        if (errs == 0) $display("==== 结论: 与 C++ 参考展开**逐符号一致** ✅ ====");
        else           $display("==== 结论: 有 %0d 处不一致 ❌ ====", errs);
        $finish;
    end

endmodule
