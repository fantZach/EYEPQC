`timescale 1ns/1ps
module tb_aes_axi_lite;
    reg clk = 0, resetn = 0;
    always #5 clk = !clk;
    reg [11:0] awaddr = 0, araddr = 0;
    reg awvalid = 0, wvalid = 0, arvalid = 0, bready = 0, rready = 0;
    reg [31:0] wdata = 0;
    reg [3:0] wstrb = 0;
    wire awready, wready, bvalid, arready, rvalid;
    wire [1:0] bresp, rresp;
    wire [31:0] rdata;
    aes_axi_lite dut(.s_axi_aclk(clk), .s_axi_aresetn(resetn),
        .s_axi_awaddr(awaddr), .s_axi_awprot(3'b0), .s_axi_awvalid(awvalid), .s_axi_awready(awready),
        .s_axi_wdata(wdata), .s_axi_wstrb(wstrb), .s_axi_wvalid(wvalid), .s_axi_wready(wready),
        .s_axi_bresp(bresp), .s_axi_bvalid(bvalid), .s_axi_bready(bready),
        .s_axi_araddr(araddr), .s_axi_arprot(3'b0), .s_axi_arvalid(arvalid), .s_axi_arready(arready),
        .s_axi_rdata(rdata), .s_axi_rresp(rresp), .s_axi_rvalid(rvalid), .s_axi_rready(rready));
    integer ticks = 0, core_start = -1, core_cycles = 0, first_core_cycles = 0;
    reg previous_core_valid = 0;
    always @(posedge clk) begin
        ticks = ticks + 1;
        if (dut.core.next) core_start = ticks;
        if (dut.core.result_valid && !previous_core_valid && core_start >= 0) begin
            core_cycles = ticks - core_start;
            if (first_core_cycles == 0) first_core_cycles = core_cycles;
            else if (core_cycles != first_core_cycles)
                $fatal(1, "variable core latency %0d != %0d", core_cycles, first_core_cycles);
            core_start = -1;
        end
        previous_core_valid = dut.core.result_valid;
    end
    initial begin #20000000; $fatal(1, "AES AXI test timeout"); end
    task automatic wr(input [11:0] addr, input [31:0] value, input [3:0] strb,
                      input integer skew, input [1:0] expected);
        begin
            fork
                begin
                    if (skew < 0) repeat(-skew) @(posedge clk);
                    @(negedge clk); awaddr = addr; awvalid = 1;
                    do @(posedge clk); while (!awready);
                    @(negedge clk); awvalid = 0;
                end
                begin
                    if (skew > 0) repeat(skew) @(posedge clk);
                    @(negedge clk); wdata = value; wstrb = strb; wvalid = 1;
                    do @(posedge clk); while (!wready);
                    @(negedge clk); wvalid = 0;
                end
            join
            while (!bvalid) @(negedge clk);
            repeat (3) begin
                @(negedge clk);
                if (!bvalid || bresp !== expected || awready || wready)
                    $fatal(1, "write response/backpressure addr=%h resp=%h expected=%h", addr, bresp, expected);
            end
            bready = 1; @(negedge clk); bready = 0;
        end
    endtask
    task automatic rd(input [11:0] addr, output [31:0] value, input [1:0] expected);
        reg [31:0] held;
        begin
            @(negedge clk); araddr = addr; arvalid = 1;
            do @(posedge clk); while (!arready);
            @(negedge clk); arvalid = 0;
            while (!rvalid) @(negedge clk);
            held = rdata;
            repeat (3) begin
                @(negedge clk);
                if (!rvalid || rdata !== held || rresp !== expected || arready)
                    $fatal(1, "read response/backpressure addr=%h", addr);
            end
            value = rdata; rready = 1; @(negedge clk); rready = 0;
        end
    endtask
    task automatic wait_done(input [31:0] flags);
        integer timeout;
        reg [31:0] status;
        begin
            timeout = 0;
            rd(4, status, 0);
            while (status[0]) begin
                rd(4, status, 0); timeout = timeout + 1;
                if (timeout > 100) $fatal(1, "AES busy stuck");
            end
            if ((status & flags) !== flags) $fatal(1, "AES completion status=%h", status);
        end
    endtask
    task automatic write_128(input [11:0] base, input [127:0] value);
        integer j;
        for (j = 0; j < 4; j = j + 1)
            wr(base + j*4, value[127-j*32 -: 32], 15, 0, 0);
    endtask
    task automatic check_block(input [127:0] value, input [127:0] answer);
        integer j;
        reg [31:0] word_read;
        reg [127:0] observed;
        begin
            write_128('h20, value);
            wr(0, 2, 15, 0, 0); wait_done(6);
            for (j = 0; j < 4; j = j + 1) begin
                rd('h30 + j*4, word_read, 0);
                observed[127-j*32 -: 32] = word_read;
            end
            if (observed !== answer) $fatal(1, "consecutive/key-update AES mismatch");
        end
    endtask
    task automatic check_cleared;
        integer j;
        begin
            if (dut.key !== 0 || dut.block !== 0 || dut.core.enc_block.new_block !== 0 ||
                dut.core.result_valid !== 0) $fatal(1, "AES state not cleared");
            for (j = 0; j < 15; j = j + 1)
                if (dut.core.keymem.key_mem[j] !== 0) $fatal(1, "round key %0d not cleared", j);
        end
    endtask
    reg [127:0] key, block, expected, actual;
    reg [31:0] word_value;
    integer file, count, fields, i;
    string vectors;
    initial begin
        repeat (4) @(negedge clk); resetn = 1;
        rd(8, word_value, 0);
        if (word_value !== 32'h41455331) $fatal(1, "AES identifier");
        wr(0, 2, 15, 0, 2); // Cannot encrypt before init.
        wr(1, 1, 15, 0, 2); // Misaligned.
        wr('h100, 1, 15, 0, 2); // No truncated-address alias.
        rd('h10, word_value, 2); // Keys are not readable.
        if (!$value$plusargs("VECTORS=%s", vectors)) $fatal(1, "missing VECTORS");
        file = $fopen(vectors, "r");
        if (!file) $fatal(1, "cannot open vectors");
        count = 0;
        while (!$feof(file)) begin
            fields = $fscanf(file, "%h %h %h\n", key, block, expected);
            if (fields == 3) begin
                for (i = 0; i < 4; i = i + 1)
                    wr('h10 + i*4, key[127-i*32 -: 32], 15, i-2, 0);
                wr(0, 1, 15, 0, 0); wait_done(2);
                for (i = 0; i < 4; i = i + 1) begin
                    wr('h20 + i*4, 32'hffffffff, 15, 0, 0);
                    wr('h20 + i*4, block[127-i*32 -: 32], 3, 2, 0);
                    wr('h20 + i*4, block[127-i*32 -: 32], 12, -2, 0);
                end
                wr(0, 2, 15, 0, 0);
                wr('h10, 0, 15, 0, 2); // Reject busy key overwrite.
                wait_done(6);
                for (i = 0; i < 4; i = i + 1) begin
                    rd('h30 + i*4, word_value, 0);
                    actual[127-i*32 -: 32] = word_value;
                end
                if (actual !== expected) $fatal(1, "AES vector %0d mismatch: %h != %h", count, actual, expected);
                // Abort an active operation and check real upstream secret state.
                wr(0, 2, 15, 0, 0); wr(0, 4, 15, 0, 0);
                rd(4, word_value, 0);
                if (word_value !== 0) $fatal(1, "zeroization status failed");
                check_cleared();
                wr(0, 2, 15, 0, 2);
                count = count + 1;
            end else if (fields != -1) $fatal(1, "malformed vector");
        end
        $fclose(file);
        if (count < 3) $fatal(1, "insufficient vectors");
        // Reuse one expanded key across consecutive blocks, then invalidate and replace it.
        key = 128'h000102030405060708090a0b0c0d0e0f;
        write_128('h10, key);
        wr(0, 1, 15, 0, 0); wait_done(2);
        check_block(128'h00112233445566778899aabbccddeeff,
                    128'h69c4e0d86a7b0430d8cdb78070b4c55a);
        check_block(0, 128'hc6a13b37878f5b826f4f8162a1c8d879);
        wr('h10, 0, 15, 0, 0);
        rd(4, word_value, 0);
        if (word_value[2:1] != 0) $fatal(1, "key update left old key/result valid");
        wr(0, 2, 15, 0, 2);
        for (i = 1; i < 4; i = i + 1) wr('h10 + i*4, 0, 15, 0, 0);
        wr(0, 1, 15, 0, 0); wait_done(2);
        check_block(0, 128'h66e94bd4ef8a2c3b884cfa59ca342b2e);

        write_128('h20, 128'h00112233445566778899aabbccddeeff);
        wr(0, 2, 15, 0, 0);
        rd(4, word_value, 0);
        if (!word_value[0]) $fatal(1, "reset test did not interrupt busy AES");
        @(negedge clk); resetn = 0;
        repeat (4) @(negedge clk); resetn = 1;
        rd(4, word_value, 0);
        if (word_value !== 0) $fatal(1, "hard reset status failed");
        check_cleared();
        wr(0, 2, 15, 0, 2);
        if (first_core_cycles < 1) $fatal(1, "missing AES cycle measurement");
        $display("AES_AXI_PASS vectors=%0d core_cycles=%0d consecutive=2 key_update=1 hard_reset=1",
                 count, first_core_cycles);
        $finish;
    end
endmodule
