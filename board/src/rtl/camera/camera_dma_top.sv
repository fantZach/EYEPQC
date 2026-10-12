module camera_dma_top #(
    parameter INIT_FILE = "board/src/rtl/camera/ov5640_jpeg.mem"
) (
    (* X_INTERFACE_INFO = "xilinx.com:signal:clock:1.0 clk CLK" *)
    (* X_INTERFACE_PARAMETER = "FREQ_HZ 100000000, ASSOCIATED_BUSIF M_CAPTURE_AXIS:S_TEST_AXIS:M_CRYPTO_AXIS, ASSOCIATED_RESET resetn" *)
    input wire clk,
    (* X_INTERFACE_PARAMETER = "POLARITY ACTIVE_LOW" *) input wire resetn,
    input wire [31:0] camera_cfg, dma_cfg,
    output wire [31:0] camera_status,
    output reg [31:0] dma_status,
    inout wire cam_scl, cam_sda,
    output wire cam_resetn, cam_pwdn,
    (* X_INTERFACE_INFO = "xilinx.com:signal:clock:1.0 cam_pclk CLK" *) input wire cam_pclk,
    input wire cam_vsync, cam_href,
    input wire [7:0] cam_data,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 S_TEST_AXIS TDATA" *) input wire [31:0] s_test_tdata,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 S_TEST_AXIS TKEEP" *) input wire [3:0] s_test_tkeep,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 S_TEST_AXIS TVALID" *) input wire s_test_tvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 S_TEST_AXIS TLAST" *) input wire s_test_tlast,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 S_TEST_AXIS TREADY" *) output wire s_test_tready,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 M_CAPTURE_AXIS TDATA" *) output wire [31:0] m_capture_tdata,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 M_CAPTURE_AXIS TKEEP" *) output wire [3:0] m_capture_tkeep,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 M_CAPTURE_AXIS TVALID" *) output wire m_capture_tvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 M_CAPTURE_AXIS TLAST" *) output wire m_capture_tlast,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 M_CAPTURE_AXIS TREADY" *) input wire m_capture_tready,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 M_CRYPTO_AXIS TDATA" *) output wire [31:0] m_crypto_tdata,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 M_CRYPTO_AXIS TKEEP" *) output wire [3:0] m_crypto_tkeep,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 M_CRYPTO_AXIS TVALID" *) output wire m_crypto_tvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 M_CRYPTO_AXIS TLAST" *) output wire m_crypto_tlast,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 M_CRYPTO_AXIS TREADY" *) input wire m_crypto_tready
);
    wire configured;
    ov5640_probe #(.INIT_FILE(INIT_FILE)) sensor (
        .clk(clk), .resetn(resetn), .cfg(camera_cfg), .status(camera_status), .capture_resetn(configured),
        .cam_scl(cam_scl), .cam_sda(cam_sda), .cam_resetn(cam_resetn), .cam_pwdn(cam_pwdn)
    );
    wire stream_resetn;
    reg stream_requestn = 0;
    always @(posedge clk or negedge resetn)
        if (!resetn) stream_requestn <= 0;
        else stream_requestn <= configured && !dma_cfg[2];
    xpm_cdc_async_rst #(.DEST_SYNC_FF(4), .INIT_SYNC_FF(0), .RST_ACTIVE_HIGH(0)) camera_reset (
        .src_arst(stream_requestn), .dest_clk(cam_pclk), .dest_arst(stream_resetn)
    );
    wire [7:0] jpeg_byte;
    wire jpeg_valid, jpeg_first, jpeg_last, jpeg_error;
    dvp_capture capture (
        .pclk(cam_pclk), .capture_resetn(stream_resetn), .cam_vsync(cam_vsync),
        .cam_href(cam_href), .cam_data(cam_data), .byte_out(jpeg_byte), .byte_valid(jpeg_valid),
        .frame_start(jpeg_first), .frame_end(jpeg_last), .frame_error(jpeg_error)
    );
    wire [31:0] data, queued, dropped, overflows, peak, sent;
    wire [3:0] keep;
    wire valid, last, ready, overflow_latched, high_water;
    camera_axis_bridge bridge (
        .pclk(cam_pclk), .axis_clk(clk), .resetn(stream_resetn),
        .byte_in(jpeg_byte), .byte_valid(jpeg_valid), .frame_start(jpeg_first),
        .frame_end(jpeg_last), .frame_error(jpeg_error),
        .m_axis_tdata(data), .m_axis_tkeep(keep), .m_axis_tvalid(valid), .m_axis_tlast(last),
        .m_axis_tready(ready), .m_axis_tuser(), .frames_queued(queued), .frames_dropped(dropped),
        .fifo_overflows(overflows), .max_fifo_level(peak), .overflow_latched(overflow_latched),
        .frames_sent(sent), .fifo_high_water(high_water)
    );
    axis_capture_route route (
        .mode(dma_cfg[1:0]), .camera_data(data), .camera_keep(keep), .camera_valid(valid),
        .camera_last(last), .camera_ready(ready),
        .test_data(s_test_tdata), .test_keep(s_test_tkeep), .test_valid(s_test_tvalid),
        .test_last(s_test_tlast), .test_ready(s_test_tready),
        .capture_data(m_capture_tdata), .capture_keep(m_capture_tkeep),
        .capture_valid(m_capture_tvalid), .capture_last(m_capture_tlast), .capture_ready(m_capture_tready),
        .crypto_data(m_crypto_tdata), .crypto_keep(m_crypto_tkeep),
        .crypto_valid(m_crypto_tvalid), .crypto_last(m_crypto_tlast), .crypto_ready(m_crypto_tready)
    );
    // Free-running clock witness, no software reset jump in the Gray-coded source counter.
    reg [31:0] pclk_ticks = 0;
    wire [31:0] ticks_axis;
    reg [31:0] test_stalls = 0;
    always @(posedge clk) begin
        if (!resetn) test_stalls <= 0;
        else if (s_test_tvalid && !s_test_tready) test_stalls <= test_stalls + 1'b1;
    end
    always @(posedge cam_pclk) pclk_ticks <= pclk_ticks + 1'b1;
    xpm_cdc_gray #(.WIDTH(32), .INIT_SYNC_FF(1)) clock_witness (
        .src_clk(cam_pclk), .src_in_bin(pclk_ticks), .dest_clk(clk), .dest_out_bin(ticks_axis)
    );
    always @* case(dma_cfg[7:4])
        0: dma_status = 32'h4d303531; // M051
        1: dma_status = queued;
        2: dma_status = dropped;
        3: dma_status = overflows;
        4: dma_status = peak;
        5: dma_status = sent;
        6: dma_status = {30'b0, high_water, overflow_latched};
        7: dma_status = ticks_axis;
        8: dma_status = test_stalls;
        default: dma_status = 0;
    endcase
endmodule
