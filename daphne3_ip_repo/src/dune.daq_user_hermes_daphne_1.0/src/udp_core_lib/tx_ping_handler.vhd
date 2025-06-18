-- <h---------------------------------------------------------------------------
--! @file tx_ping_handler.vhd
--! @page txpinghandlerpage Tx Ping Handler
--!
--! \includedoc esdg_stfc_image.md
--!
--! ### Brief ###
--! The Tx Ping Handler receives Ping Packets and generates a Reply. Only the
--! Ping request/reply code is changed for the reply.
--!
--! \includedoc txpinghandler.md
--!
--! ### License ###
--! Copyright(c) 2021 UNITED KINGDOM RESEARCH AND INNOVATION
--! Licensed under the BSD 3-Clause license. See LICENSE file in the project
--! root for details.
-- ---------------------------------------------------------------------------h>
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

library udp_core_lib;
use work.udp_core_pkg.all;
use work.udp_proj_pkg.all;

library axi4_lib;
use work.axi4s_pkg.all;

library common_stfc_lib;
use work.common_stfc_pkg.all;

entity tx_ping_handler is
    generic(
        G_FPGA_VENDOR           : string  := "xilinx";                      --! Selects the FPGA Vendor for Compilation
        G_FPGA_FAMILY           : string  := "all";                         --! Selects the FPGA Family for Compilation
        G_FIFO_IMPLEMENTATION   : string  := "auto";                        --! Selects how the Fitter implements the FIFO Memory
        G_UDP_CORE_BYTES        : natural := 8                              --! Width Of Data Busses In Bytes
    );
    port(
        clk                     : in  std_logic;                            --! Tx Path Clock
        rst_s_n                 : in  std_logic;                            --! synchronous Active Low reset
        tx_ping_s_mosi          : in  t_axi4s_mosi;                         --! Ping data from Rx Path via FIFO
        tx_ping_s_miso          : out t_axi4s_miso;                         --! Ready to Ping Data FIFO
        tx_ping_addr_mosi       : in  t_axi4s_mosi;                         --! Ping Routing Addr from Rx PAth via FIFO
        tx_ping_addr_miso       : out t_axi4s_miso;                         --! Ready to Ping Routing Addr
        ping_rdy                : out std_logic;                            --! Ping Packet Is Ready To Send
        ping_done               : out std_logic;                            --! Ping Packet Has Finished Sending
        ping_start              : in  std_logic;                            --! Go Ahead Signal for Queued Ping Packet
        ping_dst_mac_out        : out std_logic_vector(6 * 8 - 1 downto 0); --! MAC Address For Header Constructor To Construct Replies To
        ping_dst_ip_out         : out std_logic_vector(4 * 8 - 1 downto 0); --! IP Address For Header Constructor To Construct Replies To
        tx_ping_m_mosi          : out t_axi4s_mosi;                         --! Ping Reply
        tx_ping_m_miso          : in  t_axi4s_miso;                         --! Ping Reply Ready - Unused
        ip_length               : out std_logic_vector(15 downto 0)         --! Length of Pings IPV4 Packet for Heady Constructor
    );
end entity tx_ping_handler;

architecture behavioural of tx_ping_handler is

component  axi4s_fifo is
     generic (
          g_fpga_vendor        : string        := "xilinx";      --For xpm doesnt affect anything
          g_fpga_family        : string        := "all";         --For xpm doesnt affect anything
          g_implementation     : string        := "distributed"; --For xpm doesnt affect anything
          g_dual_clock         : boolean       := true;
          g_wr_adr_width       : integer       := 5;
          g_prog_full_val      : positive      := 20;
          g_sanity_check       : boolean       := true;  --TODO not implemented yet
          g_in_endianess_swap  : boolean       := false; --TODO not implemented yet
          g_out_endianess_swap : boolean       := false; --TODO not implemented yet
          g_axi4s_descr        : t_axi4s_descr := (tdata_nof_bytes => 4,
          tid_width                                                => 32,
          tuser_width                                              => 32,
          has_tlast                                                => 1,
          has_tkeep                                                => 1,
          has_tid                                                  => 0,
          has_tuser                                                => 0);
          g_in_tdata_nof_bytes       : integer := 4;
          g_out_tdata_nof_bytes      : integer := 4;
          g_bram_partition_width     : integer := 0;    --TODO not implemented yet
          g_hold_last_read           : boolean := true; --TODO not implemented yet
          g_full_packet              : boolean := false;
          g_packet_fifo_wr_adr_width : integer := 4 --TODO not implemented yet
     );
     port (
          s_axi_clk    : in std_logic;
          s_axi_rst_n  : in std_logic;
          m_axi_clk    : in std_logic;
          m_axi_rst_n  : in std_logic;
          axi4s_s_mosi : in t_axi4s_mosi;
          axi4s_s_miso : out t_axi4s_miso;
          axi4s_m_mosi : out t_axi4s_mosi;
          axi4s_m_miso : in t_axi4s_miso
     );
end component;

component tx_ping_chksm is
    generic(
        G_UDP_CORE_WIDTH    : integer := 8                                              --! Width of Data bus in Bytes
    );
    port(
        clk                 : in  std_logic;                                            --! Clk
        rst_s_n             : in  std_logic;                                            --! Active Low synchronous reset
        data_in             : in  std_logic_vector(G_UDP_CORE_WIDTH * 8 - 1 downto 0);  --! Ping Data in
        width_in            : in  std_logic_vector(G_UDP_CORE_WIDTH - 1 downto 0);      --! Width of Valid Data
        valid               : in  std_logic;                                            --! Ping Valid
        sof                 : in  std_logic;                                            --! Start of Packet
        eof                 : in  std_logic;                                            --! End of Packet
        done                : out std_logic;                                            --! Calculations Finished
        out_chksm           : out std_logic_vector(15 downto 0)                         --! Checksum Out
    );
end component  ;


component tx_ping_chksm_1bytew is
    port(
        clk         : in  std_logic;                    --! Clk
        rst_s_n     : in  std_logic;                    --! Active Low synchronous reset
        data_in     : in  std_logic_vector(7 downto 0); --! Ping Data in
        valid       : in  std_logic;                    --! Valid in
        sof         : in  std_logic;                    --! Start of Packet
        eof         : in  std_logic;                    --! End of Packet
        done        : out std_logic;                    --! Calculations Finished
        out_chksm   : out std_logic_vector(15 downto 0) --! Checksum Out
    );
end component  ;




    --CONSTANTS
    constant C_ICMP_HDR             : integer                       := 8;
    constant C_HDR_WORDS            : integer                       := header_words(C_ICMP_HDR, G_UDP_CORE_BYTES) + 1;
    constant C_FIFO_TOTAL_BYTES     : integer                       := 129; -- Store Over 2 * 64 byte Packets
    constant C_ADDR_WIDTH           : integer                       := udp_maximum(C_FIFO_MIN_WIDTH, log_2_ceil(C_FIFO_TOTAL_BYTES / G_UDP_CORE_BYTES));
    constant C_FIFO_CAPACITY        : integer                       := 2**C_ADDR_WIDTH;
    constant C_PING_TYPE_CODE_REPLY : std_logic_vector(15 downto 0) := X"0000";

    signal dst_mac : std_logic_vector(6 * 8 - 1 downto 0);
    signal dst_ip  : std_logic_vector(4 * 8 - 1 downto 0);

    --GENERAL SIGNALS
    signal checksum_incorrect : std_logic;
    signal output_length      : integer;
    signal ping_started       : std_logic;
    signal ping_triggered     : std_logic;

    --AXI4S RECORD SIGNALS
    signal ping_in_int_mosi : t_axi4s_mosi;
    signal out_of_fifo_mosi : t_axi4s_mosi;
    signal out_of_fifo_miso : t_axi4s_miso;

    --FIXED LENGTH IN/OUTPUT REGISTERS & ALIASES FOR EASILY ACCESSED ICMP AND IPV4 FIELDS
    signal ping_header_reg     : std_logic_vector(C_HDR_WORDS * G_UDP_CORE_BYTES * 8 - 1 downto 0);
    alias ping_type_code       : std_logic_vector(15 downto 0) is ping_header_reg(2 * 8 - 1 downto 0 * 8);
    alias ping_into_chksm      : std_logic_vector(15 downto 0) is ping_header_reg(4 * 8 - 1 downto 2 * 8);
    alias ping_into_identifier : std_logic_vector(15 downto 0) is ping_header_reg(6 * 8 - 1 downto 4 * 8);
    alias ping_into_seq        : std_logic_vector(15 downto 0) is ping_header_reg(8 * 8 - 1 downto 6 * 8);

    --SIGNALS FOR INTERNET CHECKSUM CALCULATIONS
    signal checksum_data_in  : std_logic_vector(G_UDP_CORE_BYTES * 8 - 1 downto 0);
    signal checksum_width_in : std_logic_vector(G_UDP_CORE_BYTES - 1 downto 0);
    signal checksum_valid_in : std_logic;
    signal checksum_sof_in   : std_logic;
    signal checksum_eof_in   : std_logic;
    signal checksum_done     : std_logic;
    signal checksum_calc     : std_logic_vector(15 downto 0);

    type t_tx_ping_handler_next_state is (
        idle,
        tx_receive_ping,
        tx_generating,
        tx_output_hdr,
        tx_output_payload,
        tx_finished
    );

    signal tx_ping_handler_next_state                      : t_tx_ping_handler_next_state := idle;
    signal ip_length_int                                   : std_logic_vector(15 downto 0);
    signal checksum_sof_n                                  : std_logic;
    signal ping_in_int_miso                                : t_axi4s_miso;
    signal tx_ping_addr_miso_tready, tx_ping_s_miso_tready : std_logic;

begin
    ping_in_int_mosi.tdata   <= tx_ping_s_mosi.tdata;
    ping_in_int_mosi.tkeep   <= tx_ping_s_mosi.tkeep;
    ping_in_int_mosi.tlast   <= tx_ping_s_mosi.tlast;
    ping_in_int_mosi.tvalid  <= tx_ping_s_mosi.tvalid and tx_ping_s_miso_tready and ping_in_int_miso.tready; --(tx_ping_s_mosi.tvalid and tx_ping_s_miso.tready) Changed for VHDL-93 Compatibility. Internal Valid Asserted Depends on Incoming Valid And Outgoing Ready
    tx_ping_addr_miso.tready <= tx_ping_addr_miso_tready and ping_in_int_miso.tready; --Addr Ready Depends On Internal Signal And Payload FIFO Ready
    tx_ping_s_miso.tready    <= tx_ping_s_miso_tready and ping_in_int_miso.tready; --Ping Data Ready Depends On Internal Signal And Payload FIFO Ready
    ping_triggered           <= ping_start or ping_started;
    ip_length                <= byte_reverse(ip_length_int);
    ping_dst_mac_out         <= dst_mac;
    ping_dst_ip_out          <= dst_ip;

    --The Ping Payload Needs to Start At different Times Depending On The Width Of The Core
    out_of_fifo_miso.tready <= ping_triggered;

    ping_payload_fifo_inst : axi4s_fifo
        generic map(
            g_fpga_vendor         => G_FPGA_VENDOR,
            g_fpga_family         => G_FPGA_FAMILY,
            g_implementation      => G_FIFO_IMPLEMENTATION,
            g_dual_clock          => false,
            g_wr_adr_width        => C_ADDR_WIDTH,
            g_prog_full_val       => C_FIFO_CAPACITY - 2,
            g_in_tdata_nof_bytes  => G_UDP_CORE_BYTES,
            g_out_tdata_nof_bytes => G_UDP_CORE_BYTES
        )
        port map(
            s_axi_clk    => clk,
            s_axi_rst_n  => rst_s_n,
            m_axi_clk    => clk,
            m_axi_rst_n  => rst_s_n,
            axi4s_s_mosi => ping_in_int_mosi,
            axi4s_s_miso => ping_in_int_miso,
            axi4s_m_mosi => out_of_fifo_mosi,
            axi4s_m_miso => out_of_fifo_miso
        );

    --Ping Reply State Machine Process
    tx_ping_handler_fsm_proc : process(clk)
        variable header_idx_i : integer range 0 to C_HDR_WORDS;
    begin
        if (rising_edge(clk)) then
            if (rst_s_n = '0') then
                ping_done                  <= '0';
                ping_rdy                   <= '0';
                tx_ping_addr_miso_tready   <= '0';
                tx_ping_s_miso_tready      <= '0';
                tx_ping_handler_next_state <= idle;
                tx_ping_m_mosi.tvalid      <= '0';
                checksum_valid_in          <= '0';
                checksum_sof_n             <= '0';
            else

                case tx_ping_handler_next_state is
                    when idle =>
                        ping_done                  <= '0';
                        ping_rdy                   <= '0';
                        tx_ping_addr_miso_tready   <= '0';
                        tx_ping_s_miso_tready      <= '0';
                        tx_ping_handler_next_state <= idle;
                        tx_ping_m_mosi.tvalid      <= '0';
                        checksum_valid_in          <= '0';
                        header_idx_i               := 0;
                        checksum_sof_n             <= '0';
                        output_length              <= 0;

                        if tx_ping_addr_mosi.tvalid = '1' then --and tx_ping_s_mosi.tvalid = '1' then
                            tx_ping_addr_miso_tready   <= '1';
                            tx_ping_s_miso_tready      <= '1';
                            tx_ping_handler_next_state <= tx_receive_ping;
                        end if;

                    when tx_receive_ping =>
                        --Register Addressses From Addr FIFO
                        if tx_ping_addr_miso_tready = '1' and tx_ping_addr_mosi.tvalid = '1' then
                            dst_mac                  <= tx_ping_addr_mosi.tdata(47 + 32 downto 32);
                            dst_ip                   <= tx_ping_addr_mosi.tdata(31 downto 0);
                            tx_ping_addr_miso_tready <= '0';
                        end if;

                        --Read Ping Data From Data FIFO
                        if ping_in_int_mosi.tvalid = '1' then
                            output_length  <= output_length + G_UDP_CORE_BYTES;
                            if header_idx_i < C_HDR_WORDS then
                                ping_header_reg((header_idx_i + 1) * G_UDP_CORE_BYTES * 8 - 1 downto G_UDP_CORE_BYTES * header_idx_i * 8) <= ping_in_int_mosi.tdata(G_UDP_CORE_BYTES * 8 - 1 downto 0);
                                header_idx_i                                                                                              := header_idx_i + 1;
                            end if;
                            checksum_sof_n <= '1';

                            --Assign Data To Checksum Calculator
                            checksum_data_in  <= ping_in_int_mosi.tdata(G_UDP_CORE_BYTES * 8 - 1 downto 0);
                            checksum_width_in <= (G_UDP_CORE_BYTES - 1 downto 0 => '1');
                            checksum_valid_in <= ping_in_int_mosi.tvalid;
                            checksum_sof_in   <= not checksum_sof_n;
                            checksum_eof_in   <= ping_in_int_mosi.tlast;

                            --Last Word Of Incoming Ping
                            if ping_in_int_mosi.tlast = '1' then
                                tx_ping_s_miso_tready      <= '0';
                                checksum_width_in          <= ping_in_int_mosi.tkeep(G_UDP_CORE_BYTES - 1 downto 0);
                                tx_ping_handler_next_state <= tx_generating;
                            else
                                tx_ping_s_miso_tready <= '1';
                            end if;
                        end if;

                    when tx_generating =>
                        --Generate Outpt Ping Header When Checksum Calculations Are Complete
                        if ping_type_code(7 downto 0) = X"08" then
                            if (checksum_done = '1') then
                                ping_type_code(15 downto 0) <= C_PING_TYPE_CODE_REPLY;
                                ping_into_chksm             <= not std_logic_vector(unsigned(not ping_into_chksm) - 8);
                                --(Checksum C0 With Word M0 That Changes To M1. New Checksum C1 = C0 - M0 + M1. In this case ICMP 'Code' Has Changed From Request M0 = X"0008", To Reply M1 = X"0000".)
                                ping_into_identifier        <= ping_into_identifier;
                                if unsigned(checksum_calc) /= unsigned'(X"FFFF") then
                                    checksum_incorrect <= '1';
                                end if;
                                ip_length_int               <= std_logic_vector(to_unsigned(output_length + 20, ip_length'length));
                                ping_rdy                    <= '1';
                                tx_ping_handler_next_state  <= tx_output_hdr;
                                header_idx_i                := 0;
                            end if;
                        else
                            tx_ping_handler_next_state <= idle;
                        end if;

                    when tx_output_hdr =>
                        --Wait for Go Signal The Output Ping  Header
                        if ping_triggered = '1' then
                            ping_started          <= '1';
                            ping_rdy              <= '0';
                            tx_ping_m_mosi.tvalid <= '1';
                            tx_ping_m_mosi.tlast  <= '0';

                            if G_UDP_CORE_BYTES <= C_ICMP_HDR then
                                tx_ping_m_mosi.tdata(G_UDP_CORE_BYTES * 8 - 1 downto 0) <= ping_header_reg((header_idx_i + 1) * G_UDP_CORE_BYTES * 8 - 1 downto G_UDP_CORE_BYTES * header_idx_i * 8);
                                header_idx_i                                            := header_idx_i + 1;
                                if header_idx_i = C_HDR_WORDS then
                                    tx_ping_handler_next_state <= tx_output_payload;
                                end if;
                            else
                                tx_ping_m_mosi.tdata(G_UDP_CORE_BYTES * 8 - 1 downto 0) <= out_of_fifo_mosi.tdata(G_UDP_CORE_BYTES * 8 - 1 downto C_ICMP_HDR * 8) & ping_header_reg(C_ICMP_HDR * 8 - 1 downto 0);
                                tx_ping_handler_next_state                              <= tx_output_payload;
                                if out_of_fifo_mosi.tlast = '1' then
                                    tx_ping_m_mosi.tkeep       <= out_of_fifo_mosi.tkeep;
                                    tx_ping_m_mosi.tlast       <= '1';
                                    ping_started               <= '0';
                                    tx_ping_handler_next_state <= tx_finished;
                                end if;
                            end if;
                        end if;

                    when tx_output_payload =>
                        --Output Ping Payload
                        if ping_triggered = '1' then
                            tx_ping_m_mosi <= out_of_fifo_mosi;
                            if out_of_fifo_mosi.tlast = '1' then
                                tx_ping_m_mosi.tkeep       <= out_of_fifo_mosi.tkeep;
                                tx_ping_m_mosi.tlast       <= '1';
                                ping_started               <= '0';
                                tx_ping_handler_next_state <= tx_finished;
                            end if;
                        end if;

                    when tx_finished =>
                        --Finished Output
                        ping_done                  <= '1';
                        tx_ping_handler_next_state <= idle;
                        tx_ping_m_mosi.tvalid      <= '0';
                        checksum_incorrect         <= '0';
                        output_length              <= 0;
                        ping_started               <= '0';
                        checksum_valid_in          <= '0';
                end case;
            end if;
        end if;
    end process;

    --Recalculate Ping Checksums to compare against
    gen_ping_chksm : if G_UDP_CORE_BYTES >= 4 generate
        ping_checksum_inst : tx_ping_chksm
            generic map(G_UDP_CORE_WIDTH => G_UDP_CORE_BYTES)
            port map(
                clk       => clk,
                rst_s_n   => rst_s_n,
                data_in   => checksum_data_in,
                width_in  => checksum_width_in,
                valid     => checksum_valid_in,
                sof       => checksum_sof_in,
                eof       => checksum_eof_in,
                done      => checksum_done,
                out_chksm => checksum_calc
            );
    end generate;
    gen_ping_chksm_w8 : if G_UDP_CORE_BYTES = 1 generate
        ping_checksum_1bytew_inst : tx_ping_chksm_1bytew
            port map(
                clk       => clk,
                rst_s_n   => rst_s_n,
                data_in   => checksum_data_in,
                valid     => checksum_valid_in,
                sof       => checksum_sof_in,
                eof       => checksum_eof_in,
                done      => checksum_done,
                out_chksm => checksum_calc
            );
    end generate;

end architecture behavioural;
