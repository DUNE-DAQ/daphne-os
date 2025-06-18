-- front_end.vhd
--
-- DAPHNE V3 AFE front end. This version is different from the DAPHNE V2 design in 
-- that the bit delay and word alignment logic is no longer automatic in the FPGA logic.
-- These adjustments are now done by the Kria CPU so that we can calibrate the AFE input 
-- timing using SOFTWARE control in the USERSPACE. This will be more flexible and more reliable
-- and it will also provide better feedback to the user about timing margins, etc.
--
-- The bit and word alignment values can be changed at any time and these values are unique for
-- each AFE group (5 total). The assumption is that signals within an AFE group are tightly 
-- matched on the PCB layout. So make adjustments to get the FCLK pattern properly aligned, then
-- those same settings will automatically be applied to all other bits in the group.
--
-- NOTE: AFEs must be configured for 16 bit transmission mode, LSb First!
--
-- The suggested calibration procedure is:
--
-- 0. disable IDELAY voltage/temperature compensation (EN_VTC=0)
-- 1. Look at the FCLK data word (trigger and read spy buffers), sweep the delay values (512 steps) and determine the bit edges by observing 
--    when the word value changes. Choose a delay tap value in the middle of a bit.
-- 2. Try different values of BITSLIP until the FCLK word reads 0x00FF
-- 3. put the AFE chip into one of the test modes, recommend count up
-- 4. read data channels (spy buffers), verify that it is counting up properly for each data channel
-- 5. put AFE back into normal data mode, 
-- 6. repeat for remaining AFE groups
-- 7. enable IDELAY voltage/temperature compensation (EN_VTC=1)
--
-- Jamieson Olsen <jamieson@fnal.gov>

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

library unisim;
use unisim.vcomponents.all;

use work.daphne3_package.all;

entity front_end is
port(

    -- AFE interface: 

    afe_p, afe_n: in array_5x9_type; -- 5 x 9 = 45 LVDS pairs (7..0 = data, 8 = fclk)
    afe_clk_p, afe_clk_n: out std_logic; -- copy of 62.5MHz master clock fanned out to AFEs

    -- high speed FPGA fabric interface:

    clk500:  in  std_logic; -- 500MHz bit clock (these 3 clocks must be related/aligned)
    clk125:  in  std_logic; -- 125MHz byte clock
    clock:   in  std_logic; -- 62.5MHz master clock
    dout:    out array_5x9x16_type; -- data synchronized to clock
    trig:    out std_logic; -- user generated trigger

    -- AXI-Lite interface:

    S_AXI_ACLK: in std_logic;
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
    S_AXI_RREADY: in std_logic
  );
end front_end;

architecture fe_arch of front_end is

    signal clock_out_temp: std_logic;
    signal idelayctrl_reset, idelayctrl_reset_clk500, idelayctrl_ready: std_logic;
    signal idelay_tap: array_5x9_type;
    signal idelay_load, idelay_load_clk125: std_logic_vector(4 downto 0);
    signal idelay_en_vtc: std_logic;
    signal iserdes_bitslip: array_5x4_type;
    signal iserdes_reset: std_logic;
    signal trig_axi, trig_reg: std_logic := '0';

    component febit3
    port(
        din_p, din_n: in std_logic;  -- LVDS data input from AFE chip
        clk500: in std_logic;  -- fast bit clock 500MHz
        clk125: in std_logic;  -- byte clock 125MHz
        clock: in std_logic;  -- word/master clock 62.5MHz
        idelay_load: in std_logic;  -- load the IDELAY value (clkdiv)
        idelay_cntvaluein: in std_logic_vector(8 downto 0); -- IDELAY tap value (clkdiv)
        idelay_en_vtc: in std_logic;  -- IDELAY temperature/voltage compensation (async)
        iserdes_reset: in std_logic;  -- reset for ISERDES (async)
        iserdes_bitslip: in std_logic_vector(3 downto 0); -- word alignment value (clock)
        dout: out std_logic_vector(15 downto 0)
    );
    end component;

    component fe_axi 
    port (
        S_AXI_ACLK	: in std_logic;
        S_AXI_ARESETN	: in std_logic;
        S_AXI_AWADDR	: in std_logic_vector(31 downto 0);
        S_AXI_AWPROT	: in std_logic_vector(2 downto 0);
        S_AXI_AWVALID	: in std_logic;
        S_AXI_AWREADY	: out std_logic;
        S_AXI_WDATA	: in std_logic_vector(31 downto 0);
        S_AXI_WSTRB	: in std_logic_vector(3 downto 0);
        S_AXI_WVALID	: in std_logic;
        S_AXI_WREADY	: out std_logic;
        S_AXI_BRESP	: out std_logic_vector(1 downto 0);
        S_AXI_BVALID	: out std_logic;
        S_AXI_BREADY	: in std_logic;
        S_AXI_ARADDR	: in std_logic_vector(31 downto 0);
        S_AXI_ARPROT	: in std_logic_vector(2 downto 0);
        S_AXI_ARVALID	: in std_logic;
        S_AXI_ARREADY	: out std_logic;
        S_AXI_RDATA	: out std_logic_vector(31 downto 0);
        S_AXI_RRESP	: out std_logic_vector(1 downto 0);
        S_AXI_RVALID	: out std_logic;
        S_AXI_RREADY	: in std_logic;        
        
        idelayctrl_ready: in std_logic;
        idelayctrl_reset: out std_logic;
        idelay_tap: out array_5x9_type;
        idelay_en_vtc: out std_logic;
        idelay_load: out std_logic_vector(4 downto 0);
        iserdes_bitslip: out array_5x4_type;
        iserdes_reset: out std_logic;
        trig: out std_logic
    );
    end component;

begin

    -- this controller is required for calibrating IDELAY elements...

    IDELAYCTRL_inst: IDELAYCTRL
        generic map( SIM_DEVICE => "ULTRASCALE" )
        port map(
            REFCLK => clk500,
            RST    => idelayctrl_reset_clk500, -- sync to clk500
            RDY    => idelayctrl_ready);

    -- Forward the 62.5MHz master clock to the AFEs...

    --    ODDR_inst: ODDR 
    --    generic map( DDR_CLK_EDGE => "OPPOSITE_EDGE" )
    --    port map(
    --        Q => clock_out_temp, 
    --        C => clock,
    --        CE => '1',
    --        D1 => '1',
    --        D2 => '0',
    --        R  => '0',
    --        S  => '0');

    ODDR_inst: ODDRE1 
    generic map( SIM_DEVICE => "ULTRASCALE_PLUS" )
    port map(
        Q => clock_out_temp, 
        C => clock,
        D1 => '1',
        D2 => '0',
        SR => '0');

    OBUFDS_inst: OBUFDS
        generic map(IOSTANDARD=>"LVDS")
        port map(
            I => clock_out_temp,
            O => afe_clk_p,
            OB => afe_clk_n);

    -- make the 45 front end bit instances...

    gen_afe: for a in 4 downto 0 generate
        gen_bit: for b in 8 downto 0 generate

        febit3_inst: febit3
        port map(
            din_p => afe_p(a)(b),
            din_n => afe_n(a)(b),
            clock  => clock,
            clk500 => clk500,
            clk125 => clk125, -- aka clkdiv
            idelay_load => idelay_load_clk125(a), -- sync to clk125
            idelay_cntvaluein => idelay_tap(a), 
            idelay_en_vtc => idelay_en_vtc,
            iserdes_reset => iserdes_reset, -- async ok
            iserdes_bitslip => iserdes_bitslip(a),
            dout => dout(a)(b)
        );

        end generate gen_bit;
    end generate gen_afe;

    -- front end control and status registers access via AXI-LITE

    fe_axi_inst: fe_axi 
    port map(
        S_AXI_ACLK => S_AXI_ACLK,
        S_AXI_ARESETN => S_AXI_ARESETN,
        S_AXI_AWADDR => S_AXI_AWADDR,
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
        S_AXI_ARADDR => S_AXI_ARADDR,
        S_AXI_ARPROT => S_AXI_ARPROT,
        S_AXI_ARVALID => S_AXI_ARVALID,
        S_AXI_ARREADY => S_AXI_ARREADY,
        S_AXI_RDATA => S_AXI_RDATA,
        S_AXI_RRESP => S_AXI_RRESP,
        S_AXI_RVALID => S_AXI_RVALID,
        S_AXI_RREADY => S_AXI_RREADY,
        
        idelayctrl_ready => idelayctrl_ready,
        idelayctrl_reset => idelayctrl_reset,

        idelay_tap => idelay_tap,
        idelay_en_vtc => idelay_en_vtc,
        idelay_load => idelay_load,

        iserdes_bitslip => iserdes_bitslip,
        iserdes_reset => iserdes_reset,
        trig => trig_axi
    );

    -- there are some timing critical signals that must cross from the AXI-LITE clock domain into other clock domains...

    -- IDELAY_LOAD originates in S_AXI_ACLK and is a short momentary pulse (two cycles long), must be resynced to clk125 domain.

    -- IDELAYCTRL_RESET originates in S_AXI_ACLK, must be resynced in clk500 domain.

    -- TRIG_AXI originates in S_AXI_ACLK and is a short momentary pulse (two cycles long), must be resynced to clock domain.

    clk125_resync_proc: process(clk125)
    begin
        if rising_edge(clk125) then
            idelay_load_clk125 <= idelay_load;
        end if;
    end process clk125_resync_proc;

    clk500_resync_proc: process(clk500)
    begin
        if rising_edge(clk500) then
            idelayctrl_reset_clk500 <= idelayctrl_reset;
        end if;
    end process clk500_resync_proc;

    clock_resync_proc: process(clock)
    begin
        if rising_edge(clk500) then
            trig_reg <= trig_axi;
        end if;
    end process clock_resync_proc;

    trig <= trig_reg;

end fe_arch;