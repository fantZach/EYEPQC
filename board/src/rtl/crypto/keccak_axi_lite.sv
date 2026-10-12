// Isolated AXI4-Lite interface to a single Keccak-f[1600] state permutation.
// State words are little-endian 32-bit slices: word[2*n] is lane[n][31:0],
// word[2*n+1] is lane[n][63:32]. One AXI transaction may be outstanding.
module keccak_axi_lite #(
    parameter integer DEFAULT_WATCHDOG_CYCLES = 1024
) (
    input  wire         s_axi_aclk,
    input  wire         s_axi_aresetn,
    input  wire [11:0]  s_axi_awaddr,
    input  wire [2:0]   s_axi_awprot,
    input  wire         s_axi_awvalid,
    output wire         s_axi_awready,
    input  wire [31:0]  s_axi_wdata,
    input  wire [3:0]   s_axi_wstrb,
    input  wire         s_axi_wvalid,
    output wire         s_axi_wready,
    output reg  [1:0]   s_axi_bresp,
    output reg          s_axi_bvalid,
    input  wire         s_axi_bready,
    input  wire [11:0]  s_axi_araddr,
    input  wire [2:0]   s_axi_arprot,
    input  wire         s_axi_arvalid,
    output wire         s_axi_arready,
    output reg  [31:0]  s_axi_rdata,
    output reg  [1:0]   s_axi_rresp,
    output reg          s_axi_rvalid,
    input  wire         s_axi_rready
);
    localparam [11:0] ADDR_CTRL   = 12'h000;
    localparam [11:0] ADDR_STATUS = 12'h004;
    localparam [11:0] ADDR_WDOG   = 12'h008;
    localparam [11:0] ADDR_ID     = 12'h00c;
    localparam [11:0] ADDR_VERSION = 12'h010;
    localparam [11:0] ADDR_STATE  = 12'h100;
    localparam [11:0] ADDR_RESULT = 12'h200;
    localparam [1:0]  RESP_OKAY   = 2'b00;
    localparam [1:0]  RESP_SLVERR = 2'b10;

    reg aw_pending, w_pending;
    reg [11:0] awaddr_q;
    reg [31:0] wdata_q;
    reg [3:0] wstrb_q;
    reg [1599:0] state_q, result_q;
    reg [31:0] watchdog_limit_q, watchdog_count_q;
    reg core_start_q, core_clear_q, launch_pending_q;
    reg busy_q, done_q, error_q, timeout_q;
    wire core_busy, core_done;
    wire [1599:0] core_result;
    wire write_commit = aw_pending && w_pending && !s_axi_bvalid;
    integer i;

    assign s_axi_awready = !aw_pending && !s_axi_bvalid;
    assign s_axi_wready  = !w_pending && !s_axi_bvalid;
    assign s_axi_arready = !s_axi_rvalid;

    keccak_f1600 u_core (
        .clk(s_axi_aclk), .rst(!s_axi_aresetn), .clear(core_clear_q),
        .start(core_start_q), .state_i(state_q), .state_o(core_result),
        .busy(core_busy), .done(core_done)
    );

    // Byte-lane merging for the 50-word input-state window.
    task automatic write_state_word(input [6:0] word_index,
                                    input [31:0] value,
                                    input [3:0] strobes);
        integer b;
        begin
            for (b = 0; b < 4; b = b + 1)
                if (strobes[b]) state_q[word_index*32 + b*8 +: 8] <= value[b*8 +: 8];
        end
    endtask

    always @(posedge s_axi_aclk) begin : axi_registers
        reg [11:0] wr_addr;
        reg [31:0] wr_data;
        reg [3:0] wr_strb;
        reg [6:0] word_index;
        reg [1:0] write_response;
        reg write_error;
        reg [31:0] read_value;
        reg [1:0] read_response;
        reg [32:0] next_count;

        if (!s_axi_aresetn) begin
            aw_pending <= 1'b0; w_pending <= 1'b0;
            awaddr_q <= 0; wdata_q <= 0; wstrb_q <= 0;
            state_q <= 0; result_q <= 0;
            watchdog_limit_q <= DEFAULT_WATCHDOG_CYCLES;
            watchdog_count_q <= 0;
            core_start_q <= 0; core_clear_q <= 0; launch_pending_q <= 0;
            busy_q <= 0; done_q <= 0; error_q <= 0; timeout_q <= 0;
            s_axi_bresp <= RESP_OKAY; s_axi_bvalid <= 0;
            s_axi_rdata <= 0; s_axi_rresp <= RESP_OKAY; s_axi_rvalid <= 0;
        end else begin
            core_start_q <= 1'b0;
            core_clear_q <= 1'b0;

            if (s_axi_bvalid && s_axi_bready) s_axi_bvalid <= 1'b0;
            if (s_axi_rvalid && s_axi_rready) s_axi_rvalid <= 1'b0;

            // Clear the permutation's old internal state before launching its
            // next state. The loaded input-state register remains private here.
            if (launch_pending_q) begin
                core_start_q <= 1'b1;
                launch_pending_q <= 1'b0;
            end

            if (s_axi_awvalid && s_axi_awready) begin
                awaddr_q <= s_axi_awaddr;
                aw_pending <= 1'b1;
            end
            if (s_axi_wvalid && s_axi_wready) begin
                wdata_q <= s_axi_wdata;
                wstrb_q <= s_axi_wstrb;
                w_pending <= 1'b1;
            end

            if (write_commit) begin
                aw_pending <= 1'b0;
                w_pending <= 1'b0;
                s_axi_bvalid <= 1'b1;
                write_response = RESP_OKAY;
                write_error = 1'b0;
                wr_addr = awaddr_q;
                wr_data = wdata_q;
                wr_strb = wstrb_q;
                word_index = (wr_addr - ADDR_STATE) >> 2;

                if (wr_addr[1:0] != 0) begin
                    write_response = RESP_SLVERR;
                    write_error = 1'b1;
                end else if (wr_strb == 0) begin
                    // An empty byte strobe is an AXI no-op.
                end else if (wr_addr == ADDR_CTRL) begin
                    if (!wr_strb[0] || (wr_data & 32'hffff_fffc) != 0 || wr_data[1:0] == 2'b11) begin
                        write_response = RESP_SLVERR;
                        write_error = 1'b1;
                    end else if (wr_data[1]) begin
                        // Clear is accepted while busy and dominates all status.
                        core_clear_q <= 1'b1;
                        core_start_q <= 1'b0; launch_pending_q <= 1'b0;
                        state_q <= 0; result_q <= 0;
                        watchdog_count_q <= 0;
                        busy_q <= 0; done_q <= 0; error_q <= 0; timeout_q <= 0;
                    end else if (busy_q) begin
                        write_response = RESP_SLVERR;
                        write_error = 1'b1;
                    end else if (wr_data[0]) begin
                        result_q <= 0;
                        watchdog_count_q <= 0;
                        done_q <= 0; error_q <= 0; timeout_q <= 0;
                        busy_q <= 1'b1;
                        core_clear_q <= 1'b1;
                        launch_pending_q <= 1'b1;
                    end else begin
                        write_response = RESP_SLVERR;
                        write_error = 1'b1;
                    end
                end else if (wr_addr == ADDR_WDOG) begin
                    if (busy_q) begin
                        write_response = RESP_SLVERR;
                        write_error = 1'b1;
                    end else begin
                        for (i = 0; i < 4; i = i + 1)
                            if (wr_strb[i]) watchdog_limit_q[i*8 +: 8] <= wr_data[i*8 +: 8];
                    end
                end else if (wr_addr >= ADDR_STATE && wr_addr < ADDR_STATE + 12'd200) begin
                    if (busy_q) begin
                        write_response = RESP_SLVERR;
                        write_error = 1'b1;
                    end else write_state_word(word_index, wr_data, wr_strb);
                end else begin
                    // Status, ID, and result words are read-only; all other
                    // addresses are unmapped and receive SLVERR.
                    write_response = RESP_SLVERR;
                    write_error = 1'b1;
                end
                s_axi_bresp <= write_response;
                if (write_error) error_q <= 1'b1;
            end

            if (busy_q && !(write_commit && awaddr_q == ADDR_CTRL &&
                            wstrb_q[0] && wdata_q[31:2] == 0 && wdata_q[1:0] == 2'b10)) begin
                if (watchdog_limit_q != 0) begin
                    next_count = {1'b0, watchdog_count_q} + 1'b1;
                    watchdog_count_q <= next_count[31:0];
                    if (next_count >= {1'b0, watchdog_limit_q}) begin
                        core_clear_q <= 1'b1;
                        core_start_q <= 1'b0; launch_pending_q <= 1'b0;
                        state_q <= 0; result_q <= 0;
                        watchdog_count_q <= 0;
                        busy_q <= 0; done_q <= 0; timeout_q <= 1'b1; error_q <= 1'b1;
                    end
                end
                if (core_done && !(watchdog_limit_q != 0 &&
                                   ({1'b0, watchdog_count_q} + 1'b1) >= {1'b0, watchdog_limit_q})) begin
                    result_q <= core_result;
                    busy_q <= 0; done_q <= 1'b1;
                    watchdog_count_q <= 0;
                end
            end

            if (s_axi_arvalid && s_axi_arready) begin
                s_axi_rvalid <= 1'b1;
                read_value = 0;
                read_response = RESP_OKAY;
                word_index = (s_axi_araddr - ADDR_RESULT) >> 2;
                if (s_axi_araddr[1:0] != 0) read_response = RESP_SLVERR;
                else if (s_axi_araddr == ADDR_CTRL) read_value = 0;
                else if (s_axi_araddr == ADDR_STATUS)
                    read_value = {28'b0, timeout_q, error_q, done_q, busy_q};
                else if (s_axi_araddr == ADDR_WDOG) read_value = watchdog_limit_q;
                else if (s_axi_araddr == ADDR_ID) read_value = 32'h4b43_4831; // KCH1
                else if (s_axi_araddr == ADDR_VERSION) read_value = 32'h0001_0000;
                else if (s_axi_araddr >= ADDR_RESULT && s_axi_araddr < ADDR_RESULT + 12'd200) begin
                    if (busy_q || !done_q) read_response = RESP_SLVERR;
                    else read_value = result_q[word_index*32 +: 32];
                end else read_response = RESP_SLVERR;
                s_axi_rdata <= read_value;
                s_axi_rresp <= read_response;
                if (read_response != RESP_OKAY) error_q <= 1'b1;
            end
        end
    end
endmodule
