// One outstanding AXI4-Lite transaction, independent AW/W, AES-128 Encrypt only.
module aes_axi_lite (
    (* X_INTERFACE_PARAMETER = "ASSOCIATED_BUSIF s_axi, ASSOCIATED_RESET s_axi_aresetn" *)
    (* X_INTERFACE_INFO = "xilinx.com:signal:clock:1.0 s_axi_aclk CLK" *)
    input wire s_axi_aclk,
    (* X_INTERFACE_PARAMETER = "POLARITY ACTIVE_LOW" *)
    (* X_INTERFACE_INFO = "xilinx.com:signal:reset:1.0 s_axi_aresetn RST" *)
    input wire s_axi_aresetn,
    input wire [11:0] s_axi_awaddr,
    input wire [2:0] s_axi_awprot,
    input wire s_axi_awvalid,
    output wire s_axi_awready,
    input wire [31:0] s_axi_wdata,
    input wire [3:0] s_axi_wstrb,
    input wire s_axi_wvalid,
    output wire s_axi_wready,
    output reg [1:0] s_axi_bresp,
    output reg s_axi_bvalid,
    input wire s_axi_bready,
    input wire [11:0] s_axi_araddr,
    input wire [2:0] s_axi_arprot,
    input wire s_axi_arvalid,
    output wire s_axi_arready,
    output reg [31:0] s_axi_rdata,
    output reg [1:0] s_axi_rresp,
    output reg s_axi_rvalid,
    input wire s_axi_rready
);
    reg aw_pending, w_pending;
    reg [11:0] address;
    reg [31:0] data;
    reg [3:0] strobes;
    reg [127:0] key, block;
    reg init, next_block, clear_core, busy, seen_busy, initializing, key_ready, valid;
    wire core_ready, core_valid;
    wire [127:0] result;
    aes_core core(.clk(s_axi_aclk), .reset_n(s_axi_aresetn && !clear_core),
                  .encdec(1'b1), .keylen(1'b0), .key({key, 128'b0}),
                  .init(init), .next(next_block), .ready(core_ready),
                  .block(block), .result(result), .result_valid(core_valid));
    assign s_axi_awready = !aw_pending && !s_axi_bvalid;
    assign s_axi_wready = !w_pending && !s_axi_bvalid;
    assign s_axi_arready = !s_axi_rvalid;
    integer i;
    always @(posedge s_axi_aclk) begin
        if (!s_axi_aresetn) begin
            aw_pending <= 0; w_pending <= 0;
            address <= 0; data <= 0; strobes <= 0;
            key <= 0; block <= 0;
            init <= 0; next_block <= 0; clear_core <= 0;
            busy <= 0; seen_busy <= 0; initializing <= 0; key_ready <= 0; valid <= 0;
            s_axi_bresp <= 0; s_axi_bvalid <= 0;
            s_axi_rdata <= 0; s_axi_rresp <= 0; s_axi_rvalid <= 0;
        end else begin
            init <= 0; next_block <= 0; clear_core <= 0;
            if (busy && !core_ready) seen_busy <= 1;
            if (busy && seen_busy && core_ready) begin
                busy <= 0;
                if (initializing) key_ready <= 1;
                else valid <= core_valid;
            end
            if (s_axi_bvalid && s_axi_bready) s_axi_bvalid <= 0;
            if (s_axi_rvalid && s_axi_rready) s_axi_rvalid <= 0;
            if (s_axi_awvalid && s_axi_awready) begin
                address <= s_axi_awaddr; aw_pending <= 1;
            end
            if (s_axi_wvalid && s_axi_wready) begin
                data <= s_axi_wdata; strobes <= s_axi_wstrb; w_pending <= 1;
            end
            if (aw_pending && w_pending && !s_axi_bvalid) begin
                aw_pending <= 0; w_pending <= 0;
                s_axi_bvalid <= 1; s_axi_bresp <= 0;
                if (address[1:0] != 0) s_axi_bresp <= 2;
                else if (strobes == 0) begin end // AXI no-op write.
                else if (address == 0 && strobes[0] && data == 4) begin
                    key <= 0; block <= 0; clear_core <= 1;
                    busy <= 0; seen_busy <= 0; key_ready <= 0; valid <= 0;
                end else if (busy) s_axi_bresp <= 2;
                else if (address == 0) begin
                    if (strobes[0] && (data == 1 || (data == 2 && key_ready))) begin
                        init <= (data == 1); next_block <= (data == 2);
                        busy <= 1; seen_busy <= 0; valid <= 0;
                        initializing <= (data == 1);
                        if (data == 1) key_ready <= 0;
                    end else s_axi_bresp <= 2;
                end else if (address >= 'h10 && address <= 'h1c) begin
                    for (i = 0; i < 4; i = i + 1)
                        if (strobes[i]) key[127 - (address-'h10)*8 - 31 + i*8 +: 8] <= data[i*8 +: 8];
                    key_ready <= 0; valid <= 0;
                end else if (address >= 'h20 && address <= 'h2c) begin
                    for (i = 0; i < 4; i = i + 1)
                        if (strobes[i]) block[127 - (address-'h20)*8 - 31 + i*8 +: 8] <= data[i*8 +: 8];
                    valid <= 0;
                end else s_axi_bresp <= 2;
            end
            if (s_axi_arvalid && s_axi_arready) begin
                s_axi_rvalid <= 1; s_axi_rresp <= 0; s_axi_rdata <= 0;
                if (s_axi_araddr[1:0] != 0) s_axi_rresp <= 2;
                else case (s_axi_araddr)
                    'h00: s_axi_rdata <= 0;
                    'h04: s_axi_rdata <= {29'b0, valid, key_ready, busy};
                    'h08: s_axi_rdata <= 32'h41455331; // AES1
                    'h30, 'h34, 'h38, 'h3c:
                        s_axi_rdata <= valid ? result[127 - (s_axi_araddr-'h30)*8 -: 32] : 0;
                    default: s_axi_rresp <= 2; // Key/input are write-only.
                endcase
            end
        end
    end
endmodule
