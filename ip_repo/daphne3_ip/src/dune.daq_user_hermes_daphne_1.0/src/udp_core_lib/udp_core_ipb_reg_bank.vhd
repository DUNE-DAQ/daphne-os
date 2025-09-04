library IEEE;
use IEEE.STD_LOGIC_1164.ALL;
use ieee.numeric_std.all;

library udp_core_lib;
use work.udp_core_pkg.all;
use work.ipbus_decode_udp_core_top_mmap_ipb.all;

library ipbus;
use work.ipbus.all;
use work.ipbus_reg_types.all;

entity udp_core_ipb_reg_bank is
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
end udp_core_ipb_reg_bank;

architecture rtl of udp_core_ipb_reg_bank is

component  ipbus_fabric_sel is
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

 component udp_core_settings_ipb_reg_bank is
    generic(
        N_NZ_CTRL_REG       : natural := 12;
        N_RX_P_COUNT_REG    : natural := 8;
        N_TX_P_COUNT_REG    : natural := 3;
        N_NZ_STAT_REG       : natural := 2;
        N_SRC_CTRL_REG      : natural := 5
    );
    port(
        clk         : in std_logic;
        rst         : in std_logic;
        ipb_in      : in ipb_wbus;
        ipb_out     : out ipb_rbus;
        extern_src_addr_in       : in t_extern_src_addr;
        udp_core_settings_in     : in t_udp_core_settings;
        udp_core_settings_out    : out t_udp_core_settings
    );
end component;

component arp_mode_ctrl_ibp_reg_bank is
    generic(
        N_ARP_CTRL_REG  : natural := 1;
        N_POS_ACT_REG   : natural := 8;
        N_NZ_REG        : natural := 1;
        N_ARP_ENTRY_REG : natural := 256
    );
    port(
        clk         : in std_logic;
        rst         : in std_logic;
        ipb_in      : in ipb_wbus;
        ipb_out     : out ipb_rbus;
        arp_mode_control_in     : in t_arp_mode_control;
        arp_mode_control_out    : out t_arp_mode_control
    );
end component;

component udp_farm_mode_luts_ipb_reg_bank is
    generic(
        ADDR_WIDTH      : positive;
        DATA_WIDTH      : positive := 32;
        LATENCY         : integer range 1 to 2 := 1;
        USER_LATENCY    : integer range 1 to 2 := 1
    );
    port(
        clk         : in std_logic;
        rst         : in std_logic;
        ipb_in      : in ipb_wbus;
        ipb_out     : out ipb_rbus;
        farm_mode_lut_in    : in t_farm_mode_lut_in;
        farm_mode_lut_out   : out t_farm_mode_lut_out
    );
end component;

    signal ipbw: ipb_wbus_array(N_SLAVES - 1 downto 0);
    signal ipbr: ipb_rbus_array(N_SLAVES - 1 downto 0);


begin
    -- ipbus address decode
    fabric: ipbus_fabric_sel
    generic map(
        NSLV => N_SLAVES,
        SEL_WIDTH => IPBUS_SEL_WIDTH
    )
    port map(
        ipb_in => ipb_in,
        ipb_out => ipb_out,
        sel => ipbus_sel_udp_core_top_mmap_ipb(ipb_in.ipb_addr),
        ipb_to_slaves => ipbw,
        ipb_from_slaves => ipbr
    );

    udp_core_settings : udp_core_settings_ipb_reg_bank
    port map(
        clk         => clk,
        rst         => rst,
        ipb_in      => ipbw(N_SLV_UDP_CORE_CONTROL),
        ipb_out     => ipbr(N_SLV_UDP_CORE_CONTROL),
        extern_src_addr_in       => extern_src_addr_in,
        udp_core_settings_in     => udp_core_settings_in,
        udp_core_settings_out    => udp_core_settings_out
    );


    lut_gen: if G_INC_LUTS generate
        arp_mode_ctrl : arp_mode_ctrl_ibp_reg_bank
        generic map(
            N_ARP_CTRL_REG  => N_ARP_CTRL_REG,
            N_POS_ACT_REG   => N_POS_ACT_REG,
            N_NZ_REG        => N_NZ_REG,
            N_ARP_ENTRY_REG => N_ARP_ENTRY_REG
        )
        port map(
            clk         => clk,
            rst         => rst,
            ipb_in      => ipbw(N_SLV_ARP_MODE_CONTROL),
            ipb_out     => ipbr(N_SLV_ARP_MODE_CONTROL),
            arp_mode_control_in     => arp_mode_control_in,
            arp_mode_control_out    => arp_mode_control_out
        );

        udp_core_farm_mode_luts: udp_farm_mode_luts_ipb_reg_bank
        generic map(
            ADDR_WIDTH   => ADDR_WIDTH,
            DATA_WIDTH   => DATA_WIDTH,
            LATENCY      => LATENCY,
            USER_LATENCY => USER_LATENCY
        )
        port map(
            clk         => clk,
            rst         => rst,
            ipb_in      => ipbw(N_SLV_FARM_MODE_LUT),
            ipb_out     => ipbr(N_SLV_FARM_MODE_LUT),
            farm_mode_lut_in    => farm_mode_lut_in,
            farm_mode_lut_out   => farm_mode_lut_out
        );
    end generate;

end rtl;
