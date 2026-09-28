`timescale 1ns/1ps
module tb_ghash;
    reg clk = 0, resetn = 0, zeroize = 0;
    always #5 clk = !clk;
    reg gf_start = 0;
    reg [127:0] gf_x = 0, gf_y = 0;
    wire gf_ready, gf_done;
    wire [127:0] gf_result;
    gf128_mul standalone(.clk(clk), .resetn(resetn), .zeroize(zeroize), .start(gf_start),
                         .x(gf_x), .y(gf_y), .ready(gf_ready), .done(gf_done), .result(gf_result));

    reg start = 0, block_valid = 0, block_is_ciphertext = 0, finish = 0;
    reg [127:0] h = 0, block_data = 0;
    reg [4:0] block_bytes = 0;
    wire start_ready, block_ready, finish_ready, state_valid, digest_valid, error;
    wire [127:0] state;
    ghash dut(.clk(clk), .resetn(resetn), .zeroize(zeroize), .start(start),
              .start_ready(start_ready), .h(h), .block_valid(block_valid),
              .block_ready(block_ready), .block_data(block_data), .block_bytes(block_bytes),
              .block_is_ciphertext(block_is_ciphertext), .finish(finish),
              .finish_ready(finish_ready), .state(state), .state_valid(state_valid),
              .digest_valid(digest_valid), .error(error));

    task automatic begin_session(input [127:0] key);
        begin
            @(negedge clk); h = key; start = 1;
            if (!start_ready) $fatal(1, "start not ready");
            @(posedge clk); @(negedge clk); start = 0;
            if (state !== 0 || error) $fatal(1, "session did not clear state");
        end
    endtask
    task automatic send_block(input bit ciphertext, input [4:0] count,
                              input [127:0] data, input [127:0] expected);
        integer elapsed;
        begin
            @(negedge clk); block_is_ciphertext = ciphertext; block_bytes = count;
            block_data = data; block_valid = 1;
            if (!block_ready) $fatal(1, "block not ready");
            @(posedge clk); @(negedge clk); block_valid = 0;
            if (block_ready || finish_ready) $fatal(1, "multiply did not apply backpressure");
            elapsed = 0;
            while (!state_valid && elapsed < 133) begin @(negedge clk); elapsed = elapsed + 1; end
            if (!state_valid || digest_valid || error || state !== expected)
                $fatal(1, "GHASH block mismatch count=%0d actual=%h expected=%h", count, state, expected);
        end
    endtask
    task automatic end_session(input [127:0] expected);
        integer elapsed;
        begin
            @(negedge clk); finish = 1;
            if (!finish_ready) $fatal(1, "finish not ready");
            @(posedge clk); @(negedge clk); finish = 0;
            elapsed = 0;
            while (!digest_valid && elapsed < 133) begin @(negedge clk); elapsed = elapsed + 1; end
            if (!digest_valid || !state_valid || error || state !== expected || !start_ready)
                $fatal(1, "GHASH final mismatch actual=%h expected=%h", state, expected);
        end
    endtask
    task automatic test_mul(input [127:0] x, input [127:0] y, input [127:0] expected);
        integer elapsed;
        begin
            @(negedge clk); gf_x = x; gf_y = y; gf_start = 1;
            if (!gf_ready) $fatal(1, "multiplier not ready");
            @(posedge clk); @(negedge clk); gf_start = 0;
            elapsed = 0;
            while (!gf_done && elapsed < 129) begin @(negedge clk); elapsed = elapsed + 1; end
            if (!gf_done || elapsed != 128 || gf_result !== expected || !gf_ready)
                $fatal(1, "GF product mismatch cycles=%0d actual=%h expected=%h",
                       elapsed, gf_result, expected);
        end
    endtask

    integer file, fields, gf_count, case_count, blocks, i, j, kind, bytes;
    reg [127:0] x, y, expected, block, key;
    string vectors;
    initial begin
        repeat (4) @(negedge clk); resetn = 1;
        if (!$value$plusargs("VECTORS=%s", vectors)) $fatal(1, "missing vectors");
        file = $fopen(vectors, "r");
        if (!file) $fatal(1, "cannot open vectors");
        fields = $fscanf(file, "%d", gf_count);
        if (fields != 1 || gf_count < 5) $fatal(1, "missing GF vectors");
        for (i = 0; i < gf_count; i = i + 1) begin
            fields = $fscanf(file, "%h %h %h", x, y, expected);
            if (fields != 3) $fatal(1, "malformed GF vector");
            test_mul(x, y, expected);
        end
        fields = $fscanf(file, "%d", case_count);
        if (fields != 1 || case_count < 20) $fatal(1, "missing GHASH cases");
        for (i = 0; i < case_count; i = i + 1) begin
            fields = $fscanf(file, "%h %d", key, blocks);
            if (fields != 2) $fatal(1, "malformed GHASH case");
            begin_session(key);
            for (j = 0; j < blocks; j = j + 1) begin
                fields = $fscanf(file, "%d %d %h %h", kind, bytes, block, expected);
                if (fields != 4 || bytes < 1 || bytes > 16) $fatal(1, "malformed GHASH block");
                send_block(kind != 0, bytes, block, expected);
            end
            fields = $fscanf(file, "%h", expected);
            if (fields != 1) $fatal(1, "missing length-block state");
            end_session(expected);
        end
        $fclose(file);

        // Reject malformed byte counts and never accept another AAD block after ciphertext.
        begin_session(128'h1);
        @(negedge clk); block_valid = 1; block_bytes = 0; block_data = 0;
        @(posedge clk); @(negedge clk); block_valid = 0;
        if (!error || finish_ready || block_ready) $fatal(1, "invalid block was accepted");
        zeroize = 1; @(posedge clk); @(negedge clk); zeroize = 0;
        if (error || state !== 0 || dut.hash_key !== 0 || dut.mul.result !== 0)
            $fatal(1, "zeroize did not clear GHASH");
        begin_session(0);
        send_block(1, 16, 128'h1234, 0);
        @(negedge clk); block_valid = 1; block_is_ciphertext = 0; block_bytes = 1;
        @(posedge clk); @(negedge clk); block_valid = 0;
        if (!error) $fatal(1, "AAD after ciphertext accepted");
        zeroize = 1; @(posedge clk); @(negedge clk); zeroize = 0;
        begin_session(0);
        end_session(0);
        begin_session(128'h1234);
        @(negedge clk); block_valid = 1; block_is_ciphertext = 1;
        block_bytes = 16; block_data = 128'h5678;
        @(posedge clk); @(negedge clk); block_valid = 0;
        repeat (3) @(negedge clk);
        if (block_ready || dut.mul.ready) $fatal(1, "zeroize test missed active multiply");
        zeroize = 1; @(posedge clk); @(negedge clk); zeroize = 0; #1;
        if (state !== 0 || dut.hash_key !== 0 || dut.operand !== 0 ||
            dut.mul.busy || dut.mul.result !== 0 || !start_ready)
            $fatal(1, "busy zeroize did not clear GHASH/multiplier");
        $display("GHASH_PASS gf=%0d cases=%0d per_block=1 reset=1", gf_count, case_count);
        $finish;
    end
endmodule
