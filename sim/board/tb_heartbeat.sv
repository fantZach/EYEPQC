`timescale 1ns/1ps
module tb_heartbeat;
    reg clk = 0;
    reg resetn = 0;
    wire led, led_each;
    integer cycle;
    heartbeat #(.HALF_PERIOD_CYCLES(3)) dut(clk, resetn, led);
    heartbeat #(.HALF_PERIOD_CYCLES(1)) each_cycle(clk, resetn, led_each);
    always #5 clk = ~clk;
    initial begin
        repeat (2) @(negedge clk);
        if (led !== 0 || led_each !== 0) $fatal(1, "reset");
        resetn = 1;
        for (cycle = 1; cycle <= 19; cycle = cycle + 1) begin
            @(negedge clk);
            if (led !== ((cycle / 3) % 2)) $fatal(1, "period at %0d", cycle);
            if (led_each !== (cycle % 2)) $fatal(1, "period one");
        end
        resetn = 0;
        @(negedge clk);
        if (led !== 0 || led_each !== 0) $fatal(1, "mid-period reset");
        resetn = 1;
        repeat (2) @(negedge clk);
        if (led !== 0) $fatal(1, "counter not reset");
        @(negedge clk);
        if (led !== 1) $fatal(1, "restart");
        $display("HEARTBEAT_PASS");
        $finish;
    end
endmodule
