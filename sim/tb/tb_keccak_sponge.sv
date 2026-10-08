`timescale 1ns/1ps
module tb_keccak_sponge;
  reg clk=0, rst=0, clear=0, start=0;
  reg [1:0] mode=0;
  reg [15:0] shake_out_bytes=0;
  reg in_valid=0, in_last=0, out_ready=0;
  reg [7:0] in_data=0;
  wire in_ready, out_valid;
  wire [7:0] out_data;
  wire busy, done;
  reg [7:0] message [0:4095];
  reg [7:0] expected [0:4095];
  reg [7:0] received [0:4095];
  integer fd, scan, mode_i, in_len, out_len, i, j, count=0, out_count, cycles;
  integer elapsed=0, min_elapsed=0, max_elapsed=0, sum_elapsed=0;
  reg [8*1024-1:0] path;
  reg [7:0] prior_data;
  reg prior_stalled=0;
  always #5 clk=~clk;
  keccak_sponge dut(.clk(clk),.rst(rst),.clear(clear),.start(start),.mode(mode),
    .shake_out_bytes(shake_out_bytes),.in_valid(in_valid),.in_ready(in_ready),
    .in_data(in_data),.in_last(in_last),.out_valid(out_valid),.out_ready(out_ready),
    .out_data(out_data),.busy(busy),.done(done));
  always @(posedge clk) begin
    if (busy) elapsed <= elapsed+1;
    if (out_valid && out_ready) begin received[out_count] <= out_data; out_count <= out_count+1; end
    if (prior_stalled && (!out_valid || out_data!==prior_data))
      $fatal(1,"output changed while stalled");
    prior_stalled <= out_valid && !out_ready;
    if (out_valid && !out_ready) prior_data <= out_data;
  end
  task send_byte(input integer k, input integer is_last);
    begin
      @(negedge clk); in_valid=1; in_data=message[k]; in_last=is_last;
      while (!in_ready) @(negedge clk);
      @(negedge clk); in_valid=0; in_last=0;
    end
  endtask
  initial begin
    if (!$value$plusargs("VECTORS=%s",path)) $fatal(1,"missing VECTORS");
    fd=$fopen(path,"r"); if (!fd) $fatal(1,"cannot open vectors");
    out_count=0;
    @(negedge clk); rst=1; @(negedge clk); rst=0;
    while (!$feof(fd)) begin
      scan=$fscanf(fd,"%d %d %d",mode_i,in_len,out_len);
      if (scan==3) begin
        for (i=0;i<in_len;i=i+1) scan=$fscanf(fd," %h",message[i]);
        for (i=0;i<out_len;i=i+1) scan=$fscanf(fd," %h",expected[i]);
        @(negedge clk); mode=mode_i[1:0]; shake_out_bytes=out_len; start=1;
        elapsed=0;
        @(negedge clk); start=0;
        if (in_len==0) begin
          wait(in_ready); @(negedge clk); in_last=1;
          @(negedge clk); in_last=0;
        end else begin
          for (j=0;j<in_len;j=j+1) send_byte(j,j==in_len-1);
        end
        cycles=0;
        while (!done && cycles<200000) begin
          @(negedge clk); cycles=cycles+1; out_ready=(cycles%4)!=1;
        end
        out_ready=0;
        if (!done) $fatal(1,"sponge timeout vector %0d",count);
        if (out_count!=out_len) $fatal(1,"output count got %0d expected %0d",out_count,out_len);
        for (i=0;i<out_len;i=i+1)
          if (received[i]!==expected[i]) $fatal(1,"digest mismatch vector %0d byte %0d got %02x expected %02x",count,i,received[i],expected[i]);
        if (busy) $fatal(1,"busy remained set after done");
        if (count==0 || elapsed<min_elapsed) min_elapsed=elapsed;
        if (elapsed>max_elapsed) max_elapsed=elapsed;
        sum_elapsed=sum_elapsed+elapsed;
        count=count+1; out_count=0;
        @(negedge clk);
      end
    end
    // Mid-permutation clear must return to idle and discard the operation.
    @(negedge clk); start=1; mode=0;
    @(negedge clk); start=0; in_valid=1; in_data=8'hA5; in_last=1;
    while (!in_ready) @(negedge clk);
    @(negedge clk); in_valid=0; in_last=0;
    repeat (4) @(negedge clk); clear=1; @(negedge clk); clear=0;
    if (busy || out_valid) $fatal(1,"clear did not cancel sponge");
    $display("KECCAK_SPONGE_PASS vectors=%0d modes=SHA3-256,SHA3-512,SHAKE128,SHAKE256 boundary_multiblock_stall_clear=1 sim_cycles_start_to_done_min=%0d max=%0d avg=%0d",count,min_elapsed,max_elapsed,sum_elapsed/count);
    $finish;
  end
endmodule
