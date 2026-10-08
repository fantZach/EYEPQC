// Iterative Keccak-f[1600], one round per clock. Synchronous active-high clear.
module keccak_f1600 (
    input  logic          clk,
    input  logic          rst,
    input  logic          clear,
    input  logic          start,
    input  logic [1599:0] state_i,
    output logic [1599:0] state_o,
    output logic          busy,
    output logic          done
);
    logic [1599:0] state_q;
    logic [4:0] round_q;
    logic [1599:0] round_state;

    keccak_round u_round(.state_i(state_q), .round_i(round_q), .state_o(round_state));

    always_ff @(posedge clk) begin
        done <= 1'b0;
        if (rst || clear) begin
            state_q <= '0;
            round_q <= '0;
            state_o <= '0;
            busy <= 1'b0;
            done <= 1'b0;
        end else if (start && !busy) begin
            state_q <= state_i;
            round_q <= 5'd0;
            busy <= 1'b1;
        end else if (busy) begin
            state_q <= round_state;
            if (round_q == 5'd23) begin
                state_o <= round_state;
                busy <= 1'b0;
                done <= 1'b1;
            end else begin
                round_q <= round_q + 1'b1;
            end
        end
    end
endmodule
