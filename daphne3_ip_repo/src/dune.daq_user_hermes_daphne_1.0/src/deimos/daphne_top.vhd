-- wib_top
--
-- Multiplexes data blocks from multiple sources onto ethernet UDP packet stream
--
-- This is the top level block for the WIB core, with interface compatible with the ip packager (no custom types, etc)
--
-- Dave Newbold, 2/1/23

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

library ipbus;
use work.ipbus.all;

use work.tx_mux_decl.all;
use work.freq_pkg.all;

entity daphne_top is
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
        --eth_clk: in std_logic ;
        eth_clk_p: in std_logic; -- Transceiver refclk
        eth_clk_n: in std_logic;
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
end entity daphne_top;

architecture rtl of daphne_top is

    signal ipbw: ipb_wbus;
    signal ipbr: ipb_rbus;
    signal ipb_clk, ipb_rst: std_logic;
    signal nuke, soft_rst: std_logic;
    constant C_S_AXI_ADDR_WIDTH: integer := 16;


begin


    ipb_ctrl : entity work.ipb_axi4_lite_ctrl
        port map (
            aclk => S_AXI_ACLK,
            aresetn => S_AXI_ARESETN,
            axi_in.awaddr(31 downto C_S_AXI_ADDR_WIDTH) => (others => '0'),
            axi_in.awaddr(C_S_AXI_ADDR_WIDTH - 1 downto 0) => S_AXI_AWADDR,
            axi_in.awprot => S_AXI_AWPROT,
            axi_in.awvalid => S_AXI_AWVALID,
            axi_in.wdata => S_AXI_WDATA,
            axi_in.wstrb => S_AXI_WSTRB,
            axi_in.wvalid => S_AXI_WVALID,
            axi_in.bready => S_AXI_BREADY,
            axi_in.araddr(31 downto C_S_AXI_ADDR_WIDTH) => (others => '0'),
            axi_in.araddr(C_S_AXI_ADDR_WIDTH - 1 downto 0) => S_AXI_ARADDR,     
            axi_in.arprot => S_AXI_ARPROT,
            axi_in.arvalid => S_AXI_ARVALID,
            axi_in.rready => S_AXI_RREADY,
            axi_out.awready => S_AXI_AWREADY,
            axi_out.wready => S_AXI_WREADY,
            axi_out.bresp => S_AXI_BRESP,
            axi_out.bvalid => S_AXI_BVALID,
            axi_out.arready => S_AXI_ARREADY,
            axi_out.rdata => S_AXI_RDATA,
            axi_out.rresp => S_AXI_RRESP,
            axi_out.rvalid => S_AXI_RVALID,

            ipb_clk => ipb_clk,
            ipb_rst => ipb_rst,
            ipb_in => ipbr,
            ipb_out => ipbw,
            nuke =>  nuke,
            soft_rst => soft_rst
            );

    mux: entity work.wib_eth_readout
        generic map(
            N_SRC => 40,
            N_MGT => 1,
            REF_FREQ => f156_25,
            IN_BUF_DEPTH => 512
        )
        port map(
            ipb_clk                => ipb_clk,
            ipb_rst                => ipb_rst,
            ipb_in                 => ipbw,
            ipb_out                => ipbr,
            
           eth_rx_p(0)               => eth0_rx_p,-- (0 => eth0_rx_p , others => '0'),   --Jacques
           eth_rx_n(0)               => eth0_rx_n,--(0 => eth0_rx_n , others => '0'),    --Jacques
            
           
            eth_tx_p(0)            => eth0_tx_p,
            eth_tx_n(0)            => eth0_tx_n,
            eth_tx_dis(0)          => eth0_tx_dis,
            --eth_clk_in => eth_clk,
            eth_clk_p              => eth_clk_p,
            eth_clk_n              => eth_clk_n,
            clk                    => clk,
            rst                    => rst,
            -- Temporary
            nuke => nuke,
            soft_rst => soft_rst,
            d(0)(0).d                 => d0,
            d(0)(0).valid             => d0_valid,
            d(0)(0).last              => d0_last,

            d(0)(1).d                 => d1,
            d(0)(1).valid             => d1_valid,
            d(0)(1).last              => d1_last,

            d(0)(2).d                 => d2,
            d(0)(2).valid             => d2_valid,
            d(0)(2).last              => d2_last,

            d(0)(3).d                 => d3,
            d(0)(3).valid             => d3_valid,
            d(0)(3).last              => d3_last,

            d(0)(4).d                 => d4,
            d(0)(4).valid             => d4_valid,
            d(0)(4).last              => d4_last,

            d(0)(5).d                 => d5,
            d(0)(5).valid             => d5_valid,
            d(0)(5).last              => d5_last,

            d(0)(6).d                 => d6,
            d(0)(6).valid             => d6_valid,
            d(0)(6).last              => d6_last,

            d(0)(7).d                 => d7,
            d(0)(7).valid             => d7_valid,
            d(0)(7).last              => d7_last,

            d(0)(8).d                 => d8,
            d(0)(8).valid             => d8_valid,
            d(0)(8).last              => d8_last,

            d(0)(9).d                 => d9,
            d(0)(9).valid             => d9_valid,
            d(0)(9).last              => d9_last,

            d(0)(10).d                 => d10,
            d(0)(10).valid             => d10_valid,
            d(0)(10).last              => d10_last,

            d(0)(11).d                 => d11,
            d(0)(11).valid             => d11_valid,
            d(0)(11).last              => d11_last,

            d(0)(12).d                 => d12,
            d(0)(12).valid             => d12_valid,
            d(0)(12).last              => d12_last,

            d(0)(13).d                 => d13,
            d(0)(13).valid             => d13_valid,
            d(0)(13).last              => d13_last,

            d(0)(14).d                 => d14,
            d(0)(14).valid             => d14_valid,
            d(0)(14).last              => d14_last,

            d(0)(15).d                 => d15,
            d(0)(15).valid             => d15_valid,
            d(0)(15).last              => d15_last,

            d(0)(16).d                 => d16,
            d(0)(16).valid             => d16_valid,
            d(0)(16).last              => d16_last,

            d(0)(17).d                 => d17,
            d(0)(17).valid             => d17_valid,
            d(0)(17).last              => d17_last,

            d(0)(18).d                 => d18,
            d(0)(18).valid             => d18_valid,
            d(0)(18).last              => d18_last,

            d(0)(19).d                 => d19,
            d(0)(19).valid             => d19_valid,
            d(0)(19).last              => d19_last,

            d(0)(20).d                 => d20,
            d(0)(20).valid             => d20_valid,
            d(0)(20).last              => d20_last,

            d(0)(21).d                 => d21,
            d(0)(21).valid             => d21_valid,
            d(0)(21).last              => d21_last,

            d(0)(22).d                 => d22,
            d(0)(22).valid             => d22_valid,
            d(0)(22).last              => d22_last,

            d(0)(23).d                 => d23,
            d(0)(23).valid             => d23_valid,
            d(0)(23).last              => d23_last,

            d(0)(24).d                 => d24,
            d(0)(24).valid             => d24_valid,
            d(0)(24).last              => d24_last,

            d(0)(25).d                 => d25,
            d(0)(25).valid             => d25_valid,
            d(0)(25).last              => d25_last,

            d(0)(26).d                 => d26,
            d(0)(26).valid             => d26_valid,
            d(0)(26).last              => d26_last,

            d(0)(27).d                 => d27,
            d(0)(27).valid             => d27_valid,
            d(0)(27).last              => d27_last,

            d(0)(28).d                 => d28,
            d(0)(28).valid             => d28_valid,
            d(0)(28).last              => d28_last,

            d(0)(29).d                 => d29,
            d(0)(29).valid             => d29_valid,
            d(0)(29).last              => d29_last,

            d(0)(30).d                 => d30,
            d(0)(30).valid             => d30_valid,
            d(0)(30).last              => d30_last,

            d(0)(31).d                 => d31,
            d(0)(31).valid             => d31_valid,
            d(0)(31).last              => d31_last,

            d(0)(32).d                 => d32,
            d(0)(32).valid             => d32_valid,
            d(0)(32).last              => d32_last,

            d(0)(33).d                 => d33,
            d(0)(33).valid             => d33_valid,
            d(0)(33).last              => d33_last,

            d(0)(34).d                 => d34,
            d(0)(34).valid             => d34_valid,
            d(0)(34).last              => d34_last,

            d(0)(35).d                 => d35,
            d(0)(35).valid             => d35_valid,
            d(0)(35).last              => d35_last,

            d(0)(36).d                 => d36,
            d(0)(36).valid             => d36_valid,
            d(0)(36).last              => d36_last,

            d(0)(37).d                 => d37,
            d(0)(37).valid             => d37_valid,
            d(0)(37).last              => d37_last,

            d(0)(38).d                 => d38,
            d(0)(38).valid             => d38_valid,
            d(0)(38).last              => d38_last,

            d(0)(39).d                 => d39,
            d(0)(39).valid             => d39_valid,
            d(0)(39).last              => d39_last,

            ts                        => ts,
            ext_mac_addr(0)           => ext_mac_addr_0,
            ext_ip_addr(0)            => ext_ip_addr_0,
            ext_port_addr(0)          => ext_port_addr_0
        );

end architecture rtl;
