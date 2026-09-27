`timescale 1ns/1ps
// Pin-level slave model. No access to controller/master internal state.
module ov5640_model (
    input wire resetn, enabled, wrong_id,
    input wire [3:0] nack_mask,
    input wire nack_once, corrupt_enable,
    input wire [15:0] corrupt_addr,
    inout wire scl, sda
);
    localparam RX=0, ACK_DRIVE=1, ACK_HIGH=2, TX=3, READ_ACK=4, IGNORE=5;
    reg [7:0] memory [0:65535];
    reg [15:0] write_addresses [0:1023];
    reg [7:0] write_values [0:1023];
    time write_times [0:1023];
    reg [7:0] shift, outgoing;
    reg [15:0] pointer;
    reg drive_low, address_byte, read_direction, accepted, nack_used;
    integer state, bits, byte_number, tx_bit;
    integer writes, starts, stops, read_nacks;
    assign sda = drive_low ? 1'b0 : 1'bz;
    initial begin
        for (integer i=0; i<65536; i=i+1) memory[i] = 0;
        drive_low=0; state=IGNORE; pointer=0; nack_used=0;
        writes=0; starts=0; stops=0; read_nacks=0;
    end
    always @(negedge resetn) begin
        drive_low=0; state=IGNORE; pointer=0; nack_used=0;
        writes=0; starts=0; stops=0; read_nacks=0;
    end
    always @(negedge sda) if (resetn && scl === 1'b1) begin
        starts=starts+1; state=RX; bits=0; shift=0;
        address_byte=1; byte_number=0; drive_low=0;
    end
    always @(posedge sda) if (resetn && scl === 1'b1) begin
        stops=stops+1; state=IGNORE; drive_low=0;
    end
    always @(posedge scl) if (resetn) begin
        case (state)
            RX: begin
                shift={shift[6:0], sda}; bits=bits+1;
                if (bits == 8) begin
                    accepted=enabled && !(nack_mask[byte_number] && (!nack_once || !nack_used));
                    if (address_byte) begin
                        accepted=accepted && shift[7:1] == 7'h3c;
                        read_direction=shift[0]; address_byte=0;
                    end else if (accepted) begin
                        case (byte_number)
                            1: pointer[15:8]=shift;
                            2: pointer[7:0]=shift;
                            3: begin
                                memory[pointer]=shift;
                                write_addresses[writes]=pointer; write_values[writes]=shift;
                                write_times[writes]=$time; writes=writes+1;
                            end
                        endcase
                    end
                    if (enabled && nack_mask[byte_number]) nack_used=1;
                    state=ACK_DRIVE;
                end
            end
            ACK_HIGH: ;
            TX: if (tx_bit == 0) state=READ_ACK; else tx_bit=tx_bit-1;
            READ_ACK: begin
                if (sda !== 1'b1) $fatal(1, "Master must NACK final read byte");
                read_nacks=read_nacks+1; state=IGNORE;
            end
            default: ;
        endcase
    end
    always @(negedge scl) if (resetn) begin
        case (state)
            ACK_DRIVE: begin drive_low=accepted; state=ACK_HIGH; end
            ACK_HIGH: begin
                drive_low=0;
                if (!accepted) state=IGNORE;
                else if (read_direction) begin
                    if (pointer == 16'h300a) outgoing=wrong_id ? 8'h55 : 8'h56;
                    else if (pointer == 16'h300b) outgoing=8'h40;
                    else outgoing=memory[pointer] ^ ((corrupt_enable && pointer == corrupt_addr) ? 8'h01 : 8'h00);
                    state=TX; tx_bit=7; drive_low=!outgoing[7];
                end else begin
                    state=RX; bits=0; shift=0; byte_number=byte_number+1;
                end
            end
            TX: drive_low=!outgoing[tx_bit];
            READ_ACK, IGNORE: drive_low=0;
            default: ;
        endcase
    end
endmodule
