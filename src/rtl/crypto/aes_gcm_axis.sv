// M08 top: AXI4-Lite control plus 32-bit AXI4-Stream payload/tag datapath.
module aes_gcm_axis (
    (* X_INTERFACE_PARAMETER = "ASSOCIATED_BUSIF s_axi:s_axis:m_axis, ASSOCIATED_RESET aresetn" *)
    (* X_INTERFACE_INFO = "xilinx.com:signal:clock:1.0 aclk CLK" *) input wire aclk,
    (* X_INTERFACE_PARAMETER = "POLARITY ACTIVE_LOW" *)
    (* X_INTERFACE_INFO = "xilinx.com:signal:reset:1.0 aresetn RST" *) input wire aresetn,
    input wire [11:0] s_axi_awaddr,
    input wire [2:0] s_axi_awprot,
    input wire s_axi_awvalid, output wire s_axi_awready,
    input wire [31:0] s_axi_wdata,
    input wire [3:0] s_axi_wstrb,
    input wire s_axi_wvalid, output wire s_axi_wready,
    output wire [1:0] s_axi_bresp,
    output wire s_axi_bvalid, input wire s_axi_bready,
    input wire [11:0] s_axi_araddr,
    input wire [2:0] s_axi_arprot,
    input wire s_axi_arvalid, output wire s_axi_arready,
    output wire [31:0] s_axi_rdata,
    output wire [1:0] s_axi_rresp,
    output wire s_axi_rvalid, input wire s_axi_rready,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 S_AXIS TDATA" *) input wire [31:0] s_axis_tdata,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 S_AXIS TKEEP" *) input wire [3:0] s_axis_tkeep,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 S_AXIS TVALID" *) input wire s_axis_tvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 S_AXIS TLAST" *) input wire s_axis_tlast,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 S_AXIS TREADY" *) output wire s_axis_tready,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 M_AXIS TDATA" *) output wire [31:0] m_axis_tdata,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 M_AXIS TKEEP" *) output wire [3:0] m_axis_tkeep,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 M_AXIS TVALID" *) output wire m_axis_tvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 M_AXIS TLAST" *) output wire m_axis_tlast,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 M_AXIS TREADY" *) input wire m_axis_tready,
    output wire irq
);
    wire [127:0] key, tag;
    wire [95:0] nonce;
    wire [511:0] aad;
    wire [31:0] aad_length, payload_length;
    wire start, zeroize, ready, busy, done, error;
    aes_gcm_regs regs(.clk(aclk), .resetn(aresetn),
        .s_axi_awaddr(s_axi_awaddr), .s_axi_awvalid(s_axi_awvalid), .s_axi_awready(s_axi_awready),
        .s_axi_wdata(s_axi_wdata), .s_axi_wstrb(s_axi_wstrb),
        .s_axi_wvalid(s_axi_wvalid), .s_axi_wready(s_axi_wready),
        .s_axi_bresp(s_axi_bresp), .s_axi_bvalid(s_axi_bvalid), .s_axi_bready(s_axi_bready),
        .s_axi_araddr(s_axi_araddr), .s_axi_arvalid(s_axi_arvalid), .s_axi_arready(s_axi_arready),
        .s_axi_rdata(s_axi_rdata), .s_axi_rresp(s_axi_rresp), .s_axi_rvalid(s_axi_rvalid),
        .s_axi_rready(s_axi_rready), .key(key), .nonce(nonce), .aad(aad),
        .aad_length(aad_length), .payload_length(payload_length), .start(start), .zeroize(zeroize),
        .engine_ready(ready), .engine_busy(busy), .engine_done(done), .engine_error(error),
        .engine_tag(tag), .irq(irq));
    aes_gcm_encrypt engine(.clk(aclk), .resetn(aresetn), .zeroize(zeroize), .start(start),
        .ready(ready), .busy(busy), .key(key), .nonce(nonce), .aad(aad),
        .aad_length(aad_length[6:0]), .payload_length(payload_length[10:0]),
        .s_axis_tdata(s_axis_tdata), .s_axis_tkeep(s_axis_tkeep),
        .s_axis_tvalid(s_axis_tvalid), .s_axis_tlast(s_axis_tlast), .s_axis_tready(s_axis_tready),
        .m_axis_tdata(m_axis_tdata), .m_axis_tkeep(m_axis_tkeep),
        .m_axis_tvalid(m_axis_tvalid), .m_axis_tlast(m_axis_tlast), .m_axis_tready(m_axis_tready),
        .tag(tag), .done(done), .error(error));
endmodule
