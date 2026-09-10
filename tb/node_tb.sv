/*
 * node_tb.sv -- self-checking testbench for the secure edge-inference node.
 * Drives the feature vectors from model/node_model.py and checks the ciphertext,
 * class, and probability bit-exactly against the golden model.
 */
`timescale 1ns/1ps
module node_tb;
    logic               clk = 0, rst = 1;
    logic signed [13:0] i_x0, i_x1;
    logic [31:0]        i_seq;
    logic               i_valid, i_ready;
    wire                o_ready, o_valid, o_class;
    wire  [127:0]       o_ct;
    wire  signed [13:0] o_prob;

    node_top dut (.clk(clk), .rst(rst), .i_x0(i_x0), .i_x1(i_x1), .i_seq(i_seq),
                  .i_valid(i_valid), .o_ready(o_ready), .o_ct(o_ct), .o_prob(o_prob),
                  .o_class(o_class), .o_valid(o_valid), .i_ready(i_ready));

    always #5 clk = ~clk;

    integer fd, n, pass = 0, fail = 0, total = 0;
    reg [13:0]  vx0, vx1, vprob;
    reg [31:0]  vseq;
    reg [127:0] vct;
    reg [3:0]   vcls;
    reg [1023:0] hdr;

    task run_one;
        begin
            @(negedge clk);
            i_x0 = $signed(vx0); i_x1 = $signed(vx1); i_seq = vseq; i_valid = 1'b1;
            @(negedge clk); i_valid = 1'b0;
            while (o_valid !== 1'b1) @(negedge clk);
            total = total + 1;
            if (o_ct === vct && o_class === vcls[0] && o_prob === $signed(vprob))
                pass = pass + 1;
            else begin
                fail = fail + 1;
                $display("MISMATCH x=(%0d,%0d):", $signed(vx0), $signed(vx1));
                $display("   ct  exp %032h", vct);
                $display("   ct  got %032h", o_ct);
                $display("   cls exp %0d got %0d | prob exp %0d got %0d",
                         vcls[0], o_class, $signed(vprob), $signed(o_prob));
            end
            @(negedge clk);     // DONE -> IDLE (i_ready held high)
        end
    endtask

    initial begin
        i_valid = 0; i_ready = 1; i_x0 = 0; i_x1 = 0; i_seq = 0;
        repeat (4) @(negedge clk); rst = 0;
        fd = $fopen("../tb/node_vectors.hex", "r");
        if (fd == 0) begin $display("ERROR: cannot open node_vectors.hex"); $finish; end
        n = $fgets(hdr, fd);                       // skip the comment header line
        while (!$feof(fd)) begin
            n = $fscanf(fd, " %h %h %h %h %h %h", vx0, vx1, vseq, vct, vcls, vprob);
            if (n == 6) run_one;
        end
        $fclose(fd);
        $display("------------------------------------------------------------");
        $display("NODE TB: %0d/%0d vectors bit-exact  (%0d mismatch)", pass, total, fail);
        if (fail == 0) $display("RESULT: ALL VECTORS PASS");
        else           $display("RESULT: FAILURES PRESENT");
        $finish;
    end
endmodule
