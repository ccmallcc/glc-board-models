//======================================================================
// rans_top_tb.v -- C2e end-to-end testbench
//
// Verifies the WHOLE custom-op path (not internal signals):
//   1. TB writes logical symbols into a simulated PL DDR in NATURAL order
//   2. TB configures rbase/rsize/wbase/nsym via the register interface, then START
//   3. PL reads DDR (512b/beat, REVERSE_IN consumes backwards), encodes,
//      writes the payload back into DDR
//   4. TB polls DONE (0x20), reads payload words from DDR, compares with
//      `_payload_words.txt` word by word
//
// NOTE on comments: this file is deliberately ASCII-only.  A previous
// version was corrupted by a PowerShell Get-Content/-replace/Set-Content
// round trip that mangled UTF-8 (line breaks and Chinese both destroyed).
//
// Run (from C2_PL<...> dir):
//   vvp <sim> +VEC=sim/vec/real
//======================================================================
`timescale 1ns / 1ps

module rans_top_tb;

    localparam MAXN   = 70000;
    localparam DBEATS = 4096;          // simulated PL DDR: 4096 beats x 64B = 256 KB

    // register word addresses (ra_awaddr[17:2])
    localparam R_START = 16'h00;
    localparam R_W0    = 16'h03;   // rbase[31:0] byte address
    localparam R_W1    = 16'h04;   // rsize (beats)
    localparam R_W2    = 16'h05;   // wbase[31:0] byte address
    localparam R_NSYM  = 16'h08;   // nsym (symbol count) -- RFU_W5 !!
    // NOTE: 0x06/0x07 (RFU_W3/W4) are 1-BIT registers in the official
    // reg_ctrl.v (ra_awdata[0] only).  Writing nsym there gives
    // nsym = bit0(nsym) -- which made stress report nsym=1 (705=0x2C1) and
    // real report nsym=0 (16384=0x4000).  Proof: sim/reg_ctrl_quirk_tb.v
    localparam R_DONE  = 16'h20;
    localparam R_R0    = 16'h21;

    reg clk = 0, ra_clk = 0, rst_n = 0, ra_rst_n = 0;
    always #5    clk    = ~clk;        // 200 MHz data domain
    always #12.5 ra_clk = ~ra_clk;     // 40 MHz  register domain (async)

    //--------------- DUT ----------------
    reg  [31:0] ra_awaddr; reg [31:0] ra_awdata; reg ra_awvalid; wire ra_awready;
    reg  [31:0] ra_araddr; reg ra_arvalid;        wire ra_arready;
    wire [31:0] ra_rdata;  wire ra_rvalid;        reg  ra_rready;
    wire [31:0]  awaddr;  wire [511:0] awdata;  wire awvalid; reg  awready;
    wire [31:0]  araddr;  wire araddr_v;        reg  arready;
    reg  [511:0] rdata;   reg  rvalid;          wire rready;
    wire reset_reg;

    rans_top #(.MEM_ROOT("mem")) dut (
        .itf_ra_awaddr(ra_awaddr), .itf_ra_awdata(ra_awdata),
        .itf_ra_awvalid(ra_awvalid), .itf_ra_awready(ra_awready),
        .itf_ra_araddr(ra_araddr), .itf_ra_arvalid(ra_arvalid),
        .itf_ra_arready(ra_arready), .itf_ra_rdata(ra_rdata),
        .itf_ra_rvalid(ra_rvalid), .itf_ra_rready(ra_rready),
        .itf_awaddr(awaddr), .itf_awdata(awdata),
        .itf_awvalid(awvalid), .itf_awready(awready),
        .itf_araddr(araddr), .itf_arvalid(araddr_v), .itf_arready(arready),
        .itf_rdata(rdata), .itf_rvalid(rvalid), .itf_rready(rready),
        .reset_reg(reset_reg),
        .clk(clk), .ra_clk(ra_clk), .rst_n(rst_n), .ra_rst_n(ra_rst_n)
    );

    //--------------- simulated PL DDR (512-bit beats) ---------------
    reg [511:0] ddr [0:DBEATS-1];
    integer k;
    initial for (k = 0; k < DBEATS; k = k + 1) ddr[k] = 512'd0;

    // read: 1 cycle latency
    reg [511:0] rdq; reg rdv;
    always @(posedge clk) begin
        if (!rst_n) begin rdv <= 1'b0; rdq <= 512'd0; end
        else begin
            if (araddr_v && arready) begin rdq <= ddr[araddr[31:6]]; rdv <= 1'b1; end
            else if (rdv && rready) rdv <= 1'b0;
        end
    end
    assign rdata   = rdq;
    assign rvalid  = rdv;
    assign arready = 1'b1;

    // write: same cycle
    always @(posedge clk) if (awvalid && awready) ddr[awaddr[31:6]] <= awdata;

    //--------------- register access tasks ---------------
    task ra_write(input [15:0] wa, input [31:0] wd);
        begin
            @(negedge ra_clk);
            ra_awaddr  <= {14'd0, wa} << 2;
            ra_awdata  <= wd;
            ra_awvalid <= 1'b1;
            @(negedge ra_clk);
            ra_awvalid <= 1'b0;
        end
    endtask

    task ra_read(input [15:0] wa, output [31:0] d);
        begin
            @(negedge ra_clk);
            ra_araddr  <= {14'd0, wa} << 2;
            ra_arvalid <= 1'b1;
            ra_rready  <= 1'b1;
            @(negedge ra_clk);
            ra_arvalid <= 1'b0;
            @(negedge ra_clk);
            d = ra_rdata;
            ra_rready <= 1'b0;
            @(negedge ra_clk);
        end
    endtask

    //--------------- vectors ---------------
    integer lg_k[0:MAXN-1], lg_v[0:MAXN-1], lg_last[0:MAXN-1];
    reg [31:0] ex_w[0:MAXN-1];
    integer n_lg = 0, n_ex = 0, errs = 0, i, r, fd, c, bi, wi;
    integer nbeat, plw, wb;
    reg [8*512-1:0] vecp, path;
    reg [31:0] rdv32, got;
    reg        done_seen;

    initial begin
        ra_awaddr=0; ra_awdata=0; ra_awvalid=0; ra_araddr=0; ra_arvalid=0;
        ra_rready=0; awready=1;
        if (!$value$plusargs("VEC=%s", vecp)) begin $display("need +VEC="); $finish; end

        $sformat(path, "%0s_logical.txt", vecp);
        fd = $fopen(path, "r");
        if (fd==0) begin $display("FAIL cannot open %0s", path); $finish; end
        while (!$feof(fd)) begin
            r = $fscanf(fd, "%d %d %d\n", lg_k[n_lg], lg_v[n_lg], lg_last[n_lg]);
            if (r==3) n_lg = n_lg + 1;
        end
        $fclose(fd);

        $sformat(path, "%0s_payload_words.txt", vecp);
        fd = $fopen(path, "r");
        if (fd==0) begin $display("FAIL cannot open %0s", path); $finish; end
        while (!$feof(fd)) begin
            r = $fscanf(fd, "%h\n", ex_w[n_ex]);
            if (r==1) n_ex = n_ex + 1;
        end
        $fclose(fd);
        $display("vector %0s : %0d logical symbols, expect %0d payload words",
                 vecp, n_lg, n_ex);

        repeat (8) @(negedge clk);
        rst_n = 1; ra_rst_n = 1;
        repeat (8) @(negedge clk);

        //---- (1) write symbols into DDR in NATURAL order ----
        // `_logical.txt` is in CONSUME order (i=n-1..0).  The PL with
        // REVERSE_IN=1 reads beats backwards and words backwards, so we place
        // consume-index c at beat (nbeat-1-c/16), word (15-c%16).
        nbeat = (n_lg + 15) / 16;
        for (c = 0; c < n_lg; c = c + 1) begin
            bi = nbeat - 1 - (c / 16);
            wi = 15 - (c % 16);
            ddr[bi][wi*32 +: 32] = {lg_v[c][15:0], 10'd0, lg_k[c][5:0]};
        end
        $display("  DDR loaded: %0d beats (%0d symbols), payload area starts at beat %0d",
                 nbeat, n_lg, nbeat);

        //---- (2) configure registers and start ----
        ra_write(R_W0, 32'd0);                  // rbase = 0 (byte address)
        ra_write(R_W1, nbeat[31:0]);            // rsize = beats
        ra_write(R_W2, nbeat[31:0] * 32'd64);   // wbase = right after symbols
        ra_write(R_NSYM, n_lg[31:0]);           // nsym  = TRUE symbol count (RFU_W5)
        ra_write(R_START, 32'd1);

        //---- (3) poll DONE ----
        i = 0; rdv32 = 0; done_seen = 1'b0;
        while ((rdv32[0] !== 1'b1) && (i < 40000)) begin
            ra_read(R_DONE, rdv32);
            i = i + 1;
        end
        done_seen = rdv32[0];      // capture BEFORE the debug reads clobber rdv32
        $display("  DONE after %0d polls = %0d", i, done_seen);
        // debug readback (RFU_R6=0x27 .. RFU_R9=0x2a)
        ra_read(R_R0+6, rdv32); $display("  DBG RFU_R6 max_raw        = %0d", rdv32);
        ra_read(R_R0+7, rdv32); $display("  DBG RFU_R7 max_n_bypass   = %0d", rdv32[4:0]);
        ra_read(R_R0+8, rdv32); $display("  DBG RFU_R8 nsym           = %0d", rdv32[15:0]);
        ra_read(R_R0+9, rdv32); $display("  DBG RFU_R9 {tstate,fed}   = %05x", rdv32[19:0]);
        if (done_seen !== 1'b1) begin
            $display("FAIL timeout waiting DONE");
            $finish;
        end

        ra_read(R_R0,   rdv32); $display("  RFU_R0 (version)       = %08x", rdv32);
        ra_read(R_R0+1, rdv32); $display("  RFU_R1 (status)        = %08x", rdv32);
        ra_read(R_R0+2, rdv32); plw = rdv32[15:0];
                                $display("  RFU_R2 (payload words) = %0d, expect %0d", plw, n_ex);
        ra_read(R_R0+3, rdv32); $display("  RFU_R3 (n_escape)      = %0d", rdv32);
        ra_read(R_R0+4, rdv32); $display("  RFU_R4 (n_bypass_syms) = %0d", rdv32);

        //---- (4) read payload back and compare ----
        wb = nbeat;
        if (plw !== n_ex) begin
            $display("FAIL payload word count: got %0d expect %0d", plw, n_ex);
            errs = errs + 1;
        end
        for (i = 0; i < n_ex; i = i + 1) begin
            got = ddr[wb + (i/16)][(i%16)*32 +: 32];
            if (got !== ex_w[i]) begin
                if (errs < 10)
                    $display("FAIL word[%0d] got %08x expect %08x", i, got, ex_w[i]);
                errs = errs + 1;
            end
        end

        $display("---------------------------------------------");
        if (errs == 0)
            $display("==== PASS: custom-op full path payload == official encode() word-for-word ====");
        else
            $display("==== FAIL: %0d mismatches ====", errs);
        $finish;
    end

    initial begin
        #20000000;
        $display("FAIL global timeout");
        $finish;
    end

endmodule
