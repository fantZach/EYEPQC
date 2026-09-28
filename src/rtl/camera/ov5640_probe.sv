// Small board probe around the reusable controller; native AXI GPIO supplies cfg.
module ov5640_probe #(
    parameter INIT_FILE = "src/rtl/camera/ov5640_jpeg.mem"
) (
    (* X_INTERFACE_PARAMETER = "FREQ_HZ 100000000, ASSOCIATED_RESET resetn" *)
    input wire clk,
    input wire resetn,
    input wire [31:0] cfg,
    output wire [31:0] status,
    output wire capture_resetn,
    inout wire cam_scl, cam_sda,
    output wire cam_resetn, cam_pwdn
);
    reg start_previous;
    wire local_resetn = resetn && !cfg[31];
    wire busy, done, configured, failed;
    wire [3:0] error;
    wire [15:0] chip_id, last_reg;
    (* ASYNC_REG = "TRUE" *) reg [1:0] scl_status_sync, sda_status_sync;
    always @(posedge clk) begin
        if (!local_resetn) begin
            start_previous <= 0; scl_status_sync <= 2'b11; sda_status_sync <= 2'b11;
        end else begin
            start_previous <= cfg[0];
            scl_status_sync <= {scl_status_sync[0], cam_scl};
            sda_status_sync <= {sda_status_sync[0], cam_sda};
        end
    end
    ov5640_ctrl #(.INIT_FILE(INIT_FILE)) ctrl (
        .clk(clk), .resetn(local_resetn), .start(cfg[0] && !start_previous),
        .width(cfg[2] ? 16'd640 : 16'd320), .height(cfg[2] ? 16'd480 : 16'd240),
        .hts(cfg[25] ? 16'd1896 : 16'd2844), .vts(cfg[24:9]),
        .quality(cfg[8:3]), .jpeg_mode(cfg[1]),
        .scl(cam_scl), .sda(cam_sda), .cam_resetn(cam_resetn), .cam_pwdn(cam_pwdn),
        .busy(busy), .done(done), .configured(configured), .failed(failed), .capture_resetn(capture_resetn),
        .error(error), .chip_id(chip_id), .last_reg(last_reg)
    );
    assign status = cfg[30] ? {chip_id, last_reg} :
        {4'b0, error, capture_resetn, sda_status_sync[1], scl_status_sync[1], cam_pwdn, cam_resetn,
         busy, failed, configured, chip_id};
endmodule
