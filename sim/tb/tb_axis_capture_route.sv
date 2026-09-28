`timescale 1ns/1ps
module tb_axis_capture_route;
    reg [1:0] mode;
    reg [31:0] cd,td;
    reg [3:0] ck,tk;
    reg cv,cl,tv,tl,cr,rr;
    wire cready,tready,v,l,rv,rl;
    wire [31:0] d,rd;
    wire [3:0] k,rk;
    axis_capture_route dut(.mode(mode), .camera_data(cd), .test_data(td),
        .camera_keep(ck), .test_keep(tk), .camera_valid(cv), .camera_last(cl),
        .test_valid(tv), .test_last(tl), .camera_ready(cready), .test_ready(tready),
        .capture_data(d), .capture_keep(k), .capture_valid(v), .capture_last(l),
        .crypto_data(rd), .crypto_keep(rk), .crypto_valid(rv), .crypto_last(rl),
        .capture_ready(cr), .crypto_ready(rr));
    integer i,m;
    initial begin
        for(m=0;m<4;m=m+1) begin
            mode=m;
            for(i=0;i<1000;i=i+1) begin
                cd=$random;td=$random;ck=$random;tk=$random;
                cv=$random;cl=$random;tv=$random;tl=$random;cr=$random;rr=$random;#1;
                if({d,k,l} !== (mode==1 ? {cd,ck,cl} : {td,tk,tl})) $fatal(1,"Capture fields");
                if(v !== (mode==1 ? cv : mode==0 ? tv : 1'b0)) $fatal(1,"Capture valid");
                if(cready !== (mode==1 && cr)) $fatal(1,"Camera backpressure");
                if(tready !== (mode==0 ? cr : mode==2 ? rr : 1'b0)) $fatal(1,"Test backpressure");
                if({rd,rk,rl} !== {td,tk,tl} || rv !== (mode==2 && tv)) $fatal(1,"Crypto loopback");
            end
        end
        $display("AXIS_ROUTE_PASS modes=4 randomized=4000");$finish;
    end
endmodule
