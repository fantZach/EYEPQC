`timescale 1ns/1ps
module tb_camera_dma_top;
    reg clk=0, pclk=0, pclk_running=1, resetn=0;
    always #5 clk=~clk;
    always #7 if(pclk_running) pclk=~pclk;
    reg [31:0] cfg=4;
    wire [31:0] status;
    tri1 scl,sda;
    reg valid=0, capture_ready=0;
    wire ready;
    camera_dma_top #(.INIT_FILE("ov5640_jpeg.mem")) dut(.clk(clk),.resetn(resetn),.camera_cfg(32'b0),.dma_cfg(cfg),
        .camera_status(),.dma_status(status),.cam_scl(scl),.cam_sda(sda),.cam_resetn(),.cam_pwdn(),
        .cam_pclk(pclk),.cam_vsync(1'b0),.cam_href(1'b0),.cam_data(8'b0),
        .s_test_tdata(32'h12345678),.s_test_tkeep(4'hf),.s_test_tvalid(valid),.s_test_tlast(1'b1),
        .s_test_tready(ready),.m_capture_tdata(),.m_capture_tkeep(),.m_capture_tvalid(),.m_capture_tlast(),
        .m_capture_tready(capture_ready),.m_crypto_tdata(),.m_crypto_tkeep(),.m_crypto_tvalid(),
        .m_crypto_tlast(),.m_crypto_tready(1'b0));
    initial begin
        force dut.configured=1; // Sensor state is verified independently by M02.
        #100 resetn=1;
        #100 cfg=0;
        #200 if(!dut.stream_resetn) $fatal(1,"PCLK reset did not release");
        wait(!dut.bridge.data_wr_busy && !dut.bridge.data_rd_busy &&
             !dut.bridge.desc_wr_busy && !dut.bridge.desc_rd_busy);
        #100;
        @(negedge pclk); pclk_running=0;
        cfg=4; #100;
        if(dut.stream_resetn) $fatal(1,"stopped-clock reset did not assert");
        cfg=0; #100;
        if(dut.stream_resetn) $fatal(1,"reset released without PCLK");
        pclk_running=1; #200;
        if(!dut.stream_resetn) $fatal(1,"PCLK reset did not recover");
        cfg=32'h80; valid=1; #100;
        if(ready || status<5) $fatal(1,"stall witness missing");
        capture_ready=1; #10; valid=0;
        if(!ready) $fatal(1,"route handshake lost");
        cfg=32'h70; #100;
        if(status<10) $fatal(1,"PCLK witness missing");
        $display("M05_NATIVE_PASS stopped_pclk_reset stall_counter clock_witness"); $finish;
    end
    initial begin #100000; $fatal(1,"watchdog"); end
endmodule
