// AES-128-GCM packet engine. One 32-bit AXIS beat at a time, one packet at a time.
// ponytail: serial AES/GHASH shares the existing cores; widen only if measured throughput needs it.
module aes_gcm_encrypt (
    input wire clk, resetn, zeroize, start,
    output wire ready, busy,
    input wire [127:0] key,
    input wire [95:0] nonce,
    input wire [511:0] aad,
    input wire [6:0] aad_length,
    input wire [10:0] payload_length,
    input wire [31:0] s_axis_tdata,
    input wire [3:0] s_axis_tkeep,
    input wire s_axis_tvalid, s_axis_tlast,
    output wire s_axis_tready,
    output wire [31:0] m_axis_tdata,
    output wire [3:0] m_axis_tkeep,
    output wire m_axis_tvalid, m_axis_tlast,
    input wire m_axis_tready,
    output reg [127:0] tag,
    output reg done, error
);
    localparam [4:0] IDLE=0, INIT=1, WAIT_INIT=2, H_AES=3, WAIT_H=4,
        GH_START=5, MASK_AES=6, WAIT_MASK=7, AAD=8, WAIT_AAD=9,
        INPUT=10, CTR_AES=11, WAIT_CTR=12, OUTPUT=13, CT_GH=14,
        WAIT_CT=15, FINISH=16, WAIT_FINISH=17, TAG_OUTPUT=18, TAG_DRAIN=19, FAILED=20;
    reg [4:0] phase;
    reg [127:0] packet_key, hash_key, tag_mask, plain, cipher;
    reg [95:0] packet_nonce;
    reg [511:0] aad_shift;
    reg [6:0] aad_remaining;
    reg [10:0] remaining;
    reg [31:0] counter;
    reg [4:0] fill, block_size;
    reg [4:0] out_byte;
    reg last_block;
    wire aes_ready, aes_valid;
    wire [127:0] aes_result;
    // Secworks samples block one cycle after next, so hold it through WAIT_*.
    wire [127:0] aes_input = phase == H_AES || phase == WAIT_H ? 128'b0 :
                             phase == MASK_AES || phase == WAIT_MASK ? {packet_nonce, 32'd1} :
                             {packet_nonce, counter};
    aes_core aes(.clk(clk), .reset_n(resetn && !zeroize), .encdec(1'b1),
        .init(phase == INIT), .next(phase == H_AES || phase == MASK_AES || phase == CTR_AES),
        .ready(aes_ready), .key({packet_key, 128'b0}), .keylen(1'b0),
        .block(aes_input), .result(aes_result), .result_valid(aes_valid));

    wire gh_start_ready, gh_block_ready, gh_finish_ready, gh_state_valid, gh_digest_valid, gh_error;
    wire [127:0] gh_state;
    wire [4:0] aad_chunk = aad_remaining >= 16 ? 5'd16 : {1'b0, aad_remaining[3:0]};
    ghash auth(.clk(clk), .resetn(resetn), .zeroize(zeroize),
        .start(phase == GH_START), .start_ready(gh_start_ready), .h(hash_key),
        .block_valid(phase == AAD && aad_remaining != 0 || phase == CT_GH),
        .block_ready(gh_block_ready),
        .block_data(phase == AAD ? aad_shift[511:384] : cipher),
        .block_bytes(phase == AAD ? aad_chunk : block_size),
        .block_is_ciphertext(phase == CT_GH),
        .finish(phase == FINISH), .finish_ready(gh_finish_ready),
        .state(gh_state), .state_valid(gh_state_valid), .digest_valid(gh_digest_valid),
        .error(gh_error));

    wire byte_ready;
    wire byte_valid = phase == OUTPUT || phase == TAG_OUTPUT;
    wire [7:0] stream_byte = phase == TAG_OUTPUT ? tag[127 - 8*out_byte -: 8] :
                                                  cipher[127 - 8*out_byte -: 8];
    axis_byte_packer #(.DATA_WIDTH(32)) packer(
        .clk(clk), .resetn(resetn && !zeroize), .s_data(stream_byte),
        .s_valid(byte_valid), .s_last(phase == TAG_OUTPUT && out_byte == 15),
        .s_first(1'b0), .s_ready(byte_ready),
        .m_axis_tdata(m_axis_tdata), .m_axis_tkeep(m_axis_tkeep),
        .m_axis_tvalid(m_axis_tvalid), .m_axis_tlast(m_axis_tlast),
        .m_axis_tuser(), .m_axis_tready(m_axis_tready));
    assign ready = resetn && !zeroize && phase == IDLE;
    assign busy = phase != IDLE && phase != FAILED;
    assign s_axis_tready = resetn && !zeroize && phase == INPUT;
    wire [2:0] beat_bytes = s_axis_tkeep == 4'hf ? 3'd4 :
                            s_axis_tkeep == 4'h7 ? 3'd3 :
                            s_axis_tkeep == 4'h3 ? 3'd2 :
                            s_axis_tkeep == 4'h1 ? 3'd1 : 3'd0;
    integer i;
    always @(posedge clk or negedge resetn) begin
        if (!resetn) begin
            phase <= IDLE; packet_key <= 0; packet_nonce <= 0; hash_key <= 0;
            tag_mask <= 0; aad_shift <= 0; aad_remaining <= 0; remaining <= 0;
            counter <= 0; plain <= 0; cipher <= 0; fill <= 0; block_size <= 0;
            out_byte <= 0; last_block <= 0; tag <= 0; done <= 0; error <= 0;
        end else if (zeroize) begin
            phase <= IDLE; packet_key <= 0; packet_nonce <= 0; hash_key <= 0;
            tag_mask <= 0; aad_shift <= 0; aad_remaining <= 0; remaining <= 0;
            counter <= 0; plain <= 0; cipher <= 0; fill <= 0; block_size <= 0;
            out_byte <= 0; last_block <= 0; tag <= 0; done <= 0; error <= 0;
        end else begin
            done <= 0;
            if (gh_error && phase != IDLE) begin phase <= FAILED; error <= 1; end
            else case (phase)
                IDLE: if (start) begin
                    if (aad_length > 64 || payload_length > 1400) begin
                        phase <= FAILED; error <= 1;
                    end else begin
                        packet_key <= key; packet_nonce <= nonce; aad_shift <= aad;
                        aad_remaining <= aad_length; remaining <= payload_length;
                        counter <= 2; plain <= 0; cipher <= 0; fill <= 0;
                        block_size <= 0; out_byte <= 0; last_block <= 0;
                        hash_key <= 0; tag_mask <= 0; tag <= 0; error <= 0;
                        phase <= INIT;
                    end
                end
                INIT: phase <= WAIT_INIT;
                WAIT_INIT: if (aes_ready) phase <= H_AES;
                H_AES: phase <= WAIT_H;
                WAIT_H: if (aes_valid) begin hash_key <= aes_result; phase <= GH_START; end
                GH_START: if (gh_start_ready) phase <= MASK_AES;
                MASK_AES: phase <= WAIT_MASK;
                WAIT_MASK: if (aes_valid) begin tag_mask <= aes_result; phase <= AAD; end
                AAD: if (aad_remaining == 0) phase <= remaining == 0 ? FINISH : INPUT;
                     else if (gh_block_ready) begin
                         aad_shift <= aad_shift << 128;
                         aad_remaining <= aad_remaining - aad_chunk;
                         phase <= WAIT_AAD;
                     end
                WAIT_AAD: if (gh_state_valid) phase <= AAD;
                INPUT: if (s_axis_tvalid) begin
                    if (beat_bytes == 0 || beat_bytes > remaining || fill + beat_bytes > 16 ||
                        beat_bytes != (remaining >= 4 ? 3'd4 : remaining[2:0]) ||
                        s_axis_tlast != (remaining == beat_bytes)) begin
                        phase <= FAILED; error <= 1;
                    end else begin
                        for (i = 0; i < 4; i = i + 1)
                            if (i < beat_bytes)
                                plain[127 - 8*(fill+i) -: 8] <= s_axis_tdata[8*i +: 8];
                        fill <= fill + beat_bytes;
                        remaining <= remaining - beat_bytes;
                        if (fill + beat_bytes == 16 || s_axis_tlast) begin
                            block_size <= fill + beat_bytes;
                            last_block <= s_axis_tlast;
                            phase <= CTR_AES;
                        end
                    end
                end
                CTR_AES: phase <= WAIT_CTR;
                WAIT_CTR: if (aes_valid) begin
                    cipher <= plain ^ aes_result; counter <= counter + 1;
                    out_byte <= 0; phase <= OUTPUT;
                end
                OUTPUT: if (byte_ready) begin
                    if (out_byte + 1 == block_size) phase <= CT_GH;
                    else out_byte <= out_byte + 1'b1;
                end
                CT_GH: if (gh_block_ready) phase <= WAIT_CT;
                WAIT_CT: if (gh_state_valid) begin
                    if (last_block) phase <= FINISH;
                    else begin plain <= 0; fill <= 0; phase <= INPUT; end
                end
                FINISH: if (gh_finish_ready) phase <= WAIT_FINISH;
                WAIT_FINISH: if (gh_digest_valid) begin
                    tag <= gh_state ^ tag_mask; out_byte <= 0; phase <= TAG_OUTPUT;
                end
                TAG_OUTPUT: if (byte_ready) begin
                    if (out_byte == 15) phase <= TAG_DRAIN;
                    else out_byte <= out_byte + 1'b1;
                end
                TAG_DRAIN: if (m_axis_tvalid && m_axis_tready && m_axis_tlast) begin
                    done <= 1; phase <= IDLE;
                end
                default: begin phase <= FAILED; error <= 1; end
            endcase
        end
    end
endmodule
