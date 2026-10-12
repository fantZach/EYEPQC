// Single-outstanding AXI4-Lite control bank; secrets are write-only.
module aes_gcm_regs (
    input wire clk, resetn,
    input wire [11:0] s_axi_awaddr,
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
    input wire s_axi_arvalid,
    output wire s_axi_arready,
    output reg [31:0] s_axi_rdata,
    output reg [1:0] s_axi_rresp,
    output reg s_axi_rvalid,
    input wire s_axi_rready,
    output reg [127:0] key,
    output reg [95:0] nonce,
    output reg [511:0] aad,
    output reg [31:0] aad_length, payload_length,
    output reg start, zeroize,
    input wire engine_ready, engine_busy, engine_done, engine_error,
    input wire [127:0] engine_tag,
    output wire irq
);
    reg aw_pending, w_pending, aw_blocked, w_blocked;
    reg [11:0] address;
    reg [31:0] data;
    reg [3:0] strobes;
    reg done_sticky, error_sticky;
    reg [31:0] packet_count;
    assign s_axi_awready = resetn && !aw_pending && !s_axi_bvalid;
    assign s_axi_wready = resetn && !w_pending && !s_axi_bvalid;
    assign s_axi_arready = resetn && !s_axi_rvalid;
    assign irq = done_sticky;
    function automatic [31:0] merge32(input [31:0] old_word, new_word, input [3:0] mask);
        integer k;
        begin
            merge32 = old_word;
            for (k = 0; k < 4; k = k + 1)
                if (mask[k]) merge32[k*8 +: 8] = new_word[k*8 +: 8];
        end
    endfunction
    integer i;
    always @(posedge clk) begin
        if (!resetn) begin
            aw_pending <= 0; w_pending <= 0; aw_blocked <= 0; w_blocked <= 0;
            address <= 0; data <= 0; strobes <= 0;
            key <= 0; nonce <= 0; aad <= 0; aad_length <= 0; payload_length <= 0;
            start <= 0; zeroize <= 0; done_sticky <= 0; error_sticky <= 0;
            packet_count <= 0; s_axi_bresp <= 0; s_axi_bvalid <= 0;
            s_axi_rdata <= 0; s_axi_rresp <= 0; s_axi_rvalid <= 0;
        end else begin
            start <= 0; zeroize <= 0;
            if (engine_done) begin done_sticky <= 1; packet_count <= packet_count + 1; end
            if (engine_error) error_sticky <= 1;
            if (s_axi_bvalid && s_axi_bready) s_axi_bvalid <= 0;
            if (s_axi_rvalid && s_axi_rready) s_axi_rvalid <= 0;
            if (s_axi_awvalid && s_axi_awready) begin
                address <= s_axi_awaddr; aw_pending <= 1;
                aw_blocked <= engine_busy || start || !engine_ready;
            end
            if (s_axi_wvalid && s_axi_wready) begin
                data <= s_axi_wdata; strobes <= s_axi_wstrb; w_pending <= 1;
                w_blocked <= engine_busy || start || !engine_ready;
            end
            if (aw_pending && w_pending && !s_axi_bvalid) begin
                aw_pending <= 0; w_pending <= 0;
                s_axi_bvalid <= 1; s_axi_bresp <= 0;
                if (address[1:0] != 0) s_axi_bresp <= 2;
                else if (strobes == 0) begin end
                else if (address == 0 && strobes[0] && data == 2) begin
                    key <= 0; nonce <= 0; aad <= 0;
                    aad_length <= 0; payload_length <= 0;
                    start <= 0; zeroize <= 1; done_sticky <= 0; error_sticky <= 0;
                end else if (aw_blocked || w_blocked || engine_busy || start || !engine_ready)
                    s_axi_bresp <= 2;
                else if (address == 0) begin
                    if (strobes[0] && data == 1 && aad_length <= 64 && payload_length <= 1400) begin
                        start <= 1; done_sticky <= 0; error_sticky <= 0;
                    end else if (strobes[0] && data == 4) begin
                        done_sticky <= 0;
                    end else begin s_axi_bresp <= 2; error_sticky <= 1; end
                end else if (address == 'h08)
                    payload_length <= merge32(payload_length, data, strobes);
                else if (address == 'h0c)
                    aad_length <= merge32(aad_length, data, strobes);
                else if (address >= 'h20 && address <= 'h2c) begin
                    for (i = 0; i < 4; i = i + 1)
                        if (strobes[i]) key[127 - (address-'h20)*8 - 31 + i*8 +: 8] <= data[i*8 +: 8];
                end else if (address >= 'h30 && address <= 'h38) begin
                    for (i = 0; i < 4; i = i + 1)
                        if (strobes[i]) nonce[95 - (address-'h30)*8 - 31 + i*8 +: 8] <= data[i*8 +: 8];
                end else if (address >= 'h40 && address <= 'h7c) begin
                    for (i = 0; i < 4; i = i + 1)
                        if (strobes[i]) aad[511 - (address-'h40)*8 - 31 + i*8 +: 8] <= data[i*8 +: 8];
                end else s_axi_bresp <= 2;
            end
            if (s_axi_arvalid && s_axi_arready) begin
                s_axi_rvalid <= 1; s_axi_rresp <= 0; s_axi_rdata <= 0;
                if (s_axi_araddr[1:0] != 0) s_axi_rresp <= 2;
                else case (s_axi_araddr)
                    'h04: s_axi_rdata <= {29'b0, error_sticky || engine_error,
                                          done_sticky, engine_busy || start};
                    'h08: s_axi_rdata <= payload_length;
                    'h0c: s_axi_rdata <= aad_length;
                    'h10: s_axi_rdata <= packet_count;
                    'h14: s_axi_rdata <= 32'h47434d31; // GCM1
                    'h80, 'h84, 'h88, 'h8c:
                        s_axi_rdata <= done_sticky ? engine_tag[127 - (s_axi_araddr-'h80)*8 -: 32] : 0;
                    default: s_axi_rresp <= 2;
                endcase
            end
        end
    end
endmodule
