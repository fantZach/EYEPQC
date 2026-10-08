`timescale 1ns/1ps
module tb_keccak_axi_lite;
    reg clk=0;
    always #5 clk=~clk;
    reg aresetn=0;
    reg [11:0] awaddr=0, araddr=0;
    reg [2:0] awprot=0, arprot=0;
    reg awvalid=0, wvalid=0, bready=0, arvalid=0, rready=0;
    reg [31:0] wdata=0;
    reg [3:0] wstrb=4'hf;
    wire awready, wready, bvalid, arready, rvalid;
    wire [1:0] bresp, rresp;
    wire [31:0] rdata;
    reg [31:0] input_words [0:49];
    reg [31:0] expected_words [0:49];
    integer fd, rc, i, cycles;
    integer global_cycles=0, start_cycle;
    reg [31:0] value;
    reg [1:0] response;
    always @(posedge clk) global_cycles <= global_cycles + 1;

    keccak_axi_lite #(.DEFAULT_WATCHDOG_CYCLES(1000)) dut (
        .s_axi_aclk(clk), .s_axi_aresetn(aresetn),
        .s_axi_awaddr(awaddr), .s_axi_awprot(awprot), .s_axi_awvalid(awvalid), .s_axi_awready(awready),
        .s_axi_wdata(wdata), .s_axi_wstrb(wstrb), .s_axi_wvalid(wvalid), .s_axi_wready(wready),
        .s_axi_bresp(bresp), .s_axi_bvalid(bvalid), .s_axi_bready(bready),
        .s_axi_araddr(araddr), .s_axi_arprot(arprot), .s_axi_arvalid(arvalid), .s_axi_arready(arready),
        .s_axi_rdata(rdata), .s_axi_rresp(rresp), .s_axi_rvalid(rvalid), .s_axi_rready(rready)
    );

    initial begin
        #20000000; $fatal(1, "Keccak AXI test timeout");
    end

    task automatic axi_write(input [11:0] addr, input [31:0] data,
                             input [3:0] strb, input bit w_first,
                             input bit hold_response, output [1:0] resp);
        begin
            if (w_first) begin
                @(negedge clk); wdata=data; wstrb=strb; wvalid=1;
                do @(posedge clk); while (!wready);
                @(negedge clk); wvalid=0;
                repeat (2) @(negedge clk);
                awaddr=addr; awvalid=1;
                do @(posedge clk); while (!awready);
                @(negedge clk); awvalid=0;
            end else begin
                @(negedge clk); awaddr=addr; awvalid=1;
                do @(posedge clk); while (!awready);
                @(negedge clk); awvalid=0;
                repeat (2) @(negedge clk);
                wdata=data; wstrb=strb; wvalid=1;
                do @(posedge clk); while (!wready);
                @(negedge clk); wvalid=0;
            end
            wait (bvalid === 1'b1);
            resp=bresp;
            if (hold_response) begin
                repeat (3) begin
                    @(posedge clk);
                    if (!bvalid || bresp !== resp) $fatal(1, "B response changed under backpressure");
                end
            end
            @(negedge clk); bready=1;
            @(posedge clk);
            @(negedge clk); bready=0;
        end
    endtask

    task automatic axi_read(input [11:0] addr, input bit hold_response,
                            output [31:0] data, output [1:0] resp);
        begin
            @(negedge clk); araddr=addr; arvalid=1;
            do @(posedge clk); while (!arready);
            @(negedge clk); arvalid=0;
            wait (rvalid === 1'b1);
            data=rdata; resp=rresp;
            if (hold_response) begin
                repeat (3) begin
                    @(posedge clk);
                    if (!rvalid || rresp !== resp || rdata !== data)
                        $fatal(1, "R response changed under backpressure");
                end
            end
            @(negedge clk); rready=1;
            @(posedge clk);
            @(negedge clk); rready=0;
        end
    endtask

    task automatic expect_write(input [11:0] addr, input [31:0] data,
                                input [1:0] want, input bit w_first);
        reg [1:0] got;
        begin
            axi_write(addr,data,4'hf,w_first,1'b0,got);
            if (got !== want) $fatal(1,"write %03x response=%b expected=%b",addr,got,want);
        end
    endtask

    task automatic expect_read(input [11:0] addr, input [1:0] want,
                               input [31:0] wanted_data);
        reg [31:0] got_data;
        reg [1:0] got_resp;
        begin
            axi_read(addr,1'b0,got_data,got_resp);
            if (got_resp !== want || got_data !== wanted_data)
                $fatal(1,"read %03x data=%08x/%b expected=%08x/%b",addr,got_data,got_resp,wanted_data,want);
        end
    endtask

    reg [2047:0] vector_path;
    initial begin
        if (!$value$plusargs("VECTORS=%s", vector_path)) $fatal(1,"missing +VECTORS");
        fd=$fopen(vector_path,"r");
        if (!fd) $fatal(1,"cannot open vector file %0s",vector_path);
        for (i=0;i<50;i=i+1) begin
            rc=$fscanf(fd,"%h",input_words[i]);
            if (rc!=1) $fatal(1,"missing input word %0d",i);
        end
        for (i=0;i<50;i=i+1) begin
            rc=$fscanf(fd,"%h",expected_words[i]);
            if (rc!=1) $fatal(1,"missing expected word %0d",i);
        end
        $fclose(fd);

        repeat (4) @(posedge clk);
        @(negedge clk); aresetn=1;
        repeat (2) @(posedge clk);

        axi_read(12'h00c,1'b1,value,response);
        if (response!=0 || value!=32'h4b434831) $fatal(1,"ID register mismatch");
        expect_read(12'h010,2'b00,32'h00010000);
        expect_read(12'h101,2'b10,0); // unaligned read
        expect_read(12'h300,2'b10,0); // unmapped read
        expect_read(12'h100,2'b10,0); // input state is write-only
        expect_read(12'h200,2'b10,0); // no result until done
        expect_write(12'h101,32'h1,2'b10,1'b0); // unaligned write
        expect_write(12'h300,32'h1,2'b10,1'b1); // unmapped write
        axi_write(12'h000,32'd1,4'h2,1'b0,1'b0,response); // illegal CTRL WSTRB
        if (response!=2'b10) $fatal(1,"illegal CTRL WSTRB accepted");

        // Load the 1600-bit state with both independent AXI channel orders.
        for (i=0;i<50;i=i+1)
            expect_write(12'h100+i*4,input_words[i],2'b00,(i%2)!=0);
        expect_write(12'h008,32'd0,2'b00,1'b0); // disable watchdog for reference run
        start_cycle=global_cycles;
        axi_write(12'h000,32'd1,4'hf,1'b0,1'b1,response); // B backpressure
        if (response!=0) $fatal(1,"start failed response=%b",response);

        // Busy-state reads/writes/restarts fail without corrupting core input.
        expect_write(12'h100,32'hdeadbeef,2'b10,1'b1);
        expect_write(12'h000,32'd1,2'b10,1'b0);
        expect_write(12'h008,32'd12,2'b10,1'b1);
        expect_read(12'h200,2'b10,0);

        cycles=global_cycles-start_cycle;
        value=0;
        while (!value[1] && cycles<200) begin
            axi_read(12'h004,1'b0,value,response);
            if (response!=0) $fatal(1,"status read failed");
            cycles=global_cycles-start_cycle;
        end
        if (!value[1] || value[0]) $fatal(1,"permutation did not complete");
        if (cycles<24 || cycles>60) $fatal(1,"unexpected permutation latency %0d",cycles);
        for (i=0;i<50;i=i+1) begin
            axi_read(12'h200+i*4,1'b0,value,response);
            if (response!=0 || value!==expected_words[i])
                $fatal(1,"result word %0d got=%08x resp=%b expected=%08x",i,value,response,expected_words[i]);
        end
        $display("KECCAK_AXI_REFERENCE_PASS sim_cycles_start_to_done=%0d state_words=50",cycles);

        // Clear while a second permutation is active; all state/results zeroize.
        expect_write(12'h000,32'd1,2'b00,1'b0);
        repeat (4) @(posedge clk);
        expect_write(12'h000,32'd2,2'b00,1'b1);
        repeat (2) @(posedge clk);
        expect_read(12'h004,2'b00,32'd0);
        if (dut.state_q !== 1600'b0 || dut.result_q !== 1600'b0 || dut.u_core.state_q !== 1600'b0)
            $fatal(1,"clear did not zeroize state/result");
        $display("KECCAK_AXI_CLEAR_PASS busy_abort=1 zeroize=1");

        // Hardware watchdog timeout sets sticky timeout/error and zeroizes.
        expect_write(12'h008,32'd4,2'b00,1'b0);
        expect_write(12'h100,input_words[0],2'b00,1'b1);
        expect_write(12'h000,32'd1,2'b00,1'b0);
        cycles=0; value=0;
        while (!value[3] && cycles<40) begin
            axi_read(12'h004,1'b0,value,response);
            cycles=cycles+1;
        end
        if (!value[3] || !value[2] || value[0]) $fatal(1,"watchdog timeout status incorrect: %08x",value);
        if (dut.state_q !== 1600'b0 || dut.result_q !== 1600'b0 || dut.u_core.state_q !== 1600'b0)
            $fatal(1,"watchdog did not zeroize state/result");
        axi_write(12'h000,32'd2,4'hf,1'b0,1'b0,response);
        if (response!=0) $fatal(1,"clear after timeout failed");
        expect_read(12'h004,2'b00,32'd0);

        // Synchronous reset aborts an in-flight operation and clears all flags.
        expect_write(12'h008,32'd0,2'b00,1'b1);
        expect_write(12'h000,32'd1,2'b00,1'b0);
        repeat (5) @(posedge clk);
        @(negedge clk); aresetn=0;
        repeat (2) @(posedge clk);
        @(negedge clk); aresetn=1;
        repeat (2) @(posedge clk);
        expect_read(12'h004,2'b00,32'd0);
        if (dut.state_q !== 1600'b0 || dut.result_q !== 1600'b0 || dut.u_core.state_q !== 1600'b0)
            $fatal(1,"reset did not zeroize state/result");
        $display("KECCAK_AXI_PASS independent_aw_w=1 backpressure=1 errors=1 busy_guards=1 reset=1 clear=1 timeout=1");
        $finish;
    end
endmodule
