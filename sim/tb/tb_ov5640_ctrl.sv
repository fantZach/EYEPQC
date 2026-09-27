`timescale 1ns/1ps
module tb_ov5640_ctrl;
    reg clk=0;
    always #5 clk=~clk;
    reg resetn=1, start=0;
    reg [15:0] width=320, height=240, hts=2844, vts=1968;
    reg [5:0] quality=1;
    reg jpeg_mode=1;
    tri1 scl, sda;
    reg hold_scl=0, enabled=1, wrong_id=0, nack_once=0, corrupt_enable=0;
    reg [3:0] nack_mask=0;
    reg [15:0] corrupt_addr=16'h3809;
    assign scl=hold_scl ? 1'b0 : 1'bz;
    wire cam_resetn, cam_pwdn, busy, done, configured, failed, capture_resetn;
    wire [3:0] error;
    wire [15:0] chip_id, last_reg;
    ov5640_ctrl #(.CLK_HZ(3_200_000), .SCCB_HZ(100_000), .TIMEOUT_CYCLES(2400),
        .RESET_CYCLES(20), .POWERUP_CYCLES(64), .SETTLE_CYCLES(16), .MAX_RETRIES(2)) dut (
        .clk(clk), .resetn(resetn), .start(start), .width(width), .height(height), .hts(hts), .vts(vts),
        .quality(quality), .jpeg_mode(jpeg_mode), .scl(scl), .sda(sda),
        .cam_resetn(cam_resetn), .cam_pwdn(cam_pwdn), .busy(busy), .done(done), .configured(configured),
        .failed(failed), .capture_resetn(capture_resetn), .error(error), .chip_id(chip_id), .last_reg(last_reg)
    );
    ov5640_model sensor (.resetn(resetn), .enabled(enabled), .wrong_id(wrong_id),
        .nack_mask(nack_mask), .nack_once(nack_once), .corrupt_enable(corrupt_enable),
        .corrupt_addr(corrupt_addr), .scl(scl), .sda(sda));
    reg [7:0] golden_index;
    reg [15:0] golden_width=320, golden_height=240, golden_hts=2844, golden_vts=1968;
    reg [5:0] golden_quality=1;
    reg golden_jpeg=1;
    wire [15:0] golden_addr;
    wire [7:0] golden_data;
    wire golden_valid;
    ov5640_reg_table golden (.index(golden_index), .width(golden_width), .height(golden_height),
        .hts(golden_hts), .vts(golden_vts), .quality(golden_quality), .jpeg_mode(golden_jpeg),
        .reg_addr(golden_addr), .reg_data(golden_data), .valid(golden_valid));
    task reset;
        begin
            @(negedge clk); resetn=0; repeat(6) @(negedge clk); resetn=1;
            if (configured || capture_resetn || cam_resetn || !cam_pwdn) $fatal(1,"unsafe reset state");
        end
    endtask
    task launch;
        begin
            @(negedge clk); start=1; @(negedge clk); start=0;
            if (capture_resetn) $fatal(1,"capture must stop during reconfiguration");
        end
    endtask
    task finish(input [3:0] expected, input integer deadline);
        integer cycles;
        begin
            cycles=0;
            while (!done && cycles < deadline) begin
                @(negedge clk); cycles=cycles+1;
                if (busy && capture_resetn) $fatal(1,"capture enabled before configuration done");
            end
            if (!done || busy || error !== expected) $fatal(1,"ctrl error=%0d expected=%0d cycles=%0d reg=%h",error,expected,cycles,last_reg);
            if (expected == 0) begin
                if (!configured || failed || !capture_resetn || !cam_resetn || cam_pwdn || chip_id !== 16'h5640)
                    $fatal(1,"success status mismatch");
            end else if (configured || !failed || capture_resetn || cam_resetn)
                $fatal(1,"failure must hold camera/capture in reset");
            @(negedge clk); if (done) $fatal(1,"done must pulse");
        end
    endtask
    task check_writes;
        begin
            if (sensor.writes != 251 || sensor.read_nacks != 18) $fatal(1,"wrong init/readback count");
            for (integer i=0; i<251; i=i+1) begin
                golden_index=i; #1;
                if (sensor.write_addresses[i] !== golden_addr || sensor.write_values[i] !== golden_data)
                    $fatal(1,"ordered table mismatch at %0d",i);
            end
            golden_index=251; #1; if (golden_valid) $fatal(1,"table index out of bounds");
            if (sensor.write_times[1]-sensor.write_times[0] < 16*10) $fatal(1,"missing soft reset delay");
            if (sensor.memory[16'h3808] !== golden_width[15:8] || sensor.memory[16'h3809] !== golden_width[7:0] ||
                sensor.memory[16'h380a] !== golden_height[15:8] || sensor.memory[16'h380b] !== golden_height[7:0] ||
                sensor.memory[16'h4407] !== {2'b00,golden_quality} ||
                sensor.memory[16'h3821] !== (golden_jpeg ? 8'h20 : 8'h00) ||
                sensor.memory[16'h3002] !== (golden_jpeg ? 8'h00 : 8'h1c) ||
                sensor.memory[16'h3006] !== (golden_jpeg ? 8'hff : 8'hd7)) $fatal(1,"runtime format/size/quality mismatch");
        end
    endtask
    initial begin
        // 20 simulated reset/initialization cycles are NOT 20 physical cold boots.
        for (integer boot=0; boot<20; boot=boot+1) begin reset; launch; finish(0,400000); check_writes; end
        // Reconfigure, latch all knobs, ignore another start while busy.
        width=640; height=480; vts=2400; quality=12; jpeg_mode=0;
        golden_width=640; golden_height=480; golden_vts=2400; golden_quality=12; golden_jpeg=0;
        sensor.writes=0; sensor.read_nacks=0;
        launch; repeat(100) @(negedge clk);
        width=16; height=16; hts=32; vts=32; quality=63; jpeg_mode=1; start=1;
        @(negedge clk); start=0; finish(0,400000); check_writes;
        width=320; height=240; hts=2844; vts=1968; quality=1; jpeg_mode=1;
        wrong_id=1; reset; launch; finish(3,10000);
        if (sensor.writes != 0 || chip_id !== 16'h5540) $fatal(1,"must check ID before init");
        wrong_id=0; enabled=0; reset; launch; finish(1,10000);
        if (sensor.starts != 3 || sensor.writes != 0) $fatal(1,"NACK retries must be bounded");
        enabled=1; nack_mask=8; nack_once=1; reset; launch; finish(0,400000);
        if (sensor.writes != 251 || !sensor.nack_used) $fatal(1,"transient NACK retry failed");
        nack_once=0; reset; launch; finish(1,15000);
        if (sensor.writes != 0 || last_reg !== 16'h3008) $fatal(1,"table write retry exhaustion failed");
        nack_mask=0; corrupt_enable=1; reset; launch; finish(5,400000);
        if (last_reg !== corrupt_addr) $fatal(1,"wrong readback failure register");
        corrupt_enable=0; hold_scl=1; reset; launch; finish(2,10000); hold_scl=0;
        reset; width=319; launch; finish(4,100);
        if (sensor.starts != 0) $fatal(1,"invalid JPEG size touched bus");
        width=320; vts=240; launch; finish(4,100); vts=1968;
        launch; repeat(1000) @(negedge clk); reset;
        if (busy || scl !== 1 || sda !== 1) $fatal(1,"reset during init failed");
        launch; finish(0,400000);
        $display("OV5640_CTRL_PASS boots=20 writes=251 readbacks=16"); $finish;
    end
    initial begin #120000000; $fatal(1,"test watchdog"); end
endmodule
