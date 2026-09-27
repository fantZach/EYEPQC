`timescale 1ns/1ps
module tb_camera_axis_bridge;
    parameter integer DATA_WIDTH = 32;
    parameter integer FIFO_DEPTH = 1024;
    localparam integer LANES = DATA_WIDTH/8;
    reg pclk=0, axis_clk=0, resetn=0;
    integer p_half=5, a_half=3;
    always begin #(p_half + $urandom_range(0,2)); pclk = !pclk; end
    initial begin #2; forever begin #(a_half + $urandom_range(0,2)); axis_clk = !axis_clk; end end
    reg [7:0] byte_in=0;
    reg valid=0, first=0, last=0, error=0;
    reg dvp_mode=0, vsync=0, href=0;
    reg [7:0] cam_data=0;
    wire [7:0] jpeg_byte;
    wire jpeg_valid, jpeg_first, jpeg_last, jpeg_error;
    wire [31:0] jpeg_length;
    dvp_capture #(.MAX_FRAME_BYTES(2048)) capture (
        .pclk(pclk), .capture_resetn(resetn), .cam_vsync(vsync), .cam_href(href), .cam_data(cam_data),
        .byte_out(jpeg_byte), .byte_valid(jpeg_valid), .frame_start(jpeg_first),
        .frame_end(jpeg_last), .frame_error(jpeg_error), .frame_length(jpeg_length)
    );
    wire [DATA_WIDTH-1:0] tdata;
    wire [LANES-1:0] tkeep;
    wire tvalid, tlast, tuser;
    reg tready=0;
    integer ready_mode=2;
    always @(negedge axis_clk)
        tready = ready_mode == 1 || (ready_mode == 2 && $urandom_range(0,3) != 0);
    wire [31:0] queued, dropped, overflows, peak, sent;
    wire overflow_latched, high_water;
    camera_axis_bridge #(.DATA_WIDTH(DATA_WIDTH), .FIFO_DEPTH(FIFO_DEPTH)) dut (
        .pclk(pclk), .axis_clk(axis_clk), .resetn(resetn),
        .byte_in(dvp_mode ? jpeg_byte : byte_in), .byte_valid(dvp_mode ? jpeg_valid : valid),
        .frame_start(dvp_mode ? jpeg_first : first), .frame_end(dvp_mode ? jpeg_last : last),
        .frame_error(dvp_mode ? jpeg_error : error),
        .m_axis_tdata(tdata), .m_axis_tkeep(tkeep), .m_axis_tvalid(tvalid),
        .m_axis_tlast(tlast), .m_axis_tuser(tuser), .m_axis_tready(tready),
        .frames_queued(queued), .frames_dropped(dropped), .fifo_overflows(overflows),
        .max_fifo_level(peak), .overflow_latched(overflow_latched), .frames_sent(sent),
        .fifo_high_water(high_water)
    );
    reg [7:0] expected [0:1048575];
    reg expected_last [0:1048575];
    reg expected_first [0:1048575];
    integer total=0, checked=0, expected_frames=0, checked_frames=0;
    integer stalls=0, high_seen=0;
    reg stalled=0;
    reg [DATA_WIDTH+LANES+2:0] held;
    integer lane, used;
    always @(posedge pclk) begin
        if(dut.data_push && (dut.data_full || dut.data_wr_busy || dut.fifo_reset))
            $fatal(1,"Illegal native data FIFO write");
        if(dut.desc_push && (dut.desc_full || dut.desc_wr_busy || dut.fifo_reset))
            $fatal(1,"Lost commit descriptor");
    end
    always @(posedge axis_clk) begin
        if (!resetn) stalled = 0;
        else if (dut.read_ready) begin
            if (high_water) high_seen = high_seen + 1;
            if (stalled && {tdata,tkeep,tlast,tuser,tvalid} !== held)
                $fatal(1, "AXIS changed while stalled");
            stalled = tvalid && !tready;
            held = {tdata,tkeep,tlast,tuser,tvalid};
            if (stalled) stalls = stalls + 1;
            if (tvalid && tready) begin
                if (checked >= total || tuser !== expected_first[checked])
                    $fatal(1, "Unexpected beat/first flag at %0d/%0d", checked,total);
                used=0;
                for (lane=0; lane<LANES; lane=lane+1) begin
                    if (tkeep[lane]) begin
                        if (used != lane || checked >= total || tdata[8*lane +: 8] !== expected[checked])
                            $fatal(1, "Byte/KEEP mismatch at %0d lane %0d",checked,lane);
                        if (expected_last[checked] && (tkeep >> (lane+1)) != 0)
                            $fatal(1, "Frame boundary inside a beat");
                        checked=checked+1; used=used+1;
                    end else if (tdata[8*lane +: 8] !== 0) $fatal(1, "Tail padding not zero");
                end
                if (used==0 || tlast !== expected_last[checked-1] || (!tlast && used!=LANES))
                    $fatal(1, "Bad LAST/KEEP");
                if (tlast) begin checked_frames=checked_frames+1; end
            end
        end
    end
    function automatic [7:0] pattern(input integer index, seed);
        pattern = (index*29 + seed*17) & 255;
    endfunction
    task automatic expect_frame(input integer length, seed);
        integer i;
        begin
            for (i=0;i<length;i=i+1) begin
                expected[total]=pattern(i,seed); expected_first[total]=(i==0);
                expected_last[total]=(i==length-1); total=total+1;
            end
            expected_frames=expected_frames+1;
        end
    endtask
    task automatic tick(input [7:0] data, input v, f, l, e);
        begin
            @(negedge pclk); byte_in=data; valid=v; first=f; last=l; error=e;
            @(posedge pclk); #0.1;
        end
    endtask
    task automatic idle(input integer cycles);
        integer i;
        begin for(i=0;i<cycles;i=i+1) tick(0,0,0,0,0); end
    endtask
    task automatic send_frame(input integer length, seed);
        integer i;
        begin
            for(i=0;i<length;i=i+1) begin
                if (i!=0 && $urandom_range(0,7)==0) idle(1);
                tick(pattern(i,seed),1,i==0,i==length-1,0);
            end
            idle(1);
        end
    endtask
    task automatic drain;
        integer timeout;
        begin
            timeout=0;
            while(checked!=total || !dut.data_empty || !dut.desc_empty || dut.remaining!=0 || tvalid) begin
                @(posedge axis_clk); #0.2; timeout=timeout+1;
                if(timeout>FIFO_DEPTH*4+40000) $fatal(1,"Drain timeout checked=%0d/%0d",checked,total);
            end
            idle(100);
            if(checked_frames != expected_frames || sent != expected_frames)
                $fatal(1,"Frame counts differ");
        end
    endtask
    task automatic reset_bridge;
        begin
            @(negedge pclk); resetn=0; valid=0; first=0; last=0; error=0; href=0; vsync=0;
            total=0; checked=0; expected_frames=0; checked_frames=0;
            repeat(20) @(posedge pclk);
            @(negedge pclk); resetn=1;
            idle(100);
            if(queued!==0 || dropped!==0 || overflows!==0 || peak!==0 || sent!==0 || overflow_latched!==0)
                $fatal(1,"Statistics did not recover across reset");
        end
    endtask
    reg [7:0] jpeg [0:684];
    integer i,j,old_queued,old_drop,old_overflow, accepted;
    initial begin
        $readmemh("jpeg.mem",jpeg);
        reset_bridge;
        // Every possible 32/64-bit tail including a one-byte frame; also continuous random clocks.
        for(i=1;i<=17;i=i+1) begin expect_frame(i,i); send_frame(i,i); drain; end
        for(j=0;j<200;j=j+1) begin
            p_half=2+j%10; a_half=2+(j*3)%9;
            i=1+$urandom_range(0,250);
            expect_frame(i,j+50); send_frame(i,j+50); drain;
        end
        // Exact storage limit is legal; limit+1 is discarded with no emitted prefix.
        expect_frame(FIFO_DEPTH,71); send_frame(FIFO_DEPTH,71); drain;
        old_drop=dropped; send_frame(FIFO_DEPTH+1,72); drain;
        if(dropped!=old_drop+1) $fatal(1,"Size rejection missing");
        // M03 nested SOI: abort the old frame and accept the new FF in that same cycle.
        for(i=0;i<13;i=i+1) tick(8'h90+i,1,i==0,0,0);
        expect_frame(17,75); tick(pattern(0,75),1,1,0,1);
        for(i=1;i<17;i=i+1) tick(pattern(i,75),1,0,i==16,0);
        idle(1); drain;
        if(dropped!=old_drop+2) $fatal(1,"Nested SOI abort missing");
        // Error after queued bytes, then a frame-less parser error: both increment once.
        send_frame_error: begin
            for(i=0;i<20;i=i+1) tick(i,1,i==0,0,0);
            tick(8'hee,1,0,0,1); idle(1); tick(0,0,0,0,1); idle(1); drain;
        end
        if(dropped!=old_drop+4) $fatal(1,"Error accounting missing");
        // Hold the AXIS consumer. A complete old frame stays intact; the new overflowing frame vanishes.
        ready_mode=0; idle(10); old_drop=dropped; old_overflow=overflows;
        expect_frame(FIFO_DEPTH*7/8,81); send_frame(FIFO_DEPTH*7/8,81);
        send_frame(FIFO_DEPTH*7/8,82); idle(100);
        if(dropped!=old_drop+1 || overflows!=old_overflow+1 || !overflow_latched || high_seen==0 ||
            peak<FIFO_DEPTH*3/4 || peak>FIFO_DEPTH+2)
            $fatal(1,"FIFO overflow/high-water accounting missing");
        ready_mode=1; drain;
        expect_frame(17,83); send_frame(17,83); drain;
        // Descriptor saturation must not leak uncommitted bytes or deadlock.
        ready_mode=0; idle(10); old_drop=dropped; accepted=0;
        for(j=0;j<40;j=j+1) begin
            old_queued=dut.queued_p; send_frame(4,100+j);
            if(dut.queued_p!=old_queued) begin expect_frame(4,100+j); accepted=accepted+1; end
        end
        idle(100);
        if(accepted>=40 || dropped!=old_drop+40-accepted) $fatal(1,"Descriptor capacity guard failed");
        ready_mode=2; drain;
        expect_frame(9,151); send_frame(9,151); drain;
        // Reset in a held output beat and an unfinished source frame; no stale data after reset.
        ready_mode=0; idle(10); send_frame(16,161);
        for(i=0;i<20;i=i+1) tick(i,1,i==0,0,0);
        reset_bridge; ready_mode=2;
        expect_frame(7,162); send_frame(7,162); drain;
        // Actual JPEG -> DVP pins -> M03 -> two native async FIFOs -> AXIS scoreboard.
        dvp_mode=1; p_half=3; a_half=2;
        for(j=0;j<1000;j=j+1) begin
            for(i=0;i<685;i=i+1) begin
                expected[total]=jpeg[i]; expected_first[total]=(i==0);
                expected_last[total]=(i==684); total=total+1;
            end
            expected_frames=expected_frames+1;
            @(negedge pclk); vsync=1; href=0;
            repeat(4) @(negedge pclk);
            vsync=0;
            for(i=0;i<685;i=i+1) begin
                @(negedge pclk); href=1; cam_data=jpeg[i];
                if(i%37==0) begin @(negedge pclk); href=0; @(negedge pclk); end
            end
            @(negedge pclk); href=0;
            repeat(6) @(negedge pclk);
            if(j%25==24) drain; // Bursts of 25 real frames, not one isolated FIFO transaction.
        end
        // Truncated JPEG from actual DVP: no prefix may escape before the next VSYNC abort.
        old_drop=dropped;
        @(negedge pclk); vsync=1; href=0;
        repeat(4) @(negedge pclk);
        vsync=0;
        for(i=0;i<100;i=i+1) begin @(negedge pclk); href=1; cam_data=jpeg[i]; end
        @(negedge pclk); href=0; vsync=1;
        idle(10); drain;
        if(dropped!=old_drop+1) $fatal(1,"Truncated DVP frame not discarded");
        dvp_mode=0; expect_frame(11,170); send_frame(11,170); drain;
        if(stalls==0 || queued!=expected_frames) $fatal(1,"Backpressure/statistics coverage missing");
        $display("CAMERA_AXIS_PASS width=%0d depth=%0d jpeg_frames=1000 tails=1..17 stalls=%0d peak=%0d",DATA_WIDTH,FIFO_DEPTH,stalls,peak);
        $finish;
    end
    initial begin #100000000; $fatal(1,"Global timeout"); end
endmodule

module tb_camera_axis_bridge32;
    tb_camera_axis_bridge #(.DATA_WIDTH(32)) test();
endmodule
module tb_camera_axis_bridge64;
    tb_camera_axis_bridge #(.DATA_WIDTH(64)) test();
endmodule
module tb_camera_axis_bridge_64k;
    tb_camera_axis_bridge #(.DATA_WIDTH(32), .FIFO_DEPTH(65536)) test();
endmodule
