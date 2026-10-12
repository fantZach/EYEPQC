// OV5640 JPEG mode 3: HREF qualifies bytes, never marks the JPEG frame end.
module dvp_capture #(
    parameter integer MAX_FRAME_BYTES = 2 * 1024 * 1024,
    parameter HREF_ACTIVE = 1'b1,
    parameter VSYNC_ACTIVE = 1'b1
) (
    input wire pclk, capture_resetn,
    input wire cam_vsync, cam_href,
    input wire [7:0] cam_data,
    output wire [7:0] byte_out,
    output wire byte_valid, frame_start, frame_end, frame_error,
    output wire [31:0] frame_length,
    output wire [5:0] error_flags,
    output reg [31:0] frames_captured, frames_dropped,
    output reg [31:0] missing_soi, missing_eoi, unexpected_vsync,
    output reg [31:0] empty_frames, oversize_frames, marker_errors
);
    // M02 configured drives capture_resetn. Assertion is asynchronous even if PCLK stops.
    (* ASYNC_REG = "TRUE" *) reg [1:0] reset_sync;
    always @(posedge pclk or negedge capture_resetn) begin
        if (!capture_resetn) reset_sync <= 0;
        else reset_sync <= {reset_sync[0], 1'b1};
    end
    wire resetn = reset_sync[1];
    wire vsync_active = cam_vsync == VSYNC_ACTIVE;
    wire href_active = cam_href == HREF_ACTIVE;
    reg aligned, vsync_previous, sample_valid, sample_boundary;
    reg [7:0] sample_data;
    always @(posedge pclk or negedge resetn) begin
        if (!resetn) begin
            aligned <= 0; vsync_previous <= 0;
            sample_data <= 0; sample_valid <= 0; sample_boundary <= 0;
        end else begin
            // Ignore a partial physical frame after reset; start at the next VSYNC interval.
            if (vsync_active) aligned <= 1;
            vsync_previous <= vsync_active;
            sample_data <= cam_data;
            sample_valid <= aligned && !vsync_active && href_active;
            sample_boundary <= aligned && vsync_active && !vsync_previous;
        end
    end
    jpeg_marker_check #(.MAX_FRAME_BYTES(MAX_FRAME_BYTES)) markers (
        .clk(pclk), .resetn(resetn), .byte_in(sample_data), .byte_valid(sample_valid),
        .frame_boundary(sample_boundary), .byte_out(byte_out), .out_valid(byte_valid),
        .frame_start(frame_start), .frame_end(frame_end), .frame_error(frame_error),
        .frame_length(frame_length), .error_flags(error_flags)
    );
    // ponytail: PCLK-domain counters wrap at 2^32; CDC/atomic host readout belongs to M04.
    always @(posedge pclk or negedge resetn) begin
        if (!resetn) begin
            frames_captured <= 0; frames_dropped <= 0; missing_soi <= 0; missing_eoi <= 0;
            unexpected_vsync <= 0; empty_frames <= 0; oversize_frames <= 0; marker_errors <= 0;
        end else begin
            if (frame_end) frames_captured <= frames_captured+1'b1;
            if (frame_error) begin
                frames_dropped <= frames_dropped+1'b1;
                if (error_flags[0]) missing_soi <= missing_soi+1'b1;
                if (error_flags[1]) missing_eoi <= missing_eoi+1'b1;
                if (error_flags[2]) unexpected_vsync <= unexpected_vsync+1'b1;
                if (error_flags[3]) empty_frames <= empty_frames+1'b1;
                if (error_flags[4]) oversize_frames <= oversize_frames+1'b1;
                if (error_flags[5]) marker_errors <= marker_errors+1'b1;
            end
        end
    end
endmodule
