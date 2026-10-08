// Byte-stream SHA3-256/SHA3-512/SHAKE128/SHAKE256 wrapper.
// mode: 0=SHA3-256, 1=SHA3-512, 2=SHAKE128, 3=SHAKE256.
// SHAKE output length is supplied in bytes at start. SHA3 length is fixed.
module keccak_sponge (
    input  logic        clk,
    input  logic        rst,
    input  logic        clear,
    input  logic        start,
    input  logic [1:0]  mode,
    input  logic [15:0] shake_out_bytes,
    input  logic        in_valid,
    output logic        in_ready,
    input  logic [7:0]  in_data,
    input  logic        in_last,
    output logic        out_valid,
    input  logic        out_ready,
    output logic [7:0]  out_data,
    output logic        busy,
    output logic        done
);
    localparam logic [2:0] S_IDLE=3'd0, S_ABSORB=3'd1,
                           S_LAUNCH=3'd2, S_WAIT=3'd3, S_SQUEEZE=3'd4;
    logic [2:0] phase_q;
    logic [1599:0] state_q, core_state;
    logic [1599:0] absorb_next, padded_after_full;
    logic [7:0] index_q;
    logic [7:0] rate_q;
    logic [15:0] remaining_q;
    logic [1:0] mode_q;
    logic final_q, full_final_q, squeeze_next_q;
    logic core_start, core_busy, core_done;
    logic [7:0] delimiter;
    wire accept_byte = in_valid && in_ready;
    wire accept_empty = !in_valid && in_last && busy && phase_q == S_ABSORB && index_q == 0;

    keccak_f1600 u_keccak(.clk(clk), .rst(rst), .clear(clear),
        .start(core_start), .state_i(state_q), .state_o(core_state),
        .busy(core_busy), .done(core_done));

    always_comb begin
        case (mode_q)
          2'd0: delimiter=8'h06;
          2'd1: delimiter=8'h06;
          default: delimiter=8'h1f;
        endcase
        absorb_next = state_q;
        if (accept_byte) begin
            absorb_next[8*index_q +: 8] = state_q[8*index_q +: 8] ^ in_data;
            if (in_last && index_q != rate_q-1'b1) begin
                absorb_next[8*(index_q+1'b1) +: 8] =
                    absorb_next[8*(index_q+1'b1) +: 8] ^ delimiter;
                absorb_next[8*(rate_q-1'b1) +: 8] =
                    absorb_next[8*(rate_q-1'b1) +: 8] ^ 8'h80;
            end
        end
        if (accept_empty) begin
            absorb_next[7:0] = state_q[7:0] ^ delimiter;
            absorb_next[8*(rate_q-1'b1) +: 8] =
                state_q[8*(rate_q-1'b1) +: 8] ^ 8'h80;
        end
        padded_after_full = core_state;
        padded_after_full[7:0] = core_state[7:0] ^ delimiter;
        padded_after_full[8*(rate_q-1'b1) +: 8] =
            core_state[8*(rate_q-1'b1) +: 8] ^ 8'h80;
    end

    always_comb begin
        in_ready = busy && phase_q == S_ABSORB;
        out_valid = busy && phase_q == S_SQUEEZE;
        out_data = state_q[8*index_q +: 8];
    end

    always_ff @(posedge clk) begin
        done <= 1'b0;
        core_start <= 1'b0;
        if (rst || clear) begin
            phase_q <= S_IDLE;
            state_q <= '0;
            index_q <= '0;
            rate_q <= 8'd136;
            remaining_q <= '0;
            mode_q <= '0;
            final_q <= 1'b0;
            full_final_q <= 1'b0;
            squeeze_next_q <= 1'b0;
            core_start <= 1'b0;
            busy <= 1'b0;
            done <= 1'b0;
        end else begin
            case (phase_q)
              S_IDLE: begin
                busy <= 1'b0;
                if (start) begin
                    state_q <= '0;
                    mode_q <= mode;
                    index_q <= '0;
                    final_q <= 1'b0;
                    full_final_q <= 1'b0;
                    squeeze_next_q <= 1'b0;
                    case (mode)
                      2'd0: begin rate_q<=8'd136; remaining_q<=16'd32; end
                      2'd1: begin rate_q<=8'd72;  remaining_q<=16'd64; end
                      2'd2: begin rate_q<=8'd168; remaining_q<=shake_out_bytes; end
                      default: begin rate_q<=8'd136; remaining_q<=shake_out_bytes; end
                    endcase
                    busy <= 1'b1;
                    if ((mode[1] && shake_out_bytes == 0)) begin
                        busy <= 1'b0;
                        phase_q <= S_IDLE;
                        done <= 1'b1;
                    end else phase_q <= S_ABSORB;
                end
              end
              S_ABSORB: if (accept_byte || accept_empty) begin
                state_q <= absorb_next;
                if (in_last) begin
                    final_q <= 1'b1;
                    if (index_q == rate_q-1'b1) begin
                        full_final_q <= 1'b1;
                        index_q <= '0;
                    end
                    phase_q <= S_LAUNCH;
                end else if (index_q == rate_q-1'b1) begin
                    index_q <= '0;
                    phase_q <= S_LAUNCH;
                end else index_q <= index_q + 1'b1;
              end
              S_LAUNCH: begin
                core_start <= 1'b1;
                phase_q <= S_WAIT;
              end
              S_WAIT: if (core_done) begin
                state_q <= core_state;
                if (full_final_q) begin
                    state_q <= padded_after_full;
                    full_final_q <= 1'b0;
                    phase_q <= S_LAUNCH;
                end else if (squeeze_next_q) begin
                    index_q <= '0;
                    squeeze_next_q <= 1'b0;
                    phase_q <= S_SQUEEZE;
                end else if (final_q) begin
                    index_q <= '0;
                    phase_q <= S_SQUEEZE;
                end else begin
                    index_q <= '0;
                    phase_q <= S_ABSORB;
                end
              end
              S_SQUEEZE: if (out_valid && out_ready) begin
                if (remaining_q == 1) begin
                    remaining_q <= '0;
                    busy <= 1'b0;
                    phase_q <= S_IDLE;
                    done <= 1'b1;
                end else begin
                    remaining_q <= remaining_q - 1'b1;
                    if (index_q == rate_q-1'b1) begin
                        index_q <= '0;
                        squeeze_next_q <= 1'b1;
                        phase_q <= S_LAUNCH;
                    end else index_q <= index_q + 1'b1;
                end
              end
              default: begin phase_q<=S_IDLE; busy<=1'b0; end
            endcase
        end
    end
endmodule
