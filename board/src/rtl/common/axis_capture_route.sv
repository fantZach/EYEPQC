// Route changes only while both DMAs are reset/idle. Mode 3 disables all routes.
module axis_capture_route (
    input wire [1:0] mode,
    input wire [31:0] camera_data, test_data,
    input wire [3:0] camera_keep, test_keep,
    input wire camera_valid, camera_last, test_valid, test_last,
    output wire camera_ready, test_ready,
    output wire [31:0] capture_data, crypto_data,
    output wire [3:0] capture_keep, crypto_keep,
    output wire capture_valid, capture_last, crypto_valid, crypto_last,
    input wire capture_ready, crypto_ready
);
    assign capture_data = mode == 1 ? camera_data : test_data;
    assign capture_keep = mode == 1 ? camera_keep : test_keep;
    assign capture_last = mode == 1 ? camera_last : test_last;
    assign capture_valid = mode == 1 ? camera_valid : mode == 0 ? test_valid : 1'b0;
    assign camera_ready = mode == 1 && capture_ready;
    assign test_ready = mode == 0 ? capture_ready : mode == 2 ? crypto_ready : 1'b0;
    assign crypto_data = test_data;
    assign crypto_keep = test_keep;
    assign crypto_last = test_last;
    assign crypto_valid = mode == 2 && test_valid;
endmodule
