`timescale 1ns/1ps
module tb_ov5640_probe;
    reg clk=0;
    always #5 clk=~clk;
    reg resetn=1;
    reg [31:0] cfg=0;
    wire [31:0] status;
    wire cam_resetn, cam_pwdn;
    tri1 scl, sda;
    ov5640_probe dut (.clk(clk), .resetn(resetn), .cfg(cfg), .status(status),
        .cam_scl(scl), .cam_sda(sda), .cam_resetn(cam_resetn), .cam_pwdn(cam_pwdn));
    // Accelerate only physical delays/divider, not the probe register mapping.
    defparam dut.ctrl.CLK_HZ=3_200_000, dut.ctrl.SCCB_HZ=100_000,
        dut.ctrl.TIMEOUT_CYCLES=2400, dut.ctrl.RESET_CYCLES=20,
        dut.ctrl.POWERUP_CYCLES=64, dut.ctrl.SETTLE_CYCLES=16;
    ov5640_model sensor (.resetn(resetn), .enabled(1'b1), .wrong_id(1'b0),
        .nack_mask(4'b0), .nack_once(1'b0), .corrupt_enable(1'b0), .corrupt_addr(16'h0), .scl(scl), .sda(sda));
    task wait_result(input [3:0] expected);
        integer cycles;
        begin
            cycles=0;
            while (!(status[16] || status[17]) && cycles<400000) begin @(negedge clk); cycles=cycles+1; end
            if (cycles==400000 || status[27:24] !== expected || status[18]) $fatal(1,"probe completion/status mapping failed");
        end
    endtask
    initial begin
        #1 resetn=0; repeat(6) @(negedge clk); resetn=1;
        cfg=1; wait_result(4); // VTS zero must fail closed.
        cfg=32'h80000000; repeat(6) @(negedge clk);
        if (status[16] || status[17] || status[19] || !status[20]) $fatal(1,"cfg reset mapping failed");
        cfg=(1968<<9) | (1<<3) | 2; repeat(6) @(negedge clk);
        cfg=cfg | 1; wait_result(0);
        if (status[15:0] !== 16'h5640 || !status[16] || !status[19] || status[20] || !status[23] ||
            status[22:21] !== 2'b11 || sensor.memory[16'h3808] !== 1 || sensor.memory[16'h3809] !== 8'h40)
            $fatal(1,"probe 320x240 JPEG/status mapping failed");
        repeat(5000) @(negedge clk);
        if (sensor.writes != 251 || !status[16]) $fatal(1,"held START must not repeat init");
        cfg=(cfg & ~32'd1) | 32'h40000000; repeat(6) @(negedge clk);
        if (status !== 32'h56403035) $fatal(1,"diagnostic page mapping failed: %h",status);
        cfg=(2400<<9) | (12<<3) | 4 | 2; repeat(6) @(negedge clk);
        cfg=cfg | 1; @(negedge clk);
        if (status[16] || status[23]) $fatal(1,"probe did not stop capture on new START");
        wait_result(0);
        if (sensor.memory[16'h3808] !== 2 || sensor.memory[16'h3809] !== 8'h80 || sensor.memory[16'h4407] !== 12 ||
            sensor.memory[16'h380e] !== 9 || sensor.memory[16'h380f] !== 8'h60) $fatal(1,"640/quality/VTS mapping failed");
        $display("OV5640_PROBE_PASS"); $finish;
    end
    initial begin #10000000; $fatal(1,"test watchdog"); end
endmodule
