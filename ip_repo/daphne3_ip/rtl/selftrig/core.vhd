-- core.vhd
-- 40 channel self triggered senders + selection logic + single channel 10G Ethernet sender
-- for DAPHNE3 / DAPHNE_MEZZ
-- Jamieson Olsen <jamieson@fnal.gov>

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

use work.daphne3_package.all;

entity core is
port(
    link_id: std_logic_vector(5 downto 0); -- static header data
    slot_id: in std_logic_vector(3 downto 0);
    crate_id: in std_logic_vector(9 downto 0);
    detector_id: in std_logic_vector(5 downto 0);
    version_id: in std_logic_vector(5 downto 0);

    clock: in std_logic; -- master clock 62.5MHz
    reset: in std_logic; -- sync to clock
    timestamp: in std_logic_vector(63 downto 0); -- timestamp sync to clock
    enable: in std_logic_vector(39 downto 0); -- self trig sender channel enables
    forcetrig: in std_logic; -- momentary pulse to force all enabled senders to trigger
    threshold: in std_logic_vector(9 downto 0); -- counts below calculated baseline

    afe_data0: in std_logic_vector(13 downto 0);
    afe_data1: in std_logic_vector(13 downto 0);
    afe_data2: in std_logic_vector(13 downto 0);
    afe_data3: in std_logic_vector(13 downto 0);
    afe_data4: in std_logic_vector(13 downto 0);
    afe_data5: in std_logic_vector(13 downto 0);
    afe_data6: in std_logic_vector(13 downto 0);
    afe_data7: in std_logic_vector(13 downto 0);
    afe_data8: in std_logic_vector(13 downto 0);
    afe_data9: in std_logic_vector(13 downto 0);
    afe_data10: in std_logic_vector(13 downto 0);
    afe_data11: in std_logic_vector(13 downto 0);
    afe_data12: in std_logic_vector(13 downto 0);
    afe_data13: in std_logic_vector(13 downto 0);
    afe_data14: in std_logic_vector(13 downto 0);
    afe_data15: in std_logic_vector(13 downto 0);
    afe_data16: in std_logic_vector(13 downto 0);
    afe_data17: in std_logic_vector(13 downto 0);
    afe_data18: in std_logic_vector(13 downto 0);
    afe_data19: in std_logic_vector(13 downto 0);
    afe_data20: in std_logic_vector(13 downto 0);
    afe_data21: in std_logic_vector(13 downto 0);
    afe_data22: in std_logic_vector(13 downto 0);
    afe_data23: in std_logic_vector(13 downto 0);
    afe_data24: in std_logic_vector(13 downto 0);
    afe_data25: in std_logic_vector(13 downto 0);
    afe_data26: in std_logic_vector(13 downto 0);
    afe_data27: in std_logic_vector(13 downto 0);
    afe_data28: in std_logic_vector(13 downto 0);
    afe_data29: in std_logic_vector(13 downto 0);
    afe_data30: in std_logic_vector(13 downto 0);
    afe_data31: in std_logic_vector(13 downto 0);
    afe_data32: in std_logic_vector(13 downto 0);
    afe_data33: in std_logic_vector(13 downto 0);
    afe_data34: in std_logic_vector(13 downto 0);
    afe_data35: in std_logic_vector(13 downto 0);
    afe_data36: in std_logic_vector(13 downto 0);
    afe_data37: in std_logic_vector(13 downto 0);
    afe_data38: in std_logic_vector(13 downto 0);
    afe_data39: in std_logic_vector(13 downto 0);
 
    S_AXI_ACLK: in std_logic; -- 10G Ethernet sender AXI-Lite interface
    S_AXI_ARESETN: in std_logic;
    S_AXI_AWADDR: in std_logic_vector(31 downto 0);
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
    S_AXI_ARADDR: in std_logic_vector(31 downto 0);
    S_AXI_ARPROT: in std_logic_vector(2 downto 0);
    S_AXI_ARVALID: in std_logic;
    S_AXI_ARREADY: out std_logic;
    S_AXI_RDATA: out std_logic_vector(31 downto 0);
    S_AXI_RRESP: out std_logic_vector(1 downto 0);
    S_AXI_RVALID: out std_logic;
    S_AXI_RREADY: in std_logic;

    eth_clk_p: in std_logic; -- external MGT refclk LVDS 156.25MHz
    eth_clk_n: in std_logic; 

    eth0_rx_p: in std_logic; -- external SFP+ transceiver
    eth0_rx_n: in std_logic;
    eth0_tx_p: out std_logic;
    eth0_tx_n: out std_logic;
    eth0_tx_dis: out std_logic;
    
        --output_spybuff-----
    out_buff_data: out std_logic_vector (63 downto 0);
    out_buff_trig: out std_logic ;
     VALID_DEBUG: out std_logic;
     LAST_DEBUG: out std_logic
);
end core;

architecture core_arch of core is

component st40_top
generic( baseline_runlength: integer := 256 );
port(
    link_id: std_logic_vector(5 downto 0);
    slot_id: in std_logic_vector(3 downto 0);
    crate_id: in std_logic_vector(9 downto 0);
    detector_id: in std_logic_vector(5 downto 0);
    version_id: in std_logic_vector(5 downto 0);
    threshold: in std_logic_vector(9 downto 0);
    version: in std_logic_vector(3 downto 0);

    clock: in std_logic; -- main clock 62.5 MHz
    reset: in std_logic;
    timestamp: in std_logic_vector(63 downto 0);
    enable: in std_logic_vector(39 downto 0);
    forcetrig: in std_logic;
	din: in array_40x14_type; -- ALL AFE channels feed into this module
    d0: out std_logic_vector(63 downto 0); -- output to single channel 10G sender
    d0_valid: out std_logic;
    d0_last: out std_logic
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

        clk: in std_logic; -- DUNE base clock
        rst: in std_logic; -- DUNE base clock sync reset

        d0: in std_logic_vector(63 downto 0);
        d0_valid: in std_logic;
        d0_last: in std_logic;

        ts : in std_logic_vector(63 downto 0);

        ext_mac_addr_0  : in std_logic_vector(47 downto 0);
        ext_ip_addr_0   : in std_logic_vector(31 downto 0);
        ext_port_addr_0 : in std_logic_vector(15 downto 0)
    );         
end component;

signal din: array_40x14_type;
signal d0: std_logic_vector(63 downto 0);
signal d0_valid, d0_last: std_logic;

begin

-- make input bus array

din(0) <= afe_data0;
din(1) <= afe_data1;
din(2) <= afe_data2;
din(3) <= afe_data3;
din(4) <= afe_data4;
din(5) <= afe_data5;
din(6) <= afe_data6;
din(7) <= afe_data7;
din(8) <= afe_data8;
din(9) <= afe_data9;

din(10) <= afe_data10;
din(11) <= afe_data11;
din(12) <= afe_data12;
din(13) <= afe_data13;
din(14) <= afe_data14;
din(15) <= afe_data15;
din(16) <= afe_data16;
din(17) <= afe_data17;
din(18) <= afe_data18;
din(19) <= afe_data19;

din(20) <= afe_data20;
din(21) <= afe_data21;
din(22) <= afe_data22;
din(23) <= afe_data23;
din(24) <= afe_data24;
din(25) <= afe_data25;
din(26) <= afe_data26;
din(27) <= afe_data27;
din(28) <= afe_data28;
din(29) <= afe_data29;

din(30) <= afe_data30;
din(31) <= afe_data31;
din(32) <= afe_data32;
din(33) <= afe_data33;
din(34) <= afe_data34;
din(35) <= afe_data35;
din(36) <= afe_data36;
din(37) <= afe_data37;
din(38) <= afe_data38;
din(39) <= afe_data39;

-- 40 self-triggered sender machines + selection logic

st40_top_inst: st40_top
generic map ( baseline_runlength => DEFAULT_runlength )
port map(
    link_id => link_id,
    slot_id => slot_id,
    crate_id => crate_id,
    detector_id => detector_id,
    version_id => version_id,
    threshold => threshold,
    version => "1010",

    clock => clock,
    reset => reset,
    timestamp => timestamp,
    enable => enable,
    forcetrig => forcetrig,
	din => din,

    d0 => d0,
    d0_valid => d0_valid,
    d0_last => d0_last
);


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

        eth_clk_p => eth_clk_p, -- external MGT refclk LVDS 156.25MHz
        eth_clk_n => eth_clk_n,

        clk => clock, -- master clock 62.5MHz
        rst => reset, -- sync reset

        d0 => d0,
        d0_valid => d0_valid,
        d0_last => d0_last,

        ts => timestamp,

        ext_mac_addr_0 => DEFAULT_ext_mac_addr_0, -- Ethernet defaults point up to generics for now
        ext_ip_addr_0 => DEFAULT_ext_ip_addr_0,
        ext_port_addr_0 => DEFAULT_ext_port_addr_0
    );         

    out_buff_data <= d0;
    out_buff_trig <= enable(8);
     VALID_DEBUG   <= d0_valid ;
     LAST_DEBUG    <= d0_last;  
  

end core_arch;