// JPEG framing, not a decoder: skip length-bearing headers before scanning markers.
module jpeg_marker_check #(
    parameter integer MAX_FRAME_BYTES = 2 * 1024 * 1024
) (
    input wire clk, resetn,
    input wire [7:0] byte_in,
    input wire byte_valid, frame_boundary,
    output reg [7:0] byte_out,
    output reg out_valid, frame_start, frame_end, frame_error,
    output reg [31:0] frame_length,
    // bit0 no SOI, 1 no EOI, 2 unexpected VSYNC, 3 empty, 4 oversize, 5 bad marker.
    output reg [5:0] error_flags
);
    localparam [3:0] SEARCH=0, PREFIX=1, CODE=2, LENGTH_HI=3, LENGTH_LO=4,
                     PAYLOAD=5, SCAN=6, SCAN_CODE=7;
    reg [3:0] state;
    reg seek_ff, scan_segment, saw_scan;
    reg window_data, window_soi;
    reg [7:0] length_hi, pending_byte;
    reg [15:0] payload_left;
    reg [31:0] length;
    reg pending_valid, pending_end;
    wire [15:0] segment_length = {length_hi, byte_in};
    wire marker_code = state == CODE || state == SCAN_CODE;
    wire new_soi = byte_valid && byte_in == 8'hd8 &&
                   ((state == SEARCH && seek_ff) || marker_code);

    initial begin
        if (MAX_FRAME_BYTES < 4 || MAX_FRAME_BYTES > 32'h7fffffff)
            $fatal(1, "Invalid JPEG frame length limit");
    end

    task fail_frame(input [5:0] flags);
        begin
            frame_error <= 1; error_flags <= flags; frame_length <= length;
            state <= SEARCH; pending_valid <= 0; pending_end <= 0;
            seek_ff <= byte_valid && byte_in == 8'hff;
        end
    endtask

    always @(posedge clk or negedge resetn) begin
        if (!resetn) begin
            state <= SEARCH; seek_ff <= 0; scan_segment <= 0; saw_scan <= 0;
            window_data <= 0; window_soi <= 0; length_hi <= 0; payload_left <= 0;
            length <= 0; pending_byte <= 0; pending_valid <= 0; pending_end <= 0;
            byte_out <= 0; out_valid <= 0; frame_start <= 0; frame_end <= 0;
            frame_error <= 0; frame_length <= 0; error_flags <= 0;
        end else begin
            byte_out <= pending_byte; out_valid <= pending_valid;
            frame_start <= 0; frame_end <= pending_end;
            frame_error <= 0; pending_valid <= 0; pending_end <= 0;
            if (pending_end) frame_length <= length;
            if (byte_valid) window_data <= 1;

            if (frame_boundary) begin
                // Bytes already forwarded are provisional; downstream must discard on error.
                if (state != SEARCH) fail_frame(6'b000110);
                else if (!window_soi) begin
                    frame_error <= 1; frame_length <= 0;
                    error_flags <= window_data ? 6'b000001 : 6'b001000;
                end
                state <= SEARCH; seek_ff <= 0;
                window_data <= 0; window_soi <= 0;
            end else if (new_soi) begin
                if (state != SEARCH) begin
                    // Abort the old frame first, then begin the new one on this same cycle.
                    frame_error <= 1; error_flags <= 6'b100010; frame_length <= length;
                end
                byte_out <= 8'hff; out_valid <= 1; frame_start <= 1;
                pending_byte <= 8'hd8; pending_valid <= 1;
                state <= PREFIX; length <= 2; seek_ff <= 0;
                saw_scan <= 0; window_soi <= 1;
            end else if (byte_valid) begin
                if (state == SEARCH) seek_ff <= byte_in == 8'hff;
                else if (length == MAX_FRAME_BYTES) fail_frame(6'b010000);
                else begin
                    pending_byte <= byte_in; pending_valid <= 1; length <= length+1'b1;
                    case (state)
                        PREFIX: if (byte_in == 8'hff) state <= CODE;
                                else fail_frame(6'b100000);
                        CODE, SCAN_CODE: begin
                            if (byte_in == 8'hff) state <= state; // Marker fill bytes.
                            else if (state == SCAN_CODE &&
                                (byte_in == 0 || (byte_in >= 8'hd0 && byte_in <= 8'hd7) || byte_in == 1))
                                state <= SCAN; // Stuffed FF, restart or TEM.
                            else if (byte_in == 8'hd9) begin
                                if (!saw_scan) fail_frame(6'b101000);
                                else begin pending_end <= 1; state <= SEARCH; seek_ff <= 0; end
                            end else if (byte_in == 1) state <= PREFIX;
                            else if (byte_in == 0 || (byte_in >= 8'hd0 && byte_in <= 8'hd7))
                                fail_frame(6'b100000);
                            else begin scan_segment <= byte_in == 8'hda; state <= LENGTH_HI; end
                        end
                        LENGTH_HI: begin length_hi <= byte_in; state <= LENGTH_LO; end
                        LENGTH_LO: begin
                            if (segment_length < 2) fail_frame(6'b100000);
                            else if (segment_length == 2) begin
                                state <= scan_segment ? SCAN : PREFIX;
                                if (scan_segment) saw_scan <= 1;
                            end else begin payload_left <= segment_length-2; state <= PAYLOAD; end
                        end
                        PAYLOAD: if (payload_left == 1) begin
                            state <= scan_segment ? SCAN : PREFIX;
                            if (scan_segment) saw_scan <= 1;
                        end else payload_left <= payload_left-1'b1;
                        SCAN: if (byte_in == 8'hff) state <= SCAN_CODE;
                        default: fail_frame(6'b100000);
                    endcase
                end
            end
        end
    end
endmodule
