/*
 * node_lat_tb.sv -- measures the latency-hiding benefit of CTR precomputation.
 * Instantiates the node twice (hidden vs blocking crypto), drives one identical
 * inference, and reports the i_valid->o_valid latency of each. Both must produce
 * the SAME ciphertext (functional equivalence; only the timing differs).
 */
`timescale 1ns/1ps
module node_lat_tb;
    logic               clk = 0, rst = 1;
    logic signed [13:0] i_x0, i_x1;
    logic [31:0]        i_seq;
    logic               i_valid, i_ready;
    wire  [127:0]       ct_h, ct_b;
    wire  signed [13:0] prob_h, prob_b;
    wire                oready_h, ovalid_h, class_h, oready_b, ovalid_b, class_b;

    node_top #(.HIDE_CRYPTO(1)) dut_h (
        .clk, .rst, .i_x0, .i_x1, .i_seq, .i_valid, .o_ready(oready_h),
        .o_ct(ct_h), .o_prob(prob_h), .o_class(class_h), .o_valid(ovalid_h), .i_ready);
    node_top #(.HIDE_CRYPTO(0)) dut_b (
        .clk, .rst, .i_x0, .i_x1, .i_seq, .i_valid, .o_ready(oready_b),
        .o_ct(ct_b), .o_prob(prob_b), .o_class(class_b), .o_valid(ovalid_b), .i_ready);

    always #5 clk = ~clk;

    integer t = 0;
    always @(negedge clk) t = t + 1;
    integer t0, th, tb;

    initial begin
        i_valid = 0; i_ready = 1; i_x0 = 0; i_x1 = 0; i_seq = 0;
        repeat (4) @(negedge clk); rst = 0;
        @(negedge clk);
        i_x0 = $signed(14'h0e4f); i_x1 = $signed(14'h3db7); i_seq = 32'd0;
        i_valid = 1; t0 = t;
        @(negedge clk); i_valid = 0;
        @(posedge ovalid_h); th = t - t0;
        @(posedge ovalid_b); tb = t - t0;
        $display("------------------------------------------------------------");
        $display("end-to-end latency (i_valid -> o_valid):");
        $display("   latency-hidden CTR : %0d cycles", th);
        $display("   blocking crypto    : %0d cycles", tb);
        $display("   cipher latency hidden = %0d cycles (%.1f%%)",
                 tb - th, 100.0 * (tb - th) / tb);
        if (ct_h === ct_b) $display("   ciphertext identical across modes: %032h", ct_h);
        else               $display("   ERROR: ct mismatch  h=%032h  b=%032h", ct_h, ct_b);
        $finish;
    end
endmodule
