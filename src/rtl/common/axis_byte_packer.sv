// Byte zero occupies TDATA[7:0]. One elastic output beat, no combinational READY loop.
module axis_byte_packer #(
    parameter integer DATA_WIDTH = 32
) (
    input wire clk, resetn,
    input wire [7:0] s_data,
    input wire s_valid, s_last, s_first,
    output wire s_ready,
    output reg [DATA_WIDTH-1:0] m_axis_tdata,
    output reg [DATA_WIDTH/8-1:0] m_axis_tkeep,
    output reg m_axis_tvalid, m_axis_tlast, m_axis_tuser,
    input wire m_axis_tready
);
    localparam integer BYTES = DATA_WIDTH/8;
    reg [$clog2(BYTES)-1:0] position;
    assign s_ready = resetn && (!m_axis_tvalid || m_axis_tready);
    initial if (DATA_WIDTH != 32 && DATA_WIDTH != 64) $fatal(1, "Use 32 or 64 bit AXIS");

    always @(posedge clk or negedge resetn) begin
        if (!resetn) begin
            position <= 0;
            m_axis_tdata <= 0;
            m_axis_tkeep <= 0;
            m_axis_tvalid <= 0;
            m_axis_tlast <= 0;
            m_axis_tuser <= 0;
        end else begin
            if (m_axis_tvalid && m_axis_tready) m_axis_tvalid <= 0;
            if (s_valid && s_ready) begin
                if (position == 0) begin
                    m_axis_tdata <= {{(DATA_WIDTH-8){1'b0}}, s_data};
                    m_axis_tkeep <= {{(BYTES-1){1'b0}}, 1'b1};
                    m_axis_tuser <= s_first;
                end else begin
                    m_axis_tdata[8*position +: 8] <= s_data;
                    m_axis_tkeep[position] <= 1;
                end
                if (s_last || position == BYTES-1) begin
                    position <= 0;
                    m_axis_tvalid <= 1;
                    m_axis_tlast <= s_last;
                end else position <= position + 1'b1;
            end
        end
    end
endmodule
