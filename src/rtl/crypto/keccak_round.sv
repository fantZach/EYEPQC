// Keccak-f[1600] single-round combinational datapath.
// State is lane-major A[x + 5*y], each lane little-endian as required by FIPS 202.
module keccak_round (
    input  logic [1599:0] state_i,
    input  logic [4:0]    round_i,
    output logic [1599:0] state_o
);
    function automatic [63:0] rol64(input [63:0] v, input integer n);
        begin
            if (n == 0) rol64 = v;
            else rol64 = (v << n) | (v >> (64-n));
        end
    endfunction

    function automatic [1599:0] transform(input [1599:0] source, input [4:0] round_no);
        reg [63:0] a [0:24];
        reg [63:0] r [0:24];
        reg [63:0] b [0:24];
        reg [63:0] c [0:4];
        reg [63:0] d [0:4];
        reg [63:0] rc;
        integer x, y, i;
        begin
        for (i=0; i<25; i=i+1) a[i] = source[64*i +: 64];
        for (x=0; x<5; x=x+1) c[x] = a[x] ^ a[x+5] ^ a[x+10] ^ a[x+15] ^ a[x+20];
        for (x=0; x<5; x=x+1) d[x] = c[(x+4)%5] ^ rol64(c[(x+1)%5], 1);
        for (y=0; y<5; y=y+1)
            for (x=0; x<5; x=x+1)
                a[x+5*y] = a[x+5*y] ^ d[x];

        // Rho offsets indexed as x + 5*y.
        r[0]  = rol64(a[0], 0);   r[1]  = rol64(a[1], 1);   r[2]  = rol64(a[2], 62);
        r[3]  = rol64(a[3], 28);  r[4]  = rol64(a[4], 27);  r[5]  = rol64(a[5], 36);
        r[6]  = rol64(a[6], 44);  r[7]  = rol64(a[7], 6);   r[8]  = rol64(a[8], 55);
        r[9]  = rol64(a[9], 20);  r[10] = rol64(a[10], 3);  r[11] = rol64(a[11], 10);
        r[12] = rol64(a[12], 43); r[13] = rol64(a[13], 25); r[14] = rol64(a[14], 39);
        r[15] = rol64(a[15], 41); r[16] = rol64(a[16], 45); r[17] = rol64(a[17], 15);
        r[18] = rol64(a[18], 21); r[19] = rol64(a[19], 8);  r[20] = rol64(a[20], 18);
        r[21] = rol64(a[21], 2);  r[22] = rol64(a[22], 61); r[23] = rol64(a[23], 56);
        r[24] = rol64(a[24], 14);
        for (y=0; y<5; y=y+1)
            for (x=0; x<5; x=x+1)
                b[y + 5*((2*x + 3*y)%5)] = r[x+5*y];

        for (y=0; y<5; y=y+1)
            for (x=0; x<5; x=x+1)
                a[x+5*y] = b[x+5*y] ^ ((~b[((x+1)%5)+5*y]) & b[((x+2)%5)+5*y]);

        case (round_no)
          0: rc=64'h0000000000000001; 1: rc=64'h0000000000008082;
          2: rc=64'h800000000000808a; 3: rc=64'h8000000080008000;
          4: rc=64'h000000000000808b; 5: rc=64'h0000000080000001;
          6: rc=64'h8000000080008081; 7: rc=64'h8000000000008009;
          8: rc=64'h000000000000008a; 9: rc=64'h0000000000000088;
          10: rc=64'h0000000080008009; 11: rc=64'h000000008000000a;
          12: rc=64'h000000008000808b; 13: rc=64'h800000000000008b;
          14: rc=64'h8000000000008089; 15: rc=64'h8000000000008003;
          16: rc=64'h8000000000008002; 17: rc=64'h8000000000000080;
          18: rc=64'h000000000000800a; 19: rc=64'h800000008000000a;
          20: rc=64'h8000000080008081; 21: rc=64'h8000000000008080;
          22: rc=64'h0000000080000001; 23: rc=64'h8000000080008008;
          default: rc=64'h0;
        endcase
        a[0] = a[0] ^ rc;
        for (i=0; i<25; i=i+1) transform[64*i +: 64] = a[i];
    end
    endfunction

    always_comb state_o = transform(state_i, round_i);
endmodule
