// One GHASH session: start(H), AAD blocks, ciphertext blocks, finish(length block).
// block_data is MSB/first-byte aligned; block_bytes=1..16, trailing bytes ignored.
module ghash (
    input wire clk,
    input wire resetn,
    input wire zeroize,
    input wire start,
    output wire start_ready,
    input wire [127:0] h,
    input wire block_valid,
    output wire block_ready,
    input wire [127:0] block_data,
    input wire [4:0] block_bytes,
    input wire block_is_ciphertext,
    input wire finish,
    output wire finish_ready,
    output reg [127:0] state,
    output reg state_valid,
    output reg digest_valid,
    output reg error
);
    reg active, waiting, final_block, seen_cipher, partial_aad, partial_cipher;
    reg [127:0] hash_key, operand;
    reg [63:0] aad_bytes, cipher_bytes;
    reg mul_start;
    wire mul_done;
    wire [127:0] mul_result;
    wire [63:0] aad_bits = aad_bytes << 3;
    wire [63:0] cipher_bits = cipher_bytes << 3;
    reg [127:0] padded;
    integer i;
    always @* begin
        padded = 0;
        for (i = 0; i < 16; i = i + 1)
            if (i < block_bytes) padded[127-i*8 -: 8] = block_data[127-i*8 -: 8];
    end

    assign start_ready = resetn && !active && !waiting && !zeroize;
    assign block_ready = resetn && active && !waiting && !error && !start && !finish && !zeroize;
    assign finish_ready = resetn && active && !waiting && !error && !start && !block_valid && !zeroize;
    gf128_mul mul(.clk(clk), .resetn(resetn), .zeroize(zeroize), .start(mul_start),
                  .x(operand), .y(hash_key), .ready(), .done(mul_done), .result(mul_result));

    always @(posedge clk or negedge resetn) begin
        if (!resetn) begin
            active <= 0; waiting <= 0; final_block <= 0;
            seen_cipher <= 0; partial_aad <= 0; partial_cipher <= 0;
            hash_key <= 0; operand <= 0; aad_bytes <= 0; cipher_bytes <= 0;
            mul_start <= 0; state <= 0; state_valid <= 0; digest_valid <= 0; error <= 0;
        end else if (zeroize) begin
            active <= 0; waiting <= 0; final_block <= 0;
            seen_cipher <= 0; partial_aad <= 0; partial_cipher <= 0;
            hash_key <= 0; operand <= 0; aad_bytes <= 0; cipher_bytes <= 0;
            mul_start <= 0; state <= 0; state_valid <= 0; digest_valid <= 0; error <= 0;
        end else begin
            mul_start <= 0; state_valid <= 0; digest_valid <= 0;
            if (start && start_ready) begin
                active <= 1; hash_key <= h; state <= 0; operand <= 0;
                aad_bytes <= 0; cipher_bytes <= 0; seen_cipher <= 0;
                partial_aad <= 0; partial_cipher <= 0; error <= 0;
            end else if (block_valid && block_ready) begin
                if (block_bytes == 0 || block_bytes > 16 || partial_cipher ||
                    (!block_is_ciphertext && (seen_cipher || partial_aad))) error <= 1;
                else begin
                    operand <= state ^ padded; mul_start <= 1; waiting <= 1; final_block <= 0;
                    if (block_is_ciphertext) begin
                        seen_cipher <= 1; cipher_bytes <= cipher_bytes + block_bytes;
                        if (block_bytes != 16) partial_cipher <= 1;
                    end else begin
                        aad_bytes <= aad_bytes + block_bytes;
                        if (block_bytes != 16) partial_aad <= 1;
                    end
                end
            end else if (finish && finish_ready) begin
                operand <= state ^ {aad_bits, cipher_bits};
                mul_start <= 1; waiting <= 1; final_block <= 1;
            end else if (waiting && mul_done) begin
                state <= mul_result; state_valid <= 1; waiting <= 0;
                if (final_block) begin
                    digest_valid <= 1; active <= 0; final_block <= 0;
                end
            end
        end
    end
endmodule
