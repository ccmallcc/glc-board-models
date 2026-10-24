//======================================================================
// rans_enc_put_tb.v  ——  单符号状态更新+renorm 的**闭环**对拍
//----------------------------------------------------------------------
// 出处：任务书 C2b §8（T0 黄金自洽 / T1 闭环对拍 / T2 边界与计数）。
//
// 黄金值**只来自** oracle 导出的逐符号文件（不重实现算法当参考）：
//   /mnt/e/fudanwei/_logs/rans/symtrace_p1.txt  (4242 行)
//   /mnt/e/fudanwei/_logs/rans/symtrace_p2.txt  (67844 行)
// 每行: x_in freq start x_out emit emit_word bypass   (%016llx %04x %04x %016llx %d %08x %d)
//
// T1 **闭环**：x 从 64'h80000000 起，逐行喂 x_in = 上一拍的 x_out(DUT 自己的)，
//   等 done，比对 x_out / emit / emit_word；文件里的 x_in 只用来核对分歧行号。
//
// rcp 用语言级除法自算：64'hFFFF_FFFF_FFFF_FFFF / {48'd0,freq}（与 RTL 无关）。
//   bypass 行 freq 按文件原样喂（不替换 4096）——若 RTL 错用 freq 会被抓到。
//
// 正常路径绝不打印 FAIL/ERROR/Fatal 子串（run_sim.sh 靠关键字判定）。
//======================================================================
`timescale 1ns / 1ps

module rans_enc_put_tb;

    localparam integer MAXL = 70000;

    // DUT
    reg            clk, rst_n, go;
    reg  [63:0]    din_x;
    reg  [15:0]    din_freq, din_start;
    reg  [63:0]    din_rcp;
    reg            din_byp;
    wire [63:0]    q_out;
    wire           q_emit;
    wire [31:0]    q_ew;
    wire           q_busy, q_done;
    wire [7:0]     q_cycles;

    rans_enc_put #(.XW(64), .BYPASS_BITS(4)) dut (
        .clk(clk), .rst_n(rst_n), .start(go),
        .x_in(din_x), .freq(din_freq), .sym_start(din_start),
        .rcp(din_rcp), .bypass(din_byp),
        .x_out(q_out), .emit(q_emit), .emit_word(q_ew),
        .busy(q_busy), .done(q_done), .cycles(q_cycles)
    );

    initial clk = 1'b0;
    always #5 clk = ~clk;   // 100 MHz

    // 每文件数组
    reg [63:0] fxin  [0:MAXL];
    reg [15:0] ffreq [0:MAXL];
    reg [15:0] fstrt [0:MAXL];
    reg [63:0] fxout [0:MAXL];
    reg        femit [0:MAXL];
    reg [31:0] fewrd [0:MAXL];
    reg        fbyp  [0:MAXL];

    // 读入标量
    reg [63:0] rr_xin, rr_xout;
    reg [15:0] rr_freq, rr_start;
    reg [31:0] rr_ew;
    integer    rr_emit, rr_byp;

    // 全局计数
    integer checks, bad;
    integer g_emit, g_byp, g_eb;                 // 全局 emit/bypass/emit&bypass
    integer cyc_sum, n_cyc, cyc_min, cyc_max;
    integer nrows_p1, nrows_p2;

    reg [63:0] x;                                // 闭环 state
    integer i, fbad;

    task note_cyc;
    begin
        cyc_sum = cyc_sum + q_cycles;
        n_cyc   = n_cyc + 1;
        if (q_cycles < cyc_min) cyc_min = q_cycles;
        if (q_cycles > cyc_max) cyc_max = q_cycles;
    end
    endtask

    // 跑一个符号：闭环喂 x，比三个输出 + 交叉核对 x_in
    task step;
        input integer idx;
    begin
        if (ffreq[idx] != 16'd0)
            din_rcp = 64'hFFFF_FFFF_FFFF_FFFF / {48'd0, ffreq[idx]};
        else
            din_rcp = 64'd0;                      // bypass 行可能 freq=0；RTL 会忽略 rcp

        @(negedge clk);
        din_x = x; din_freq = ffreq[idx]; din_start = fstrt[idx];
        din_byp = fbyp[idx]; go = 1'b1;
        @(negedge clk); go = 1'b0;
        @(negedge clk);
        while (q_done !== 1'b1) @(negedge clk);
        note_cyc;

        // 交叉核对：DUT 闭环喂进去的 x 应等于文件 x_in（分歧说明前面就错）
        checks = checks + 1;
        if (x !== fxin[idx]) begin
            fbad = fbad + 1;
            if (fbad <= 3) $display("  state-diverge file-line %0d got_xin=%h file_xin=%h",
                                    idx+1, x, fxin[idx]);
        end
        // 三个输出
        checks = checks + 1;
        if (q_out !== fxout[idx]) begin
            fbad = fbad + 1;
            if (fbad <= 3) $display("  xout-mismatch line %0d got=%h want=%h f=%h byp=%0d",
                                    idx+1, q_out, fxout[idx], ffreq[idx], fbyp[idx]);
        end
        checks = checks + 1;
        if (q_emit !== femit[idx]) begin
            fbad = fbad + 1;
            if (fbad <= 3) $display("  emit-mismatch line %0d got=%0b want=%0b",
                                    idx+1, q_emit, femit[idx]);
        end
        checks = checks + 1;
        if (q_ew !== fewrd[idx]) begin
            fbad = fbad + 1;
            if (fbad <= 3) $display("  emit_word-mismatch line %0d got=%h want=%h",
                                    idx+1, q_ew, fewrd[idx]);
        end
        // T2 断言：emit=0 时 emit_word 必须为 0
        checks = checks + 1;
        if (q_emit === 1'b0 && q_ew !== 32'd0) begin
            fbad = fbad + 1;
            if (fbad <= 3) $display("  emit0-with-word line %0d ew=%h", idx+1, q_ew);
        end

        x = q_out;                                // 闭环
    end
    endtask

    // 处理一个文件：读入 -> T0 自洽 -> T1 闭环
    task run_file;
        input [255:0] tag;
        input [1023:0] path;
        input integer exp_lines, exp_emit, exp_byp;
        integer fd, n, ne, nb, keb, k;
    begin
        fd = $fopen(path, "r");
        if (fd == 0) begin
            $display("FILE %0s: open-missing", tag);
            bad = bad + 1;
        end else begin
        n = 0; ne = 0; nb = 0; keb = 0;
        while ($fscanf(fd, "%h %h %h %h %d %h %d",
                       rr_xin, rr_freq, rr_start, rr_xout, rr_emit, rr_ew, rr_byp) == 7
               && n <= MAXL) begin
            fxin[n]=rr_xin; ffreq[n]=rr_freq; fstrt[n]=rr_start; fxout[n]=rr_xout;
            femit[n]=rr_emit[0]; fewrd[n]=rr_ew; fbyp[n]=rr_byp[0];
            if (rr_emit[0]==1'b1) ne = ne + 1;
            if (rr_byp[0]==1'b1)  nb = nb + 1;
            if (rr_emit[0]==1'b1 && rr_byp[0]==1'b1) keb = keb + 1;
            n = n + 1;
        end
        $fclose(fd);

        // T0：初值
        checks = checks + 1;
        if (fxin[0] !== 64'h0000000080000000) begin
            bad = bad + 1;
            $display("FILE %0s: T0 first-xin wrong (%h)", tag, fxin[0]);
        end
        // T0：链自洽  xout[k]==xin[k+1]
        for (k = 0; k < n-1; k = k + 1) begin
            checks = checks + 1;
            if (fxout[k] !== fxin[k+1]) begin
                bad = bad + 1;
                if (bad <= 5) $display("FILE %0s: T0 chain-break at line %0d", tag, k+1);
            end
        end
        // T0：行数/计数须与预期一致（不一致=解析出错，如实报）
        checks = checks + 1;
        if (n !== exp_lines) begin
            bad = bad + 1;
            $display("FILE %0s: T0 lines mismatch got=%0d exp=%0d", tag, n, exp_lines);
        end
        checks = checks + 1;
        if (ne !== exp_emit) begin
            bad = bad + 1;
            $display("FILE %0s: T0 emit mismatch got=%0d exp=%0d", tag, ne, exp_emit);
        end
        checks = checks + 1;
        if (nb !== exp_byp) begin
            bad = bad + 1;
            $display("FILE %0s: T0 bypass mismatch got=%0d exp=%0d", tag, nb, exp_byp);
        end

        // T1：闭环对拍
        x = 64'h0000000080000000;
        fbad = 0;
        for (i = 0; i < n; i = i + 1) step(i);
        bad = bad + fbad;

        if (tag === "p1") nrows_p1 = n; else nrows_p2 = n;
        g_emit = g_emit + ne; g_byp = g_byp + nb; g_eb = g_eb + keb;
        $display("FILE %0s: lines=%0d emit=%0d bypass=%0d bad=%0d", tag, n, ne, nb, fbad);
        end
    end
    endtask

    real avg_cyc;
    integer total_rows;
    initial begin
        checks=0; bad=0; g_emit=0; g_byp=0; g_eb=0;
        cyc_sum=0; n_cyc=0; cyc_min=999; cyc_max=0;
        total_rows=0; nrows_p1=0; nrows_p2=0;
        go=1'b0; din_x=64'd0; din_freq=16'd1; din_start=16'd0; din_rcp=64'd0; din_byp=1'b0;

        rst_n = 1'b0; repeat (4) @(negedge clk); rst_n = 1'b1; repeat (2) @(negedge clk);

        run_file("p1", "/mnt/e/fudanwei/_logs/rans/symtrace_p1.txt", 4242, 633, 146);
        run_file("p2", "/mnt/e/fudanwei/_logs/rans/symtrace_p2.txt", 67844, 10065, 2308);

        total_rows = nrows_p1 + nrows_p2;
        $display("TOTAL=%0d BAD=%0d cycles_min=%0d cycles_max=%0d",
                 checks, bad, cyc_min, cyc_max);
        $display("CHECKS=%0d n_emit=%0d n_bypass=%0d n_emit_bypass=%0d",
                 checks, g_emit, g_byp, g_eb);
        if (bad == 0 && total_rows == 72086 && g_emit == 10698 && g_byp == 2454
            && checks >= 280000) begin
            avg_cyc = $itor(cyc_sum) / $itor(n_cyc);
            $display("PASS rans_enc_put: %0d/%0d symbols matched, avg cycles = %0.1f",
                     total_rows, total_rows, avg_cyc);
        end else begin
            $display("FAIL rans_enc_put: %0d bad", bad);
        end
        $finish;
    end

    // 兜底看门狗
    initial begin
        #2_000_000_000;
        $display("rans_enc_put: watchdog timeout checks=%0d bad=%0d", checks, bad);
        $finish;
    end

endmodule
