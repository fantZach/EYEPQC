// Ordered register facts, not a copy of the vendor SCCB driver.
module ov5640_reg_table #(
    parameter INIT_FILE = "board/src/rtl/camera/ov5640_jpeg.mem"
) (
    input wire [7:0] index,
    input wire [15:0] width, height, hts, vts,
    input wire [5:0] quality,
    input wire jpeg_mode, // 0 YUYV, 1 JPEG; both use YUV422 ISP input
    output reg [15:0] reg_addr,
    output reg [7:0] reg_data,
    output wire valid
);
    reg [23:0] registers [0:250];
    wire fast_mode = hts == 16'd1896;
    assign valid = index < 251;
    initial $readmemh(INIT_FILE, registers);
    always @* begin
        {reg_addr, reg_data} = 0;
        if (valid) begin
            {reg_addr, reg_data} = registers[index];
            case (reg_addr)
                16'h3035: if (fast_mode) reg_data = 8'h11;
                16'h3036: if (fast_mode) reg_data = 8'h70;
                16'h3c07: if (fast_mode) reg_data = 8'h08;
                16'h3618: if (fast_mode) reg_data = 8'h00;
                16'h3612: if (fast_mode) reg_data = 8'h29;
                16'h3709: if (fast_mode) reg_data = 8'h52;
                16'h370c: if (fast_mode) reg_data = 8'h03;
                16'h3803: if (fast_mode) reg_data = 8'h04;
                16'h3807: if (fast_mode) reg_data = 8'h9b;
                16'h3808: reg_data = width[15:8];
                16'h3809: reg_data = width[7:0];
                16'h380a: reg_data = height[15:8];
                16'h380b: reg_data = height[7:0];
                16'h380c: reg_data = hts[15:8];
                16'h380d: reg_data = hts[7:0];
                16'h380e: reg_data = vts[15:8];
                16'h380f: reg_data = vts[7:0];
                16'h3813: if (fast_mode) reg_data = 8'h06;
                16'h3814, 16'h3815: if (fast_mode) reg_data = 8'h31;
                16'h3820: if (fast_mode) reg_data = 8'h41;
                16'h3821: if (reg_data == 8'h20)
                    reg_data = jpeg_mode ? (fast_mode ? 8'h27 : 8'h20) : (fast_mode ? 8'h07 : 8'h00);
                16'h3a02, 16'h3a14: if (fast_mode) reg_data = vts[15:8];
                16'h3a03, 16'h3a15: if (fast_mode) reg_data = vts[7:0];
                16'h4004: if (fast_mode) reg_data = 8'h02;
                16'h3824: if (fast_mode) reg_data = 8'h04; // Faster sensor, PCLK still within 72 MHz.
                16'h3002: reg_data = jpeg_mode ? 8'h00 : 8'h1c;
                16'h3006: reg_data = jpeg_mode ? 8'hff : 8'hd7; // Disable JPEG clocks (bits 5,3).
                16'h4407: reg_data = {2'b00, quality};
                default: ;
            endcase
        end
    end
endmodule
