------------------------------------------------------------------------------
--! @file   udp_core_interface_wrapper.vhd
--! @page udpcoreinterfacewrapperpage UDP Core Interface Wrapper
--!
--! \includedoc esdg_stfc_image.md
--!
--! This is 1 of 2 options for instantiating the [UDP Core](../../index.html).
--!
--! For detailed generic/port descriptions refer to [Instantiation](../../instantiation.html).
--!
--! ### Brief ###
--! Top level UDP Core wrapper which does contain Layer 1 Ethernet MAC
--! Functions. Contains Clk crossing FIFOs, pipeline stages, reset logic and
--! the @ref udpcoretopxmlmmspage which contains most of the Core's functionality
--!
--! For 1 & 10GbE with Layer 1 MAC connect tdata to the PHY data bus and tkeep
--! to the PHY ctrl. Rx Side to rx_axi4s_s_mosi and Tx side to tx_axi4s_m_mosi.
--!
--! ### License ###
--! Copyright(c) 2021 UNITED KINGDOM RESEARCH AND INNOVATION
--! Licensed under the BSD 3-Clause license. See LICENSE file in the project
--! root for details.
--------------------------------------------------------------------------------
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

library common_stfc_lib;
use work.common_stfc_pkg.all;

library udp_core_lib;
use work.udp_core_pkg.all;
use work.udp_proj_pkg.all;

library ipbus;
use work.ipbus.all;
use work.ipbus_reg_types.all;

library axi4_lib;
use work.axi4lite_pkg.all;
use work.axi4s_pkg.all;

entity udp_core_interface_withmac_ipbus_wrapper is
    generic(
        G_FPGA_VENDOR          : string  := "xilinx"; --!       Selects the FPGA Vendor for Compilation
        G_FPGA_FAMILY          : string  := "all"; --!          Selects the FPGA Family for Compilation
        G_FIFO_IMPLEMENTATION  : string  := "auto"; --!         Selects how the Fitter implements the FIFO Memory
        G_FIFO_TYPE            : string  := "inferred_mem"; --! Selects how to implement the Core's FIFOs
        G_UDP_CORE_BYTES       : integer := 8; --!              Width Of Data Busses In Bytes
        G_NUM_OF_ARP_POS       : natural := 8; --!              Number Of Positions In ARP Table to treat as dynamic ARP Positions
        G_INC_MAC_CRC          : boolean := true; --!           Generate Internal MAC and CRC Functions. Ignored Regardless In 100GbE
        G_UDP_CLK_FIFOS        : boolean := true; --!           Generate Clk Crossing FIFOs At The I/O of UDP Payloads
        G_EXT_CLK_FIFOS        : boolean := true; --!           Generate Clk Crossing FIFOs At The I/O of Unsupported Packet Types
        G_TX_EXT_IP_FIFO_CAP   : integer := 2048; --!           Capacity In Bits Of Uns IPV4 Protocol Packets FIFOs in Tx Path
        G_TX_EXT_ETH_FIFO_CAP  : integer := 2048; --!           Capacity In Bits Of Uns Ethernet Type Packets FIFOs in Tx Path
        G_TX_OUT_FIFO_CAP      : integer := 2048; --!           Capacity In Bits Of FIFO at End Of Tx Path. Necessary For 100GbE But Less Important For 1/10GbE. Can Be Set to 0.
        G_RX_IN_FIFO_CAP       : integer := 2048; --!           Capacity In Bits Of FIFO at Start Of Rx Path. At least 16 Words Recommended.
        G_RX_INPUT_PIPE_STAGES : integer := 1; --!              Pipeline Stages From External MAC/PHY To Rx Path
        G_INC_RX_PATH          : boolean := true;
        G_INC_PING             : boolean := true; --!           Generate Logic For Internal Ping Replies
        G_INC_ARP              : boolean := true; --!           Generate Logic For Internal ARP Requests And Replies
        G_INC_LUTS             : boolean := true;
        G_CORE_FREQ_KHZ        : integer := 156250; --!         Clock frequency, in KHz, Of Tx Path, Only Used To Calibrate ARP Refresh Timers
        G_INC_ETH              : boolean := false; --!          Generate Logic To Transmit Externally Provided Ethernet Payloads
        G_INC_IPV4             : boolean := false; --!           Generate Logic To Transmit Externally Provided IPV4 Payloads
        debug_arp              : boolean := false;
        debug_ping             : boolean := false
    );
    port(
        clk                 : in  std_logic                     := '0';
        rst                 : in  std_logic                     := '0';
        ipb_in              : in  ipb_wbus                      := (
            ipb_addr   => (others => '0'),
            ipb_wdata  => (others => '0'),
            ipb_strobe => '0',
            ipb_write  => '0');
        ipb_out             : out ipb_rbus;
        -- Main Core Clocks
        tx_core_clk         : in  std_logic; --!    Tx Path Main Clock, Recommend Use Tx PHY Clock
        rx_core_clk         : in  std_logic; --!    Rx Path Main Clock, Recommend Using PHY Clock For 1/10/40GbE. Can be 200MHz for 100GbE
        -- PHY Axi4s Interfaces
        rx_axi4s_s_aclk     : in  std_logic; --!    Rx PHY Clk
        rx_axi4s_s_areset   : in  std_logic; --!    Rx PHY Reset, always required
        rx_axi4s_s_mosi     : in  t_axi4s_mosi; --! Rx Data From PHY
        rx_axi4s_s_miso     : out t_axi4s_miso; --! Rx Backpressure (To) PHY, Will Be Ignored By a PHY, Included for Debug & Verification
        tx_axi4s_m_aclk     : in  std_logic; --!    Tx PHY Clk
        tx_axi4s_m_areset   : in  std_logic; --!    Tx PHY reset, always required
        tx_axi4s_m_mosi     : out t_axi4s_mosi; --! Tx Data To PHY
        tx_axi4s_m_miso     : in  t_axi4s_miso; --! Tx Backpressure (From) PHY, Will Only be utilised for 100GbE
        -- UDP Axi4s Interfaces
        udp_axi4s_s_aclk    : in  std_logic                     := 'X'; --! UDP Tx In Clk, Ignored if G_UDP_CLK_FIFOS = False
        udp_axi4s_s_areset  : in  std_logic                     := '1'; --! UDP Tx In Reset, Ignored if G_UDP_CLK_FIFOS = False
        udp_axi4s_s_mosi    : in  t_axi4s_mosi; --! UDP Tx In Data
        udp_axi4s_s_miso    : out t_axi4s_miso; --! UDP Tx In Backpressure
        udp_axi4s_m_aclk    : in  std_logic                     := 'X'; --! UDP Rx Out Clk, Ignored if G_UDP_CLK_FIFOS = False
        udp_axi4s_m_areset  : in  std_logic                     := '1'; --! UDP Rx Out Reset, Ignored if G_UDP_CLK_FIFOS = False
        udp_axi4s_m_miso    : in  t_axi4s_miso; --! UDP Rx Out Backpressure
        udp_axi4s_m_mosi    : out t_axi4s_mosi; --! UDP Rx Out Data

        ext_mac_addr        : in  std_logic_vector(47 downto 0) := (others => 'X'); --! An Optional Mac Address For The Core To Be Set At Board Level
        ext_ip_addr         : in  std_logic_vector(31 downto 0) := (others => 'X'); --! An Optional IP Address For The Core To Be Set At Board Level
        ext_port_addr       : in  std_logic_vector(15 downto 0) := (others => 'X'); --! An Optional Port Address For The Core To Be Set At Board Level
        use_ext_addr        : in  std_logic;
        
        --Optional Eth Axi4s Interface
        eth_axi4s_s_aclk    : in  std_logic                     := 'X'; --! Uns Ethernet Packet Tx In Clk
        eth_axi4s_s_areset  : in  std_logic                     := '1'; --! Uns Ethernet Packet Tx In Reset
        eth_axi4s_s_mosi    : in  t_axi4s_mosi                  := c_axi4s_mosi_default; --! Uns Ethernet Packet Tx In Data
        eth_axi4s_s_miso    : out t_axi4s_miso; --! Uns Ethernet Packet Tx In Backpressure
        eth_axi4s_m_aclk    : in  std_logic                     := 'X'; --! Uns Ethernet Packet Rx Out Clk
        eth_axi4s_m_areset  : in  std_logic                     := '1'; --! Uns Ethernet Packet Rx Out Reset
        eth_axi4s_m_miso    : in  t_axi4s_miso                  := c_axi4s_miso_default; --! Uns Ethernet Packet Rx Out Backpressure
        eth_axi4s_m_mosi    : out t_axi4s_mosi; --! Uns Ethernet Packet Rx Out Data
        --Optional IPv4 Axi4s Interface
        ipv4_axi4s_s_aclk   : in  std_logic                     := 'X'; --! Uns IPV4 Packet Tx In Clk
        ipv4_axi4s_s_areset : in  std_logic                     := '1'; --! Uns IPV4 Packet Tx In Reset
        ipv4_axi4s_s_mosi   : in  t_axi4s_mosi                  := c_axi4s_mosi_default; --! Uns IPV4 Packet Tx In Data
        ipv4_axi4s_s_miso   : out t_axi4s_miso; --! Uns IPV4 Packet Tx In Backpressure
        ipv4_axi4s_m_aclk   : in  std_logic                     := 'X'; --! Uns IPV4 Packet Rx Out Clk
        ipv4_axi4s_m_areset : in  std_logic                     := '1'; --! Uns IPV4 Packet Rx Out Reset
        ipv4_axi4s_m_miso   : in  t_axi4s_miso                  := c_axi4s_miso_default; --! Uns IPV4 Packet Rx Out Backpressure
        ipv4_axi4s_m_mosi   : out t_axi4s_mosi --! Uns IPV4 Packet Rx Out Data
    );
end entity udp_core_interface_withmac_ipbus_wrapper;

architecture wrapper of udp_core_interface_withmac_ipbus_wrapper is


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

component udp_core_xml_mm_scalable_top is
    generic(
        G_FPGA_VENDOR         : string  := "xilinx"; --! Selects the FPGA Vendor for Compilation
        G_FPGA_FAMILY         : string  := "all"; --! Selects the FPGA Family for Compilation
        G_FIFO_IMPLEMENTATION : string  := "auto"; --! Selects how the Fitter implements the FIFO Memory
        G_FIFO_TYPE           : string  := "inferred_mem"; --! Selects how to implement the Core's FIFOs
        G_UDP_CORE_BYTES      : integer := 8; --! Width of Data Bus In Bytes
        G_NUM_OF_ARP_POS      : natural := 8; --! Number Of Positions In ARP Table
        G_TX_BACKPRESSURE     : boolean := false; --! Whether Tx Path needs to respond to backpressure
        G_TX_EXT_IP_FIFO_CAP  : integer := (64 * 4); --! Capacity In Bytes Of Uns IPV4 Protocol Packets FIFOs in Tx Path
        G_TX_EXT_ETH_FIFO_CAP : integer := (64 * 4); --! Capacity In Bytes Of Uns Ethernet Type Packets FIFOs in Tx Path
        G_TX_OUT_FIFO_CAP     : integer := (8 * 64 * 32); --! Capicity Of FIFO at End Of Tx Path. Necessary For 100GbE But Less Important For 1/10GbE. Can Be Set to 0.
        G_RX_IN_FIFO_CAP      : integer := (8 * 64 * 64); --! Capacity Of FIFO at Start Of Rx Path. At least 16 Words Recommended.
        G_CORE_FREQ_KHZ       : integer := 156250; --! KHz Of Tx Path, Used For ARP Refresh Timers, Not Essential
        G_INC_RX_PATH         : boolean := true;
        G_INC_PING            : boolean := true; --! Generate Logic For Internal Ping Replies
        G_INC_ARP             : boolean := true; --! Generate Logic For Interal ARP Requests And Replies
        G_INC_LUTS            : boolean := true;
        G_INC_ETH             : boolean := false; --! Generate Logic To Transmit Externally Provided Ethernet Payloads
        G_INC_IPV4            : boolean := false; --! Generate Logic To Transmit Externally Provided IPV4 Payloads
        debug_arp             : boolean := false;
        debug_ping            : boolean := false
    );
    port(
        -- udp core settings
        udp_core_settings_status_regs  : out t_udp_core_settings;
        udp_core_settings_control_regs : in  t_udp_core_settings;
        -- arp mode control
        arp_mode_status_regs           : out t_arp_mode_control;
        arp_mode_control_regs          : in  t_arp_mode_control;
        -- farm mode lut
        farm_mode_lut_status           : out t_farm_mode_lut_in;
        farm_mode_lut_control          : in  t_farm_mode_lut_out;
        -- Main Core Clocks and Synchronised Resets
        tx_core_clk                    : in  std_logic; --! UDP Core Tx Path Clock
        rx_core_clk                    : in  std_logic; --! UDP Core Rx Path Clock
        tx_core_rst_s_n                : in  std_logic; --! UDP Core Tx Synchronous Active-High Reset
        rx_core_rst_s_n                : in  std_logic; --! UDP Core Rx Synchronous Active-High Reset

        -- Packet Axi4s Interfaces
        rx_axi4s_s_aclk                : in  std_logic; --! Rx PHY Axi4s Clk
        rx_axi4s_s_areset_n            : in  std_logic; --! Rx PHY Axi4s Reset
        rx_in_axi4s_s_mosi             : in  t_axi4s_mosi; --! Rx Data In
        rx_in_axi4s_s_miso             : out t_axi4s_miso; --! Rx Backpressure
        tx_axi4s_m_aclk                : in  std_logic; --! Tx PHY Axi4s Clk
        tx_axi4s_m_areset_n            : in  std_logic; --! Tx PHY Axi4s Reset
        tx_out_axi4s_m_mosi            : out t_axi4s_mosi; --! Tx Data Out
        tx_out_axi4s_m_miso            : in  t_axi4s_miso; --! Tx Backpressure

        -- UDP Axi4s Interfaces
        udp_axi4s_s_mosi               : in  t_axi4s_mosi; --! UDP Tx In Data
        udp_axi4s_s_miso               : out t_axi4s_miso; --! UDP Tx In Backpressure
        udp_axi4s_m_miso               : in  t_axi4s_miso; --! UDP Rx Out Backpressure
        udp_axi4s_m_mosi               : out t_axi4s_mosi; --! UDP Rx Out Data

        --Optional IPV4 Axi4s Interfaces
        ipv4_axi4s_s_aclk              : in  std_logic                     := '0'; --! Uns IPV4 Packet Tx In Clk
        ipv4_axi4s_s_areset_n          : in  std_logic                     := '0'; --! Uns IPV4 Packet Tx In Reset
        ipv4_axi4s_s_mosi              : in  t_axi4s_mosi                  := c_axi4s_mosi_default; --! Uns IPV4 Packet Tx In Data
        ipv4_axi4s_s_miso              : out t_axi4s_miso; --! Uns IPV4 Packet Tx In Backpressure
        ipv4_axi4s_m_miso              : in  t_axi4s_miso                  := c_axi4s_miso_default; --! Uns IPV4 Packet Rx Out Backpressure
        ipv4_axi4s_m_mosi              : out t_axi4s_mosi; --! Uns IPV4 Packet Rx Out Data

        --Optional Eth Axi4s Interfaces
        eth_axi4s_s_aclk               : in  std_logic                     := '0'; --! Uns Ethernet Packet Tx In Clk
        eth_axi4s_s_areset_n           : in  std_logic                     := '0'; --! Uns Ethernet Packet Tx In Reset
        eth_axi4s_s_mosi               : in  t_axi4s_mosi                  := c_axi4s_mosi_default; --! Uns Ethernet Packet Tx In Data
        eth_axi4s_s_miso               : out t_axi4s_miso; --! Uns Ethernet Packet Tx In Backpressure
        eth_axi4s_m_miso               : in  t_axi4s_miso                  := c_axi4s_miso_default; --! Uns Ethernet Packet Rx Out Backpressure
        eth_axi4s_m_mosi               : out t_axi4s_mosi; --! Uns Ethernet Packet Rx Out Data

        --Optional External Network Address Assingment Ports
        ext_mac_addr                   : in  std_logic_vector(47 downto 0) := (others => 'X'); --! Optional SRC Mac Address For The Core To Be Set At Board Level
        ext_ip_addr                    : in  std_logic_vector(31 downto 0) := (others => 'X'); --! Optional SRC IP Address For The Core To Be Set At Board Level
        ext_port_addr                  : in  std_logic_vector(15 downto 0) := (others => 'X'); --! Optional DESTINATION PORT ADDRESS (Not SRC like the preceeding two)
        use_ext_addr                   : in  std_logic                     := 'X' --! Use Optional External MAC & IP Addresses

    );
end component;


component udp_axi4s_pipe is
    generic(
        G_STAGES       : integer := 1;      --! Pipeline stages to generate
        G_BACKPRESSURE : boolean := true    --! Whether downstream tready signals can be ignored
    );
    port(
        axi_clk      : in  std_logic;       --! Clk
        axi_rst_n    : in  std_logic;       --! Active Low Synchronous Reset
        axi4s_s_mosi : in  t_axi4s_mosi;    --! Input Axi4s
        axi4s_s_miso : out t_axi4s_miso;    --! Input Backpressure
        axi4s_m_mosi : out t_axi4s_mosi;    --! Output Axi4s
        axi4s_m_miso : in  t_axi4s_miso     --! Output Backpressure
    );
end component;

component rx_frame_sync_align is
    generic(
        G_UDP_CORE_BYTES    : integer := 8                                              --! Width of Data Bus In Bytes
    );
    port(
        udp_core_clk        : in  std_logic;                                            --! Clk
        udp_core_rst_s_n    : in  std_logic;                                            --! Active Low synchronous Reset
        xgmii_rx_d          : in  std_logic_vector(G_UDP_CORE_BYTES * 8 - 1 downto 0);  --! XGMII Input Data Bus
        xgmii_rx_c          : in  std_logic_vector(G_UDP_CORE_BYTES - 1 downto 0);      --! XGMII Input Control Bus
        axi4s_out_miso      : in  t_axi4s_miso := c_axi4s_miso_default;                 --! Axi4s Output Backpressure, currently unused
        axi4s_out_mosi      : out t_axi4s_mosi                                          --! Axi4s Aligned Data Out
    );
end component;

component rx_frame_sync_align_small is
    generic(
        G_UDP_CORE_BYTES    : integer := 1                                              --! Width of Data Bus In Bytes
    );
    port(
        udp_core_clk        : in  std_logic;                                            --! Clk
        udp_core_rst_s_n    : in  std_logic;                                            --! Active Low synchronous Reset
        xgmii_rx_d          : in  std_logic_vector(G_UDP_CORE_BYTES * 8 - 1 downto 0);  --! MII Input Data Byte
        xgmii_rx_c          : in  std_logic_vector(G_UDP_CORE_BYTES - 1 downto 0);      --! MII Input Control Bit
        axi4s_out_miso      : in  t_axi4s_miso := c_axi4s_miso_default;                 --! Axi4s Output Backpressure, Currently Unused
        axi4s_out_mosi      : out t_axi4s_mosi                                          --! Axi4s Data Out
    );
end component;

component udp_axi4s_crc_remove is
    generic(
        G_UDP_CORE_BYTES    : natural := 8                      --! Width of Data Bus In Bytes
    );
    port(
        clk                 : in  std_logic;                    --! Clk
        rst_s_n             : in  std_logic;                    --! Active Low Reset
        axi4s_in_mosi       : in  t_axi4s_mosi;                 --! Axi4s In With CRC Data
        axi4s_in_miso       : out t_axi4s_miso;                 --! Axi4s In With CRC Backpressure
        axi4s_out_mosi      : out t_axi4s_mosi;                 --! Axi4s Out Removed CRC Data
        axi4s_out_miso      : in  t_axi4s_miso;                 --! Axi4s Out Removed CRC backpressure
        crc                 : out std_logic_vector(31 downto 0) --! The Removed CRC
    );
end component;

component tx_path_crc_mii is
    generic(
        G_UDP_CORE_BYTES    : natural := 8;             --! Width of Data Bus In Bytes
        G_CRC_TYPE          : string  := "soft_crc_lut" --! Set CRC Type
    );
    port(
        clk                 : in  std_logic;            --! Clk
        rst_s_n             : in  std_logic;            --! Active Low Reset
        axi4s_s_mosi        : in  t_axi4s_mosi;         --! Axi4s Ethernet Packets In
        axi4s_m_mosi        : out t_axi4s_mosi          --! XGMII Ethernet Packets Out

    );
end component  ;


component tx_path_8b10b_crc_mii is
    port(
        clk             : in  std_logic;                    --! Clk
        rst_s_n         : in  std_logic;                    --! Active Low synchronous Reset
        axi4s_s_mosi    : in  t_axi4s_mosi;                 --! Axi4s ethernet Packets In
        data_out        : out std_logic_vector(7 downto 0); --! Data Bus Out
        ctrl_out        : out std_logic;                    --! Control character out
        last_out        : out std_logic;                    --! Last out, unused
        valid_out       : out std_logic                     --! Valid out, unused
    );
end component  ;

component reset_sync is
    generic(
        g_rst_extend            : boolean := false;     --! Delay the reset deassertion
        g_rst_extend_msb        : natural := 20         --! A counter is used to delay the deassertion until the counter MSB is asserted
    );
    port(
        clk                     : in    std_logic;
        reset_n                 : in    std_logic;
        synced_reset            : out   std_logic;
        synced_reset_n          : out   std_logic
    );
end component  ;

component udp_core_ipb_reg_bank is
    generic(
        G_INC_LUTS : boolean := true;
        N_ARP_CTRL_REG  : natural := 1;
        N_POS_ACT_REG   : natural := 8;
        N_NZ_REG        : natural := 1;
        N_ARP_ENTRY_REG : natural := 256;

        ADDR_WIDTH      : positive := 8;
        DATA_WIDTH      : positive := 32;
        LATENCY         : integer range 1 to 2 := 1;
        USER_LATENCY    : integer range 1 to 2 := 1
    );
    port(
        clk       : in  std_logic;
        rst       : in  std_logic;
        ipb_in    : in  ipb_wbus;
        ipb_out   : out ipb_rbus;
        -- output records for control signals
        -- udp core settings
        extern_src_addr_in      : in t_extern_src_addr;
        udp_core_settings_in    : in t_udp_core_settings;
        udp_core_settings_out   : out t_udp_core_settings;
        -- arp mode control
        arp_mode_control_in     : in t_arp_mode_control;
        arp_mode_control_out    : out t_arp_mode_control;
        -- lut farm control
        farm_mode_lut_in        : in t_farm_mode_lut_in;
        farm_mode_lut_out       : out t_farm_mode_lut_out
    );
end component;

    ----------------------------------------------------------------------------
    -- Constants:
    ----------------------------------------------------------------------------
    constant C_UDP_FIFO_DESC : t_axi4s_descr := (tdata_nof_bytes => 64, -- G_UDP_CORE_BYTES,
                                                 tid_width       => 8,
                                                 tuser_width     => 32,
                                                 has_tlast       => 1,
                                                 has_tkeep       => 1,
                                                 has_tid         => 1,
                                                 has_tuser       => 1);
    constant C_IPV4_FIFO_DESC : t_axi4s_descr := (tdata_nof_bytes => 64, -- G_UDP_CORE_BYTES,
                                                  tid_width       => 8,
                                                  tuser_width     => 24,
                                                  has_tlast       => 1,
                                                  has_tkeep       => 1,
                                                  has_tid         => 1,
                                                  has_tuser       => 1);
    constant C_ETH_FIFO_DESC : t_axi4s_descr := (tdata_nof_bytes => 64, -- G_UDP_CORE_BYTES,
                                                 tid_width       => 8,
                                                 tuser_width     => 16,
                                                 has_tlast       => 1,
                                                 has_tkeep       => 1,
                                                 has_tid         => 1,
                                                 has_tuser       => 1);

    constant C_AXI4S_PIPE_BACKPRESSURE : boolean := (G_UDP_CORE_BYTES = 64) or (not G_INC_MAC_CRC);
    constant C_TX_OUTPUT_PIPE_STAGES   : integer := 2;
    constant C_RESET_SR_SIZE           : integer := 4;

    ----------------------------------------------------------------------------
    -- Signals:
    ----------------------------------------------------------------------------
    signal udp_axi4s_tx_s_mosi    : t_axi4s_mosi;
    signal udp_axi4s_tx_s_miso    : t_axi4s_miso;
    signal udp_axi4s_rx_m_mosi    : t_axi4s_mosi;
    signal udp_axi4s_rx_m_miso    : t_axi4s_miso;
    signal ipv4_axi4s_tx_s_mosi   : t_axi4s_mosi;
    signal ipv4_axi4s_tx_s_miso   : t_axi4s_miso;
    signal ipv4_axi4s_rx_m_mosi   : t_axi4s_mosi;
    signal ipv4_axi4s_rx_m_miso   : t_axi4s_miso;
    signal eth_axi4s_tx_s_mosi    : t_axi4s_mosi;
    signal eth_axi4s_tx_s_miso    : t_axi4s_miso;
    signal eth_axi4s_rx_m_mosi    : t_axi4s_mosi;
    signal eth_axi4s_rx_m_miso    : t_axi4s_miso;
    signal tx_out_axi4s_m_mosi    : t_axi4s_mosi;
    signal tx_out_axi4s_m_miso    : t_axi4s_miso;
    signal rx_in_axi4s_reg_s_mosi : t_axi4s_mosi;
    signal rx_in_axi4s_reg_s_miso : t_axi4s_miso;

    signal tx_out_axi4s_reg_m_mosi : t_axi4s_mosi;
    signal tx_out_axi4s_reg_m_miso : t_axi4s_miso;
    signal rx_in_axi4s_s_mosi      : t_axi4s_mosi;
    signal rx_in_axi4s_s_miso      : t_axi4s_miso;
    signal rx_axi4s_crc_mosi       : t_axi4s_mosi;
    signal rx_axi4s_crc_miso       : t_axi4s_miso;

    --Reset Shift Registers, Initialise To 0s
    signal tx_axi4s_rstn_SR : std_logic_vector(C_RESET_SR_SIZE - 1 downto 0) := (others => '0');
    signal rx_axi4s_rstn_SR : std_logic_vector(C_RESET_SR_SIZE - 1 downto 0) := (others => '0');
    signal tx_core_rstn_SR  : std_logic_vector(C_RESET_SR_SIZE - 1 downto 0) := (others => '0');
    signal rx_core_rstn_SR  : std_logic_vector(C_RESET_SR_SIZE - 1 downto 0) := (others => '0');

    --Resets and Clock Signals
    signal rx_axi4s_s_areset_n      : std_logic;
    signal tx_axi4s_m_areset_n      : std_logic;
    signal rx_core_int_rst_n        : std_logic;
    signal tx_core_int_rst_n        : std_logic;
    signal rx_axi4s_int_rst_n       : std_logic;
    signal tx_axi4s_int_rst_n       : std_logic;
    signal rx_core_rst_s_n          : std_logic;
    signal tx_core_rst_s_n          : std_logic;
    signal rx_axi4s_rst_s_n         : std_logic;
    signal tx_axi4s_rst_s_n         : std_logic;
    signal ipv4_axi4s_s_areset_n    : std_logic;
    signal eth_axi4s_s_areset_n     : std_logic;
    signal ipv4_axi4s_m_areset_n    : std_logic;
    signal eth_axi4s_m_areset_n     : std_logic;
    signal udp_axi4s_s_areset_n     : std_logic;
    signal udp_axi4s_m_areset_n     : std_logic;
    signal ipv4_axi4s_in_s_aclk     : std_logic;
    signal ipv4_axi4s_in_s_areset_n : std_logic;
    signal eth_axi4s_in_s_aclk      : std_logic;
    signal eth_axi4s_in_s_areset_n  : std_logic;

    -- control signals
    signal udp_core_settings_status_regs_we  : t_udp_core_settings_decoded;
    signal udp_core_settings_status_regs     : t_udp_core_settings;
    signal udp_core_settings_control_regs_we : t_udp_core_settings_decoded;
    signal udp_core_settings_control_regs    : t_udp_core_settings;
    signal arp_mode_status_regs_we           : t_arp_mode_control_decoded;
    signal arp_mode_status_regs              : t_arp_mode_control;
    signal arp_mode_control_regs_we          : t_arp_mode_control_decoded;
    signal arp_mode_control_regs             : t_arp_mode_control;
    signal farm_mode_lut_control             : t_farm_mode_lut_out;
    signal farm_mode_lut_status              : t_farm_mode_lut_in;
    signal rx_in_axi4s_pre_pline_s_mosi      : t_axi4s_mosi;
    signal rx_in_axi4s_pre_pline_s_miso      : t_axi4s_miso;

    signal extern_src_addrs   : t_extern_src_addr;
    
begin

    rx_axi4s_s_areset_n   <= not rx_axi4s_s_areset;
    tx_axi4s_m_areset_n   <= not tx_axi4s_m_areset;
    ipv4_axi4s_s_areset_n <= not ipv4_axi4s_s_areset;
    ipv4_axi4s_m_areset_n <= not ipv4_axi4s_m_areset;
    eth_axi4s_s_areset_n  <= not eth_axi4s_s_areset;
    eth_axi4s_m_areset_n  <= not eth_axi4s_m_areset;
    udp_axi4s_s_areset_n  <= not udp_axi4s_s_areset;
    udp_axi4s_m_areset_n  <= not udp_axi4s_m_areset;

    --If External Clock Generic Is Set Use External Interface Clock and Reset Ports For These interfaces Entering The Tx Path
    --otherwise use the Normal Tx Clock
    ipv4_axi4s_in_s_aclk     <= ipv4_axi4s_s_aclk when G_EXT_CLK_FIFOS else
                                tx_core_clk;
    ipv4_axi4s_in_s_areset_n <= ipv4_axi4s_s_areset_n when G_EXT_CLK_FIFOS else
                                tx_core_rst_s_n;
    eth_axi4s_in_s_aclk      <= eth_axi4s_s_aclk when G_EXT_CLK_FIFOS else
                                tx_core_clk;
    eth_axi4s_in_s_areset_n  <= eth_axi4s_s_areset_n when G_EXT_CLK_FIFOS else
                                tx_core_rst_s_n;

    ----------------------------------------------------------------------------
    -- UDP Generate I/O Clk Crossing FIFOs If Generic Set, Else Straight Assign
    ----------------------------------------------------------------------------
    gen_udp_clk_fifos : if G_UDP_CLK_FIFOS generate
        udp_in_fifo_inst : axi4s_fifo
            generic map(
                g_fpga_vendor         => G_FPGA_VENDOR,
                g_fpga_family         => G_FPGA_FAMILY,
                g_implementation      => G_FIFO_IMPLEMENTATION,
                g_dual_clock          => true,
                g_wr_adr_width        => C_FIFO_MIN_WIDTH,
                g_axi4s_descr         => C_UDP_FIFO_DESC,
                g_in_tdata_nof_bytes  => G_UDP_CORE_BYTES,
                g_out_tdata_nof_bytes => G_UDP_CORE_BYTES,
                g_hold_last_read      => false
            )
            port map(
                s_axi_clk    => udp_axi4s_s_aclk,
                s_axi_rst_n  => udp_axi4s_s_areset_n,
                m_axi_clk    => tx_core_clk,
                m_axi_rst_n  => tx_core_rst_s_n,
                axi4s_s_mosi => udp_axi4s_s_mosi,
                axi4s_s_miso => udp_axi4s_s_miso,
                axi4s_m_mosi => udp_axi4s_tx_s_mosi,
                axi4s_m_miso => udp_axi4s_tx_s_miso
            );

        udp_out_fifo_inst : axi4s_fifo
            generic map(
                g_fpga_vendor         => G_FPGA_VENDOR,
                g_fpga_family         => G_FPGA_FAMILY,
                g_implementation      => G_FIFO_IMPLEMENTATION,
                g_dual_clock          => true,
                g_wr_adr_width        => C_FIFO_MIN_WIDTH,
                g_axi4s_descr         => C_UDP_FIFO_DESC,
                g_in_tdata_nof_bytes  => G_UDP_CORE_BYTES,
                g_out_tdata_nof_bytes => G_UDP_CORE_BYTES,
                g_hold_last_read      => false
            )
            port map(
                s_axi_clk    => rx_core_clk,
                s_axi_rst_n  => rx_core_rst_s_n,
                m_axi_clk    => udp_axi4s_m_aclk,
                m_axi_rst_n  => udp_axi4s_m_areset_n,
                axi4s_s_mosi => udp_axi4s_rx_m_mosi,
                axi4s_s_miso => udp_axi4s_rx_m_miso,
                axi4s_m_mosi => udp_axi4s_m_mosi,
                axi4s_m_miso => udp_axi4s_m_miso
            );
    end generate gen_udp_clk_fifos;

    gen_udp_same_clk : if not G_UDP_CLK_FIFOS generate
        udp_axi4s_tx_s_mosi <= udp_axi4s_s_mosi;
        udp_axi4s_s_miso    <= udp_axi4s_tx_s_miso;
        udp_axi4s_m_mosi    <= udp_axi4s_rx_m_mosi;
        udp_axi4s_rx_m_miso <= udp_axi4s_m_miso;
    end generate gen_udp_same_clk;

    ----------------------------------------------------------------------------
    -- IPV4 Generate I/O Clk Crossing FIFOs If Generic Set, Else Straight Assign
    ----------------------------------------------------------------------------
    ipv4_axi4s_tx_s_mosi <= ipv4_axi4s_s_mosi;
    ipv4_axi4s_s_miso    <= ipv4_axi4s_tx_s_miso;

    gen_ipv4_clk_fifos : if G_EXT_CLK_FIFOS and G_INC_IPV4 generate

        ipv4_out_fifo_inst : axi4s_fifo
            generic map(
                g_fpga_vendor         => G_FPGA_VENDOR,
                g_fpga_family         => G_FPGA_FAMILY,
                g_implementation      => G_FIFO_IMPLEMENTATION,
                g_dual_clock          => true,
                g_wr_adr_width        => C_FIFO_MIN_WIDTH,
                g_axi4s_descr         => C_IPV4_FIFO_DESC,
                g_in_tdata_nof_bytes  => G_UDP_CORE_BYTES,
                g_out_tdata_nof_bytes => G_UDP_CORE_BYTES,
                g_hold_last_read      => false
            )
            port map(
                s_axi_clk    => rx_core_clk,
                s_axi_rst_n  => rx_core_rst_s_n,
                m_axi_clk    => ipv4_axi4s_m_aclk,
                m_axi_rst_n  => ipv4_axi4s_m_areset_n,
                axi4s_s_mosi => ipv4_axi4s_rx_m_mosi,
                axi4s_s_miso => ipv4_axi4s_rx_m_miso,
                axi4s_m_mosi => ipv4_axi4s_m_mosi,
                axi4s_m_miso => ipv4_axi4s_m_miso
            );
    end generate gen_ipv4_clk_fifos;

    gen_ipv4_same_clk : if not G_EXT_CLK_FIFOS and G_INC_IPV4 generate
        ipv4_axi4s_m_mosi    <= ipv4_axi4s_rx_m_mosi;
        ipv4_axi4s_rx_m_miso <= ipv4_axi4s_m_miso;
    end generate gen_ipv4_same_clk;

    ----------------------------------------------------------------------------
    -- Eth Generate I/O Clk Crossing FIFOs If Generic Set, Else Straight Assign
    ----------------------------------------------------------------------------
    eth_axi4s_tx_s_mosi <= eth_axi4s_s_mosi;
    eth_axi4s_s_miso    <= eth_axi4s_tx_s_miso;

    gen_eth_clk_fifos : if G_EXT_CLK_FIFOS and G_INC_ETH generate
        eth_out_fifo_inst : axi4s_fifo
            generic map(
                g_fpga_vendor         => G_FPGA_VENDOR,
                g_fpga_family         => G_FPGA_FAMILY,
                g_implementation      => G_FIFO_IMPLEMENTATION,
                g_dual_clock          => true,
                g_wr_adr_width        => C_FIFO_MIN_WIDTH,
                g_axi4s_descr         => C_ETH_FIFO_DESC,
                g_in_tdata_nof_bytes  => G_UDP_CORE_BYTES,
                g_out_tdata_nof_bytes => G_UDP_CORE_BYTES,
                g_hold_last_read      => false
            )
            port map(
                s_axi_clk    => rx_core_clk,
                s_axi_rst_n  => rx_core_rst_s_n,
                m_axi_clk    => eth_axi4s_m_aclk,
                m_axi_rst_n  => eth_axi4s_m_areset_n,
                axi4s_s_mosi => eth_axi4s_rx_m_mosi,
                axi4s_s_miso => eth_axi4s_rx_m_miso,
                axi4s_m_mosi => eth_axi4s_m_mosi,
                axi4s_m_miso => eth_axi4s_m_miso
            );
    end generate gen_eth_clk_fifos;
    gen_eth_same_clk : if not G_EXT_CLK_FIFOS and G_INC_ETH generate
        eth_axi4s_m_mosi    <= eth_axi4s_rx_m_mosi;
        eth_axi4s_rx_m_miso <= eth_axi4s_m_miso;
    end generate gen_eth_same_clk;

    ----------------------------------------------------------------------------
    -- UDP Core:
    ----------------------------------------------------------------------------
    udp_core_top_xml_mm_inst : udp_core_xml_mm_scalable_top
        generic map(
            G_TX_BACKPRESSURE     => C_AXI4S_PIPE_BACKPRESSURE,
            G_FPGA_VENDOR         => G_FPGA_VENDOR,
            G_FPGA_FAMILY         => G_FPGA_FAMILY,
            G_FIFO_IMPLEMENTATION => G_FIFO_IMPLEMENTATION,
            G_FIFO_TYPE           => G_FIFO_TYPE,
            G_UDP_CORE_BYTES      => G_UDP_CORE_BYTES,
            G_NUM_OF_ARP_POS      => G_NUM_OF_ARP_POS,
            G_CORE_FREQ_KHZ       => G_CORE_FREQ_KHZ,
            G_TX_EXT_IP_FIFO_CAP  => G_TX_EXT_IP_FIFO_CAP,
            G_TX_EXT_ETH_FIFO_CAP => G_TX_EXT_ETH_FIFO_CAP,
            G_TX_OUT_FIFO_CAP     => G_TX_OUT_FIFO_CAP,
            G_RX_IN_FIFO_CAP      => G_RX_IN_FIFO_CAP,
            G_INC_RX_PATH         => G_INC_RX_PATH,
            G_INC_PING            => G_INC_PING,
            G_INC_ARP             => G_INC_ARP,
            G_INC_LUTS            => G_INC_LUTS,
            G_INC_ETH             => G_INC_ETH,
            G_INC_IPV4            => G_INC_IPV4,
            debug_arp             => debug_arp,
            debug_ping            => debug_ping
        )
        port map(
            tx_core_clk                    => tx_core_clk,
            rx_core_clk                    => rx_core_clk,
            tx_core_rst_s_n                => tx_core_rst_s_n,
            rx_core_rst_s_n                => rx_core_rst_s_n,
            -- udp core control records
            udp_core_settings_status_regs  => udp_core_settings_status_regs,
            udp_core_settings_control_regs => udp_core_settings_control_regs,
            -- arp mode control
            arp_mode_control_regs          => arp_mode_control_regs,
            arp_mode_status_regs           => arp_mode_status_regs,
            -- farm mode LUT
            farm_mode_lut_control          => farm_mode_lut_control,
            farm_mode_lut_status           => farm_mode_lut_status,
            rx_axi4s_s_aclk                => rx_axi4s_s_aclk,
            rx_axi4s_s_areset_n            => rx_axi4s_rst_s_n,
            rx_in_axi4s_s_mosi             => rx_in_axi4s_reg_s_mosi,
            rx_in_axi4s_s_miso             => rx_in_axi4s_reg_s_miso,
            tx_axi4s_m_aclk                => tx_axi4s_m_aclk,
            tx_axi4s_m_areset_n            => tx_axi4s_rst_s_n,
            tx_out_axi4s_m_mosi            => tx_out_axi4s_m_mosi,
            tx_out_axi4s_m_miso            => tx_out_axi4s_m_miso,
            udp_axi4s_s_mosi               => udp_axi4s_tx_s_mosi,
            udp_axi4s_s_miso               => udp_axi4s_tx_s_miso,
            udp_axi4s_m_miso               => udp_axi4s_rx_m_miso,
            udp_axi4s_m_mosi               => udp_axi4s_rx_m_mosi,
            ipv4_axi4s_s_aclk              => ipv4_axi4s_in_s_aclk,
            ipv4_axi4s_s_areset_n          => ipv4_axi4s_in_s_areset_n,
            ipv4_axi4s_s_mosi              => ipv4_axi4s_tx_s_mosi,
            ipv4_axi4s_s_miso              => ipv4_axi4s_tx_s_miso,
            ipv4_axi4s_m_miso              => ipv4_axi4s_rx_m_miso,
            ipv4_axi4s_m_mosi              => ipv4_axi4s_rx_m_mosi,
            eth_axi4s_s_aclk               => eth_axi4s_in_s_aclk,
            eth_axi4s_s_areset_n           => eth_axi4s_in_s_areset_n,
            eth_axi4s_s_mosi               => eth_axi4s_tx_s_mosi,
            eth_axi4s_s_miso               => eth_axi4s_tx_s_miso,
            eth_axi4s_m_miso               => eth_axi4s_rx_m_miso,
            eth_axi4s_m_mosi               => eth_axi4s_rx_m_mosi,
            ext_mac_addr                   => ext_mac_addr,
            ext_ip_addr                    => ext_ip_addr,
            ext_port_addr                  => ext_port_addr,
            use_ext_addr                   => udp_core_settings_control_regs.use_ext_src_addr
        );

    ----------------------------------------------------------------------------
    -- I/O Pipelines For Interface With PHY
    ----------------------------------------------------------------------------
    rx_input_pipe : udp_axi4s_pipe
        generic map(
            G_STAGES       => G_RX_INPUT_PIPE_STAGES,
            G_BACKPRESSURE => C_AXI4S_PIPE_BACKPRESSURE
        )
        port map(
            axi_clk      => rx_axi4s_s_aclk,
            axi_rst_n    => rx_axi4s_rst_s_n,
            axi4s_s_mosi => rx_in_axi4s_pre_pline_s_mosi,
            axi4s_s_miso => rx_in_axi4s_pre_pline_s_miso,
            axi4s_m_mosi => rx_in_axi4s_reg_s_mosi,
            axi4s_m_miso => rx_in_axi4s_reg_s_miso
        );

    tx_output_pipe : udp_axi4s_pipe
        generic map(
            G_STAGES       => C_TX_OUTPUT_PIPE_STAGES,
            G_BACKPRESSURE => C_AXI4S_PIPE_BACKPRESSURE
        )
        port map(
            axi_clk      => tx_axi4s_m_aclk,
            axi_rst_n    => tx_axi4s_rst_s_n,
            axi4s_s_mosi => tx_out_axi4s_m_mosi,
            axi4s_s_miso => tx_out_axi4s_m_miso,
            axi4s_m_mosi => tx_out_axi4s_reg_m_mosi,
            axi4s_m_miso => tx_out_axi4s_reg_m_miso
        );

    ----------------------------------------------------------------------------
    -- MAC Function: Byte Align MII and Remove CRC
    ----------------------------------------------------------------------------
    gen_mac_functions : if G_INC_MAC_CRC and (G_UDP_CORE_BYTES /= 64) generate
        --Frame Sync Align X/GMII To Axi4s Interface for 1 & 10GbE--------------
        gen_frame_sync_aligner : if G_UDP_CORE_BYTES > 4 generate
            scalable_frame_sync_align_inst : rx_frame_sync_align
                generic map(
                    G_UDP_CORE_BYTES => G_UDP_CORE_BYTES
                )
                port map(
                    udp_core_clk     => rx_axi4s_s_aclk,
                    udp_core_rst_s_n => rx_axi4s_rst_s_n,
                    xgmii_rx_d       => rx_axi4s_s_mosi.tdata(G_UDP_CORE_BYTES * 8 - 1 downto 0),
                    xgmii_rx_c       => rx_axi4s_s_mosi.tkeep(G_UDP_CORE_BYTES - 1 downto 0),
                    axi4s_out_miso   => rx_axi4s_crc_miso,
                    axi4s_out_mosi   => rx_axi4s_crc_mosi
                );
        end generate gen_frame_sync_aligner;

        gen_1g_frame_aligner : if G_UDP_CORE_BYTES = 1 generate
            scalable_frame_sync_align_inst :rx_frame_sync_align_small
                generic map(
                    G_UDP_CORE_BYTES => G_UDP_CORE_BYTES
                )
                port map(
                    udp_core_clk     => rx_axi4s_s_aclk,
                    udp_core_rst_s_n => rx_axi4s_rst_s_n,
                    xgmii_rx_d       => rx_axi4s_s_mosi.tdata(G_UDP_CORE_BYTES * 8 - 1 downto 0),
                    xgmii_rx_c       => rx_axi4s_s_mosi.tkeep(G_UDP_CORE_BYTES - 1 downto 0),
                    axi4s_out_miso   => rx_axi4s_crc_miso,
                    axi4s_out_mosi   => rx_axi4s_crc_mosi
                );
        end generate gen_1g_frame_aligner;

        --Remove CRC From Incoming Ethernet Packets------------------
        rx_remove_crc_inst : udp_axi4s_crc_remove
            generic map(
                G_UDP_CORE_BYTES => G_UDP_CORE_BYTES
            )
            port map(
                clk            => rx_axi4s_s_aclk,
                rst_s_n        => rx_axi4s_rst_s_n,
                axi4s_in_mosi  => rx_axi4s_crc_mosi,
                axi4s_in_miso  => rx_axi4s_crc_miso,
                axi4s_out_mosi => rx_in_axi4s_pre_pline_s_mosi,
                axi4s_out_miso => rx_in_axi4s_pre_pline_s_miso,
                crc            => open
            );

        --Calculate and Add CRC To Outgoing Tx Ethernet Packets
        gen_tx_10g_crc : if G_UDP_CORE_BYTES /= 1 generate
            tx_add_crc_inst : tx_path_crc_mii
                generic map(
                    G_UDP_CORE_BYTES => G_UDP_CORE_BYTES,
                    G_CRC_TYPE       => "soft_crc_lut"
                )
                port map(
                    clk          => tx_axi4s_m_aclk,
                    rst_s_n      => tx_axi4s_rst_s_n,
                    axi4s_s_mosi => tx_out_axi4s_reg_m_mosi,
                    axi4s_m_mosi => tx_axi4s_m_mosi
                );
        end generate gen_tx_10g_crc;

        gen_tx_1g_crc : if G_UDP_CORE_BYTES = 1 generate
            tx_add_small_crc_inst : tx_path_8b10b_crc_mii
                port map(
                    clk          => tx_axi4s_m_aclk,
                    rst_s_n      => tx_axi4s_rst_s_n,
                    axi4s_s_mosi => tx_out_axi4s_reg_m_mosi,
                    data_out     => tx_axi4s_m_mosi.tdata(7 downto 0),
                    ctrl_out     => tx_axi4s_m_mosi.tkeep(0),
                    last_out     => tx_axi4s_m_mosi.tlast,
                    valid_out    => tx_axi4s_m_mosi.tvalid
                );
        end generate gen_tx_1g_crc;
    end generate gen_mac_functions;

    gen_no_mac_functions : if not G_INC_MAC_CRC or G_UDP_CORE_BYTES = 64 generate
        rx_in_axi4s_pre_pline_s_mosi <= rx_axi4s_s_mosi;
        rx_axi4s_s_miso              <= rx_in_axi4s_pre_pline_s_miso; -- For Debug Only
        tx_axi4s_m_mosi              <= tx_out_axi4s_reg_m_mosi;
        tx_out_axi4s_reg_m_miso      <= tx_axi4s_m_miso;
    end generate gen_no_mac_functions;

    ----------------------------------------------------------------------------
    -- Reset Logic: Sync Resets To Various Clks & Pipeline (Helps timing)
    ----------------------------------------------------------------------------
    rx_rst_sync_core_clk_inst : reset_sync
        port map(
            clk            => rx_core_clk,
            reset_n        => rx_axi4s_s_areset_n,
            synced_reset   => open,
            synced_reset_n => rx_core_int_rst_n
        );

    rx_rst_sync_phy_clk_inst :  reset_sync
        port map(
            clk            => rx_axi4s_s_aclk,
            reset_n        => rx_axi4s_s_areset_n,
            synced_reset   => open,
            synced_reset_n => rx_axi4s_int_rst_n
        );

    tx_rst_sync_core_clk_inst :  reset_sync
        port map(
            clk            => tx_core_clk,
            reset_n        => tx_axi4s_m_areset_n,
            synced_reset   => open,
            synced_reset_n => tx_core_int_rst_n
        );

    tx_rst_sync_phy_clk_inst :  reset_sync
        port map(
            clk            => tx_axi4s_m_aclk,
            reset_n        => tx_axi4s_m_areset_n,
            synced_reset   => open,
            synced_reset_n => tx_axi4s_int_rst_n
        );

    rx_core_rstn_proc : process(rx_core_clk) is
    begin
        if rising_edge(rx_core_clk) then
            rx_core_rstn_SR <= rx_core_int_rst_n & rx_core_rstn_SR(rx_core_rstn_SR'left downto 1);
        end if;
    end process rx_core_rstn_proc;

    rx_axi4s_rstn_proc : process(rx_axi4s_s_aclk) is
    begin
        if rising_edge(rx_axi4s_s_aclk) then
            rx_axi4s_rstn_SR <= rx_axi4s_int_rst_n & rx_axi4s_rstn_SR(rx_axi4s_rstn_SR'left downto 1);
        end if;
    end process rx_axi4s_rstn_proc;

    tx_core_rstn_proc : process(tx_core_clk) is
    begin
        if rising_edge(tx_core_clk) then
            tx_core_rstn_SR <= tx_core_int_rst_n & tx_core_rstn_SR(tx_core_rstn_SR'left downto 1);
        end if;
    end process tx_core_rstn_proc;

    tx_axi4s_rstn_proc : process(tx_axi4s_m_aclk) is
    begin
        if rising_edge(tx_axi4s_m_aclk) then
            tx_axi4s_rstn_SR <= tx_axi4s_int_rst_n & tx_axi4s_rstn_SR(tx_axi4s_rstn_SR'left downto 1);
        end if;
    end process tx_axi4s_rstn_proc;

    rx_core_rst_s_n  <= rx_core_rstn_SR(0);
    tx_core_rst_s_n  <= tx_core_rstn_SR(0);
    rx_axi4s_rst_s_n <= rx_axi4s_rstn_SR(0);
    tx_axi4s_rst_s_n <= tx_axi4s_rstn_SR(0);
    ----------------------------------------------------------------------------
    -- End Of Reset Logic
    ----------------------------------------------------------------------------

    extern_src_addrs.src_mac_addr_lower <= ext_mac_addr(31 downto 0);
    extern_src_addrs.src_mac_addr_upper <= ext_mac_addr(47 downto 32);
    extern_src_addrs.src_ip_addr        <= ext_ip_addr;    
    extern_src_addrs.src_port           <= ext_port_addr;
    extern_src_addrs.use_external       <= use_ext_addr;
    
    ----------------------------------------------------------------------------
    --  Register Bank
    ----------------------------------------------------------------------------
    ipb_reg_bank : udp_core_ipb_reg_bank
        generic map(
            G_INC_LUTS  => G_INC_LUTS
        )
        port map(
            clk                   => clk,
            rst                   => rst,
            ipb_in                => ipb_in,
            ipb_out               => ipb_out,
            extern_src_addr_in    => extern_src_addrs,
            udp_core_settings_in  => udp_core_settings_status_regs,
            udp_core_settings_out => udp_core_settings_control_regs,
            arp_mode_control_in   => arp_mode_status_regs,
            arp_mode_control_out  => arp_mode_control_regs,
            farm_mode_lut_in      => farm_mode_lut_status,
            farm_mode_lut_out     => farm_mode_lut_control
        );

end architecture wrapper;
