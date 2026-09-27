// M03 provisional bytes -> AMD CDC FIFOs -> committed whole frames -> AXIS.
module camera_axis_bridge #(
    parameter integer DATA_WIDTH = 32,
    parameter integer FIFO_DEPTH = 65536,
    parameter integer MAX_FRAME_BYTES = FIFO_DEPTH,
    parameter integer HIGH_WATER_BYTES = FIFO_DEPTH == 16 ? 11 : FIFO_DEPTH*3/4
) (
    input wire pclk, axis_clk, resetn,
    input wire [7:0] byte_in,
    input wire byte_valid, frame_start, frame_end, frame_error,
    output wire [DATA_WIDTH-1:0] m_axis_tdata,
    output wire [DATA_WIDTH/8-1:0] m_axis_tkeep,
    output wire m_axis_tvalid, m_axis_tlast, m_axis_tuser,
    input wire m_axis_tready,
    // All exported statistics are in axis_clk; queued/dropped/etc. form one atomic snapshot.
    output reg [31:0] frames_queued, frames_dropped, fifo_overflows, max_fifo_level,
    output reg overflow_latched,
    output reg [31:0] frames_sent,
    output wire fifo_high_water
);
    localparam integer COUNT_WIDTH = $clog2(FIFO_DEPTH)+1;
    initial begin
        if (FIFO_DEPTH < 16 || (FIFO_DEPTH & (FIFO_DEPTH-1)) != 0 || FIFO_DEPTH > 4194304)
            $fatal(1, "FIFO_DEPTH must be a power of two, 16..4194304");
        if (MAX_FRAME_BYTES < 1 || MAX_FRAME_BYTES > FIFO_DEPTH ||
            HIGH_WATER_BYTES < 7 || HIGH_WATER_BYTES > FIFO_DEPTH-5)
            $fatal(1, "Invalid frame limit/high water");
    end
    // XPM reset is synchronous to wr_clk; both clocks must run during reset/recovery.
    reg fifo_reset = 1;
    always @(posedge pclk) fifo_reset <= !resetn;
    (* ASYNC_REG = "TRUE" *) reg [1:0] axis_reset_sync;
    always @(posedge axis_clk or negedge resetn)
        if (!resetn) axis_reset_sync <= 0;
        else axis_reset_sync <= {axis_reset_sync[0], 1'b1};

    wire data_full, data_empty, data_wr_busy, data_rd_busy, data_high;
    wire desc_full, desc_empty, desc_wr_busy, desc_rd_busy;
    wire [COUNT_WIDTH-1:0] data_count;
    wire [4:0] desc_count;
    wire [7:0] data_out;
    wire [32:0] desc_out;
    reg data_push, desc_push;
    reg [32:0] descriptor;
    wire data_pop, desc_pop;
    wire write_ready = resetn && !fifo_reset && !data_wr_busy && !desc_wr_busy;
    wire read_ready = axis_reset_sync[1] && !data_rd_busy && !desc_rd_busy;

    // ponytail: bounded store-and-forward, not a JTAG snapshot. Raise this BRAM budget only
    // after measuring JPEG lengths; larger-than-on-chip frames need a DDR commit design.
    xpm_fifo_async #(
        .FIFO_MEMORY_TYPE("block"), .FIFO_WRITE_DEPTH(FIFO_DEPTH),
        .WRITE_DATA_WIDTH(8), .READ_DATA_WIDTH(8), .READ_MODE("fwft"), .FIFO_READ_LATENCY(0),
        .WR_DATA_COUNT_WIDTH(COUNT_WIDTH), .PROG_FULL_THRESH(HIGH_WATER_BYTES),
        .USE_ADV_FEATURES("0006"), .CDC_SYNC_STAGES(2), .SIM_ASSERT_CHK(1)
    ) data_fifo (
        .rst(fifo_reset), .wr_clk(pclk), .wr_en(data_push), .din(byte_in),
        .full(data_full), .empty(data_empty), .wr_data_count(data_count), .prog_full(data_high),
        .wr_rst_busy(data_wr_busy), .rd_rst_busy(data_rd_busy),
        .rd_clk(axis_clk), .rd_en(data_pop), .dout(data_out),
        .sleep(1'b0), .injectsbiterr(1'b0), .injectdbiterr(1'b0),
        .overflow(), .almost_full(), .wr_ack(), .prog_empty(), .rd_data_count(),
        .underflow(), .almost_empty(), .data_valid(), .sbiterr(), .dbiterr()
    );
    // Reserve two descriptor slots: an old-frame abort and a simultaneous new SOI are legal.
    xpm_fifo_async #(
        .FIFO_MEMORY_TYPE("distributed"), .FIFO_WRITE_DEPTH(16),
        .WRITE_DATA_WIDTH(33), .READ_DATA_WIDTH(33), .READ_MODE("fwft"), .FIFO_READ_LATENCY(0),
        .WR_DATA_COUNT_WIDTH(5), .USE_ADV_FEATURES("0004"), .SIM_ASSERT_CHK(1)
    ) commit_fifo (
        .rst(fifo_reset), .wr_clk(pclk), .wr_en(desc_push), .din(descriptor),
        .full(desc_full), .empty(desc_empty), .wr_data_count(desc_count),
        .wr_rst_busy(desc_wr_busy), .rd_rst_busy(desc_rd_busy),
        .rd_clk(axis_clk), .rd_en(desc_pop), .dout(desc_out),
        .sleep(1'b0), .injectsbiterr(1'b0), .injectdbiterr(1'b0),
        .prog_full(), .overflow(), .almost_full(), .wr_ack(), .prog_empty(), .rd_data_count(),
        .underflow(), .almost_empty(), .data_valid(), .sbiterr(), .dbiterr()
    );

    reg tracking, reserved, bad;
    reg next_tracking, next_reserved, next_bad;
    reg [31:0] stored, next_stored;
    reg [31:0] queued_p, dropped_p, overflows_p, max_level_p;
    reg overflow_p;
    reg commit_event, drop_event, overflow_event;
    always @* begin
        next_tracking = tracking; next_reserved = reserved; next_bad = bad; next_stored = stored;
        data_push = 0; desc_push = 0; descriptor = 0;
        commit_event = 0; drop_event = 0; overflow_event = 0;
        if (write_ready) begin
            // Discard old pending bytes on error before handling a new same-cycle SOI.
            if (frame_error || (frame_start && tracking)) begin
                if (tracking && reserved && stored != 0) begin
                    desc_push = 1; descriptor = {1'b0, stored};
                end
                if (tracking || !frame_start) drop_event = 1;
                next_tracking = 0; next_reserved = 0; next_stored = 0; next_bad = 0;
            end
            if (frame_start) begin
                next_tracking = 1; next_stored = 0;
                next_reserved = !desc_full && desc_count < 14;
                next_bad = !next_reserved;
            end
            if (byte_valid && next_tracking && (!frame_error || frame_start) && !next_bad) begin
                if (data_full || next_stored == MAX_FRAME_BYTES) begin
                    next_bad = 1;
                    // Size rejection is not a physical FIFO overflow.
                    overflow_event = data_full;
                end else begin
                    data_push = 1; next_stored = next_stored + 1'b1;
                end
            end
            if (frame_end && next_tracking && (!frame_error || frame_start)) begin
                if (next_reserved && next_stored != 0) begin
                    desc_push = 1;
                    descriptor = {!next_bad, next_stored};
                end
                commit_event = !next_bad && next_stored != 0;
                drop_event = drop_event || !commit_event;
                next_tracking = 0; next_reserved = 0; next_bad = 0; next_stored = 0;
            end
        end
    end
    always @(posedge pclk or negedge resetn) begin
        if (!resetn) begin
            tracking <= 0; reserved <= 0; bad <= 0; stored <= 0;
            queued_p <= 0; dropped_p <= 0; overflows_p <= 0; max_level_p <= 0; overflow_p <= 0;
        end else if (write_ready) begin
            tracking <= next_tracking; reserved <= next_reserved; bad <= next_bad; stored <= next_stored;
            if (commit_event) queued_p <= queued_p + 1'b1;
            if (drop_event) dropped_p <= dropped_p + 1'b1;
            if (overflow_event) begin overflows_p <= overflows_p + 1'b1; overflow_p <= 1; end
            if (data_count > max_level_p) max_level_p <= data_count;
        end
    end

    reg [31:0] remaining;
    reg good, first_byte;
    wire pack_ready;
    assign desc_pop = read_ready && remaining == 0 && !desc_empty;
    assign data_pop = read_ready && remaining != 0 && !data_empty && (!good || pack_ready);
    always @(posedge axis_clk or negedge resetn) begin
        if (!resetn) begin remaining <= 0; good <= 0; first_byte <= 0; frames_sent <= 0; end
        else if (read_ready) begin
            if (desc_pop) begin
                remaining <= desc_out[31:0]; good <= desc_out[32]; first_byte <= 1;
            end else if (data_pop) begin remaining <= remaining - 1'b1; first_byte <= 0; end
            if (m_axis_tvalid && m_axis_tready && m_axis_tlast) frames_sent <= frames_sent + 1'b1;
        end
    end
    axis_byte_packer #(.DATA_WIDTH(DATA_WIDTH)) packer (
        .clk(axis_clk), .resetn(read_ready), .s_data(data_out),
        .s_valid(read_ready && remaining != 0 && !data_empty && good), .s_ready(pack_ready),
        .s_last(remaining == 1), .s_first(first_byte),
        .m_axis_tdata(m_axis_tdata), .m_axis_tkeep(m_axis_tkeep),
        .m_axis_tvalid(m_axis_tvalid), .m_axis_tready(m_axis_tready),
        .m_axis_tlast(m_axis_tlast), .m_axis_tuser(m_axis_tuser)
    );

    // Snapshot handshake, not independent synchronizers on a binary bus or jumping peak count.
    // Complete outstanding handshakes even across user reset (XPM has no reset port).
    reg snapshot_send = 0;
    reg [128:0] snapshot = 0;
    wire snapshot_received, snapshot_valid;
    wire [128:0] snapshot_axis;
    always @(posedge pclk) begin
        if (snapshot_received) snapshot_send <= 0;
        else if (!snapshot_send) begin
            snapshot <= {queued_p, dropped_p, overflows_p, max_level_p, overflow_p};
            snapshot_send <= 1;
        end
    end
    xpm_cdc_handshake #(.WIDTH(129), .DEST_EXT_HSK(0), .INIT_SYNC_FF(1), .SIM_ASSERT_CHK(1)) stats_cdc (
        .src_clk(pclk), .src_in(snapshot), .src_send(snapshot_send), .src_rcv(snapshot_received),
        .dest_clk(axis_clk), .dest_out(snapshot_axis), .dest_req(snapshot_valid), .dest_ack(1'b0)
    );
    always @(posedge axis_clk or negedge resetn) begin
        if (!resetn) begin
            frames_queued <= 0; frames_dropped <= 0; fifo_overflows <= 0;
            max_fifo_level <= 0; overflow_latched <= 0;
        end else if (axis_reset_sync[1] && snapshot_valid)
            {frames_queued, frames_dropped, fifo_overflows, max_fifo_level, overflow_latched} <= snapshot_axis;
    end
    xpm_cdc_single #(.SRC_INPUT_REG(0), .DEST_SYNC_FF(2)) high_water_cdc (
        .src_clk(pclk), .src_in(data_high), .dest_clk(axis_clk), .dest_out(fifo_high_water)
    );
endmodule
