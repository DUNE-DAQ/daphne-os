-- core.vhd
-- 40 channel self triggered senders + 10G Ethernet sender
-- for DAPHNE3
-- Jamieson Olsen <jamieson@fnal.gov>

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

use work.daphne3_package.all;

entity core is
generic( 
    link_id: std_logic_vector(5 downto 0) := DEFAULT_link_id;
    slot_id: std_logic_vector(3 downto 0) := DEFAULT_slot_id;
    crate_id: std_logic_vector(9 downto 0) := DEFAULT_crate_id;
    detector_id: std_logic_vector(5 downto 0) := DEFAULT_detector_id;
    version_id: std_logic_vector(5 downto 0) := DEFAULT_version_id;
    threshold: std_logic_vector(13 downto 0) := DEFAULT_threshold;
    runlength: integer := DEFAULT_runlength;
    ext_mac_addr_0: std_logic_vector(47 downto 0) := DEFAULT_ext_mac_addr_0; -- default Ethernet MAC address
    ext_ip_addr_0: std_logic_vector(31 downto 0) := DEFAULT_ext_ip_addr_0; -- default Ethernet IP address 192.168.0.100
    ext_port_addr_0: std_logic_vector(15 downto 0) := DEFAULT_ext_port_addr_0 -- default Ethernet Port number
);
port(

    clock: in std_logic; -- master clock 62.5MHz
    reset: in std_logic; -- sync to clock
    timestamp: in std_logic_vector(63 downto 0); -- timestamp sync to clock
    din: in array_5x8x14_type; -- AFE data from frontend sync to clock
    chan_enable: in std_logic_vector(39 downto 0); -- self trig sender channel enables

    -- 10G Ethernet sender AXI-Lite interface

    S_AXI_ACLK: in std_logic;
    S_AXI_ARESETN: in std_logic;
    S_AXI_AWADDR: in std_logic_vector(31 downto 0); -- make 32-bit for AXI-LITE
    S_AXI_AWPROT: in std_logic_vector(2 downto 0);
    S_AXI_AWVALID: in std_logic;
    S_AXI_AWREADY: out std_logic;
    S_AXI_WDATA: in std_logic_vector(31 downto 0);
    S_AXI_WSTRB: in std_logic_vector(3 downto 0);
    S_AXI_WVALID: in std_logic;
    S_AXI_WREADY: out std_logic;
    S_AXI_BRESP: out std_logic_vector(1 downto 0);
    S_AXI_BVALID: out std_logic;
    S_AXI_BREADY: in std_logic;
    S_AXI_ARADDR: in std_logic_vector(31 downto 0); -- make 32-bit for AXI-LITE
    S_AXI_ARPROT: in std_logic_vector(2 downto 0);
    S_AXI_ARVALID: in std_logic;
    S_AXI_ARREADY: out std_logic;
    S_AXI_RDATA: out std_logic_vector(31 downto 0);
    S_AXI_RRESP: out std_logic_vector(1 downto 0);
    S_AXI_RVALID: out std_logic;
    S_AXI_RREADY: in std_logic;

    -- 10G Ethernet sender interface to external MGT refclk LVDS 156.25MHz
    eth_clk: in std_logic;
    eth_clk_p: in std_logic;
    eth_clk_n: in std_logic; 

    -- 10G Ethernet sender interface to external SFP+ transceiver

    eth0_rx_p: in std_logic;
    eth0_rx_n: in std_logic;
    eth0_tx_p: out std_logic;
    eth0_tx_n: out std_logic;
    eth0_tx_dis: out std_logic

);
end core;

architecture core_arch of core is

component stc3 -- single channel self-triggered sender
generic( 
    link_id: std_logic_vector(5 downto 0) := "000000"; 
    ch_id: std_logic_vector(7 downto 0) := "00000000";
    version: std_logic_vector(3 downto 0) := "1010";
    slot_id: std_logic_vector(3 downto 0) := "0010";
    crate_id: std_logic_vector(9 downto 0) := "0000000011";
    detector_id: std_logic_vector(5 downto 0) := "000010";
    version_id: std_logic_vector(5 downto 0) := "000011";
    runlength: integer := 256; -- self trig baseline runlength must be one of: 32, 64, 128, 256
    threshold: std_logic_vector(13 downto 0):= "10000000000000" -- trig threshold relative to calculated baseline
);
port(
    clock: in std_logic; -- master clock 62.5MHz
    reset: in std_logic;
    enable: in std_logic; 
    timestamp: in std_logic_vector(63 downto 0);
	din: in std_logic_vector(13 downto 0); -- aligned AFE data
    dout: out std_logic_vector(63 downto 0);
    valid: out std_logic;
    last: out std_logic
);
end component;

component daphne_top -- single output 10G Ethernet sender
    port(
        S_AXI_ACLK: in std_logic;
        S_AXI_ARESETN: in std_logic;
        S_AXI_AWADDR: in std_logic_vector(15 downto 0);
        S_AXI_AWPROT: in std_logic_vector(2 downto 0);
        S_AXI_AWVALID: in std_logic;
        S_AXI_AWREADY: out std_logic;
        S_AXI_WDATA: in std_logic_vector(31 downto 0);
        S_AXI_WSTRB: in std_logic_vector(3 downto 0);
        S_AXI_WVALID: in std_logic;
        S_AXI_WREADY: out std_logic;
        S_AXI_BRESP: out std_logic_vector(1 downto 0);
        S_AXI_BVALID: out std_logic;
        S_AXI_BREADY: in std_logic;
        S_AXI_ARADDR: in std_logic_vector(15 downto 0);
        S_AXI_ARPROT: in std_logic_vector(2 downto 0);
        S_AXI_ARVALID: in std_logic;
        S_AXI_ARREADY: out std_logic;
        S_AXI_RDATA: out std_logic_vector(31 downto 0);
        S_AXI_RRESP: out std_logic_vector(1 downto 0);
        S_AXI_RVALID: out std_logic;
        S_AXI_RREADY: in std_logic;
        eth0_rx_p: in std_logic; -- Ethernet rx from SFP
        eth0_rx_n: in std_logic;
        eth0_tx_p: out std_logic; -- Ethernet tx to SFP
        eth0_tx_n: out std_logic;
        eth0_tx_dis: out std_logic; -- SFP tx_disable
        eth_clk_p: in std_logic; -- Transceiver refclk
        eth_clk_n: in std_logic;
        --eth_clk: in std_logic ;
        clk: in std_logic; -- DUNE base clock
        rst: in std_logic; -- DUNE base clock sync reset

        d0: in std_logic_vector(63 downto 0);
        d0_valid: in std_logic;
        d0_last: in std_logic;

        d1: in std_logic_vector(63 downto 0);
        d1_valid: in std_logic;
        d1_last: in std_logic;

        d2: in std_logic_vector(63 downto 0);
        d2_valid: in std_logic;
        d2_last: in std_logic;

        d3: in std_logic_vector(63 downto 0);
        d3_valid: in std_logic;
        d3_last: in std_logic;

        d4: in std_logic_vector(63 downto 0);
        d4_valid: in std_logic;
        d4_last: in std_logic;

        d5: in std_logic_vector(63 downto 0);
        d5_valid: in std_logic;
        d5_last: in std_logic;

        d6: in std_logic_vector(63 downto 0);
        d6_valid: in std_logic;
        d6_last: in std_logic;

        d7: in std_logic_vector(63 downto 0);
        d7_valid: in std_logic;
        d7_last: in std_logic;

        d8: in std_logic_vector(63 downto 0);
        d8_valid: in std_logic;
        d8_last: in std_logic;

        d9: in std_logic_vector(63 downto 0);
        d9_valid: in std_logic;
        d9_last: in std_logic;

        d10: in std_logic_vector(63 downto 0);
        d10_valid: in std_logic;
        d10_last: in std_logic;

        d11: in std_logic_vector(63 downto 0);
        d11_valid: in std_logic;
        d11_last: in std_logic;

        d12: in std_logic_vector(63 downto 0);
        d12_valid: in std_logic;
        d12_last: in std_logic;

        d13: in std_logic_vector(63 downto 0);
        d13_valid: in std_logic;
        d13_last: in std_logic;

        d14: in std_logic_vector(63 downto 0);
        d14_valid: in std_logic;
        d14_last: in std_logic;

        d15: in std_logic_vector(63 downto 0);
        d15_valid: in std_logic;
        d15_last: in std_logic;

        d16: in std_logic_vector(63 downto 0);
        d16_valid: in std_logic;
        d16_last: in std_logic;

        d17: in std_logic_vector(63 downto 0);
        d17_valid: in std_logic;
        d17_last: in std_logic;

        d18: in std_logic_vector(63 downto 0);
        d18_valid: in std_logic;
        d18_last: in std_logic;

        d19: in std_logic_vector(63 downto 0);
        d19_valid: in std_logic;
        d19_last: in std_logic;

        d20: in std_logic_vector(63 downto 0);
        d20_valid: in std_logic;
        d20_last: in std_logic;

        d21: in std_logic_vector(63 downto 0);
        d21_valid: in std_logic;
        d21_last: in std_logic;

        d22: in std_logic_vector(63 downto 0);
        d22_valid: in std_logic;
        d22_last: in std_logic;

        d23: in std_logic_vector(63 downto 0);
        d23_valid: in std_logic;
        d23_last: in std_logic;

        d24: in std_logic_vector(63 downto 0);
        d24_valid: in std_logic;
        d24_last: in std_logic;

        d25: in std_logic_vector(63 downto 0);
        d25_valid: in std_logic;
        d25_last: in std_logic;

        d26: in std_logic_vector(63 downto 0);
        d26_valid: in std_logic;
        d26_last: in std_logic;

        d27: in std_logic_vector(63 downto 0);
        d27_valid: in std_logic;
        d27_last: in std_logic;

        d28: in std_logic_vector(63 downto 0);
        d28_valid: in std_logic;
        d28_last: in std_logic;

        d29: in std_logic_vector(63 downto 0);
        d29_valid: in std_logic;
        d29_last: in std_logic;

        d30: in std_logic_vector(63 downto 0);
        d30_valid: in std_logic;
        d30_last: in std_logic;

        d31: in std_logic_vector(63 downto 0);
        d31_valid: in std_logic;
        d31_last: in std_logic;

        d32: in std_logic_vector(63 downto 0);
        d32_valid: in std_logic;
        d32_last: in std_logic;

        d33: in std_logic_vector(63 downto 0);
        d33_valid: in std_logic;
        d33_last: in std_logic;

        d34: in std_logic_vector(63 downto 0);
        d34_valid: in std_logic;
        d34_last: in std_logic;

        d35: in std_logic_vector(63 downto 0);
        d35_valid: in std_logic;
        d35_last: in std_logic;

        d36: in std_logic_vector(63 downto 0);
        d36_valid: in std_logic;
        d36_last: in std_logic;

        d37: in std_logic_vector(63 downto 0);
        d37_valid: in std_logic;
        d37_last: in std_logic;

        d38: in std_logic_vector(63 downto 0);
        d38_valid: in std_logic;
        d38_last: in std_logic;

        d39: in std_logic_vector(63 downto 0);
        d39_valid: in std_logic;
        d39_last: in std_logic;

        ts : in std_logic_vector(63 downto 0);
        ext_mac_addr_0  : in std_logic_vector(47 downto 0);
        ext_ip_addr_0   : in std_logic_vector(31 downto 0);
        ext_port_addr_0 : in std_logic_vector(15 downto 0)
    );         
end component;

signal dout: array_40x64_type;
signal last, valid: std_logic_vector(39 downto 0);

begin

-- make 40 self-triggered senders...

gena_stc3: for a in 4 downto 0 generate -- 5 AFE chips
    genc_stc3: for c in 7 downto 0 generate -- 8 channels per AFE

        stc3_inst: stc3 
        generic map( 
            link_id => link_id,
            ch_id => std_logic_vector( to_unsigned(8*a+c, 8) ), -- now 8 bits
            version => "1010",
            slot_id => slot_id,
            crate_id => crate_id,
            detector_id => detector_id,
            version_id => version_id,
            runlength => runlength,
            threshold => threshold
        )
        port map(
            clock => clock,
            reset => reset,
            enable => chan_enable(8*a+c), -- for now, point up to generic
            timestamp => timestamp,
        	din => din(a)(c),
            dout => dout(8*a+c),
            valid => valid(8*a+c),
            last => last(8*a+c)
        );

    end generate genc_stc3;
end generate gena_stc3;

-- single output 10G Ethernet sender

daphne_top_inst: daphne_top 
    port map(
        S_AXI_ACLK => S_AXI_ACLK,  -- AXI-Lite interface
        S_AXI_ARESETN => S_AXI_ARESETN,
        S_AXI_AWADDR => S_AXI_AWADDR(15 downto 0),
        S_AXI_AWPROT => S_AXI_AWPROT,
        S_AXI_AWVALID => S_AXI_AWVALID,
        S_AXI_AWREADY => S_AXI_AWREADY,
        S_AXI_WDATA => S_AXI_WDATA,
        S_AXI_WSTRB => S_AXI_WSTRB,
        S_AXI_WVALID => S_AXI_WVALID,
        S_AXI_WREADY => S_AXI_WREADY,
        S_AXI_BRESP => S_AXI_BRESP,
        S_AXI_BVALID => S_AXI_BVALID,
        S_AXI_BREADY => S_AXI_BREADY,
        S_AXI_ARADDR => S_AXI_ARADDR(15 downto 0),
        S_AXI_ARPROT => S_AXI_ARPROT,
        S_AXI_ARVALID => S_AXI_ARVALID,
        S_AXI_ARREADY => S_AXI_ARREADY, 
        S_AXI_RDATA => S_AXI_RDATA,
        S_AXI_RRESP => S_AXI_RRESP,
        S_AXI_RVALID => S_AXI_RVALID,
        S_AXI_RREADY => S_AXI_RREADY,

        eth0_rx_p => eth0_rx_p, -- external SFP+ transceiver
        eth0_rx_n => eth0_rx_n,
        eth0_tx_p => eth0_tx_p,
        eth0_tx_n => eth0_tx_n,
        eth0_tx_dis => eth0_tx_dis,
        --eth_clk => eth_clk,
        eth_clk_p => eth_clk_p, -- external MGT refclk LVDS 156.25MHz
        eth_clk_n => eth_clk_n,

        ext_mac_addr_0 => ext_mac_addr_0, -- Ethernet defaults point up to generics for now
        ext_ip_addr_0 => ext_ip_addr_0,
        ext_port_addr_0 => ext_port_addr_0,

        clk => clock, -- master clock 62.5MHz
        rst => reset, -- sync reset
        ts => timestamp,

        d0 => dout(0), d0_valid => valid(0), d0_last => last(0),
        d1 => dout(1), d1_valid => valid(1), d1_last => last(1),
        d2 => dout(2), d2_valid => valid(2), d2_last => last(2),
        d3 => dout(3), d3_valid => valid(3), d3_last => last(3),
        d4 => dout(4), d4_valid => valid(4), d4_last => last(4),
        d5 => dout(5), d5_valid => valid(5), d5_last => last(5),
        d6 => dout(6), d6_valid => valid(6), d6_last => last(6),
        d7 => dout(7), d7_valid => valid(7), d7_last => last(7),
        d8 => dout(8), d8_valid => valid(8), d8_last => last(8),
        d9 => dout(9), d9_valid => valid(9), d9_last => last(9),

        d10 => dout(10), d10_valid => valid(10), d10_last => last(10),
        d11 => dout(11), d11_valid => valid(11), d11_last => last(11),
        d12 => dout(12), d12_valid => valid(12), d12_last => last(12),
        d13 => dout(13), d13_valid => valid(13), d13_last => last(13),
        d14 => dout(14), d14_valid => valid(14), d14_last => last(14),
        d15 => dout(15), d15_valid => valid(15), d15_last => last(15),
        d16 => dout(16), d16_valid => valid(16), d16_last => last(16),
        d17 => dout(17), d17_valid => valid(17), d17_last => last(17),
        d18 => dout(18), d18_valid => valid(18), d18_last => last(18),
        d19 => dout(19), d19_valid => valid(19), d19_last => last(19),

        d20 => dout(20), d20_valid => valid(20), d20_last => last(20),
        d21 => dout(21), d21_valid => valid(21), d21_last => last(21),
        d22 => dout(22), d22_valid => valid(22), d22_last => last(22),
        d23 => dout(23), d23_valid => valid(23), d23_last => last(23),
        d24 => dout(24), d24_valid => valid(24), d24_last => last(24),
        d25 => dout(25), d25_valid => valid(25), d25_last => last(25),
        d26 => dout(26), d26_valid => valid(26), d26_last => last(26),
        d27 => dout(27), d27_valid => valid(27), d27_last => last(27),
        d28 => dout(28), d28_valid => valid(28), d28_last => last(28),
        d29 => dout(29), d29_valid => valid(29), d29_last => last(29),

        d30 => dout(30), d30_valid => valid(30), d30_last => last(30),
        d31 => dout(31), d31_valid => valid(31), d31_last => last(31),
        d32 => dout(32), d32_valid => valid(32), d32_last => last(32),
        d33 => dout(33), d33_valid => valid(33), d33_last => last(33),
        d34 => dout(34), d34_valid => valid(34), d34_last => last(34),
        d35 => dout(35), d35_valid => valid(35), d35_last => last(35),
        d36 => dout(36), d36_valid => valid(36), d36_last => last(36),
        d37 => dout(37), d37_valid => valid(37), d37_last => last(37),
        d38 => dout(38), d38_valid => valid(38), d38_last => last(38),
        d39 => dout(39), d39_valid => valid(39), d39_last => last(39)

    );         

end core_arch;

