//======================================================================
// rans_div_tb.v  ——  rans_div 基线版对拍 tb
//----------------------------------------------------------------------
// 出处：任务书 C2a1 §2/§3/§4 + §5 两个坑
//
// 用法：vvp rans_div_tb.vvp +VEC=/mnt/e/fudanwei/_logs/rans/divvec_p1.txt
//      不给 +VEC 时默认走该绝对路径。
//
// 完成判据（严格照 §4-3 的格式，不用多行字符串拼接，避开 §5-2）：
//   PASS rans_div: N/N vectors matched, avg cycles = X.X
//   FAIL rans_div: K bad
//======================================================================
`timescale 1ns / 1ps

module rans_div_tb;

    localparam integer XW = 64;

    //--- DUT 端口：连到输出的必须都是 wire（§5 坑 1） ---
    reg           clk;
    reg           rst_n;
    reg           start;
    reg  [XW-1:0] x;
    reg  [15:0]   freq;
    wire [XW-1:0] q;
    wire [15:0]   r;
    wire          busy;
    wire          done;
    wire [7:0]    cycles;

    rans_div #(.XW(XW)) dut (
        .clk   (clk),
        .rst_n (rst_n),
        .start (start),
        .x     (x),
        .freq  (freq),
        .q     (q),
        .r     (r),
        .busy  (busy),
        .done  (done),
        .cycles(cycles)
    );

    // 100 MHz：周期 10 ns
    initial clk = 1'b0;
    always #5 clk = ~clk;

    //--- 对拍状态 ---
    integer fd;
    integer total;
    integer bad;
    integer cyc_sum;
    integer cyc_min;
    integer cyc_max;
    real    avg_cyc;

    // 期望
    reg [XW-1:0] gq;
    reg [15:0]   gr;
    // 从文件读到的（用 64 位宽临时，防 %h 目标位宽歧义）
    reg [63:0]   tx, tf, tq, tr;
    reg [XW-1:0] vx;
    reg [15:0]   vf;
    reg [XW-1:0] vq;
    reg [15:0]   vr;

    integer rc;
    integer line_no;
    integer i_loop;
    reg [1023:0] vpath;
    reg [255:0]  tok;

    //--- 一次除法：拉 start 一拍，等 done 一拍，比对 q/r ---
    //  调用前须已设好 x / freq / gq / gr
    task run_and_check(input [255:0] tag);
    begin
        @(negedge clk);
        start = 1'b1;
        @(negedge clk);
        start = 1'b0;
        @(negedge clk);
        while (done !== 1'b1) @(negedge clk);
        total   = total + 1;
        cyc_sum = cyc_sum + cycles;
        if (cycles < cyc_min) cyc_min = cycles;
        if (cycles > cyc_max) cyc_max = cycles;
        if (q !== gq || r !== gr) begin
            bad = bad + 1;
            if (bad <= 5) begin
                $display("BAD %0s x=%h f=%h  got q=%h r=%h  want q=%h r=%h",
                         tag, x, freq, q, r, gq, gr);
            end
        end
    end
    endtask

    //--- 边界用例（§4-2） ---
    task boundary_tests;
    begin
        x = 48'd0;                freq = 16'd1;     gq = 48'd0;                gr = 16'd0;
        run_and_check("bnd x=0 f=1");
        x = 48'd0;                freq = 16'd65535; gq = 48'd0;                gr = 16'd0;
        run_and_check("bnd x=0 f=65535");
        x = 48'hFFFFFFFFFFFF;     freq = 16'd1;     gq = 48'hFFFFFFFFFFFF;     gr = 16'd0;
        run_and_check("bnd x=FFFF_f  f=1");
        // (2^48-1) / 65535 = 2^32+2^16+1 = 0x000100010001, 余 0
        x = 48'hFFFFFFFFFFFF;     freq = 16'd65535; gq = 48'h000100010001;     gr = 16'd0;
        run_and_check("bnd x=FFFF_f  f=65535");
        x = 48'd1;                freq = 16'd65535; gq = 48'd0;                gr = 16'd1;
        run_and_check("bnd x=1 f=65535");
        x = 48'd65535;            freq = 16'd65535; gq = 48'd1;                gr = 16'd0;
        run_and_check("bnd x=f f=f");
        x = 48'd65536;            freq = 16'd65535; gq = 48'd1;                gr = 16'd1;
        run_and_check("bnd x=f+1 f=f");
    end
    endtask

    //--- 主流程 ---
    initial begin
        total   = 0;
        bad     = 0;
        cyc_sum = 0;
        cyc_min = 999;
        cyc_max = 0;
        start   = 1'b0;
        x       = 48'd0;
        freq    = 16'd1;
        gq      = 48'd0;
        gr      = 16'd0;

        if (!$value$plusargs("VEC=%s", vpath))
            vpath = "/mnt/e/fudanwei/_logs/rans/divvec_p1.txt";
        $display("VEC file = %0s", vpath);

        fd = $fopen(vpath, "r");
        if (fd == 0) begin
            $display("FAIL rans_div: cannot open VEC file");
            $finish;
        end

        // 复位
        rst_n = 1'b0;
        repeat (4) @(negedge clk);
        rst_n = 1'b1;
        repeat (2) @(negedge clk);

        // 1) 边界
        boundary_tests;
        $display("BOUNDARY done: total=%0d bad=%0d", total, bad);

        // 2) 文件里 24492 条：每行 "x freq q r"，全 16 进制
        line_no = 0;
        rc = $fscanf(fd, "%h %h %h %h", tx, tf, tq, tr);
        while (rc == 4) begin
            line_no = line_no + 1;
            vx = tx[XW-1:0];
            vf = tf[15:0];
            vq = tq[XW-1:0];
            vr = tr[15:0];
            x    = vx;
            freq = vf;
            gq   = vq;
            gr   = vr;
            run_and_check(line_no);
            rc = $fscanf(fd, "%h %h %h %h", tx, tf, tq, tr);
        end
        $display("FILE lines read = %0d", line_no);

        $fclose(fd);

        // 3) 结果
        $display("TOTAL=%0d BAD=%0d cycles_min=%0d cycles_max=%0d",
                 total, bad, cyc_min, cyc_max);
        if (bad == 0) begin
            avg_cyc = $itor(cyc_sum) / $itor(total);
            $display("PASS rans_div: %0d/%0d vectors matched, avg cycles = %0.1f",
                     total, total, avg_cyc);
        end else begin
            $display("FAIL rans_div: %0d bad", bad);
        end
        $finish;
    end

    // 兜底看门狗：24499 * 60 * 10ns ≈ 15 ms，给 200 ms 足够
    initial begin
        #200_000_000;
        $display("FAIL rans_div: watchdog timeout at total=%0d bad=%0d", total, bad);
        $finish;
    end

endmodule
