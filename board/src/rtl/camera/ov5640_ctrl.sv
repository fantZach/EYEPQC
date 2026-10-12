module ov5640_ctrl #(
    parameter integer CLK_HZ = 100_000_000,
    parameter integer SCCB_HZ = 100_000,
    parameter integer TIMEOUT_CYCLES = CLK_HZ / 100,
    parameter integer RESET_CYCLES = CLK_HZ / 200,
    parameter integer POWERUP_CYCLES = CLK_HZ / 50,
    parameter integer SETTLE_CYCLES = CLK_HZ / 1000,
    parameter integer MAX_RETRIES = 2,
    parameter INIT_FILE = "board/src/rtl/camera/ov5640_jpeg.mem"
) (
    input wire clk, resetn, start,
    input wire [15:0] width, height, hts, vts,
    input wire [5:0] quality,
    input wire jpeg_mode,
    inout wire scl, sda,
    output reg cam_resetn, cam_pwdn,
    output reg busy, done, configured, failed,
    output wire capture_resetn,
    output reg [3:0] error, // 0 OK, 1 NACK, 2 timeout, 3 ID, 4 params, 5 readback
    output reg [15:0] chip_id, last_reg
);
    localparam [3:0] IDLE=0, HOLD_RESET=1, WAKE=2, POWERUP=3,
                     ISSUE=4, WAIT_BUS=5, SETTLE=6, RETRY=7;
    localparam [1:0] ID_HIGH=0, ID_LOW=1, WRITE_TABLE=2, VERIFY=3;
    reg [3:0] state;
    reg [1:0] operation;
    reg [31:0] delay_left, retries;
    reg [7:0] index;
    reg [3:0] verify_index;
    reg [15:0] width_latched, height_latched, hts_latched, vts_latched;
    reg [5:0] quality_latched;
    reg jpeg_latched, bus_start;
    wire bus_busy, bus_done;
    wire [1:0] bus_error;
    wire [7:0] bus_data;
    wire [15:0] table_addr;
    wire [7:0] table_data;
    wire table_valid;
    reg [7:0] table_index;
    wire [15:0] bus_addr = operation == ID_HIGH ? 16'h300a :
                           operation == ID_LOW ? 16'h300b : table_addr;
    assign capture_resetn = configured;

    // Reuse the table for 16 final-value readbacks; no second register database.
    always @* begin
        table_index = index;
        if (operation == VERIFY) begin
            case (verify_index)
                0,1,2,3,4,5,6,7: table_index = 218 + verify_index;
                8: table_index = 227; // JPEG enable
                9: table_index = 52;  // YUYV ISP input
                10: table_index = 53;
                11: table_index = 241; // JPEG quality
                12: table_index = 238;
                13: table_index = 239;
                14: table_index = 240;
                15: table_index = 203; // PLL divider
            endcase
        end
    end
    ov5640_reg_table #(.INIT_FILE(INIT_FILE)) table_rom (
        .index(table_index), .width(width_latched), .height(height_latched),
        .hts(hts_latched), .vts(vts_latched), .quality(quality_latched),
        .jpeg_mode(jpeg_latched), .reg_addr(table_addr), .reg_data(table_data), .valid(table_valid)
    );
    sccb_master #(.CLK_HZ(CLK_HZ), .SCCB_HZ(SCCB_HZ), .TIMEOUT_CYCLES(TIMEOUT_CYCLES)) bus (
        .clk(clk), .resetn(resetn), .start(bus_start),
        .read_not_write(operation != WRITE_TABLE), .reg_addr(bus_addr), .write_data(table_data),
        .scl(scl), .sda(sda), .busy(bus_busy), .done(bus_done), .error(bus_error), .read_data(bus_data)
    );
    initial begin
        if (RESET_CYCLES < 1 || POWERUP_CYCLES < 1 || SETTLE_CYCLES < 1 || MAX_RETRIES < 0)
            $fatal(1, "Invalid camera delay/retry parameters");
    end
    always @(posedge clk) begin
        if (!resetn) begin
            state <= IDLE; operation <= ID_HIGH; delay_left <= 0; retries <= 0;
            index <= 0; verify_index <= 0; bus_start <= 0;
            width_latched <= 0; height_latched <= 0; hts_latched <= 0; vts_latched <= 0;
            quality_latched <= 0; jpeg_latched <= 0;
            cam_resetn <= 0; cam_pwdn <= 1; busy <= 0; done <= 0;
            configured <= 0; failed <= 0; error <= 0; chip_id <= 0; last_reg <= 0;
        end else begin
            done <= 0; bus_start <= 0;
            case (state)
                IDLE: if (start) begin
                    configured <= 0; failed <= 0; error <= 0; chip_id <= 0;
                    cam_resetn <= 0; cam_pwdn <= 1;
                    width_latched <= width; height_latched <= height;
                    hts_latched <= hts; vts_latched <= vts;
                    quality_latched <= quality; jpeg_latched <= jpeg_mode;
                    index <= 0; verify_index <= 0; operation <= ID_HIGH; retries <= 0;
                    if (width == 0 || height == 0 || width > 2592 || height > 1944 ||
                        hts <= width || vts <= height || width[0] ||
                        (jpeg_mode && (width[3:0] != 0 || height[3:0] != 0))) begin
                        failed <= 1; error <= 4; done <= 1;
                    end else begin
                        busy <= 1; delay_left <= RESET_CYCLES-1; state <= HOLD_RESET;
                    end
                end
                HOLD_RESET: if (delay_left != 0) delay_left <= delay_left-1'b1;
                    else begin cam_pwdn <= 0; delay_left <= RESET_CYCLES-1; state <= WAKE; end
                WAKE: if (delay_left != 0) delay_left <= delay_left-1'b1;
                    else begin cam_resetn <= 1; delay_left <= POWERUP_CYCLES-1; state <= POWERUP; end
                POWERUP, SETTLE, RETRY: if (delay_left != 0) delay_left <= delay_left-1'b1;
                    else state <= ISSUE;
                ISSUE: begin bus_start <= 1; last_reg <= bus_addr; state <= WAIT_BUS; end
                WAIT_BUS: if (bus_done) begin
                    if (bus_error != 0) begin
                        if (retries < MAX_RETRIES) begin
                            retries <= retries+1'b1; delay_left <= SETTLE_CYCLES-1; state <= RETRY;
                        end else begin
                            failed <= 1; error <= {2'b00, bus_error}; busy <= 0; done <= 1;
                            cam_resetn <= 0; state <= IDLE;
                        end
                    end else begin
                        retries <= 0;
                        case (operation)
                            ID_HIGH: begin chip_id[15:8] <= bus_data; operation <= ID_LOW; state <= ISSUE; end
                            ID_LOW: begin
                                chip_id[7:0] <= bus_data;
                                if ({chip_id[15:8], bus_data} != 16'h5640) begin
                                    failed <= 1; error <= 3; busy <= 0; done <= 1;
                                    cam_resetn <= 0; state <= IDLE;
                                end else begin operation <= WRITE_TABLE; state <= ISSUE; end
                            end
                            WRITE_TABLE: begin
                                if (index == 250) begin operation <= VERIFY; state <= ISSUE; end
                                else begin
                                    index <= index+1'b1;
                                    if (index == 0) begin delay_left <= SETTLE_CYCLES-1; state <= SETTLE; end
                                    else state <= ISSUE;
                                end
                            end
                            VERIFY: if (bus_data != table_data) begin
                                failed <= 1; error <= 5; busy <= 0; done <= 1;
                                cam_resetn <= 0; state <= IDLE;
                            end else if (verify_index == 15) begin
                                configured <= 1; busy <= 0; done <= 1; state <= IDLE;
                            end else begin verify_index <= verify_index+1'b1; state <= ISSUE; end
                        endcase
                    end
                end
                default: state <= IDLE;
            endcase
        end
    end
endmodule
