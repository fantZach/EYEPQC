`timescale 1ns/1ps
module tb_keccak_f1600;
  reg clk=0, rst=0, clear=0, start=0;
  reg [1599:0] state_i=0;
  wire [1599:0] state_o;
  wire busy, done;
  reg [1599:0] expected;
  integer fd, scan, count=0, cycles, ignored_start=0;
  reg [8*1024-1:0] path;
  always #5 clk=~clk;
  keccak_f1600 dut(.clk(clk),.rst(rst),.clear(clear),.start(start),
    .state_i(state_i),.state_o(state_o),.busy(busy),.done(done));
  initial begin
    if (!$value$plusargs("VECTORS=%s",path)) $fatal(1,"missing VECTORS");
    fd=$fopen(path,"r"); if (!fd) $fatal(1,"cannot open vectors");
    @(negedge clk); rst=1; @(negedge clk); rst=0;
    while (!$feof(fd)) begin
      scan=$fscanf(fd,"%h %h\n",state_i,expected);
      if (scan==2) begin
        @(negedge clk); start=1;
        @(negedge clk); start=0;
        // One sampled start while busy must not restart the permutation.
        start=1; @(posedge clk); cycles=1;
        @(negedge clk); start=0; ignored_start=ignored_start+1;
        while (!done && cycles<40) begin
          @(posedge clk); cycles=cycles+1;
          @(negedge clk);
        end
        if (!done) $fatal(1,"permutation timeout");
        if (cycles!=24) $fatal(1,"expected 24 rounds, observed %0d",cycles);
        if (state_o!==expected) begin
          $display("got=%h",state_o); $display("expected=%h",expected);
          $fatal(1,"permutation mismatch vector %0d",count);
        end
        if (busy) $fatal(1,"busy remained set at done");
        count=count+1;
      end
    end
    // clear must abort an active operation and zero visible state.
    @(negedge clk); state_i=1600'h1; start=1;
    @(negedge clk); start=0; clear=1;
    @(negedge clk); clear=0;
    if (busy || state_o!==1600'b0) $fatal(1,"clear did not abort and zero state");
    if (count<1 || ignored_start==0) $fatal(1,"control checks were not exercised");
    $display("KECCAK_F1600_PASS vectors=%0d cycles_per_permutation=24 busy_start_ignored=1 clear_abort=1",count);
    $finish;
  end
endmodule
