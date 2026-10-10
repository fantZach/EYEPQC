// Stateful SHAKE128x4 service for the isolated ML-KEM experiment.
// Four independent 1600-bit states remain in PL. One Keccak core is reused
// serially across the four states. Input/output bytes follow FIPS202 order:
// byte 0 is the least-significant byte of lane 0.
module keccak_sponge_x4_axi_lite #(
    parameter integer DEFAULT_WATCHDOG_CYCLES = 200000
) (
    input  wire         s_axi_aclk,
    input  wire         s_axi_aresetn,
    input  wire [11:0]  s_axi_awaddr,
    input  wire [2:0]   s_axi_awprot,
    input  wire         s_axi_awvalid,
    output wire         s_axi_awready,
    input  wire [31:0]  s_axi_wdata,
    input  wire [3:0]   s_axi_wstrb,
    input  wire         s_axi_wvalid,
    output wire         s_axi_wready,
    output reg  [1:0]   s_axi_bresp,
    output reg          s_axi_bvalid,
    input  wire         s_axi_bready,
    input  wire [11:0]  s_axi_araddr,
    input  wire [2:0]   s_axi_arprot,
    input  wire         s_axi_arvalid,
    output wire         s_axi_arready,
    output reg  [31:0]  s_axi_rdata,
    output reg  [1:0]   s_axi_rresp,
    output reg          s_axi_rvalid,
    input  wire         s_axi_rready
);
    localparam [11:0] ADDR_CTRL=12'h000, ADDR_STATUS=12'h004,
        ADDR_WDOG=12'h008, ADDR_ID=12'h00c, ADDR_VERSION=12'h010,
        ADDR_INLEN=12'h020, ADDR_INPUT=12'h100, ADDR_OUTPUT=12'h400;
    localparam [31:0] ID_VALUE=32'h4b58_3431; // KX41
    localparam [1:0] RESP_OKAY=2'b00, RESP_SLVERR=2'b10;
    localparam [3:0] P_IDLE=0, P_ABSORB_INIT=1, P_ABSORB_LAUNCH=2,
        P_ABSORB_WAIT=3, P_SQUEEZE_LAUNCH=4, P_SQUEEZE_WAIT=5,
        P_ABSORB_WORD=6, P_ABSORB_UPDATE=7;

    reg aw_pending, w_pending;
    reg [11:0] awaddr_q;
    reg [31:0] wdata_q;
    reg [3:0] wstrb_q;
    reg [31:0] input_words [0:171]; // 4 x 43 words; at most 169 input bytes
    reg [31:0] output_words [0:167]; // 4 x 42 words; one 168-byte block/lane
    reg [1599:0] state_q [0:3];
    reg [7:0] input_len_q, tail_len_q;
    reg [31:0] watchdog_limit_q, watchdog_count_q;
    reg [4:0] absorb_word_q;
    reg absorb_full_q, tail_base_q;
    reg [63:0] absorb_word_data_q;
    reg [3:0] phase_q;
    reg [1:0] lane_q;
    reg busy_q, done_q, error_q, timeout_q, context_valid_q;
    reg core_start_q, core_clear_q;
    wire core_busy, core_done;
    wire [1599:0] core_result;
    integer i;
    wire write_commit = aw_pending && w_pending && !s_axi_bvalid;
    wire clear_commit = write_commit && awaddr_q == ADDR_CTRL &&
        wstrb_q[0] && wdata_q[31:3] == 0 && wdata_q[2];
    wire watchdog_expire = busy_q && watchdog_limit_q != 0 &&
        watchdog_count_q + 1 >= watchdog_limit_q;

    assign s_axi_awready = !aw_pending && !s_axi_bvalid;
    assign s_axi_wready  = !w_pending && !s_axi_bvalid;
    assign s_axi_arready = !s_axi_rvalid;

    keccak_f1600 u_core(.clk(s_axi_aclk), .rst(!s_axi_aresetn),
        .clear(core_clear_q), .start(core_start_q), .state_i(state_q[lane_q]),
        .state_o(core_result), .busy(core_busy), .done(core_done));

    function automatic [7:0] input_byte(input [1:0] lane, input [7:0] index);
        reg [7:0] lane_base;
        reg [7:0] word_index;
        reg [1:0] byte_index;
        begin
            case (lane)
                2'd0: lane_base=8'd0;
                2'd1: lane_base=8'd43;
                2'd2: lane_base=8'd86;
                default: lane_base=8'd129;
            endcase
            word_index = lane_base + {2'b0,index[7:2]};
            byte_index = index[1:0];
            case (byte_index)
                2'd0: input_byte=input_words[word_index][7:0];
                2'd1: input_byte=input_words[word_index][15:8];
                2'd2: input_byte=input_words[word_index][23:16];
                default: input_byte=input_words[word_index][31:24];
            endcase
        end
    endfunction

    // Build just one 64-bit rate word per cycle. Keeping the remaining byte
    // count in an 8-bit register avoids a 32-bit subtract/compare chain feeding
    // the 1600-bit state register bank.
    function automatic [63:0] build_absorb_word(input [1:0] lane,
                                                 input [4:0] word_index,
                                                 input [7:0] remaining,
                                                 input full_block,
                                                 input tail_base);
        integer b;
        reg [7:0] pos, src_index;
        reg [63:0] value;
        begin
            value = '0;
            for (b = 0; b < 8; b = b + 1) begin
                pos = {word_index,3'b000} + b[7:0];
                if (full_block) begin
                    value[b*8 +: 8] = input_byte(lane,pos);
                end else begin
                    if (pos < remaining) begin
                        src_index = pos + (tail_base ? 8'd168 : 8'd0);
                        value[b*8 +: 8] = input_byte(lane,src_index);
                    end
                    if (remaining == 8'd167 && pos == 8'd167)
                        value[b*8 +: 8] = value[b*8 +: 8] ^ 8'h9f;
                    else begin
                        if (pos == remaining)
                            value[b*8 +: 8] = value[b*8 +: 8] ^ 8'h1f;
                        if (pos == 8'd167)
                            value[b*8 +: 8] = value[b*8 +: 8] ^ 8'h80;
                    end
                end
            end
            build_absorb_word = value;
        end
    endfunction

    always @(posedge s_axi_aclk) begin : axi_registers
        reg [11:0] wr_addr;
        reg [31:0] wr_data;
        reg [3:0] wr_strb;
        reg [1:0] write_response, read_response;
        reg write_error;
        reg [31:0] read_value;
        reg [31:0] next_count;
        integer word_index;
        if (!s_axi_aresetn) begin
            aw_pending<=0; w_pending<=0; awaddr_q<=0; wdata_q<=0; wstrb_q<=0;
            input_len_q<=0; tail_len_q<=0; absorb_word_q<=0;
            absorb_full_q<=0; tail_base_q<=0;
            absorb_word_data_q<=0;
            watchdog_limit_q<=DEFAULT_WATCHDOG_CYCLES;
            watchdog_count_q<=0; phase_q<=P_IDLE; lane_q<=0;
            busy_q<=0; done_q<=0; error_q<=0; timeout_q<=0; context_valid_q<=0;
            core_start_q<=0; core_clear_q<=0;
            s_axi_bresp<=RESP_OKAY; s_axi_bvalid<=0;
            s_axi_rdata<=0; s_axi_rresp<=RESP_OKAY; s_axi_rvalid<=0;
            for (i=0;i<172;i=i+1) input_words[i]<=0;
            for (i=0;i<168;i=i+1) output_words[i]<=0;
            for (i=0;i<4;i=i+1) state_q[i]<=0;
        end else begin
            core_start_q<=0; core_clear_q<=0;
            if (s_axi_bvalid && s_axi_bready) s_axi_bvalid<=0;
            if (s_axi_rvalid && s_axi_rready) s_axi_rvalid<=0;
            if (s_axi_awvalid && s_axi_awready) begin awaddr_q<=s_axi_awaddr; aw_pending<=1; end
            if (s_axi_wvalid && s_axi_wready) begin
                wdata_q<=s_axi_wdata; wstrb_q<=s_axi_wstrb; w_pending<=1;
            end
            if (write_commit) begin
                aw_pending<=0; w_pending<=0; s_axi_bvalid<=1;
                write_response=RESP_OKAY; write_error=0;
                wr_addr=awaddr_q; wr_data=wdata_q; wr_strb=wstrb_q;
                if (wr_addr[1:0]!=0) begin write_response=RESP_SLVERR; write_error=1; end
                else if (wr_strb==0) begin end
                else if (wr_addr==ADDR_CTRL) begin
                    if (!wr_strb[0] || wr_data[31:3]!=0 || wr_data[1:0]==2'b11) begin
                        write_response=RESP_SLVERR; write_error=1;
                    end else if (wr_data[2]) begin
                        core_clear_q<=1; phase_q<=P_IDLE; lane_q<=0;
                        busy_q<=0; done_q<=0; error_q<=0; timeout_q<=0;
                        context_valid_q<=0; watchdog_count_q<=0; input_len_q<=0;
                        tail_len_q<=0; absorb_word_q<=0; absorb_full_q<=0; tail_base_q<=0;
                        absorb_word_data_q<=0;
                        for (i=0;i<172;i=i+1) input_words[i]<=0;
                        for (i=0;i<168;i=i+1) output_words[i]<=0;
                        for (i=0;i<4;i=i+1) state_q[i]<=0;
                    end else if (busy_q) begin
                        write_response=RESP_SLVERR; write_error=1;
                    end else if (wr_data[1:0]==2'b01) begin
                        if (input_len_q>169) begin
                            write_response=RESP_SLVERR; write_error=1; error_q<=1;
                        end else begin
                            done_q<=0; error_q<=0; timeout_q<=0; busy_q<=1;
                            watchdog_count_q<=0; lane_q<=0; phase_q<=P_ABSORB_INIT;
                            context_valid_q<=0;
                            absorb_full_q<=input_len_q>=8'd168;
                        end
                    end else if (wr_data[1:0]==2'b10) begin
                        if (!context_valid_q) begin
                            write_response=RESP_SLVERR; write_error=1; error_q<=1;
                        end else begin
                            done_q<=0; error_q<=0; timeout_q<=0; busy_q<=1;
                            watchdog_count_q<=0; lane_q<=0; phase_q<=P_SQUEEZE_LAUNCH;
                        end
                    end else begin write_response=RESP_SLVERR; write_error=1; end
                end else if (wr_addr==ADDR_INLEN) begin
                    if (busy_q || wr_data>169) begin write_response=RESP_SLVERR; write_error=1; end
                    else begin
                        input_len_q<=wr_data[7:0];
                        tail_base_q<=wr_data>=32'd168;
                        tail_len_q<=wr_data>=32'd168 ? wr_data[7:0]-8'd168 : wr_data[7:0];
                    end
                end else if (wr_addr==ADDR_WDOG) begin
                    if (busy_q) begin write_response=RESP_SLVERR; write_error=1; end
                    else watchdog_limit_q<=wr_data;
                end else if (wr_addr>=ADDR_INPUT && wr_addr<ADDR_INPUT+12'd688) begin
                    word_index=(wr_addr-ADDR_INPUT)>>2;
                    if (busy_q || word_index>=172) begin write_response=RESP_SLVERR; write_error=1; end
                    else begin
                        for (integer b=0;b<4;b=b+1)
                            if (wr_strb[b]) input_words[word_index][b*8 +: 8]<=wr_data[b*8 +: 8];
                    end
                end else begin write_response=RESP_SLVERR; write_error=1; end
                s_axi_bresp<=write_response;
                if (write_error) error_q<=1;
            end

            if (busy_q && !clear_commit) begin
                if (watchdog_limit_q!=0) begin
                    next_count=watchdog_count_q+1;
                    watchdog_count_q<=next_count;
                    if (next_count>=watchdog_limit_q) begin
                        core_clear_q<=1; phase_q<=P_IDLE; busy_q<=0; done_q<=0;
                        error_q<=1; timeout_q<=1; context_valid_q<=0; watchdog_count_q<=0;
                        absorb_word_data_q<=0;
                        for (i=0;i<172;i=i+1) input_words[i]<=0;
                        for (i=0;i<168;i=i+1) output_words[i]<=0;
                        for (i=0;i<4;i=i+1) state_q[i]<=0;
                    end
                end
            end

            if (!clear_commit && !watchdog_expire) case (phase_q)
              P_ABSORB_INIT: begin
                state_q[lane_q]<=0;
                absorb_word_q<=0;
                absorb_full_q<=tail_base_q;
                phase_q<=P_ABSORB_WORD;
              end
              P_ABSORB_WORD: begin
                // Capture the lane/input-byte mux output before updating the
                // 1600-bit state bank. This breaks the high-fanout lane select
                // path that otherwise spans both muxing and state writeback.
                absorb_word_data_q<=build_absorb_word(lane_q,absorb_word_q,tail_len_q,
                                                       absorb_full_q,tail_base_q);
                phase_q<=P_ABSORB_UPDATE;
              end
              P_ABSORB_UPDATE: begin
                state_q[lane_q][absorb_word_q*64 +: 64] <=
                    state_q[lane_q][absorb_word_q*64 +: 64] ^
                    absorb_word_data_q;
                if (absorb_word_q==5'd20) begin
                    if (absorb_full_q) phase_q<=P_ABSORB_LAUNCH;
                    else if (lane_q==3) begin
                        phase_q<=P_IDLE; busy_q<=0; done_q<=1; context_valid_q<=1;
                    end else begin lane_q<=lane_q+1'b1; phase_q<=P_ABSORB_INIT; end
                end else begin
                    absorb_word_q<=absorb_word_q+1'b1;
                    phase_q<=P_ABSORB_WORD;
                end
              end
              P_ABSORB_LAUNCH: begin core_start_q<=1; phase_q<=P_ABSORB_WAIT; end
              P_ABSORB_WAIT: if (core_done) begin
                state_q[lane_q]<=core_result;
                absorb_full_q<=0; absorb_word_q<=0; phase_q<=P_ABSORB_WORD;
              end
              P_SQUEEZE_LAUNCH: begin core_start_q<=1; phase_q<=P_SQUEEZE_WAIT; end
              P_SQUEEZE_WAIT: if (core_done) begin
                state_q[lane_q]<=core_result;
                for (integer w=0;w<42;w=w+1)
                    output_words[lane_q*42+w]<=core_result[w*32 +: 32];
                if (lane_q==3) begin phase_q<=P_IDLE; busy_q<=0; done_q<=1; end
                else begin lane_q<=lane_q+1'b1; phase_q<=P_SQUEEZE_LAUNCH; end
              end
              default: begin end
            endcase

            if (s_axi_arvalid && s_axi_arready) begin
                s_axi_rvalid<=1; read_value=0; read_response=RESP_OKAY;
                if (s_axi_araddr[1:0]!=0) read_response=RESP_SLVERR;
                else if (s_axi_araddr==ADDR_CTRL) read_value=0;
                else if (s_axi_araddr==ADDR_STATUS)
                    read_value={27'b0,context_valid_q,timeout_q,error_q,done_q,busy_q};
                else if (s_axi_araddr==ADDR_WDOG) read_value=watchdog_limit_q;
                else if (s_axi_araddr==ADDR_ID) read_value=ID_VALUE;
                else if (s_axi_araddr==ADDR_VERSION) read_value=32'h0001_0000;
                else if (s_axi_araddr==ADDR_INLEN) read_value=input_len_q;
                else if (s_axi_araddr>=ADDR_OUTPUT && s_axi_araddr<ADDR_OUTPUT+12'd672) begin
                    word_index=(s_axi_araddr-ADDR_OUTPUT)>>2;
                    if (clear_commit || busy_q || !done_q || !context_valid_q)
                        read_response=RESP_SLVERR;
                    else read_value=output_words[word_index];
                end else read_response=RESP_SLVERR;
                s_axi_rdata<=read_value; s_axi_rresp<=read_response;
                if (read_response!=RESP_OKAY && !clear_commit) error_q<=1;
            end
        end
    end
endmodule
