-- ethernet_wib
--
-- This block instantiates and connects the tx_path and the ultrascale_pcs_pma 
--
-- Erdem Motuk 24/07/2023

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

library ipbus;
use work.ipbus.all;
use work.ipbus_reg_types.all;

use work.ipbus_decode_wib_eth_readout.all;



library axi4_lib;
use work.axi4s_pkg.all;
use work.axi4_conversion_pkg.all;

library deimos;
use work.xgmii_pkg.all;
use work.addr_pkg.all;
use work.tx_mux_decl.all;
use work.freq_pkg.all;
use work.version_pkg.all;
use work.hermes_core_version_pkg.all;

library common_stfc_lib;
use work.common_stfc_pkg.all;

library udp_core_lib;

entity wib_eth_readout is
    generic(
        N_SRC: integer:= 4;
        N_MGT: positive range 1 to 4 := 1;
        IN_BUF_DEPTH: natural;
        REF_FREQ: t_freq := f156_25
    );
    port(
        ipb_clk: in std_logic;
        ipb_rst: in std_logic;
        ipb_in: in  ipb_wbus;
        ipb_out: out ipb_rbus;
        
        eth_rx_p: in std_logic_vector(N_MGT-1 downto 0); -- Ethernet rx from SFP
        eth_rx_n: in std_logic_vector(N_MGT-1 downto 0);
        eth_tx_p: out std_logic_vector(N_MGT-1 downto 0); -- Ethernet tx to SFP
        eth_tx_n: out std_logic_vector(N_MGT-1 downto 0);
        eth_tx_dis: out std_logic_vector(N_MGT-1 downto 0); -- SFP tx_disable
        --eth_clk_in :   in std_logic ;
        eth_clk_p: in std_logic; -- Transceiver refclk
        eth_clk_n: in std_logic;
        clk: in std_logic; -- DUNE base clock
        rst: in std_logic; -- DUNE base clock sync reset
        d: in array_of_src_d_arrays (N_MGT-1 downto 0)(N_SRC-1 downto 0); -- Data from sources 
       
        ts: in std_logic_vector(63 downto 0);
        nuke: out std_logic;
        soft_rst: out std_logic;
        ext_mac_addr    : in mac_addr_array(N_MGT-1 downto 0);
        ext_ip_addr     : in ip_addr_array(N_MGT-1 downto 0);
        ext_port_addr   : in udp_port_array(N_MGT-1 downto 0)     
    );

end entity wib_eth_readout;

architecture rtl of wib_eth_readout is





 component ultrascale_pcs_pma is
      generic(
        GT_LOOPBACK      : boolean := false;
        ref_freq         : t_freq := f156_25;
        N_MGT            : positive range 1 to 4 := 1;
        N_CLK_DEBUG      : positive := 3
      );
      port(
        eth_clk_p           : in  std_logic;
        eth_clk_n           : in  std_logic;
        --eth_clk : in std_logic ;
        ipb_clk             : in  std_logic;
        ipb_rst             : in  std_logic;
        ipb_in              : in  ipb_wbus;
        ipb_out             : out ipb_rbus;

        clk_drp             : in  std_logic;

        clk_156_o           : out std_logic_vector(N_MGT-1 downto 0);

        sfp_rxp_array       : in  std_logic_vector(N_MGT-1 downto 0);
        sfp_rxn_array       : in  std_logic_vector(N_MGT-1 downto 0);
        sfp_txp_array       : out std_logic_vector(N_MGT-1 downto 0);
        sfp_txn_array       : out std_logic_vector(N_MGT-1 downto 0);
        sfp_tx_dis_array    : out std_logic_vector(N_MGT-1 downto 0);

        tx_path_ready_array : out std_logic_vector(N_MGT-1 downto 0);
        rst_156_25_array    : out std_logic_vector(N_MGT-1 downto 0);

        xgmii_clk           : out std_logic;

        tx_xgmii_d_array    : in xgmii_d_array(N_MGT-1 downto 0);
        tx_xgmii_c_array    : in xgmii_c_array(N_MGT-1 downto 0);

        rx_xgmii_d_array    : out xgmii_d_array(N_MGT-1 downto 0);
        rx_xgmii_c_array    : out xgmii_c_array(N_MGT-1 downto 0)
        
      );
end  component;


component ipbus_ctrlreg_v is
	generic(
		N_CTRL: natural := 1;
		N_STAT: natural := 1;
		SWAP_ORDER: boolean := false
	);
	port(
		clk: in std_logic;
		reset: in std_logic;
		ipbus_in: in ipb_wbus;
		ipbus_out: out ipb_rbus;
		d: in ipb_reg_v(N_STAT - 1 downto 0) := (others => (others => '0'));
		q: out ipb_reg_v(N_CTRL - 1 downto 0);
		qmask: in ipb_reg_v(N_CTRL - 1 downto 0) := (others => (others => '1'));		
		stb: out std_logic_vector(N_CTRL - 1 downto 0)
	);
	
end component;

component ipbus_roreg_v is
	generic(
		N_REG: positive := 1;
		DATA: std_logic_vector
	);
	port(
		ipb_in: in ipb_wbus;
		ipb_out: out ipb_rbus
	);
	
end component;


component ipbus_fabric_sel is
  generic(
    NSLV: positive;
    STROBE_GAP: boolean := false;
    SEL_WIDTH: natural
   );
  port(
  	sel: in std_logic_vector(SEL_WIDTH - 1 downto 0);
    ipb_in: in ipb_wbus;
    ipb_out: out ipb_rbus;
    ipb_to_slaves: out ipb_wbus_array(NSLV - 1 downto 0);
    ipb_from_slaves: in ipb_rbus_array(NSLV - 1 downto 0) := (others => IPB_RBUS_NULL)
   );

end component;

    signal ipbw: ipb_wbus_array(N_SLAVES - 1 downto 0);
    signal ipbr: ipb_rbus_array(N_SLAVES - 1 downto 0);
    signal ctrl: ipb_reg_v(0 downto 0);
    signal eth_d: src_d_array(N_MGT - 1 downto 0);
    signal eth_ready: std_logic_vector(N_MGT - 1 downto 0);
    signal eth_clk, eth_rst, udp_ready: std_logic_vector(3 downto 0);
    signal tx_axi4s_mosi: t_axi4s_mosi_arr(3 downto 0);
    signal tx_axi4s_miso: t_axi4s_miso_arr(3 downto 0);
    constant N_INFO_REG: positive := 4;

    signal info_vec: std_logic_vector(N_INFO_REG*32-1 downto 0);
    signal refclk_info: std_logic_vector(3 downto 0);

    constant BOARD_DESIGN_ID : std_logic_vector(7 downto 0) := X"07";
    signal ctrl_sel_mux: std_logic_vector(1 downto 0);
    signal ipbw_mux: ipb_wbus_array(N_MGT - 1 downto 0);
    signal ipbr_mux: ipb_rbus_array(N_MGT - 1 downto 0);
    signal samp, mark: std_logic;
    signal xgmii_clk : std_logic; 
    signal tx_xgmii_d_array, rx_xgmii_d_array : xgmii_d_array(N_MGT-1 downto 0);
    signal tx_xgmii_c_array, rx_xgmii_c_array : xgmii_c_array(N_MGT-1 downto 0);
    signal clk_156_o : std_logic_vector (N_MGT-1 downto 0);
    signal rst_156_25_array : std_logic_vector (N_MGT-1 downto 0);
    signal txpath_ready_array : std_logic_vector(N_MGT-1 downto 0);

begin

-- ipbus address decoder

    fabric: ipbus_fabric_sel
        generic map(
            NSLV => N_SLAVES,
            SEL_WIDTH => IPBUS_SEL_WIDTH
        )
        port map(
            ipb_in => ipb_in,
            ipb_out => ipb_out,
            sel => ipbus_sel_wib_eth_readout(ipb_in.ipb_addr),
            ipb_to_slaves => ipbw,
            ipb_from_slaves => ipbr
        );

-- Multiplexer
    refclk_info <= X"1" when (REF_FREQ = f156_25) else
                  X"2" when (REF_FREQ = f125)    else 
                  X"0";

    info_vec <= 
        X"000" & refclk_info & std_logic_vector(to_unsigned(N_MGT, 8)) & std_logic_vector(to_unsigned(N_SRC, 8)) & -- generics
        X"00" & C_HERMES_VERSION_HEX & -- version
        BOARD_DESIGN_ID & C_VERSION_HEX & -- version
        X"DEADBEEF"; -- magic

    info :ipbus_roreg_v
        generic map(
            N_REG => N_INFO_REG,
            DATA => info_vec
        )
        port map(
            ipb_in => ipbw(N_SLV_INFO),
            ipb_out => ipbr(N_SLV_INFO)
        );

-- Global timeslice block

    slice: entity work.tx_mux_timeslice
        port map(
            ipb_clk => ipb_clk,
            ipb_rst => ipb_rst,
            ipb_in => ipbw(N_SLV_SAMP),
            ipb_out => ipbr(N_SLV_SAMP),
            src_clk => clk,
            src_rst => rst,
            ts => ts,
            samp => samp,
            mark => mark
        );
        
-- CSR
    csr: ipbus_ctrlreg_v
        generic map(
            N_CTRL => 1,
            N_STAT => 0
        )
        port map(
            clk => ipb_clk,
            reset => ipb_rst,
            ipbus_in => ipbw(N_SLV_CSR),
            ipbus_out => ipbr(N_SLV_CSR),
            q => ctrl
        ); 
    nuke <= ctrl(0)(0);
    soft_rst <= ctrl(0)(1);

    tx_path: entity work.ultrascale_combined_tx_path

      generic map(
        N_SRC  => N_SRC,
        N_MGT  => N_MGT,
        IN_BUF_DEPTH => IN_BUF_DEPTH
        )

      port map(
        ipb_clk             => ipb_clk,
        ipb_rst             => ipb_rst,
        ipb_in              => ipbw(N_SLV_TX_PATH),
        ipb_out             => ipbr(N_SLV_TX_PATH),
        ref_clk_156_in      => clk_156_o (0), --global_ref_clk_in,
        dune_base_clk       => clk,
        dune_rst            => rst,
        ts => ts,
        samp => samp,
        mark => mark,
        xgmii_clk           => xgmii_clk,
        tx_xgmii_rst        => rst_156_25_array(0), --gttxreset_out,
        tx_xgmii_d_array    => tx_xgmii_d_array,
        tx_xgmii_c_array    => tx_xgmii_c_array,
        rx_xgmii_rst        => rst_156_25_array(0), --gtrxreset_out,
        rx_xgmii_d_array    => rx_xgmii_d_array,
        rx_xgmii_c_array    => rx_xgmii_c_array,
        phy_ready_array     => txpath_ready_array,
        rst_156_25_array    => rst_156_25_array,
        d => d,
        ext_mac_addr    => ext_mac_addr,  
        ext_ip_addr     => ext_ip_addr,   
        ext_port_addr   => ext_port_addr, 
        use_ext_addr    => '1'  
        );


    pcs_pma: ultrascale_pcs_pma
      Generic map(
        GT_LOOPBACK         =>  false,
        ref_freq            =>  REF_FREQ,
        N_MGT               =>  N_MGT
      )
      Port map(
        eth_clk_p => eth_clk_p,
        eth_clk_n => eth_clk_n,
        --eth_clk => eth_clk_in,
        ipb_clk => ipb_clk,
        ipb_rst => ipb_rst,
        ipb_in => ipbw(N_SLV_PCS_PMA),
        ipb_out => ipbr(N_SLV_PCS_PMA),
        clk_drp => ipb_clk,

        clk_156_o => clk_156_o,

        sfp_rxp_array => eth_rx_p, --sfp_rxp_array,
        sfp_rxn_array => eth_rx_n, --sfp_rxn_array,
        sfp_txp_array => eth_tx_p, --sfp_txp_array,
        sfp_txn_array => eth_tx_n, --sfp_txn_array,
        sfp_tx_dis_array => eth_tx_dis, --sfp_tx_dis_array,

        xgmii_clk => xgmii_clk,

        tx_path_ready_array  => txpath_ready_array,
        rst_156_25_array   => rst_156_25_array,

        tx_xgmii_d_array => tx_xgmii_d_array,
        tx_xgmii_c_array => tx_xgmii_c_array,

        rx_xgmii_d_array => rx_xgmii_d_array,
        rx_xgmii_c_array => rx_xgmii_c_array
      );
      

end architecture rtl;
