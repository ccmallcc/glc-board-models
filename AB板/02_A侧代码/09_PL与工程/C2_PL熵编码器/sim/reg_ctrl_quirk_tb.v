//======================================================================
// reg_ctrl_quirk_tb.v -- DIRECT PROOF of an official-file quirk
//
// Claim under test: in the UNMODIFIED official rtl/official/reg_ctrl.v,
//   * RFU_W3 (0x06) and RFU_W4 (0x07) are ONE-BIT registers:
//         rfu_wreg3 <= ra_awdata[0];
//         rfu_wreg4 <= ra_awdata[0];
//   * every other RFU write register (0x03,0x04,0x05,0x08..0x0c) stores
//     the full 32-bit ra_awdata.
//
// Method: instantiate reg_ctrl verbatim, write the SAME value to every RFU
// write register in turn, and print the resulting register contents.  No
// inference from reading source: the numbers printed below are the register
// values as simulated.
//
// Why it matters: C2e used to put `nsym` in RFU_W3.  With nsym=705 (0x2C1)
// that register read back 1; with nsym=16384 (0x4000) it read back 0 --
// exactly the two symptoms seen on the first C2e run.
//
// This file is deliberately ASCII-only (see rans_top_tb.v header note).
//======================================================================
`timescale 1ns / 1ps

module reg_ctrl_quirk_tb;

    reg clk = 0, rst_n = 0;
    always #5 clk = ~clk;               // 100 MHz

    reg  [15:0] awaddr;  reg [31:0] awdata;  reg awvalid;
    wire        awready;
    reg  [15:0] araddr = 0;  reg arvalid = 0;  wire arready;
    wire [31:0] rdata;   wire rvalid;   reg  rready = 1;

    wire        comp_start;
    reg         comp_done = 0;
    wire [15:0] rbase, rsize, wbase, wsize;
    wire [31:0] rfu_wreg0, rfu_wreg1, rfu_wreg2, rfu_wreg3, rfu_wreg4,
                rfu_wreg5, rfu_wreg6, rfu_wreg7, rfu_wreg8, rfu_wreg9;

    // official file, verbatim
    reg_ctrl dut (
        .ra_awaddr(awaddr), .ra_awdata(awdata), .ra_awvalid(awvalid),
        .ra_awready(awready),
        .ra_araddr(araddr), .ra_arvalid(arvalid), .ra_arready(arready),
        .ra_rdata(rdata),   .ra_rvalid(rvalid),   .ra_rready(rready),
        .comp_start(comp_start), .comp_done(comp_done),
        .rbase(rbase), .rsize(rsize), .wbase(wbase), .wsize(wsize),
        .rfu_rreg0(32'd0), .rfu_rreg1(32'd0), .rfu_rreg2(32'd0),
        .rfu_rreg3(32'd0), .rfu_rreg4(32'd0), .rfu_rreg5(32'd0),
        .rfu_rreg6(32'd0), .rfu_rreg7(32'd0), .rfu_rreg8(32'd0),
        .rfu_rreg9(32'd0),
        .rfu_wreg0(rfu_wreg0), .rfu_wreg1(rfu_wreg1), .rfu_wreg2(rfu_wreg2),
        .rfu_wreg3(rfu_wreg3), .rfu_wreg4(rfu_wreg4), .rfu_wreg5(rfu_wreg5),
        .rfu_wreg6(rfu_wreg6), .rfu_wreg7(rfu_wreg7), .rfu_wreg8(rfu_wreg8),
        .rfu_wreg9(rfu_wreg9),
        .clk(clk), .rst_n(rst_n)
    );

    task wr(input [15:0] a, input [31:0] d);
        begin
            @(negedge clk);
            awaddr <= a; awdata <= d; awvalid <= 1'b1;
            @(negedge clk);
            awvalid <= 1'b0;
            @(negedge clk);
        end
    endtask

    integer fails = 0;

    task check(input [15:0] a, input [31:0] got, input [31:0] want);
        begin
            if (got === want)
                $display("  addr 0x%02h : got %08x  == want %08x   OK",
                         a, got, want);
            else begin
                $display("  addr 0x%02h : got %08x  != want %08x   ** QUIRK **",
                         a, got, want);
                fails = fails + 1;
            end
        end
    endtask

    initial begin
        awaddr = 0; awdata = 0; awvalid = 0;
        repeat (6) @(negedge clk);
        rst_n = 1;
        repeat (4) @(negedge clk);

        //---------------------------------------------------------------
        $display("== TEST 1: write 32'h0000_2C1 (=705, the stress symbol count) ==");
        wr(16'h03, 32'h0000_02C1); check(16'h03, rfu_wreg0, 32'h0000_02C1);
        wr(16'h04, 32'h0000_02C1); check(16'h04, rfu_wreg1, 32'h0000_02C1);
        wr(16'h05, 32'h0000_02C1); check(16'h05, rfu_wreg2, 32'h0000_02C1);
        wr(16'h06, 32'h0000_02C1); check(16'h06, rfu_wreg3, 32'h0000_02C1); // expect 1
        wr(16'h07, 32'h0000_02C1); check(16'h07, rfu_wreg4, 32'h0000_02C1); // expect 1
        wr(16'h08, 32'h0000_02C1); check(16'h08, rfu_wreg5, 32'h0000_02C1);
        wr(16'h09, 32'h0000_02C1); check(16'h09, rfu_wreg6, 32'h0000_02C1);
        wr(16'h0a, 32'h0000_02C1); check(16'h0a, rfu_wreg7, 32'h0000_02C1);
        wr(16'h0b, 32'h0000_02C1); check(16'h0b, rfu_wreg8, 32'h0000_02C1);
        wr(16'h0c, 32'h0000_02C1); check(16'h0c, rfu_wreg9, 32'h0000_02C1);

        //---------------------------------------------------------------
        $display("== TEST 2: write 32'h0000_4000 (=16384, the real symbol count) ==");
        wr(16'h06, 32'h0000_4000); check(16'h06, rfu_wreg3, 32'h0000_4000); // expect 0
        wr(16'h07, 32'h0000_4000); check(16'h07, rfu_wreg4, 32'h0000_4000); // expect 0
        wr(16'h08, 32'h0000_4000); check(16'h08, rfu_wreg5, 32'h0000_4000);

        //---------------------------------------------------------------
        $display("== TEST 3: RSIZE_BASE_ADDR (0x01) packs rbase/rsize, full width ==");
        wr(16'h01, 32'h1234_5678);
        $display("  addr 0x01 : rbase=%04x rsize=%04x  (want 5678 / 1234)",
                 rbase, rsize);
        if (rbase !== 16'h5678 || rsize !== 16'h1234) fails = fails + 1;

        $display("---------------------------------------------");
        if (fails == 0)
            $display("==== NOTE: every register matched -- the quirk is GONE ====");
        else
            $display("==== QUIRK CONFIRMED: %0d register(s) dropped bits ====", fails);
        $display("==== the dropped ones are exactly 0x06 and 0x07 ====");
        $finish;
    end

endmodule
