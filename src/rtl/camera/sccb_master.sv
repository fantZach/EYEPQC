// Single-master SCCB, OV5640 address 0x3c: 16-bit register / 8-bit data.
module sccb_master #(
    parameter integer CLK_HZ = 100_000_000,
    parameter integer SCCB_HZ = 100_000,
    parameter integer TIMEOUT_CYCLES = CLK_HZ / 100
) (
    input wire clk, resetn, start, read_not_write,
    input wire [15:0] reg_addr,
    input wire [7:0] write_data,
    inout wire scl, sda,
    output reg busy, done,
    output reg [1:0] error, // 0 OK, 1 NACK, 2 transaction timeout
    output reg [7:0] read_data
);
    localparam integer QUARTER = (CLK_HZ + 4*SCCB_HZ - 1) / (4*SCCB_HZ);
    localparam integer DIV_BITS = (QUARTER < 2) ? 1 : $clog2(QUARTER);
    localparam integer TIME_BITS = (TIMEOUT_CYCLES < 2) ? 1 : $clog2(TIMEOUT_CYCLES);
    localparam [3:0] IDLE=0, FREE=1, START=2, SEND=3, ACK=4,
                     RESTART=5, READ=6, NACK=7, STOP=8, FINISH=9;
    reg [3:0] state;
    reg [1:0] phase, byte_index;
    reg [2:0] bit_index;
    reg [7:0] tx, data_latched;
    reg [15:0] addr_latched;
    reg reading, ack_bad, scl_low, sda_low;
    reg [DIV_BITS-1:0] divider;
    reg [TIME_BITS-1:0] elapsed;
    (* ASYNC_REG = "TRUE" *) reg [1:0] scl_sync, sda_sync;
    assign scl = scl_low ? 1'b0 : 1'bz;
    assign sda = sda_low ? 1'b0 : 1'bz;

    initial begin
        // Two-stage input synchronizers need settling time before sampling.
        if (SCCB_HZ <= 0 || QUARTER < 4 || TIMEOUT_CYCLES < 1)
            $fatal(1, "Invalid SCCB clock/timeout parameters");
    end
    always @(posedge clk) begin
        if (!resetn) begin
            scl_sync <= 2'b11; sda_sync <= 2'b11;
        end else begin
            scl_sync <= {scl_sync[0], scl};
            sda_sync <= {sda_sync[0], sda};
        end
    end
    // ponytail: one point-to-point bus; no multi-master arbitration.
    always @(posedge clk) begin
        if (!resetn) begin
            state <= IDLE; phase <= 0; byte_index <= 0; bit_index <= 7;
            tx <= 0; data_latched <= 0; addr_latched <= 0; reading <= 0;
            ack_bad <= 0; scl_low <= 0; sda_low <= 0;
            divider <= 0; elapsed <= 0;
            busy <= 0; done <= 0; error <= 0; read_data <= 0;
        end else begin
            done <= 0;
            if (state == IDLE) begin
                if (start) begin
                    addr_latched <= reg_addr; data_latched <= write_data;
                    reading <= read_not_write; tx <= 8'h78;
                    byte_index <= 0; bit_index <= 7; phase <= 0;
                    error <= 0; read_data <= 0; busy <= 1;
                    elapsed <= 0; divider <= QUARTER-1; state <= FREE;
                end
            end else if (elapsed == TIMEOUT_CYCLES-1) begin
                state <= IDLE; busy <= 0; done <= 1; error <= 2;
                scl_low <= 0; sda_low <= 0;
            end else begin
                elapsed <= elapsed + 1'b1;
                if (divider != 0) divider <= divider - 1'b1;
                else begin
                    divider <= QUARTER-1;
                    // Phase 2 waits for the physical SCL, including stretching.
                    if (!((state == SEND || state == ACK || state == READ ||
                           state == NACK || state == STOP || state == RESTART) &&
                          phase == 2 && !scl_sync[1])) begin
                        phase <= phase + 1'b1;
                        case (state)
                            FREE: if (scl_sync[1] && sda_sync[1]) begin
                                sda_low <= 1; state <= START;
                            end
                            START: begin
                                scl_low <= 1; state <= SEND; phase <= 0;
                            end
                            SEND: case (phase)
                                0: sda_low <= !tx[bit_index];
                                1: scl_low <= 0;
                                3: begin
                                    scl_low <= 1;
                                    if (bit_index == 0) state <= ACK;
                                    else bit_index <= bit_index-1'b1;
                                end
                                default: ;
                            endcase
                            ACK: case (phase)
                                0: sda_low <= 0;
                                1: scl_low <= 0;
                                2: ack_bad <= sda_sync[1];
                                3: begin
                                    scl_low <= 1; bit_index <= 7;
                                    if (ack_bad) begin error <= 1; state <= STOP; end
                                    else case (byte_index)
                                        0: begin tx <= addr_latched[15:8]; byte_index <= 1; state <= SEND; end
                                        1: begin tx <= addr_latched[7:0]; byte_index <= 2; state <= SEND; end
                                        2: begin
                                            byte_index <= 3;
                                            if (reading) begin tx <= 8'h79; state <= RESTART; end
                                            else begin tx <= data_latched; state <= SEND; end
                                        end
                                        3: state <= reading ? READ : STOP;
                                    endcase
                                end
                                default: ;
                            endcase
                            RESTART: case (phase)
                                0: sda_low <= 0;
                                1: scl_low <= 0;
                                3: begin sda_low <= 1; state <= START; end
                                default: ;
                            endcase
                            READ: case (phase)
                                0: sda_low <= 0;
                                1: scl_low <= 0;
                                2: read_data[bit_index] <= sda_sync[1];
                                3: begin
                                    scl_low <= 1;
                                    if (bit_index == 0) state <= NACK;
                                    else bit_index <= bit_index-1'b1;
                                end
                                default: ;
                            endcase
                            NACK: case (phase)
                                0: sda_low <= 0; // Single-byte read ends with master NACK.
                                1: scl_low <= 0;
                                3: begin scl_low <= 1; state <= STOP; end
                                default: ;
                            endcase
                            STOP: case (phase)
                                0: sda_low <= 1;
                                1: scl_low <= 0;
                                3: begin sda_low <= 0; state <= FINISH; end
                                default: ;
                            endcase
                            FINISH: if (scl_sync[1] && sda_sync[1]) begin
                                state <= IDLE; busy <= 0; done <= 1;
                            end
                            default: state <= IDLE;
                        endcase
                    end
                end
            end
        end
    end
endmodule
