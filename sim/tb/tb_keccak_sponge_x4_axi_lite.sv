`timescale 1ns/1ps
module tb_keccak_sponge_x4_axi_lite;
  reg clk=0, resetn=0;
  reg [11:0] awaddr=0, araddr=0;
  reg [2:0] awprot=0, arprot=0;
  reg awvalid=0, wvalid=0, bready=0, arvalid=0, rready=0;
  reg [31:0] wdata=0;
  reg [3:0] wstrb=4'hf;
  wire awready,wready,bvalid,arready,rvalid;
  wire [1:0] bresp,rresp;
  wire [31:0] rdata;
  reg [7:0] msg[0:675];
  reg [7:0] expected[0:671];
  integer fd, ncases, scan, case_i, len, lane, i, w, status, cycles;
  reg [8*1024-1:0] path;
  reg [31:0] read_word;
  always #5 clk=~clk;
  keccak_sponge_x4_axi_lite #(.DEFAULT_WATCHDOG_CYCLES(200000)) dut(
    .s_axi_aclk(clk),.s_axi_aresetn(resetn),.s_axi_awaddr(awaddr),
    .s_axi_awprot(awprot),.s_axi_awvalid(awvalid),.s_axi_awready(awready),
    .s_axi_wdata(wdata),.s_axi_wstrb(wstrb),.s_axi_wvalid(wvalid),
    .s_axi_wready(wready),.s_axi_bresp(bresp),.s_axi_bvalid(bvalid),
    .s_axi_bready(bready),.s_axi_araddr(araddr),.s_axi_arprot(arprot),
    .s_axi_arvalid(arvalid),.s_axi_arready(arready),.s_axi_rdata(rdata),
    .s_axi_rresp(rresp),.s_axi_rvalid(rvalid),.s_axi_rready(rready));

  task automatic write_reg(input [11:0] address,input [31:0] value);
    begin
      @(negedge clk); awaddr=address; wdata=value; awvalid=1; wvalid=1; bready=0;
      while (!(awready && wready)) @(negedge clk);
      @(negedge clk); awvalid=0; wvalid=0; bready=1;
      while (!bvalid) @(negedge clk);
      if (bresp!==2'b00) $fatal(1,"write SLVERR address=%03x",address);
      @(negedge clk); bready=0;
    end
  endtask
  task automatic read_reg(input [11:0] address,output [31:0] value);
    begin
      @(negedge clk); araddr=address; arvalid=1; rready=0;
      while (!arready) @(negedge clk);
      @(negedge clk); arvalid=0; rready=1;
      while (!rvalid) @(negedge clk);
      if (rresp!==2'b00) $fatal(1,"read SLVERR address=%03x",address);
      value=rdata;
      @(negedge clk); rready=0;
    end
  endtask
  task automatic read_expect_error(input [11:0] address);
    reg [31:0] ignored;
    begin
      @(negedge clk); araddr=address; arvalid=1; rready=0;
      while (!arready) @(negedge clk);
      @(negedge clk); arvalid=0; rready=1;
      while (!rvalid) @(negedge clk);
      if (rresp!==2'b10 || rdata!==0)
        $fatal(1,"expected SLVERR/zero address=%03x resp=%b data=%08x",address,rresp,rdata);
      ignored=rdata;
      @(negedge clk); rready=0;
    end
  endtask
  task automatic wait_done(output [31:0] value);
    begin
      cycles=0; value=0;
      while ((value&32'h2)==0 && cycles<50000) begin
        read_reg(12'h004,value); cycles=cycles+1;
        if (value&32'hc) $fatal(1,"engine error status=%08x",value);
      end
      if (cycles>=50000 || (value&32'h11)!=32'h10)
        $fatal(1,"wait done failed status=%08x cycles=%0d",value,cycles);
    end
  endtask

  initial begin
    if (!$value$plusargs("VECTORS=%s",path)) $fatal(1,"missing VECTORS");
    fd=$fopen(path,"r"); if (!fd) $fatal(1,"cannot open vectors");
    scan=$fscanf(fd,"%d",ncases);
    repeat(3) @(negedge clk); resetn=1;
    for (case_i=0;case_i<ncases;case_i=case_i+1) begin
      scan=$fscanf(fd," %d",len);
      for (lane=0;lane<4;lane=lane+1)
        for (i=0;i<len;i=i+1) scan=$fscanf(fd," %h",msg[lane*169+i]);
      for (lane=0;lane<4;lane=lane+1)
        for (i=0;i<168;i=i+1) scan=$fscanf(fd," %h",expected[lane*168+i]);
      write_reg(12'h020,len);
      for (lane=0;lane<4;lane=lane+1) begin
        for (w=0;w<(len+3)/4;w=w+1) begin
          write_reg(12'h100+(lane*43+w)*4,
            {msg[lane*169+w*4+3],msg[lane*169+w*4+2],
             msg[lane*169+w*4+1],msg[lane*169+w*4]});
        end
      end
      write_reg(12'h000,1);
      wait_done(status);
      write_reg(12'h000,2);
      wait_done(status);
      for (lane=0;lane<4;lane=lane+1) begin
        for (w=0;w<42;w=w+1) begin
          read_reg(12'h400+(lane*42+w)*4,read_word);
          for (i=0;i<4;i=i+1)
            if (read_word[i*8+:8]!==expected[lane*168+w*4+i])
              $fatal(1,"SHAKE mismatch case=%0d lane=%0d byte=%0d got=%02x expected=%02x",
                case_i,lane,w*4+i,read_word[i*8+:8],expected[lane*168+w*4+i]);
        end
      end
      $display("KECCAK_SX4_VECTOR_PASS case=%0d inlen=%0d",case_i,len);
    end
    // Hold an already accepted R-channel result stable across a clear. AXI
    // VALID cannot be retracted; a simultaneous new result read must SLVERR.
    @(negedge clk); araddr=12'h400; arvalid=1; rready=0;
    while (!arready) @(negedge clk);
    @(negedge clk); arvalid=0;
    while (!rvalid) @(negedge clk);
    status=rdata;
    if (rresp!==2'b00) $fatal(1,"expected valid result before clear");
    repeat(3) begin
      @(negedge clk);
      if (!rvalid || rdata!==status) $fatal(1,"stalled R response changed/dropped");
    end
    @(negedge clk); rready=1;
    @(negedge clk); rready=0;
    // Queue CLEAR and a new RESULT read so both commit on the same edge.
    @(negedge clk);
    awaddr=12'h000; wdata=4; awvalid=1; wvalid=1; bready=0;
    while (!(awready && wready)) @(negedge clk);
    @(negedge clk); awvalid=0; wvalid=0;
    araddr=12'h400; arvalid=1;
    while (!arready) @(negedge clk);
    @(negedge clk); arvalid=0; rready=1; bready=1;
    while (!bvalid) @(negedge clk);
    if (!rvalid || rresp!==2'b10 || rdata!==0)
      $fatal(1,"same-cycle clear/result read not rejected resp=%b data=%08x",rresp,rdata);
    @(negedge clk); rready=0; bready=0;
    read_reg(12'h004,status);
    if (status!==0) $fatal(1,"clear status did not return zero: %08x",status);
    write_reg(12'h020,169);
    write_reg(12'h100,32'h03020100);
    write_reg(12'h000,1);
    read_expect_error(12'h400);
    write_reg(12'h000,4);
    read_reg(12'h004,status);
    if (status!==0) $fatal(1,"busy-read clear status did not return zero: %08x",status);
    write_reg(12'h008,1);
    write_reg(12'h000,1);
    read_reg(12'h004,status);
    if ((status&32'hc)!=32'hc || (status&32'h11)!=0)
      $fatal(1,"watchdog did not abort and invalidate context status=%08x",status);
    write_reg(12'h000,4);
    read_reg(12'h004,status);
    if (status!==0) $fatal(1,"clear status did not return zero: %08x",status);
    $display("KECCAK_SX4_PASS vectors=%0d byte_order=little_endian stateful=1 timeout_abort=1 clear_status=0 busy_read=1 clear_read=1 rvalid_backpressure=1",ncases);
    $finish;
  end
endmodule
