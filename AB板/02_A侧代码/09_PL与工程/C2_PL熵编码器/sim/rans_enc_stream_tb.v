//======================================================================
// rans_enc_stream_tb.v  ——  符号流 + 逆序缓冲 + flush 的对拍
//----------------------------------------------------------------------
// 出处：任务书 C2c1 §5（T1 逐字一致 / T2 计数自洽 / T3 吞吐）。
//
// 黄金值**只来自**两个外部文件，tb 内不重实现算法：
//   逐符号   /mnt/e/fudanwei/_logs/rans/symtrace_p{1,2}.txt
//            每行 x_in freq start x_out emit emit_word bypass (%016llx %04x %04x %016llx %d %08x %d)
//   黄金 payload /mnt/e/fudanwei/_logs/rans/payload_p{1,2}_words.hex
//            一字一行 %08x，用 $readmemh 读（**不做任何十六进制字符解析** —— 上一批超时根因）
//
// 为什么比字就够（任务书 §1）：工具/verify_payload.py 已独立证明「黄金字节流 == 字序列小端展开」，
//   故逐字相符 <=> 逐字节相符；字节层在 Python 侧验过，tb 不比字节。
//
// 喂符号：按 symtrace **行序**（已是编码顺序），最后一行 s_last=1，**尊重 s_ready**；
//   rcp 用语言级除法自算 64'hFFFF_FFFF_FFFF_FFFF / {48'd0,freq}（照 rans_enc_put_tb，与 RTL 无关）。
//
// 正常路径绝不打印 FAIL/ERROR/Fatal 子串（run_sim.sh 靠关键字判定）。
//======================================================================
`timescale 1ns / 1ps

module rans_enc_stream_tb;

    localparam integer MAXL  = 70000;   // 最大符号数（p2=67844）
    localparam integer MAXW  = 16384;   // 最大字数（=DEPTH；黄金 <=10067）
    localparam integer DEPTH = 16384;
    localparam integer AW    = 14;

    // DUT
    reg             clk, rst_n, go_frame;
    reg             s_valid, s_last, s_bypass;
    reg  [15:0]     s_start, s_freq;
    reg  [63:0]     s_rcp;
    reg  [AW-1:0]   rd_addr;
    wire            s_ready;
    wire            busy, done;
    wire [31:0]     cyc_total, rd_data;
    wire [7:0]      cyc_put;
    wire [AW-1:0]   pl_base, pl_words;

    rans_enc_stream #(.XW(64), .DEPTH(DEPTH), .AW(AW)) dut (
        .clk(clk), .rst_n(rst_n), .start(go_frame),
        .s_valid(s_valid), .s_ready(s_ready), .s_last(s_last),
        .s_start(s_start), .s_freq(s_freq), .s_rcp(s_rcp), .s_bypass(s_bypass),
        .busy(busy), .done(done), .cyc_total(cyc_total), .cyc_put(cyc_put),
        .pl_base(pl_base), .pl_words(pl_words), .rd_addr(rd_addr), .rd_data(rd_data)
    );

    initial clk = 1'b0;
    always #5 clk = ~clk;   // 100 MHz

    // 每符号数组（只需 start/freq/bypass；emit 单独计数存 ne）
    reg [15:0] fs   [0:MAXL];
    reg [15:0] ff   [0:MAXL];
    reg        fb   [0:MAXL];
    reg [31:0] gold [0:MAXW];

    // $fscanf 读入标量（symtrace 7 列）
    reg [63:0] rr_xin, rr_xout;
    reg [15:0] rr_freq, rr_start;
    reg [31:0] rr_ew;
    integer    rr_emit, rr_byp;

    // 全局
    integer checks, bad;
    integer total_good, total_words;
    integer cyc_p1, cyc_p2;
    reg     [63:0] rcp_tmp;
    integer i, n, a, ne;
    integer pw_i, pb_i;               // pl_words / pl_base 取整型
    integer bad_words, first_bad, first_got, first_want;
    integer fd;
    real    cps;

    // 喂一个符号：驱动 -> 等 s_ready 高的负边 -> 跨过被接收那一拍 -> 撤 valid
    task feed_sym;
        input integer idx;
        input         last;
    begin
        if (ff[idx] != 16'd0) rcp_tmp = 64'hFFFF_FFFF_FFFF_FFFF / {48'd0, ff[idx]};
        else                  rcp_tmp = 64'd0;      // bypass 行 freq 可能 0；put 忽略 rcp

        @(negedge clk);
        s_start  = fs[idx];
        s_freq   = ff[idx];
        s_rcp    = rcp_tmp;
        s_bypass = fb[idx];
        s_last   = last;
        s_valid  = 1'b1;
        while (s_ready !== 1'b1) @(negedge clk);      // 等一个 ready 高的负边
        @(negedge clk);                               // 跨过接收正边（该边 valid&ready 成立）
        s_valid = 1'b0;
        s_last  = 1'b0;
        checks  = checks + 1;                          // 该符号确被 s_ready 放行（未丢符号）
    end
    endtask

    // 跑一整个文件
    task run_file;
        input [255:0]  tag;
        input [1023:0] sym_path;
        input [1023:0] gold_path;
        input integer  exp_lines, exp_words;
    begin
        // 读 symtrace
        n = 0; ne = 0;
        fd = $fopen(sym_path, "r");
        if (fd == 0) begin
            $display("FILE %0s: symtrace-open-missing", tag);
            bad = bad + 1;
        end else begin
            while ($fscanf(fd, "%h %h %h %h %d %h %d",
                           rr_xin, rr_freq, rr_start, rr_xout, rr_emit, rr_ew, rr_byp) == 7
                   && n <= MAXL) begin
                fs[n] = rr_start;  ff[n] = rr_freq;  fb[n] = rr_byp[0];
                if (rr_emit[0] == 1'b1) ne = ne + 1;
                n = n + 1;
            end
            $fclose(fd);
        end
        // T2：行数须与预期一致（不一致=解析出错，如实报）
        checks = checks + 1;
        if (n !== exp_lines) begin
            bad = bad + 1;
            $display("FILE %0s: lines got=%0d exp=%0d", tag, n, exp_lines);
        end

        // 读黄金 payload（$readmemh，一字一行）
        // ⚠️ 先填哨兵值：数组比文件长很多（16385 vs 635/10067），$readmemh 会报
        //    "Not enough words" 并把**未覆盖项保留原值**。填哨兵后，
        //    「比对区间是否被文件完整覆盖」从**隐式**变成**显式** —— 没覆盖到就一定比不中。
        for (a = 0; a <= MAXW; a = a + 1) gold[a] = 32'hDEAD_BEEF;
        $readmemh(gold_path, gold);

        // 起一帧
        @(negedge clk);
        s_valid = 1'b0;  s_last = 1'b0;
        go_frame = 1'b1;
        @(negedge clk);
        go_frame = 1'b0;

        // 逐符号喂（最后一行 s_last=1）
        for (i = 0; i < n; i = i + 1)
            feed_sym(i, (i == n-1));

        // 等 flush + done：busy 在 S_DONE 正边清零，同拍 pl_base/pl_words 有效
        @(negedge clk);
        while (busy !== 1'b0) @(negedge clk);
        pw_i = pl_words;
        pb_i = pl_base;
        if (tag === "p1") cyc_p1 = cyc_total; else cyc_p2 = cyc_total;

        // T2 计数断言
        checks = checks + 1;
        if (pw_i !== exp_words) begin
            bad = bad + 1;
            $display("FILE %0s: pl_words got=%0d exp=%0d", tag, pw_i, exp_words);
        end
        checks = checks + 1;
        if ((pb_i + pw_i) !== DEPTH) begin
            bad = bad + 1;
            $display("FILE %0s: base+words got=%0d exp=%0d", tag, (pb_i + pw_i), DEPTH);
        end
        checks = checks + 1;
        if (ne !== (pw_i - 2)) begin                    // emit 数 == payload 字数 - 2(flush)
            bad = bad + 1;
            $display("FILE %0s: emit(words-2) got=%0d want=%0d", tag, ne, (pw_i - 2));
        end

        // T1 逐字比对
        bad_words = 0; first_bad = -1; first_got = 0; first_want = 0;
        for (a = 0; a < pw_i; a = a + 1) begin
            rd_addr = pb_i + a;                          // <= DEPTH-1，截到 AW 位安全
            #1;                                          // 让组合读稳定（mem 在 done 后恒定）
            checks = checks + 1;
            if (rd_data !== gold[a]) begin
                bad_words = bad_words + 1;
                if (first_bad < 0) begin
                    first_bad  = a;
                    first_got  = rd_data;
                    first_want = gold[a];
                end
            end
        end
        total_good  = total_good + (pw_i - bad_words);
        total_words = total_words + pw_i;
        bad = bad + bad_words;

        $display("FILE %0s: symbols=%0d words=%0d bad_words=%0d cyc_total=%0d first_bad=%0d got=%h want=%h",
                 tag, n, pw_i, bad_words, cyc_total,
                 first_bad, first_got, first_want);
    end
    endtask

    initial begin
        checks=0; bad=0; total_good=0; total_words=0; cyc_p1=0; cyc_p2=0;
        go_frame=1'b0; s_valid=1'b0; s_last=1'b0;
        s_start=16'd0; s_freq=16'd1; s_rcp=64'd0; s_bypass=1'b0; rd_addr={AW{1'b0}};

        rst_n = 1'b0; repeat (4) @(negedge clk); rst_n = 1'b1; repeat (2) @(negedge clk);

        // p1: 4242 符号, 635 字(=633 emit + 2 flush); p2: 67844 符号, 10067 字(=10065 emit + 2 flush)
        run_file("p1",
                 "/mnt/e/fudanwei/_logs/rans/symtrace_p1.txt",
                 "/mnt/e/fudanwei/_logs/rans/payload_p1_words.hex",
                 4242, 635);
        run_file("p2",
                 "/mnt/e/fudanwei/_logs/rans/symtrace_p2.txt",
                 "/mnt/e/fudanwei/_logs/rans/payload_p2_words.hex",
                 67844, 10067);

        cps = $itor(cyc_p1 + cyc_p2) / $itor(4242 + 67844);
        $display("TOTAL=%0d BAD=%0d CHECKS=%0d cycles_per_symbol=%0.2f",
                 total_words, bad, checks, cps);

        if (bad == 0 && total_words == 10702 && total_good == 10702 && checks >= 11000)
            $display("PASS rans_enc_stream: %0d/%0d words matched", total_good, total_words);
        else
            $display("FAIL rans_enc_stream: %0d bad", bad);
        $finish;
    end

    // 兜底看门狗（p2 有 6.8 万符号，给足时间）
    initial begin
        #5_000_000_000;
        $display("rans_enc_stream: watchdog checks=%0d bad=%0d", checks, bad);
        $finish;
    end

endmodule
