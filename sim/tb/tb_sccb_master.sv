`timescale 1ns/1ps
module tb_sccb_master;
    reg clk=0;
    always #5 clk=~clk;
    reg resetn=1, start=0, reading=0;
    reg [15:0] addr=16'h1234;
    reg [7:0] data=8'ha5;
    tri1 scl, sda;
    reg hold_scl=0, hold_sda=0, enabled=1;
    reg [3:0] nack_mask=0;
    assign scl=hold_scl ? 1'b0 : 1'bz;
    assign sda=hold_sda ? 1'b0 : 1'bz;
    wire busy, done;
    wire [1:0] error;
    wire [7:0] result;
    sccb_master #(.CLK_HZ(3_200_000), .SCCB_HZ(100_000), .TIMEOUT_CYCLES(2400)) dut (
        .clk(clk), .resetn(resetn), .start(start), .read_not_write(reading),
        .reg_addr(addr), .write_data(data), .scl(scl), .sda(sda),
        .busy(busy), .done(done), .error(error), .read_data(result)
    );
    ov5640_model sensor (.resetn(resetn), .enabled(enabled), .wrong_id(1'b0),
        .nack_mask(nack_mask), .nack_once(1'b0), .corrupt_enable(1'b0), .corrupt_addr(16'h0), .scl(scl), .sda(sda));
    task launch(input bit read_reg);
        begin
            @(negedge clk); reading=read_reg; start=1;
            @(negedge clk); start=0;
        end
    endtask
    task finish(input [1:0] expected);
        integer cycles;
        begin
            cycles=0;
            while (!done && cycles < 2500) begin @(negedge clk); cycles=cycles+1; end
            if (!done || busy || error !== expected) $fatal(1,"SCCB result error=%0d expected=%0d cycles=%0d",error,expected,cycles);
            @(negedge clk);
            if (done) $fatal(1,"done must be a pulse");
        end
    endtask
    initial begin
        #1 resetn=0; repeat(6) @(negedge clk); resetn=1;
        launch(0); finish(0);
        if (sensor.memory[16'h1234] !== 8'ha5 || sensor.writes != 1 || sensor.starts != 1 || sensor.stops != 1)
            $fatal(1,"16-bit register write/STOP mismatch");
        launch(1); finish(0);
        if (result !== 8'ha5 || sensor.starts != 3 || sensor.stops != 2 || sensor.read_nacks != 1)
            $fatal(1,"read/repeated START/final NACK mismatch");
        for (integer n=0; n<4; n=n+1) begin
            nack_mask=1 << n; launch(0); finish(1);
            if (scl !== 1 || sda !== 1) $fatal(1,"NACK must STOP and release bus");
        end
        nack_mask=1; launch(1); finish(1); nack_mask=0;
        // Stretch a clock for less than the transaction deadline.
        launch(0);
        @(negedge scl); hold_scl=1; repeat(80) @(negedge clk); hold_scl=0;
        finish(0);
        // A busy request and live changes to inputs must not corrupt the latched job.
        addr=16'h4321; data=8'h5a; launch(0);
        repeat(50) @(negedge clk); addr=16'hffff; data=0; start=1;
        @(negedge clk); start=0; finish(0);
        if (sensor.memory[16'h4321] !== 8'h5a || sensor.memory[16'hffff] !== 0)
            $fatal(1,"busy request/input latch failed");
        hold_scl=1; launch(0); finish(2); hold_scl=0;
        repeat(10) @(negedge clk); hold_sda=1; launch(0); finish(2); hold_sda=0;
        repeat(10) @(negedge clk);
        launch(0); repeat(50) @(negedge clk); resetn=0;
        repeat(5) @(negedge clk);
        if (busy || done || scl !== 1 || sda !== 1) $fatal(1,"reset did not release bus");
        resetn=1; addr=16'h3456; data=8'hc7; launch(0); finish(0);
        $display("SCCB_PASS"); $finish;
    end
    initial begin #500000; $fatal(1,"test watchdog"); end
endmodule
