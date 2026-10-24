//======================================================================
// rans_div_rcp_tb.v  ——  倒数乘法除法器对拍 tb
//----------------------------------------------------------------------
// 出处：任务书 C2a2 §6（T1 真实向量 / T2 全 f 扫描 / T3 边界 20 条）
//
// 黄金参考 = Verilog 语言自带的无符号除法（与 RTL 实现无关）：
//   gq = x / {48'd0, freq};  gr = x % {48'd0, freq};
//   rcp = 64'hFFFF_FFFF_FFFF_FFFF / {48'd0, freq};   // 按定义喂给 DUT
//
// 用法：vvp rans_div_rcp_tb.vvp +VEC=/mnt/e/fudanwei/_logs/rans/divvec_p1.txt
//
// 完成判据（格式照抄 §6，正常路径绝不打印 FAIL/ERROR/Fatal 子串）：
//   TOTAL=... BAD=... cycles_min=.. cycles_max=..
//   CHECKS=... n_vec=... n_sweep=... n_bnd=... n_cor1=...
//   PASS rans_div_rcp: N/N vectors matched, avg cycles = X.X
//   （失败才打 FAIL rans_div_rcp: K bad）
//======================================================================
`timescale 1ns / 1ps

module rans_div_rcp_tb;

    localparam integer XW = 64;

    reg            clk;
    reg            rst_n;

    // 共享激励
    reg            start_n;   // 新模块
    reg            start_o;   // 旧模块（仅 T1 用）
    reg  [XW-1:0]  x;
    reg  [15:0]    freq;
    reg  [63:0]    rcp;

    // 新模块 DUT
    wire [XW-1:0]  qn;
    wire [15:0]    rn;
    wire           donen;
    wire           busyn;
    wire [7:0]     cyclesn;
    rans_div_rcp #(.XW(XW)) dut_new (
        .clk(clk), .rst_n(rst_n), .start(start_n),
        .x(x), .freq(freq), .rcp(rcp),
        .q(qn), .r(rn), .busy(busyn), .done(donen), .cycles(cyclesn)
    );

    // 旧模块 DUT（C2a1 基线，交叉对拍用；端口无 rcp）
    wire [XW-1:0]  qo;
    wire [15:0]    ro;
    wire           doneo;
    wire           busyo;
    wire [7:0]     cycleso;
    rans_div #(.XW(XW)) dut_old (
        .clk(clk), .rst_n(rst_n), .start(start_o),
        .x(x), .freq(freq),
        .q(qo), .r(ro), .busy(busyo), .done(doneo), .cycles(cycleso)
    );

    // 100 MHz：周期 10 ns
    initial clk = 1'b0;
    always #5 clk = ~clk;

    //--- 计数 ---
    integer checks;    // 逐条断言总数（须 >= 245000）
    integer bad;       // 不吻合数
    integer n_vec;     // T1
    integer n_sweep;   // T2
    integer n_bnd;     // T3
    integer n_cor1;    // 修正支路命中数
    integer cyc_sum, n_cyc, cyc_min, cyc_max;   // 新模块 cycles

    //--- 黄金参考 / 参考算法量 ---
    reg [XW-1:0] gq;
    reg [15:0]   gr;
    reg [127:0]  prod;
    reg [63:0]   q0_ref;
    integer      cor_ref;

    integer fd, rc, line_no;
    reg [63:0]   tx, tf, tq, tr;   // 文件里 4 个 token（q/r 只解析不作黄金参考）
    reg [1023:0] vpath;

    //--- 由当前 x / freq 算语言级黄金参考 + 参考商 q0/cor ---
    task compute_golden;
    begin
        gq   = x / {48'd0, freq};
        gr   = x % {48'd0, freq};
        rcp  = 64'hFFFF_FFFF_FFFF_FFFF / {48'd0, freq};
        prod = x * rcp;                 // 128 位 LHS -> 完整积
        q0_ref = prod[127:64];           // (x*rcp)>>64
        if (gq === q0_ref)            cor_ref = 0;
        else if (gq === q0_ref + 1)   cor_ref = 1;
        else                          cor_ref = 8;  // 算法层异常（不该出现）
        if (cor_ref == 1) n_cor1 = n_cor1 + 1;
    end
    endtask

    task note_cycles;   // 记新模块 cycles
    begin
        cyc_sum = cyc_sum + cyclesn;
        n_cyc   = n_cyc + 1;
        if (cyclesn < cyc_min) cyc_min = cyclesn;
        if (cyclesn > cyc_max) cyc_max = cyclesn;
    end
    endtask

    //--- T1：同时喂新/旧，等较慢的旧模块 done，三方比对 ---
    //   新模块输出寄存器在 done 后保持，故旧模块 66 拍结束时读数仍有效。
    task run_both;
        input [255:0] tag;
    begin
        compute_golden;
        @(negedge clk); start_n = 1'b1; start_o = 1'b1;
        @(negedge clk); start_n = 1'b0; start_o = 1'b0;
        @(negedge clk);
        while (doneo !== 1'b1) @(negedge clk);
        note_cycles;
        // 1) 新 vs 黄金
        checks = checks + 1;
        if (qn !== gq || rn !== gr) begin
            bad = bad + 1;
            if (bad <= 5) $display("BAD new vs gold %0s x=%h f=%h got q=%h r=%h want q=%h r=%h",
                                   tag, x, freq, qn, rn, gq, gr);
        end
        // 2) 旧 vs 黄金
        checks = checks + 1;
        if (qo !== gq || ro !== gr) begin
            bad = bad + 1;
            if (bad <= 5) $display("BAD old vs gold %0s x=%h f=%h got q=%h r=%h want q=%h r=%h",
                                   tag, x, freq, qo, ro, gq, gr);
        end
        // 3) 新 vs 旧
        checks = checks + 1;
        if (qn !== qo || rn !== ro) begin
            bad = bad + 1;
            if (bad <= 5) $display("BAD new vs old %0s x=%h f=%h", tag, x, freq);
        end
        n_vec = n_vec + 1;
    end
    endtask

    //--- T2：只喂新模块，比黄金 ---
    task run_rcp;
    begin
        compute_golden;
        @(negedge clk); start_n = 1'b1;
        @(negedge clk); start_n = 1'b0;
        @(negedge clk);
        while (donen !== 1'b1) @(negedge clk);
        note_cycles;
        checks = checks + 1;
        if (qn !== gq || rn !== gr) begin
            bad = bad + 1;
            if (bad <= 5) $display("BAD rcp vs gold x=%h f=%h got q=%h r=%h want q=%h r=%h",
                                   x, freq, qn, rn, gq, gr);
        end
        n_sweep = n_sweep + 1;
    end
    endtask

    //--- T3：边界，喂新模块，比黄金 + 表内 q/r + cor ---
    task run_bnd;
        input [XW-1:0] xval;
        input [15:0]   fval;
        input [XW-1:0] qexp;
        input [15:0]   rexp;
        input integer  corexp;
    begin
        x = xval; freq = fval;
        compute_golden;
        @(negedge clk); start_n = 1'b1;
        @(negedge clk); start_n = 1'b0;
        @(negedge clk);
        while (donen !== 1'b1) @(negedge clk);
        note_cycles;
        checks = checks + 1;
        // 新模块 vs 表内期望 q/r
        if (qn !== qexp || rn !== rexp || gq !== qexp || gr !== rexp) begin
            bad = bad + 1;
            if (bad <= 5) $display("BAD bnd x=%h f=%h got q=%h r=%h exp q=%h r=%h",
                                   x, freq, qn, rn, qexp, rexp);
        end
        // 参考修正支路命中数 vs 表内 cor
        checks = checks + 1;
        if (cor_ref !== corexp) begin
            bad = bad + 1;
            if (bad <= 5) $display("BAD bnd-cor x=%h f=%h cor_ref=%0d exp=%0d",
                                   x, freq, cor_ref, corexp);
        end
        n_bnd = n_bnd + 1;
    end
    endtask

    //--- T2 全 f 扫描（循环生成，绝不从文件读）---
    integer f, k;
    reg [63:0]  sx;
    task sweep_tests;
    begin
        for (f = 1; f <= 65535; f = f + 1) begin
            for (k = 1; k <= 3; k = k + 1) begin
                sx = ({48'd0, f[15:0]} << 47) - k;   // x = 2^47 * f - k（最大合法被除数）
                x = sx;
                freq = f[15:0];
                run_rcp;
            end
        end
    end
    endtask

    //--- T3 边界 20 条（期望值照抄任务书 §6 表，Python 大整数独立算出）---
    task boundary_tests;
    begin
        //          x                    freq   q0/cor/q/r 已折进 q,r；cor=是否修正
        run_bnd(64'h0000000000000000, 16'd1,     64'h0000000000000000, 16'd0, 0);
        run_bnd(64'h0000000080000000, 16'd1,     64'h0000000080000000, 16'd0, 1);
        run_bnd(64'h7fffffffffffffff, 16'd1,     64'h7fffffffffffffff, 16'd0, 1);
        run_bnd(64'hffffffffffffffff, 16'd1,     64'hffffffffffffffff, 16'd0, 1);
        run_bnd(64'hffffffffffffffff, 16'd2,     64'h7fffffffffffffff, 16'd1, 1);
        run_bnd(64'h7fffffffffffffff, 16'd2,     64'h3fffffffffffffff, 16'd1, 0);
        run_bnd(64'h7fffffffffffffff, 16'd3,     64'h2aaaaaaaaaaaaaaa, 16'd1, 0);
        run_bnd(64'hffffffffffffffff, 16'd3,     64'h5555555555555555, 16'd0, 1);
        run_bnd(64'h0000000000000000, 16'd65533, 64'h0000000000000000, 16'd0, 0);
        run_bnd(64'h000000000000fffc, 16'd65533, 64'h0000000000000000, 16'd65532, 0);
        run_bnd(64'h7ffe7ffffffffffe, 16'd65533, 64'h00007fffffffffff, 16'd65531, 0);
        run_bnd(64'h7ffe7fffffffffff, 16'd65533, 64'h00007fffffffffff, 16'd65532, 0);
        run_bnd(64'h7fff7fffffffffff, 16'd65535, 64'h00007fffffffffff, 16'd65534, 0);
        run_bnd(64'h07ffffffffffffff, 16'd4096,  64'h00007fffffffffff, 16'd4095, 0);
        run_bnd(64'h0000ffffffffffff, 16'd2,     64'h00007fffffffffff, 16'd1, 0);
        run_bnd(64'h0001fffffffffffd, 16'd4,     64'h00007fffffffffff, 16'd1, 0);
        run_bnd(64'h000000000d6d7d24, 16'd1,     64'h000000000d6d7d24, 16'd0, 1);
        run_bnd(64'h000000000a2f48c8, 16'd1,     64'h000000000a2f48c8, 16'd0, 1);
        run_bnd(64'h1fc4ed356d2f7f95, 16'd24918, 64'h0000538e23854315, 16'd391, 1);
        run_bnd(64'h000000000000a480, 16'd1,     64'h000000000000a480, 16'd0, 1);
    end
    endtask

    //--- 主流程 ---
    real avg_cyc;
    initial begin
        checks = 0; bad = 0;
        n_vec = 0; n_sweep = 0; n_bnd = 0; n_cor1 = 0;
        cyc_sum = 0; n_cyc = 0; cyc_min = 999; cyc_max = 0;
        start_n = 1'b0; start_o = 1'b0;
        x = 64'd0; freq = 16'd1; rcp = 64'd0;

        if (!$value$plusargs("VEC=%s", vpath))
            vpath = "/mnt/e/fudanwei/_logs/rans/divvec_p1.txt";
        $display("VEC file = %0s", vpath);
        fd = $fopen(vpath, "r");
        if (fd == 0) begin
            $display("FAIL rans_div_rcp: cannot open VEC file");
            $finish;
        end

        rst_n = 1'b0;
        repeat (4) @(negedge clk);
        rst_n = 1'b1;
        repeat (2) @(negedge clk);

        // T3 边界（先做，20 条）
        boundary_tests;
        $display("BOUNDARY done: checks=%0d bad=%0d", checks, bad);

        // T2 全 f 扫描（196605 例）
        sweep_tests;
        $display("SWEEP done: checks=%0d bad=%0d n_sweep=%0d", checks, bad, n_sweep);

        // T1 真实向量 24492 条（三方对拍）
        line_no = 0;
        rc = $fscanf(fd, "%h %h %h %h", tx, tf, tq, tr);
        while (rc == 4) begin
            line_no = line_no + 1;
            x    = tx;
            freq = tf[15:0];
            run_both(line_no);
            rc = $fscanf(fd, "%h %h %h %h", tx, tf, tq, tr);
        end
        $fclose(fd);
        $display("FILE lines read = %0d", line_no);

        // 结果
        $display("TOTAL=%0d BAD=%0d cycles_min=%0d cycles_max=%0d",
                 checks, bad, cyc_min, cyc_max);
        $display("CHECKS=%0d n_vec=%0d n_sweep=%0d n_bnd=%0d n_cor1=%0d",
                 checks, n_vec, n_sweep, n_bnd, n_cor1);
        if (bad == 0 && checks >= 245000 && n_cor1 > 0) begin
            avg_cyc = $itor(cyc_sum) / $itor(n_cyc);
            $display("PASS rans_div_rcp: %0d/%0d vectors matched, avg cycles = %0.1f",
                     checks, checks, avg_cyc);
        end else begin
            $display("FAIL rans_div_rcp: %0d bad", bad);
        end
        $finish;
    end

    // 兜底看门狗：T1(旧66拍*24492)+T2(5拍*196605) 约 3~4M 拍 x10ns ~ 40ms，给 2s 足够
    initial begin
        #2_000_000_000;
        $display("FAIL rans_div_rcp: watchdog timeout checks=%0d bad=%0d", checks, bad);
        $finish;
    end

endmodule
