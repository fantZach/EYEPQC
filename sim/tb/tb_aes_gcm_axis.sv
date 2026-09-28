`timescale 1ns/1ps
module tb_aes_gcm_axis;
    reg clk = 0, resetn = 0;
    always #5 clk = !clk;
    reg [11:0] awaddr = 0, araddr = 0;
    reg awvalid = 0, wvalid = 0, arvalid = 0, bready = 0, rready = 0;
    reg [31:0] wdata = 0, sdata = 0;
    reg [3:0] wstrb = 0, skeep = 0;
    reg svalid = 0, slast = 0, mready = 0;
    wire awready, wready, bvalid, arready, rvalid, sready, mvalid, mlast, irq;
    wire [1:0] bresp, rresp;
    wire [31:0] rdata, mdata;
    wire [3:0] mkeep;
    aes_gcm_axis dut(.aclk(clk), .aresetn(resetn),
        .s_axi_awaddr(awaddr), .s_axi_awprot(3'b0), .s_axi_awvalid(awvalid), .s_axi_awready(awready),
        .s_axi_wdata(wdata), .s_axi_wstrb(wstrb), .s_axi_wvalid(wvalid), .s_axi_wready(wready),
        .s_axi_bresp(bresp), .s_axi_bvalid(bvalid), .s_axi_bready(bready),
        .s_axi_araddr(araddr), .s_axi_arprot(3'b0), .s_axi_arvalid(arvalid), .s_axi_arready(arready),
        .s_axi_rdata(rdata), .s_axi_rresp(rresp), .s_axi_rvalid(rvalid), .s_axi_rready(rready),
        .s_axis_tdata(sdata), .s_axis_tkeep(skeep), .s_axis_tvalid(svalid),
        .s_axis_tlast(slast), .s_axis_tready(sready),
        .m_axis_tdata(mdata), .m_axis_tkeep(mkeep), .m_axis_tvalid(mvalid),
        .m_axis_tlast(mlast), .m_axis_tready(mready), .irq(irq));

    reg [31:0] random_state = 32'h4d3038a5;
    always @(negedge clk) begin
        random_state = {random_state[30:0], random_state[31]^random_state[21]^random_state[1]^random_state[0]};
        mready = random_state[0] || random_state[3];
    end
    reg checking = 0, held = 0;
    reg [31:0] held_data;
    reg [3:0] held_keep;
    reg held_last;
    reg [11199:0] expected_cipher;
    reg [127:0] expected_tag;
    integer expected_length = 0, output_bytes = 0, stalls = 0;
    integer lane;
    reg [7:0] observed, wanted;
    always @(posedge clk) if (resetn && checking) begin
        if (held && (!mvalid || mdata !== held_data || mkeep !== held_keep || mlast !== held_last))
            $fatal(1, "AXIS output changed under backpressure");
        held = mvalid && !mready;
        if (held) begin held_data = mdata; held_keep = mkeep; held_last = mlast; stalls = stalls + 1; end
        if (mvalid && mready) begin
            if (!(mkeep == 4'h1 || mkeep == 4'h3 || mkeep == 4'h7 || mkeep == 4'hf))
                $fatal(1, "invalid output TKEEP=%h", mkeep);
            for (lane = 0; lane < 4; lane = lane + 1) if (mkeep[lane]) begin
                observed = mdata[8*lane +: 8];
                wanted = output_bytes < expected_length ?
                    expected_cipher[11199 - 8*output_bytes -: 8] :
                    expected_tag[127 - 8*(output_bytes-expected_length) -: 8];
                if (output_bytes >= expected_length + 16 || observed !== wanted)
                    $fatal(1, "output byte %0d actual=%h expected=%h tag=%h mask=%h hash=%h h=%h", output_bytes, observed, wanted, dut.engine.tag, dut.engine.tag_mask, dut.engine.auth.state, dut.engine.hash_key);
                output_bytes = output_bytes + 1;
            end
            if (mlast !== (output_bytes == expected_length + 16))
                $fatal(1, "TLAST at wrong length %0d/%0d", output_bytes, expected_length+16);
        end
    end
    initial begin #100000000; $fatal(1, "M08 timeout"); end

    task automatic wr(input [11:0] addr, input [31:0] value,
                      input [3:0] strb, input integer skew, input [1:0] expected);
        begin
            fork
                begin
                    if (skew < 0) repeat (-skew) @(posedge clk);
                    @(negedge clk); awaddr = addr; awvalid = 1;
                    do @(posedge clk); while (!awready);
                    @(negedge clk); awvalid = 0;
                end
                begin
                    if (skew > 0) repeat (skew) @(posedge clk);
                    @(negedge clk); wdata = value; wstrb = strb; wvalid = 1;
                    do @(posedge clk); while (!wready);
                    @(negedge clk); wvalid = 0;
                end
            join
            while (!bvalid) @(negedge clk);
            repeat (2) begin
                @(negedge clk);
                if (!bvalid || bresp !== expected || awready || wready)
                    $fatal(1, "write %h resp=%b expected=%b", addr, bresp, expected);
            end
            bready = 1; @(negedge clk); bready = 0;
        end
    endtask
    task automatic rd(input [11:0] addr, output [31:0] value, input [1:0] expected);
        begin
            @(negedge clk); araddr = addr; arvalid = 1;
            do @(posedge clk); while (!arready);
            @(negedge clk); arvalid = 0;
            while (!rvalid) @(negedge clk);
            repeat (2) begin
                @(negedge clk);
                if (!rvalid || rresp !== expected || arready)
                    $fatal(1, "read %h resp=%b", addr, rresp);
            end
            value = rdata; rready = 1; @(negedge clk); rready = 0;
        end
    endtask
    task automatic load_config(input [127:0] key, input [95:0] nonce,
                               input [511:0] aad, input integer aad_len, payload_len);
        integer k;
        begin
            for (k = 0; k < 4; k = k + 1) wr('h20+k*4, key[127-k*32 -: 32], 15, k%3-1, 0);
            for (k = 0; k < 3; k = k + 1) wr('h30+k*4, nonce[95-k*32 -: 32], 15, 0, 0);
            for (k = 0; k < 16; k = k + 1) wr('h40+k*4, aad[511-k*32 -: 32], 15, 0, 0);
            wr('h08, payload_len, 15, 0, 0);
            wr('h0c, aad_len, 15, 0, 0);
        end
    endtask
    task automatic send_plain(input [11199:0] plain, input integer length);
        integer pos, k, count;
        begin
            pos = 0;
            while (pos < length) begin
                count = length-pos >= 4 ? 4 : length-pos;
                @(negedge clk); sdata = 0; skeep = (1 << count)-1;
                slast = pos+count == length; svalid = 1;
                for (k = 0; k < count; k = k + 1)
                    sdata[k*8 +: 8] = plain[11199 - 8*(pos+k) -: 8];
                do @(posedge clk); while (!sready);
                @(negedge clk); svalid = 0; pos = pos+count;
            end
        end
    endtask
    integer file, fields, cases, n, aad_len, payload_len, wait_cycles, k;
    reg [127:0] key, tag_expected, observed_tag;
    reg [95:0] nonce;
    reg [511:0] aad;
    reg [11199:0] plain, cipher_expected;
    reg [31:0] word_value;
    string vectors;
    initial begin
        repeat (4) @(negedge clk); resetn = 1;
        if (!$value$plusargs("VECTORS=%s", vectors)) $fatal(1, "missing vectors");
        file = $fopen(vectors, "r");
        if (!file) $fatal(1, "cannot open vectors");
        fields = $fscanf(file, "%d", cases);
        if (fields != 1 || cases < 100) $fatal(1, "missing GCM cases");
        rd('h14, word_value, 0);
        if (word_value !== 32'h47434d31) $fatal(1, "bad ID");
        rd('h20, word_value, 2); // Key is write-only.
        wr('h20, 32'h11223344, 15, -2, 0);
        wr('h20, 32'h0000aa00, 4'h2, 2, 0);
        if (dut.regs.key[127:96] !== 32'h1122aa44) $fatal(1, "WSTRB key update");
        wr('h21, 32'h12345678, 15, 0, 2); // Misaligned.
        wr('h100, 32'h12345678, 15, 0, 2); // No truncated-address alias.
        wr(0, 2, 15, 0, 0);
        wr('h0c, 65, 15, 0, 0);
        wr(0, 1, 15, 0, 2); // Overlong AAD rejected.
        wr(0, 2, 15, 0, 0);
        wr('h08, 1401, 15, 0, 0);
        wr(0, 1, 15, 0, 2); // Overlong packet rejected.
        wr(0, 2, 15, 0, 0);
        for (n = 0; n < cases; n = n + 1) begin
            fields = $fscanf(file, "%h %h %d %d %h %h %h %h",
                            key, nonce, aad_len, payload_len, aad, plain, cipher_expected, tag_expected);
            if (fields != 8) $fatal(1, "malformed vector %0d fields=%0d", n, fields);
            load_config(key, nonce, aad, aad_len, payload_len);
            expected_cipher = cipher_expected; expected_tag = tag_expected;
            expected_length = payload_len; output_bytes = 0; checking = 1;
            wr(0, 1, 15, 0, 0);
            if (n == 2) begin
                wr('h20, 32'hdeadbeef, 15, 1, 2);
                wr('h30, 32'hdeadbeef, 15, -1, 2);
                wr('h40, 32'hdeadbeef, 15, 0, 2);
            end // Busy writes must not alter Key, Nonce or AAD.
            send_plain(plain, payload_len);
            wait_cycles = 0;
            while (!irq && wait_cycles < 40000) begin @(negedge clk); wait_cycles = wait_cycles+1; end
            if (!irq || output_bytes != payload_len+16 || dut.engine.error)
                $fatal(1, "packet %0d incomplete bytes=%0d/%0d", n, output_bytes, payload_len+16);
            for (k = 0; k < 4; k = k + 1) begin
                rd('h80+k*4, word_value, 0);
                observed_tag[127-k*32 -: 32] = word_value;
            end
            if (observed_tag !== tag_expected) $fatal(1, "tag register mismatch %0d", n);
            rd('h10, word_value, 0);
            if (word_value !== n+1) $fatal(1, "packet count %0d actual=%0d", n, word_value);
            checking = 0; held = 0;
        end
        $fclose(file);
        wr(0, 4, 15, 0, 0);
        if (irq) $fatal(1, "done interrupt did not clear");
        // Malformed input is fail-closed; zeroize clears all secret state.
        load_config(128'h1234, 96'h5678, 512'b0, 0, 5);
        wr(0, 1, 15, 0, 0);
        while (!sready) @(negedge clk);
        @(negedge clk); sdata = 32'h11223344; skeep = 4'h5; slast = 0; svalid = 1;
        @(posedge clk); @(negedge clk); svalid = 0;
        if (!dut.engine.error || irq) $fatal(1, "invalid TKEEP not rejected");
        wr(0, 2, 15, 0, 0);
        @(negedge clk);
        if (dut.regs.key !== 0 || dut.regs.nonce !== 0 || dut.regs.aad !== 0 ||
            dut.engine.packet_key !== 0 || dut.engine.tag !== 0 ||
            dut.engine.auth.hash_key !== 0 || dut.engine.aes.keymem.key_mem[0] !== 0)
            $fatal(1, "zeroize left secret state");
        for (k = 0; k < 15; k = k + 1)
            if (dut.engine.aes.keymem.key_mem[k] !== 0)
                $fatal(1, "zeroize left round key %0d", k);
        load_config(128'h1234, 96'h5678, 512'b0, 0, 5);
        wr(0, 1, 15, 0, 0);
        while (!sready) @(negedge clk);
        @(negedge clk); sdata = 32'h11223344; skeep = 4'hf; slast = 1; svalid = 1;
        @(posedge clk); @(negedge clk); svalid = 0;
        if (!dut.engine.error || mvalid) $fatal(1, "early TLAST not rejected");
        wr(0, 2, 15, 0, 0);
        load_config(128'h1234, 96'h5678, 512'b0, 0, 16);
        wr(0, 1, 15, 0, 0);
        while (!sready) @(negedge clk);
        wr(0, 2, 15, 0, 0); // Abort an active packet.
        @(negedge clk);
        if (dut.engine.busy || dut.engine.packet_key !== 0 || mvalid)
            $fatal(1, "busy zeroize failed");
        load_config(128'h1234, 96'h5678, 512'b0, 0, 16);
        wr(0, 1, 15, 0, 0);
        repeat (6) @(negedge clk); resetn = 0;
        repeat (3) @(negedge clk);
        if (dut.regs.key !== 0 || dut.engine.packet_key !== 0 || dut.engine.aes.keymem.key_mem[0] !== 0)
            $fatal(1, "reset left secret state");
        resetn = 1;
        rd('h10, word_value, 0);
        if (word_value !== 0) $fatal(1, "reset did not clear count");
        if (stalls == 0) $fatal(1, "random backpressure never occurred");
        $display("AES_GCM_AXIS_PASS cases=%0d stalls=%0d limits=1 busy_write=1 zeroize=1 reset=1", cases, stalls);
        $finish;
    end
endmodule
