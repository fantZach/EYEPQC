module heartbeat #(
    parameter integer HALF_PERIOD_CYCLES = 50_000_000
) (
    (* X_INTERFACE_PARAMETER = "FREQ_HZ 100000000, ASSOCIATED_RESET resetn" *)
    input wire clk,
    input wire resetn,
    output reg led = 1'b0
);
    localparam integer WIDTH = (HALF_PERIOD_CYCLES < 2) ? 1 : $clog2(HALF_PERIOD_CYCLES);
    reg [WIDTH-1:0] count = 0;

    always @(posedge clk) begin
        if (!resetn) begin
            count <= 0;
            led <= 0;
        end else if (count == HALF_PERIOD_CYCLES - 1) begin
            count <= 0;
            led <= ~led;
        end else begin
            count <= count + 1'b1;
        end
    end
endmodule
