`timescale 1ns/1ps
module tb_dvp_capture;
    parameter integer MAX_FRAME_BYTES=4096;
    reg pclk=0, run_clock=1, resetn=1, vsync=0, href=0;
    reg [7:0] data=0;
    integer clock_ticks=0;
    always begin
        #(4+clock_ticks%4);
        if (run_clock) pclk=~pclk; else pclk=0;
        clock_ticks=clock_ticks+1;
    end
    wire [7:0] byte_out, inverted_byte;
    wire valid, start_frame, end_frame, error_frame;
    wire inverted_valid, inverted_start, inverted_end, inverted_error;
    wire [31:0] length, inverted_length;
    wire [5:0] flags, inverted_flags;
    wire [31:0] captured, dropped, no_soi, no_eoi, unexpected, empty, oversize, bad_marker;
    dvp_capture #(.MAX_FRAME_BYTES(MAX_FRAME_BYTES)) dut (
        .pclk(pclk), .capture_resetn(resetn), .cam_vsync(vsync), .cam_href(href), .cam_data(data),
        .byte_out(byte_out), .byte_valid(valid), .frame_start(start_frame), .frame_end(end_frame),
        .frame_error(error_frame), .frame_length(length), .error_flags(flags),
        .frames_captured(captured), .frames_dropped(dropped), .missing_soi(no_soi),
        .missing_eoi(no_eoi), .unexpected_vsync(unexpected), .empty_frames(empty),
        .oversize_frames(oversize), .marker_errors(bad_marker)
    );
    // Independently drive the opposite physical polarities throughout the same scenarios.
    dvp_capture #(.MAX_FRAME_BYTES(MAX_FRAME_BYTES), .HREF_ACTIVE(0), .VSYNC_ACTIVE(0)) inverted (
        .pclk(pclk), .capture_resetn(resetn), .cam_vsync(!vsync), .cam_href(!href), .cam_data(data),
        .byte_out(inverted_byte), .byte_valid(inverted_valid), .frame_start(inverted_start),
        .frame_end(inverted_end), .frame_error(inverted_error), .frame_length(inverted_length),
        .error_flags(inverted_flags), .frames_captured(), .frames_dropped(), .missing_soi(),
        .missing_eoi(), .unexpected_vsync(), .empty_frames(), .oversize_frames(), .marker_errors()
    );
    reg [7:0] jpeg [0:2097151];
    string jpeg_path;
    integer jpeg_length, input_length, frames=1000, faults=1, i, j;
    integer seen_ends=0, seen_errors=0, position=0, last_length=0;
    reg open_frame=0, check_stream=0, check_this_frame=0;
    reg [5:0] last_flags=0;
    always @(posedge pclk) begin
        #1;
        if (resetn) begin
            if ({valid,start_frame,end_frame,error_frame,length,flags} !==
                {inverted_valid,inverted_start,inverted_end,inverted_error,inverted_length,inverted_flags} ||
                (valid && byte_out !== inverted_byte)) $fatal(1,"polarity calibration mismatch");
            if ((start_frame || end_frame) && !valid) $fatal(1,"marker without valid byte");
            if (error_frame) begin
                seen_errors=seen_errors+1; last_flags=flags; open_frame=0; position=0;
                if (!flags) $fatal(1,"unclassified frame error");
            end
            if (start_frame) begin
                if (open_frame || byte_out !== 8'hff) $fatal(1,"SOI framing mismatch");
                open_frame=1; position=0;
                check_this_frame=check_stream;
            end
            if (valid && (!error_frame || start_frame)) begin
                if (!open_frame) $fatal(1,"output byte outside a JPEG frame");
                if (check_this_frame && (position>=jpeg_length || byte_out !== jpeg[position]))
                    $fatal(1,"byte mismatch frame=%0d offset=%0d got=%h expected=%h",seen_ends,position,byte_out,jpeg[position]);
                position=position+1;
            end
            if (end_frame) begin
                if (error_frame || byte_out !== 8'hd9 || length !== position)
                    $fatal(1,"EOI length/byte mismatch length=%0d bytes=%0d",length,position);
                if (check_this_frame && position!=jpeg_length) $fatal(1,"truncated/oversized JPEG output");
                seen_ends=seen_ends+1; last_length=length; open_frame=0; position=0;
            end
        end
    end
    task tick(input reg v, h, input reg [7:0] d);
        begin @(negedge pclk); vsync=v; href=h; data=d; @(posedge pclk); #2; end
    endtask
    task idle(input integer cycles);
        integer k;
        begin for(k=0;k<cycles;k=k+1) tick(vsync,0,8'hd9); end
    endtask
    task send(input [7:0] value); begin tick(0,1,value); end endtask
    task boundary;
        begin tick(1,0,0); idle(4); tick(0,0,0); idle(4); end
    endtask
    task replay;
        integer k;
        begin
            check_stream=1;
            for(k=0;k<input_length;k=k+1) begin
                send(jpeg[k]);
                // Includes a gap between SOI bytes and many header/entropy bytes.
                if (k%73==0 || k%127==0) idle(1+k%3);
            end
            idle(5); check_stream=0;
        end
    endtask
    task expect_error(input integer before_errors, input [5:0] expected);
        begin
            idle(5);
            if (seen_errors!=before_errors+1 || last_flags!==expected)
                $fatal(1,"error classification got=%h count=%0d expected=%h before=%0d",last_flags,seen_errors,expected,before_errors);
        end
    endtask
    task reset_capture;
        begin
            #1 resetn=0; #1;
            if (valid || start_frame || end_frame || error_frame || captured || dropped)
                $fatal(1,"reset did not immediately suppress output/counters");
            seen_ends=0; seen_errors=0; open_frame=0; position=0;
            idle(4); resetn=1; idle(5);
        end
    endtask
    task scan_header;
        begin send(8'hff); send(8'hd8); send(8'hff); send(8'hda); send(0); send(2); end
    endtask
    initial begin
        if (!$value$plusargs("JPEG=%s",jpeg_path) || !$value$plusargs("JPEG_LENGTH=%d",jpeg_length))
            $fatal(1,"JPEG fixture required");
        i=$value$plusargs("FRAMES=%d",frames); i=$value$plusargs("FAULTS=%d",faults);
        input_length=jpeg_length; i=$value$plusargs("INPUT_LENGTH=%d",input_length);
        if (jpeg_length<4 || jpeg_length>MAX_FRAME_BYTES) $fatal(1,"bad test fixture length");
        if (input_length<jpeg_length || input_length>2097152) $fatal(1,"bad input length");
        $readmemh(jpeg_path,jpeg,0,input_length-1);
        reset_capture();
        // Releasing capture mid-frame must ignore the partial input until VSYNC alignment.
        replay();
        if (seen_ends || seen_errors) $fatal(1,"accepted an unaligned physical frame");
        boundary();
        for(j=0;j<frames;j=j+1) begin
            if (j==0) begin send(8'h11); send(8'hff); send(0); end // Noise before SOI.
            replay();
            send(8'hff); send(0); send(8'hd9); // Sensor padding after EOI is not part of the JPEG.
            boundary();
        end
        if (seen_ends!=frames || seen_errors || captured!=frames || dropped)
            $fatal(1,"continuous frame/counter mismatch captured=%0d errors=%0d",captured,seen_errors);
        $display("DVP_REPLAY_PASS frames=%0d bytes=%0d",frames,jpeg_length);
        // VSYNC immediately after the last byte must not cancel the pending EOI output.
        check_stream=1;
        for(j=0;j<input_length;j=j+1) send(jpeg[j]);
        boundary(); check_stream=0;
        if (captured!=frames+1 || dropped) $fatal(1,"tight EOI/VSYNC boundary failed");
        if (faults) begin
            i=seen_errors; send(8'h11); send(8'hff); send(0); send(8'hd9);
            boundary(); expect_error(i,6'b000001); replay(); boundary();
            i=seen_errors; boundary(); expect_error(i,6'b001000); replay(); boundary();
            i=seen_errors;
            for(j=0;j<jpeg_length-2;j=j+1) send(jpeg[j]);
            boundary(); expect_error(i,6'b000110); replay(); boundary();
            i=seen_errors;
            for(j=0;j<60;j=j+1) send(jpeg[j]);
            boundary(); expect_error(i,6'b000110); replay(); boundary();
            i=seen_errors; send(8'hff); send(8'hd8); send(8'h33);
            boundary(); expect_error(i,6'b100000); replay(); boundary();
            i=seen_errors; send(8'hff); send(8'hd8); send(8'hff); send(8'hd9);
            boundary(); expect_error(i,6'b101000); replay(); boundary();
            for(j=0;j<2;j=j+1) begin
                i=seen_errors; send(8'hff); send(8'hd8); send(8'hff); send(8'he1); send(0); send(j);
                boundary(); expect_error(i,6'b100000); replay(); boundary();
            end
            // Structurally framed test streams, not JPEG decode test vectors.
            i=seen_errors; scan_header(); send(8'hff); send(0); send(8'hd8);
            send(8'hff); send(0); send(8'hd9); send(8'hff); send(8'hd0);
            send(8'hff); send(8'hff); send(8'hd7); send(8'hff); send(8'hd9);
            idle(5);
            if (seen_errors!=i || last_length!=19) $fatal(1,"stuffed/restart/fill marker handling");
            boundary();
            i=seen_errors; scan_header(); send(8'h11); idle(5);
            replay(); expect_error(i,6'b100010); boundary();
            scan_header();
            for(j=0;j<MAX_FRAME_BYTES-8;j=j+1) send(1);
            send(8'hff); send(8'hd9); idle(5);
            if (last_length!=MAX_FRAME_BYTES) $fatal(1,"exact maximum rejected");
            boundary();
            i=seen_errors; scan_header();
            for(j=0;j<MAX_FRAME_BYTES-7;j=j+1) send(1);
            send(8'hff); send(8'hd9); expect_error(i,6'b010000);
            replay(); boundary(); // Recovery on next SOI, even without another VSYNC.
            if (no_soi!=1 || no_eoi!=3 || unexpected!=2 || empty!=2 || oversize!=1 || bad_marker!=5 ||
                captured!=seen_ends || dropped!=seen_errors) $fatal(1,"error counters mismatch");
            // Reset a partial frame while PCLK has stopped, then require alignment again.
            scan_header(); send(8'h11); idle(3);
            @(negedge pclk); run_clock=0; #20; resetn=0; #2;
            if (valid || start_frame || end_frame || error_frame || captured || dropped)
                $fatal(1,"stopped-PCLK reset failed");
            seen_ends=0; seen_errors=0; open_frame=0; position=0;
            resetn=1; #20;
            if (valid || start_frame || end_frame || error_frame) $fatal(1,"released reset without clock");
            run_clock=1; idle(5); replay();
            if (seen_ends || seen_errors) $fatal(1,"partial frame after reset accepted");
            boundary(); replay(); boundary();
            if (captured!=1 || dropped) $fatal(1,"reset recovery failed");
            $display("DVP_FAULT_PASS counters polarity stopped_clock_reset recovery");
        end
        $finish;
    end
    initial begin #1000000000; $fatal(1,"test watchdog"); end
endmodule
