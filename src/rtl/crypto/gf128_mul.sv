// SP 800-38D Algorithm 1: MSB-first, R = e1 || 0^120. One bit per cycle.
// ponytail: 128-cycle serial multiply; use a wider datapath only if M08 throughput requires it.
module gf128_mul (
    input wire clk,
    input wire resetn,
    input wire zeroize,
    input wire start,
    input wire [127:0] x,
    input wire [127:0] y,
    output wire ready,
    output reg done,
    output reg [127:0] result
);
    reg busy;
    reg [6:0] bit_index;
    reg [127:0] bits, v, product;
    wire [127:0] next_product = product ^ (v & {128{bits[127]}});
    wire [127:0] next_v = {1'b0, v[127:1]} ^ (128'he1000000000000000000000000000000 & {128{v[0]}});
    assign ready = resetn && !busy && !zeroize;

    always @(posedge clk or negedge resetn) begin
        if (!resetn) begin
            busy <= 0; done <= 0; result <= 0; bit_index <= 0;
            bits <= 0; v <= 0; product <= 0;
        end else if (zeroize) begin
            busy <= 0; done <= 0; result <= 0; bit_index <= 0;
            bits <= 0; v <= 0; product <= 0;
        end else begin
            done <= 0;
            if (start && ready) begin
                busy <= 1; result <= 0; bit_index <= 0;
                bits <= x; v <= y; product <= 0;
            end else if (busy) begin
                if (bit_index == 127) begin
                    result <= next_product; done <= 1; busy <= 0;
                    bits <= 0; v <= 0; product <= 0;
                end else begin
                    product <= next_product;
                    bits <= {bits[126:0], 1'b0};
                    v <= next_v;
                    bit_index <= bit_index + 1'b1;
                end
            end
        end
    end
endmodule
