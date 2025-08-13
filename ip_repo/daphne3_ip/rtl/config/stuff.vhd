-- stuff.vhd
--
-- this module is a "catch all" for a bunch of misc stuff that exists on the PL side
-- and needs to connect to the PS side via a single axi-lite interface.
--
-- "stuff" has some 32-bit registers:
--
-- base+00: fan speed control register, 8 bits, R/W. 
--          0x00=off, 0xFF=full speed. power on default is full speed.
-- base+04: fan0 speed in RPM, 12 bits unsigned, R/O
-- base+08: fan1 speed in RPM, 12 bits unsigned, R/O
-- base+12: vbias control, one bit, R/W
-- base+16: analog mux enable lines (mux_en), 2 bits, R/W
-- base+20: analog mux address lines (mux_a), 2 bits, R/W
-- base+24: status LEDs, 6 bits, R/W
-- base+28: the GIT commit number, 28 bits, R/O
-- base+32: self triggered mode channel enable ch31..ch00 (31..0) R/W 
-- base+36: self triggered mode channel enable ch39..ch32 (7..0) R/W 

-- *** TO DO:
-- base+32: link_id(5..0) R/W 
-- base+36: slot_id(3..0) R/W 
-- base+40: crate_id(9..0) R/W 
-- base+44: detector_id(5..0) R/W 
-- base+48: version_id(5..0) R/W 
-- base+52: threshold(13..0) R/W 

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

use work.daphne3_package.all;

entity stuff is
port(
    fan_tach: in  std_logic_vector(1 downto 0); -- fan tach speed monitoring
    fan_ctrl: out std_logic; -- pwm speed control common to both fans
    hvbias_en: out std_logic; -- high = high voltage bias generator is ON
    mux_en: out std_logic_vector(1 downto 0); -- analog mux enables
    mux_a: out std_logic_vector(1 downto 0); -- analog mux selects
    stat_led: out std_logic_vector(5 downto 0); -- general purpose LEDs
    version: in std_logic_vector(27 downto 0); -- GIT version number
    core_chan_enable: out std_logic_vector(39 downto 0); -- channel enables for self-trig core
    adhoc: out std_logic_vector(7 downto 0); -- command for adhoc trigger
    st_config: out std_logic_vector(13 downto 0); -- Config param for Self-Trigger and Local Primitive Calculation, CIEMAT (Nacho)
    signal_delay: out std_logic_vector(4 downto 0); -- amount of delays to set for Self Trigger Latency (8 x signal_delay, signal delay is from 0 to 31 tics)
    threshold_xc: out std_logic_vector(41 downto 0); -- cross correlation trigger threshold 
    filter_output_selector: out std_logic_vector(1 downto 0); --Esteban 
    -- ti_trigger: out std_logic_vector(7 downto 0); -------------------------
    -- ti_trigger_stbr: out std_logic;  -------------------------
    reset_st_counters: out std_logic; -- reset for self trigger counter flags
    afe_comp_enable: out std_logic_vector(39 downto 0); -- enable digital afe compensator
    invert_enable: out std_logic_vector(39 downto 0); -- invert signal polarity
    TCount: in array_40x64_type; -- array of number of trigger in self trigger mode per channel
    Pcount: in array_40x64_type; -- array of total self trigger frames per channel

    -- AXI-LITE interface

	S_AXI_ACLK	    : in std_logic; -- assume this is 100MHz
	S_AXI_ARESETN	: in std_logic;
	S_AXI_AWADDR	: in std_logic_vector(31 downto 0);
	S_AXI_AWPROT	: in std_logic_vector(2 downto 0);
	S_AXI_AWVALID	: in std_logic;
	S_AXI_AWREADY	: out std_logic;
	S_AXI_WDATA	    : in std_logic_vector(31 downto 0);
	S_AXI_WSTRB	    : in std_logic_vector(3 downto 0);
	S_AXI_WVALID	: in std_logic;
	S_AXI_WREADY	: out std_logic;
	S_AXI_BRESP	    : out std_logic_vector(1 downto 0);
	S_AXI_BVALID	: out std_logic;
	S_AXI_BREADY	: in std_logic;
	S_AXI_ARADDR	: in std_logic_vector(31 downto 0);
	S_AXI_ARPROT	: in std_logic_vector(2 downto 0);
	S_AXI_ARVALID	: in std_logic;
	S_AXI_ARREADY	: out std_logic;
	S_AXI_RDATA	    : out std_logic_vector(31 downto 0);
	S_AXI_RRESP	    : out std_logic_vector(1 downto 0);
	S_AXI_RVALID	: out std_logic;
	S_AXI_RREADY	: in std_logic
  );
end stuff;

architecture stuff_arch of stuff is

	signal axi_awaddr: std_logic_vector(31 downto 0);
	signal axi_awready: std_logic;
	signal axi_wready: std_logic;
	signal axi_bresp: std_logic_vector(1 downto 0);
	signal axi_bvalid: std_logic;
	signal axi_araddr: std_logic_vector(31 downto 0);
	signal axi_arready: std_logic;
	signal axi_rdata: std_logic_vector(31 downto 0);
	signal axi_rresp: std_logic_vector(1 downto 0);
	signal axi_rvalid: std_logic;
	signal axi_arready_reg: std_logic;
    signal axi_arvalid: std_logic;    
	signal reg_rden: std_logic;
	signal reg_wren: std_logic;
	signal reg_data_out:std_logic_vector(31 downto 0);
	signal aw_en: std_logic;

  signal adhoc_reg: std_logic_vector(7 downto 0) := DEFAULT_st_adhoc_command; -- command for ad hoc trigger
  signal st_config_reg: std_logic_vector(13 downto 0) := DEFAULT_st_config_command(15 downto 2); -- Config param for Self-Trigger and Local Primitive Calculation, CIEMAT (Nacho)
  signal signal_delay_reg: std_logic_vector(4 downto 0) := DEFAULT_st_config_command(20 downto 16);
  signal threshold_xc_reg: std_logic_vector(41 downto 0) := DEFAULT_threshold_xc; -- trig threshold relative to calculated baseline
  signal filter_output_selector_reg: std_logic_vector(1 downto 0) := DEFAULT_st_config_command(1 downto 0); --Esteban
  signal reset_st_counters_reg: std_logic := '0';
  signal afe_comp_enable_reg: std_logic_vector(39 downto 0) := DEFAULT_st_comp_command;
  signal invert_enable_reg: std_logic_vector(39 downto 0) := DEFAULT_st_invert_command;
  signal TCount_reg: array_40x64_type := (others => (others => '0')); 
  signal Pcount_reg: array_40x64_type := (others => (others => '0')); 
   
    component fanmon is
    port(
        clock: in std_logic;
        reset: in std_logic;
        tach: in std_logic;
        rpm: out std_logic_vector(11 downto 0)
      );
    end component;

    signal reset: std_logic;
    signal fan_count_reg: std_logic_vector(11 downto 0) := X"000";
    signal fan_speed_reg: std_logic_vector(7 downto 0) := X"FF"; 
    signal fan_ctrl_reg: std_logic;
    signal fan0_rpm, fan1_rpm: std_logic_vector(11 downto 0);
    signal stat_led_reg: std_logic_vector(5 downto 0) := "000000";
    signal hvbias_en_reg: std_logic := '0';
    signal mux_a_reg, mux_en_reg: std_logic_vector(1 downto 0) := "00";
    signal core_enable_reg: std_logic_vector(39 downto 0) := DEFAULT_core_enable;

    -- register offsets are relative to the base address specified for this AXI-LITE slave instance

    constant FANCTRL_OFFSET:                   std_logic_vector(9 downto 0) := "0000000000"; -- base+0
    constant FAN0SPD_OFFSET:                   std_logic_vector(9 downto 0) := "0000000100"; -- base+4
    constant FAN1SPD_OFFSET:                   std_logic_vector(9 downto 0) := "0000001000"; -- base+8
    constant HVBIAS_OFFSET:                    std_logic_vector(9 downto 0) := "0000001100"; -- base+12
    constant MUXEN_OFFSET:                     std_logic_vector(9 downto 0) := "0000010000"; -- base+16
    constant MUXA_OFFSET:                      std_logic_vector(9 downto 0) := "0000010100"; -- base+20
    constant LED_OFFSET:                       std_logic_vector(9 downto 0) := "0000011000"; -- base+24
    constant VER_OFFSET:                       std_logic_vector(9 downto 0) := "0000011100"; -- base+28
    constant CORE_EN_LO_OFFSET:                std_logic_vector(9 downto 0) := "0000100000"; -- base+32
    constant CORE_EN_HI_OFFSET:                std_logic_vector(9 downto 0) := "0000100100"; -- base+36

    constant ST_ADHOC_OFFSET:                  std_logic_vector(9 downto 0) := "0000101000"; -- base+40
    constant ST_CONFIG_OFFSET:                 std_logic_vector(9 downto 0) := "0000101100"; -- base+44
    constant ST_DELAY_OFFSET:                  std_logic_vector(9 downto 0) := "0000110000"; -- base+48
    constant ST_THRESHOLD_XC_LO_OFFSET:        std_logic_vector(9 downto 0) := "0000110100"; -- base+52
    constant ST_THRESHOLD_XC_HI_OFFSET:        std_logic_vector(9 downto 0) := "0000111000"; -- base+56
    constant ST_FILTER_OUTPUT_SELECTOR_OFFSET: std_logic_vector(9 downto 0) := "0000111100"; -- base+60
    constant ST_RESET_COUNTERS_OFFSET:         std_logic_vector(9 downto 0) := "0001000000"; -- base+64
    constant ST_AFE_COMP_ENABLE_LO_OFFSET:     std_logic_vector(9 downto 0) := "0001000100"; -- base+68
    constant ST_AFE_COMP_ENABLE_HI_OFFSET:     std_logic_vector(9 downto 0) := "0001001000"; -- base+72
    constant ST_INVERT_ENABLE_LO_OFFSET:       std_logic_vector(9 downto 0) := "0001001100"; -- base+76
    constant ST_INVERT_ENABLE_HI_OFFSET:       std_logic_vector(9 downto 0) := "0001010000"; -- base+80
    constant ST_PCOUNT_CH00_LO_OFFSET:         std_logic_vector(9 downto 0) := "0001010100"; -- base+84
    constant ST_PCOUNT_CH00_HI_OFFSET:         std_logic_vector(9 downto 0) := "0001011000"; -- base+88
    constant ST_PCOUNT_CH01_LO_OFFSET:         std_logic_vector(9 downto 0) := "0001011100"; -- base+92
    constant ST_PCOUNT_CH01_HI_OFFSET:         std_logic_vector(9 downto 0) := "0001100000"; -- base+96
    constant ST_PCOUNT_CH02_LO_OFFSET:         std_logic_vector(9 downto 0) := "0001100100"; -- base+100
    constant ST_PCOUNT_CH02_HI_OFFSET:         std_logic_vector(9 downto 0) := "0001101000"; -- base+104
    constant ST_PCOUNT_CH03_LO_OFFSET:         std_logic_vector(9 downto 0) := "0001101100"; -- base+108
    constant ST_PCOUNT_CH03_HI_OFFSET:         std_logic_vector(9 downto 0) := "0001110000"; -- base+112
    constant ST_PCOUNT_CH04_LO_OFFSET:         std_logic_vector(9 downto 0) := "0001110100"; -- base+116
    constant ST_PCOUNT_CH04_HI_OFFSET:         std_logic_vector(9 downto 0) := "0001111000"; -- base+120
    constant ST_PCOUNT_CH05_LO_OFFSET:         std_logic_vector(9 downto 0) := "0001111100"; -- base+124
    constant ST_PCOUNT_CH05_HI_OFFSET:         std_logic_vector(9 downto 0) := "0010000000"; -- base+128
    constant ST_PCOUNT_CH06_LO_OFFSET:         std_logic_vector(9 downto 0) := "0010000100"; -- base+132
    constant ST_PCOUNT_CH06_HI_OFFSET:         std_logic_vector(9 downto 0) := "0010001000"; -- base+136
    constant ST_PCOUNT_CH07_LO_OFFSET:         std_logic_vector(9 downto 0) := "0010001100"; -- base+140
    constant ST_PCOUNT_CH07_HI_OFFSET:         std_logic_vector(9 downto 0) := "0010010000"; -- base+144
    constant ST_PCOUNT_CH08_LO_OFFSET:         std_logic_vector(9 downto 0) := "0010010100"; -- base+148
    constant ST_PCOUNT_CH08_HI_OFFSET:         std_logic_vector(9 downto 0) := "0010011000"; -- base+152
    constant ST_PCOUNT_CH09_LO_OFFSET:         std_logic_vector(9 downto 0) := "0010011100"; -- base+156
    constant ST_PCOUNT_CH09_HI_OFFSET:         std_logic_vector(9 downto 0) := "0010100000"; -- base+160
    constant ST_PCOUNT_CH10_LO_OFFSET:         std_logic_vector(9 downto 0) := "0010100100"; -- base+164
    constant ST_PCOUNT_CH10_HI_OFFSET:         std_logic_vector(9 downto 0) := "0010101000"; -- base+168
    constant ST_PCOUNT_CH11_LO_OFFSET:         std_logic_vector(9 downto 0) := "0010101100"; -- base+172
    constant ST_PCOUNT_CH11_HI_OFFSET:         std_logic_vector(9 downto 0) := "0010110000"; -- base+176
    constant ST_PCOUNT_CH12_LO_OFFSET:         std_logic_vector(9 downto 0) := "0010110100"; -- base+180
    constant ST_PCOUNT_CH12_HI_OFFSET:         std_logic_vector(9 downto 0) := "0010111000"; -- base+184
    constant ST_PCOUNT_CH13_LO_OFFSET:         std_logic_vector(9 downto 0) := "0010111100"; -- base+188
    constant ST_PCOUNT_CH13_HI_OFFSET:         std_logic_vector(9 downto 0) := "0011000000"; -- base+192
    constant ST_PCOUNT_CH14_LO_OFFSET:         std_logic_vector(9 downto 0) := "0011000100"; -- base+196
    constant ST_PCOUNT_CH14_HI_OFFSET:         std_logic_vector(9 downto 0) := "0011001000"; -- base+200
    constant ST_PCOUNT_CH15_LO_OFFSET:         std_logic_vector(9 downto 0) := "0011001100"; -- base+204
    constant ST_PCOUNT_CH15_HI_OFFSET:         std_logic_vector(9 downto 0) := "0011010000"; -- base+208
    constant ST_PCOUNT_CH16_LO_OFFSET:         std_logic_vector(9 downto 0) := "0011010100"; -- base+212
    constant ST_PCOUNT_CH16_HI_OFFSET:         std_logic_vector(9 downto 0) := "0011011000"; -- base+216
    constant ST_PCOUNT_CH17_LO_OFFSET:         std_logic_vector(9 downto 0) := "0011011100"; -- base+220
    constant ST_PCOUNT_CH17_HI_OFFSET:         std_logic_vector(9 downto 0) := "0011100000"; -- base+224
    constant ST_PCOUNT_CH18_LO_OFFSET:         std_logic_vector(9 downto 0) := "0011100100"; -- base+228
    constant ST_PCOUNT_CH18_HI_OFFSET:         std_logic_vector(9 downto 0) := "0011101000"; -- base+232
    constant ST_PCOUNT_CH19_LO_OFFSET:         std_logic_vector(9 downto 0) := "0011101100"; -- base+236
    constant ST_PCOUNT_CH19_HI_OFFSET:         std_logic_vector(9 downto 0) := "0011110000"; -- base+240
    constant ST_PCOUNT_CH20_LO_OFFSET:         std_logic_vector(9 downto 0) := "0011110100"; -- base+244
    constant ST_PCOUNT_CH20_HI_OFFSET:         std_logic_vector(9 downto 0) := "0011111000"; -- base+248
    constant ST_PCOUNT_CH21_LO_OFFSET:         std_logic_vector(9 downto 0) := "0011111100"; -- base+252
    constant ST_PCOUNT_CH21_HI_OFFSET:         std_logic_vector(9 downto 0) := "0100000000"; -- base+256
    constant ST_PCOUNT_CH22_LO_OFFSET:         std_logic_vector(9 downto 0) := "0100000100"; -- base+260
    constant ST_PCOUNT_CH22_HI_OFFSET:         std_logic_vector(9 downto 0) := "0100001000"; -- base+264
    constant ST_PCOUNT_CH23_LO_OFFSET:         std_logic_vector(9 downto 0) := "0100001100"; -- base+268
    constant ST_PCOUNT_CH23_HI_OFFSET:         std_logic_vector(9 downto 0) := "0100010000"; -- base+272
    constant ST_PCOUNT_CH24_LO_OFFSET:         std_logic_vector(9 downto 0) := "0100010100"; -- base+276
    constant ST_PCOUNT_CH24_HI_OFFSET:         std_logic_vector(9 downto 0) := "0100011000"; -- base+280
    constant ST_PCOUNT_CH25_LO_OFFSET:         std_logic_vector(9 downto 0) := "0100011100"; -- base+284
    constant ST_PCOUNT_CH25_HI_OFFSET:         std_logic_vector(9 downto 0) := "0100100000"; -- base+288
    constant ST_PCOUNT_CH26_LO_OFFSET:         std_logic_vector(9 downto 0) := "0100100100"; -- base+292
    constant ST_PCOUNT_CH26_HI_OFFSET:         std_logic_vector(9 downto 0) := "0100101000"; -- base+296
    constant ST_PCOUNT_CH27_LO_OFFSET:         std_logic_vector(9 downto 0) := "0100101100"; -- base+300
    constant ST_PCOUNT_CH27_HI_OFFSET:         std_logic_vector(9 downto 0) := "0100110000"; -- base+304
    constant ST_PCOUNT_CH28_LO_OFFSET:         std_logic_vector(9 downto 0) := "0100110100"; -- base+308
    constant ST_PCOUNT_CH28_HI_OFFSET:         std_logic_vector(9 downto 0) := "0100111000"; -- base+312
    constant ST_PCOUNT_CH29_LO_OFFSET:         std_logic_vector(9 downto 0) := "0100111100"; -- base+316
    constant ST_PCOUNT_CH29_HI_OFFSET:         std_logic_vector(9 downto 0) := "0101000000"; -- base+320
    constant ST_PCOUNT_CH30_LO_OFFSET:         std_logic_vector(9 downto 0) := "0101000100"; -- base+324
    constant ST_PCOUNT_CH30_HI_OFFSET:         std_logic_vector(9 downto 0) := "0101001000"; -- base+328
    constant ST_PCOUNT_CH31_LO_OFFSET:         std_logic_vector(9 downto 0) := "0101001100"; -- base+332
    constant ST_PCOUNT_CH31_HI_OFFSET:         std_logic_vector(9 downto 0) := "0101010000"; -- base+336
    constant ST_PCOUNT_CH32_LO_OFFSET:         std_logic_vector(9 downto 0) := "0101010100"; -- base+340
    constant ST_PCOUNT_CH32_HI_OFFSET:         std_logic_vector(9 downto 0) := "0101011000"; -- base+344
    constant ST_PCOUNT_CH33_LO_OFFSET:         std_logic_vector(9 downto 0) := "0101011100"; -- base+348
    constant ST_PCOUNT_CH33_HI_OFFSET:         std_logic_vector(9 downto 0) := "0101100000"; -- base+352
    constant ST_PCOUNT_CH34_LO_OFFSET:         std_logic_vector(9 downto 0) := "0101100100"; -- base+356
    constant ST_PCOUNT_CH34_HI_OFFSET:         std_logic_vector(9 downto 0) := "0101101000"; -- base+360
    constant ST_PCOUNT_CH35_LO_OFFSET:         std_logic_vector(9 downto 0) := "0101101100"; -- base+364
    constant ST_PCOUNT_CH35_HI_OFFSET:         std_logic_vector(9 downto 0) := "0101110000"; -- base+368
    constant ST_PCOUNT_CH36_LO_OFFSET:         std_logic_vector(9 downto 0) := "0101110100"; -- base+372
    constant ST_PCOUNT_CH36_HI_OFFSET:         std_logic_vector(9 downto 0) := "0101111000"; -- base+376
    constant ST_PCOUNT_CH37_LO_OFFSET:         std_logic_vector(9 downto 0) := "0101111100"; -- base+380
    constant ST_PCOUNT_CH37_HI_OFFSET:         std_logic_vector(9 downto 0) := "0110000000"; -- base+384
    constant ST_PCOUNT_CH38_LO_OFFSET:         std_logic_vector(9 downto 0) := "0110000100"; -- base+388
    constant ST_PCOUNT_CH38_HI_OFFSET:         std_logic_vector(9 downto 0) := "0110001000"; -- base+392
    constant ST_PCOUNT_CH39_LO_OFFSET:         std_logic_vector(9 downto 0) := "0110001100"; -- base+396
    constant ST_PCOUNT_CH39_HI_OFFSET:         std_logic_vector(9 downto 0) := "0110010000"; -- base+400
    constant ST_TCOUNT_CH00_LO_OFFSET:         std_logic_vector(9 downto 0) := "0110010100"; -- base+404
    constant ST_TCOUNT_CH00_HI_OFFSET:         std_logic_vector(9 downto 0) := "0110011000"; -- base+408
    constant ST_TCOUNT_CH01_LO_OFFSET:         std_logic_vector(9 downto 0) := "0110011100"; -- base+412
    constant ST_TCOUNT_CH01_HI_OFFSET:         std_logic_vector(9 downto 0) := "0110100000"; -- base+416
    constant ST_TCOUNT_CH02_LO_OFFSET:         std_logic_vector(9 downto 0) := "0110100100"; -- base+420
    constant ST_TCOUNT_CH02_HI_OFFSET:         std_logic_vector(9 downto 0) := "0110101000"; -- base+424
    constant ST_TCOUNT_CH03_LO_OFFSET:         std_logic_vector(9 downto 0) := "0110101100"; -- base+428
    constant ST_TCOUNT_CH03_HI_OFFSET:         std_logic_vector(9 downto 0) := "0110110000"; -- base+432
    constant ST_TCOUNT_CH04_LO_OFFSET:         std_logic_vector(9 downto 0) := "0110110100"; -- base+436
    constant ST_TCOUNT_CH04_HI_OFFSET:         std_logic_vector(9 downto 0) := "0110111000"; -- base+440
    constant ST_TCOUNT_CH05_LO_OFFSET:         std_logic_vector(9 downto 0) := "0110111100"; -- base+444
    constant ST_TCOUNT_CH05_HI_OFFSET:         std_logic_vector(9 downto 0) := "0111000000"; -- base+448
    constant ST_TCOUNT_CH06_LO_OFFSET:         std_logic_vector(9 downto 0) := "0111000100"; -- base+452
    constant ST_TCOUNT_CH06_HI_OFFSET:         std_logic_vector(9 downto 0) := "0111001000"; -- base+456
    constant ST_TCOUNT_CH07_LO_OFFSET:         std_logic_vector(9 downto 0) := "0111001100"; -- base+460
    constant ST_TCOUNT_CH07_HI_OFFSET:         std_logic_vector(9 downto 0) := "0111010000"; -- base+464
    constant ST_TCOUNT_CH08_LO_OFFSET:         std_logic_vector(9 downto 0) := "0111010100"; -- base+468
    constant ST_TCOUNT_CH08_HI_OFFSET:         std_logic_vector(9 downto 0) := "0111011000"; -- base+472
    constant ST_TCOUNT_CH09_LO_OFFSET:         std_logic_vector(9 downto 0) := "0111011100"; -- base+476
    constant ST_TCOUNT_CH09_HI_OFFSET:         std_logic_vector(9 downto 0) := "0111100000"; -- base+480
    constant ST_TCOUNT_CH10_LO_OFFSET:         std_logic_vector(9 downto 0) := "0111100100"; -- base+484
    constant ST_TCOUNT_CH10_HI_OFFSET:         std_logic_vector(9 downto 0) := "0111101000"; -- base+488
    constant ST_TCOUNT_CH11_LO_OFFSET:         std_logic_vector(9 downto 0) := "0111101100"; -- base+492
    constant ST_TCOUNT_CH11_HI_OFFSET:         std_logic_vector(9 downto 0) := "0111110000"; -- base+496
    constant ST_TCOUNT_CH12_LO_OFFSET:         std_logic_vector(9 downto 0) := "0111110100"; -- base+500
    constant ST_TCOUNT_CH12_HI_OFFSET:         std_logic_vector(9 downto 0) := "0111111000"; -- base+504
    constant ST_TCOUNT_CH13_LO_OFFSET:         std_logic_vector(9 downto 0) := "0111111100"; -- base+508
    constant ST_TCOUNT_CH13_HI_OFFSET:         std_logic_vector(9 downto 0) := "1000000000"; -- base+512
    constant ST_TCOUNT_CH14_LO_OFFSET:         std_logic_vector(9 downto 0) := "1000000100"; -- base+516
    constant ST_TCOUNT_CH14_HI_OFFSET:         std_logic_vector(9 downto 0) := "1000001000"; -- base+520
    constant ST_TCOUNT_CH15_LO_OFFSET:         std_logic_vector(9 downto 0) := "1000001100"; -- base+524
    constant ST_TCOUNT_CH15_HI_OFFSET:         std_logic_vector(9 downto 0) := "1000010000"; -- base+528
    constant ST_TCOUNT_CH16_LO_OFFSET:         std_logic_vector(9 downto 0) := "1000010100"; -- base+532
    constant ST_TCOUNT_CH16_HI_OFFSET:         std_logic_vector(9 downto 0) := "1000011000"; -- base+536
    constant ST_TCOUNT_CH17_LO_OFFSET:         std_logic_vector(9 downto 0) := "1000011100"; -- base+540
    constant ST_TCOUNT_CH17_HI_OFFSET:         std_logic_vector(9 downto 0) := "1000100000"; -- base+544
    constant ST_TCOUNT_CH18_LO_OFFSET:         std_logic_vector(9 downto 0) := "1000100100"; -- base+548
    constant ST_TCOUNT_CH18_HI_OFFSET:         std_logic_vector(9 downto 0) := "1000101000"; -- base+552
    constant ST_TCOUNT_CH19_LO_OFFSET:         std_logic_vector(9 downto 0) := "1000101100"; -- base+556
    constant ST_TCOUNT_CH19_HI_OFFSET:         std_logic_vector(9 downto 0) := "1000110000"; -- base+560
    constant ST_TCOUNT_CH20_LO_OFFSET:         std_logic_vector(9 downto 0) := "1000110100"; -- base+564
    constant ST_TCOUNT_CH20_HI_OFFSET:         std_logic_vector(9 downto 0) := "1000111000"; -- base+568
    constant ST_TCOUNT_CH21_LO_OFFSET:         std_logic_vector(9 downto 0) := "1000111100"; -- base+572
    constant ST_TCOUNT_CH21_HI_OFFSET:         std_logic_vector(9 downto 0) := "1001000000"; -- base+576
    constant ST_TCOUNT_CH22_LO_OFFSET:         std_logic_vector(9 downto 0) := "1001000100"; -- base+580
    constant ST_TCOUNT_CH22_HI_OFFSET:         std_logic_vector(9 downto 0) := "1001001000"; -- base+584
    constant ST_TCOUNT_CH23_LO_OFFSET:         std_logic_vector(9 downto 0) := "1001001100"; -- base+588
    constant ST_TCOUNT_CH23_HI_OFFSET:         std_logic_vector(9 downto 0) := "1001010000"; -- base+592
    constant ST_TCOUNT_CH24_LO_OFFSET:         std_logic_vector(9 downto 0) := "1001010100"; -- base+596
    constant ST_TCOUNT_CH24_HI_OFFSET:         std_logic_vector(9 downto 0) := "1001011000"; -- base+600
    constant ST_TCOUNT_CH25_LO_OFFSET:         std_logic_vector(9 downto 0) := "1001011100"; -- base+604
    constant ST_TCOUNT_CH25_HI_OFFSET:         std_logic_vector(9 downto 0) := "1001100000"; -- base+608
    constant ST_TCOUNT_CH26_LO_OFFSET:         std_logic_vector(9 downto 0) := "1001100100"; -- base+612
    constant ST_TCOUNT_CH26_HI_OFFSET:         std_logic_vector(9 downto 0) := "1001101000"; -- base+616
    constant ST_TCOUNT_CH27_LO_OFFSET:         std_logic_vector(9 downto 0) := "1001101100"; -- base+620
    constant ST_TCOUNT_CH27_HI_OFFSET:         std_logic_vector(9 downto 0) := "1001110000"; -- base+624
    constant ST_TCOUNT_CH28_LO_OFFSET:         std_logic_vector(9 downto 0) := "1001110100"; -- base+628
    constant ST_TCOUNT_CH28_HI_OFFSET:         std_logic_vector(9 downto 0) := "1001111000"; -- base+632
    constant ST_TCOUNT_CH29_LO_OFFSET:         std_logic_vector(9 downto 0) := "1001111100"; -- base+636
    constant ST_TCOUNT_CH29_HI_OFFSET:         std_logic_vector(9 downto 0) := "1010000000"; -- base+640
    constant ST_TCOUNT_CH30_LO_OFFSET:         std_logic_vector(9 downto 0) := "1010000100"; -- base+644
    constant ST_TCOUNT_CH30_HI_OFFSET:         std_logic_vector(9 downto 0) := "1010001000"; -- base+648
    constant ST_TCOUNT_CH31_LO_OFFSET:         std_logic_vector(9 downto 0) := "1010001100"; -- base+652
    constant ST_TCOUNT_CH31_HI_OFFSET:         std_logic_vector(9 downto 0) := "1010010000"; -- base+656
    constant ST_TCOUNT_CH32_LO_OFFSET:         std_logic_vector(9 downto 0) := "1010010100"; -- base+660
    constant ST_TCOUNT_CH32_HI_OFFSET:         std_logic_vector(9 downto 0) := "1010011000"; -- base+664
    constant ST_TCOUNT_CH33_LO_OFFSET:         std_logic_vector(9 downto 0) := "1010011100"; -- base+668
    constant ST_TCOUNT_CH33_HI_OFFSET:         std_logic_vector(9 downto 0) := "1010100000"; -- base+672
    constant ST_TCOUNT_CH34_LO_OFFSET:         std_logic_vector(9 downto 0) := "1010100100"; -- base+676
    constant ST_TCOUNT_CH34_HI_OFFSET:         std_logic_vector(9 downto 0) := "1010101000"; -- base+680
    constant ST_TCOUNT_CH35_LO_OFFSET:         std_logic_vector(9 downto 0) := "1010101100"; -- base+684
    constant ST_TCOUNT_CH35_HI_OFFSET:         std_logic_vector(9 downto 0) := "1010110000"; -- base+688
    constant ST_TCOUNT_CH36_LO_OFFSET:         std_logic_vector(9 downto 0) := "1010110100"; -- base+692
    constant ST_TCOUNT_CH36_HI_OFFSET:         std_logic_vector(9 downto 0) := "1010111000"; -- base+696
    constant ST_TCOUNT_CH37_LO_OFFSET:         std_logic_vector(9 downto 0) := "1010111100"; -- base+700
    constant ST_TCOUNT_CH37_HI_OFFSET:         std_logic_vector(9 downto 0) := "1011000000"; -- base+704
    constant ST_TCOUNT_CH38_LO_OFFSET:         std_logic_vector(9 downto 0) := "1011000100"; -- base+708
    constant ST_TCOUNT_CH38_HI_OFFSET:         std_logic_vector(9 downto 0) := "1011001000"; -- base+712
    constant ST_TCOUNT_CH39_LO_OFFSET:         std_logic_vector(9 downto 0) := "1011001100"; -- base+716
    constant ST_TCOUNT_CH39_HI_OFFSET:         std_logic_vector(9 downto 0) := "1011010000"; -- base+720

begin

reset <= not S_AXI_ARESETN;

-- fan pwm control logic

-- The fan speed is directly proportional to the duty cycle of the PWM signal. 
-- Internally the fans have an analog circuit to do this, so the fan speed is 
-- in theory infinitely adjustable.

-- The output fan_ctrl is inverted by Q2 on the board and is common to both fans.
--
-- if fan_ctrl=0 the fan PWM signal will be HIGH and fans run at FULL SPEED. 
-- if fan_ctrl=1 the PWM signal will be LOW and the fans will be STOPPED.
-- if fan_ctrl is 25kHz clock (high 25%, low 75%) then the fans will be running at 75%
-- if fan_ctrl is 25kHz clock (high 75%, low 25%) then the fans will be running at 25%

-- take the 100MHz AXI clock and divide it by 4096 to produce 24.4kHz clock
-- suitable for driving the fan speed pwm signal. duty cycle is controlled by
-- fan_speed_reg: 0 = fan off, 255 = fan full speed.

fanspeed_proc: process(S_AXI_ACLK)
begin
    if rising_edge(S_AXI_ACLK) then
        if (reset='1') then
            fan_count_reg <= (others=>'0');
            fan_speed_reg <= X"FF";
            fan_ctrl_reg <= '0';
        else
            fan_count_reg <= std_logic_vector( unsigned(fan_count_reg) + 1 );
            if (fan_count_reg = X"000") then
                fan_ctrl_reg <= '1'; 
            elsif (fan_count_reg(11 downto 4)=fan_speed_reg) then
                fan_ctrl_reg <= '0';
            end if;
        end if;
    end if;
end process fanspeed_proc;

-- fan speed monitoring

fanmon0_inst: fanmon
port map( clock => S_AXI_ACLK, reset => reset, tach => fan_tach(0), rpm => fan0_rpm );

fanmon1_inst: fanmon
port map( clock => S_AXI_ACLK, reset => reset, tach => fan_tach(1), rpm => fan1_rpm );

-- AXI-LITE slave interface logic

S_AXI_AWREADY <= axi_awready;
S_AXI_WREADY <= axi_wready;
S_AXI_BRESP	<= axi_bresp;
S_AXI_BVALID <= axi_bvalid;
S_AXI_ARREADY <= axi_arready;
S_AXI_RDATA	<= axi_rdata;
S_AXI_RRESP	<= axi_rresp;
S_AXI_RVALID <= axi_rvalid;

-- Implement axi_awready generation
-- axi_awready is asserted for one S_AXI_ACLK clock cycle when both
-- S_AXI_AWVALID and S_AXI_WVALID are asserted. axi_awready is
-- de-asserted when reset is low.

process (S_AXI_ACLK)
begin
  if rising_edge(S_AXI_ACLK) then 
    if S_AXI_ARESETN = '0' then
      axi_awready <= '0';
      aw_en <= '1';
    else
      if (axi_awready = '0' and S_AXI_AWVALID = '1' and S_AXI_WVALID = '1' and aw_en = '1') then
        -- slave is ready to accept write address when
        -- there is a valid write address and write data
        -- on the write address and data bus. This design 
        -- expects no outstanding transactions. 
           axi_awready <= '1';
           aw_en <= '0';
        elsif (S_AXI_BREADY = '1' and axi_bvalid = '1') then
           aw_en <= '1';
           axi_awready <= '0';
      else
        axi_awready <= '0';
      end if;
    end if;
  end if;
end process;

-- Implement axi_awaddr latching
-- This process is used to latch the address when both 
-- S_AXI_AWVALID and S_AXI_WVALID are valid. 

process (S_AXI_ACLK)
begin
  if rising_edge(S_AXI_ACLK) then 
    if S_AXI_ARESETN = '0' then
      axi_awaddr <= (others => '0');
    else
      if (axi_awready = '0' and S_AXI_AWVALID = '1' and S_AXI_WVALID = '1' and aw_en = '1') then
        -- Write Address latching
        axi_awaddr <= S_AXI_AWADDR;
      end if;
    end if;
  end if;                   
end process; 

-- Implement axi_wready generation
-- axi_wready is asserted for one S_AXI_ACLK clock cycle when both
-- S_AXI_AWVALID and S_AXI_WVALID are asserted. axi_wready is 
-- de-asserted when reset is low. 

process (S_AXI_ACLK)
begin
  if rising_edge(S_AXI_ACLK) then 
    if S_AXI_ARESETN = '0' then
      axi_wready <= '0';
    else
      if (axi_wready = '0' and S_AXI_WVALID = '1' and S_AXI_AWVALID = '1' and aw_en = '1') then
          -- slave is ready to accept write data when 
          -- there is a valid write address and write data
          -- on the write address and data bus. This design 
          -- expects no outstanding transactions.           
          axi_wready <= '1';
      else
        axi_wready <= '0';
      end if;
    end if;
  end if;
end process; 

-- Implement memory mapped register select and write logic generation
-- The write data is accepted and written to memory mapped registers when
-- axi_awready, S_AXI_WVALID, axi_wready and S_AXI_WVALID are asserted. Write strobes are used to
-- select byte enables of slave registers while writing.
-- These registers are cleared when reset (active low) is applied.
-- Slave register write enable is asserted when valid address and data are available
-- and the slave is ready to accept the write address and write data.

reg_wren <= axi_wready and S_AXI_WVALID and axi_awready and S_AXI_AWVALID ;

process (S_AXI_ACLK)
begin
  if rising_edge(S_AXI_ACLK) then 
    if (S_AXI_ARESETN = '0') then
        fan_speed_reg <= X"FF";
        hvbias_en_reg <= '0';
        mux_en_reg <= "00";
        mux_a_reg <= "00";
        stat_led_reg <= "000000";
        core_enable_reg <= DEFAULT_core_enable;
        adhoc_reg <= DEFAULT_st_adhoc_command;
        st_config_reg <= DEFAULT_st_config_command(15 downto 2);
        signal_delay_reg <= DEFAULT_st_config_command(20 downto 16);
        threshold_xc_reg <= DEFAULT_threshold_xc;
        filter_output_selector_reg <= DEFAULT_st_config_command(1 downto 0);
        reset_st_counters_reg <= '0';
        afe_comp_enable_reg <= DEFAULT_st_comp_command;
        invert_enable_reg <= DEFAULT_st_invert_command;
    else
      if (reg_wren = '1' and S_AXI_WSTRB = "1111") then

        -- treat all of these register writes as if they are full 32 bits
        -- e.g. the four write strobe bits should be high

        case ( axi_awaddr(9 downto 0) ) is

          when FANCTRL_OFFSET => 
            fan_speed_reg <= S_AXI_WDATA(7 downto 0);

          when HVBIAS_OFFSET => 
            hvbias_en_reg <= S_AXI_WDATA(0);

          when MUXEN_OFFSET => 
            mux_en_reg <= S_AXI_WDATA(1 downto 0);

          when MUXA_OFFSET => 
            mux_a_reg <= S_AXI_WDATA(1 downto 0);

          when LED_OFFSET => 
            stat_led_reg <= S_AXI_WDATA(5 downto 0);

          when CORE_EN_LO_OFFSET => 
            core_enable_reg(31 downto 0) <= S_AXI_WDATA(31 downto 0);

          when CORE_EN_HI_OFFSET => 
            core_enable_reg(39 downto 32) <= S_AXI_WDATA(7 downto 0);

          when ST_ADHOC_OFFSET =>
            adhoc_reg <= S_AXI_WDATA(7 downto 0);

          when ST_CONFIG_OFFSET =>
            st_config_reg <= S_AXI_WDATA(13 downto 0);

          when ST_DELAY_OFFSET => 
            signal_delay_reg <= S_AXI_WDATA(4 downto 0);

          when ST_THRESHOLD_XC_LO_OFFSET => 
            threshold_xc_reg(31 downto 0) <= S_AXI_WDATA(31 downto 0);

          when ST_THRESHOLD_XC_HI_OFFSET =>
            threshold_xc_reg(41 downto 32) <= S_AXI_WDATA(9 downto 0);

          when ST_FILTER_OUTPUT_SELECTOR_OFFSET => 
            filter_output_selector_reg <= S_AXI_WDATA(1 downto 0);

          when ST_RESET_COUNTERS_OFFSET => 
            reset_st_counters_reg <= S_AXI_WDATA(0);

          when ST_AFE_COMP_ENABLE_LO_OFFSET => 
            afe_comp_enable_reg(31 downto 0) <= S_AXI_WDATA(31 downto 0);

          when ST_AFE_COMP_ENABLE_HI_OFFSET =>
            afe_comp_enable_reg(39 downto 32) <= S_AXI_WDATA(7 downto 0);

          when ST_INVERT_ENABLE_LO_OFFSET => 
            invert_enable_reg(31 downto 0) <= S_AXI_WDATA(31 downto 0);

          when ST_INVERT_ENABLE_HI_OFFSET =>
            invert_enable_reg(39 downto 32) <= S_AXI_WDATA(7 downto 0);        

          when others =>
            null;
             
        end case;

      end if;
    end if;
  end if;                   
end process; 

-- Implement write response logic generation
-- The write response and response valid signals are asserted by the slave 
-- when axi_wready, S_AXI_WVALID, axi_wready and S_AXI_WVALID are asserted.  
-- This marks the acceptance of address and indicates the status of 
-- write transaction.

process (S_AXI_ACLK)
begin
  if rising_edge(S_AXI_ACLK) then 
    if S_AXI_ARESETN = '0' then
      axi_bvalid  <= '0';
      axi_bresp   <= "00"; --need to work more on the responses
    else
      if (axi_awready = '1' and S_AXI_AWVALID = '1' and axi_wready = '1' and S_AXI_WVALID = '1' and axi_bvalid = '0'  ) then
        axi_bvalid <= '1';
        axi_bresp  <= "00"; 
      elsif (S_AXI_BREADY = '1' and axi_bvalid = '1') then   --check if bready is asserted while bvalid is high)
        axi_bvalid <= '0';                                   -- (there is a possibility that bready is always asserted high)
      end if;
    end if;
  end if;                   
end process; 

-- Implement axi_arready generation
-- axi_arready is asserted for one S_AXI_ACLK clock cycle when
-- S_AXI_ARVALID is asserted. axi_awready is 
-- de-asserted when reset (active low) is asserted. 
-- The read address is also latched when S_AXI_ARVALID is 
-- asserted. axi_araddr is reset to zero on reset assertion.

process (S_AXI_ACLK)
begin
  if rising_edge(S_AXI_ACLK) then 
    if S_AXI_ARESETN = '0' then
      axi_arready <= '0';
      axi_araddr  <= (others => '1');
    else
      if (axi_arready = '0' and S_AXI_ARVALID = '1') then
        -- indicates that the slave has acceped the valid read address
        axi_arready <= '1';
        -- Read Address latching 
        axi_araddr  <= S_AXI_ARADDR;           
      else
        axi_arready <= '0';
      end if;
    end if;
  end if;                   
end process; 

-- Implement axi_arvalid generation
-- axi_rvalid is asserted for one S_AXI_ACLK clock cycle when both 
-- S_AXI_ARVALID and axi_arready are asserted. The slave registers 
-- data are available on the axi_rdata bus at this instance. The 
-- assertion of axi_rvalid marks the validity of read data on the 
-- bus and axi_rresp indicates the status of read transaction.axi_rvalid 
-- is deasserted on reset (active low). axi_rresp and axi_rdata are 
-- cleared to zero on reset (active low). 

process (S_AXI_ACLK)
begin
  if rising_edge(S_AXI_ACLK) then
    if S_AXI_ARESETN = '0' then
      axi_rvalid <= '0';
      axi_rresp  <= "00";
    else
      if (axi_arready = '1' and S_AXI_ARVALID = '1' and axi_rvalid = '0') then
        -- Valid read data is available at the read data bus
        axi_rvalid <= '1';
        axi_rresp  <= "00"; -- 'OKAY' response
      elsif (axi_rvalid = '1' and S_AXI_RREADY = '1') then
        -- Read data is accepted by the master
        axi_rvalid <= '0';
      end if;            
    end if;
  end if;
end process;

-- Implement memory mapped register select and read logic generation
-- Slave register read enable is asserted when valid address is available
-- and the slave is ready to accept the read address.
-- reg_data_out is 32 bits

reg_rden <= axi_arready and S_AXI_ARVALID and (not axi_rvalid) ;

reg_data_out <= (X"000000" & fan_speed_reg)                        when (axi_araddr(9 downto 0)=FANCTRL_OFFSET) else
                (X"00000" & fan0_rpm)                              when (axi_araddr(9 downto 0)=FAN0SPD_OFFSET) else
                (X"00000" & fan1_rpm)                              when (axi_araddr(9 downto 0)=FAN1SPD_OFFSET) else
                (X"0000000" & "000" & hvbias_en_reg)               when (axi_araddr(9 downto 0)=HVBIAS_OFFSET) else
                (X"0000000" & "00" & mux_en_reg)                   when (axi_araddr(9 downto 0)=MUXEN_OFFSET) else
                (X"0000000" & "00" & mux_a_reg)                    when (axi_araddr(9 downto 0)=MUXA_OFFSET) else
                (X"000000" & "00" & stat_led_reg)                  when (axi_araddr(9 downto 0)=LED_OFFSET) else
                ("0000" & version)                                 when (axi_araddr(9 downto 0)=VER_OFFSET) else
                core_enable_reg(31 downto 0)                       when (axi_araddr(9 downto 0)=CORE_EN_LO_OFFSET) else
                (X"000000" & core_enable_reg(39 downto 32))        when (axi_araddr(9 downto 0)=CORE_EN_HI_OFFSET) else
                (X"000000" & adhoc_reg)                            when (axi_araddr(9 downto 0)=ST_ADHOC_OFFSET) else
                (X"0000" & "00" & st_config_reg)                   when (axi_araddr(9 downto 0)=ST_CONFIG_OFFSET) else
                (X"000000" & "000" & signal_delay_reg)             when (axi_araddr(9 downto 0)=ST_DELAY_OFFSET) else
                (threshold_xc_reg(31 downto 0))                    when (axi_araddr(9 downto 0)=ST_THRESHOLD_XC_LO_OFFSET) else
                (X"00000" & "00" & threshold_xc_reg(41 downto 32)) when (axi_araddr(9 downto 0)=ST_THRESHOLD_XC_HI_OFFSET) else
                (X"0000000" & "00" & filter_output_selector_reg)   when (axi_araddr(9 downto 0)=ST_FILTER_OUTPUT_SELECTOR_OFFSET) else
                (X"0000000" & "000" & reset_st_counters_reg)       when (axi_araddr(9 downto 0)=ST_RESET_COUNTERS_OFFSET) else
                (afe_comp_enable_reg(31 downto 0))                 when (axi_araddr(9 downto 0)=ST_AFE_COMP_ENABLE_LO_OFFSET) else
                (X"000000" & afe_comp_enable_reg(39 downto 32))    when (axi_araddr(9 downto 0)=ST_AFE_COMP_ENABLE_HI_OFFSET) else
                (invert_enable_reg(31 downto 0))                   when (axi_araddr(9 downto 0)=ST_INVERT_ENABLE_LO_OFFSET) else
                (X"000000" & invert_enable_reg(39 downto 32))      when (axi_araddr(9 downto 0)=ST_INVERT_ENABLE_HI_OFFSET) else
                
                (PCount_reg(0)(31 downto 0))                       when (axi_araddr(9 downto 0)=ST_PCOUNT_CH00_LO_OFFSET) else
                (PCount_reg(0)(63 downto 32))                      when (axi_araddr(9 downto 0)=ST_PCOUNT_CH00_HI_OFFSET) else
                (PCount_reg(1)(31 downto 0))                       when (axi_araddr(9 downto 0)=ST_PCOUNT_CH01_LO_OFFSET) else
                (PCount_reg(1)(63 downto 32))                      when (axi_araddr(9 downto 0)=ST_PCOUNT_CH01_HI_OFFSET) else
                (PCount_reg(2)(31 downto 0))                       when (axi_araddr(9 downto 0)=ST_PCOUNT_CH02_LO_OFFSET) else
                (PCount_reg(2)(63 downto 32))                      when (axi_araddr(9 downto 0)=ST_PCOUNT_CH02_HI_OFFSET) else
                (PCount_reg(3)(31 downto 0))                       when (axi_araddr(9 downto 0)=ST_PCOUNT_CH03_LO_OFFSET) else
                (PCount_reg(3)(63 downto 32))                      when (axi_araddr(9 downto 0)=ST_PCOUNT_CH03_HI_OFFSET) else
                (PCount_reg(4)(31 downto 0))                       when (axi_araddr(9 downto 0)=ST_PCOUNT_CH04_LO_OFFSET) else
                (PCount_reg(4)(63 downto 32))                      when (axi_araddr(9 downto 0)=ST_PCOUNT_CH04_HI_OFFSET) else
                (PCount_reg(5)(31 downto 0))                       when (axi_araddr(9 downto 0)=ST_PCOUNT_CH05_LO_OFFSET) else
                (PCount_reg(5)(63 downto 32))                      when (axi_araddr(9 downto 0)=ST_PCOUNT_CH05_HI_OFFSET) else
                (PCount_reg(6)(31 downto 0))                       when (axi_araddr(9 downto 0)=ST_PCOUNT_CH06_LO_OFFSET) else
                (PCount_reg(6)(63 downto 32))                      when (axi_araddr(9 downto 0)=ST_PCOUNT_CH06_HI_OFFSET) else
                (PCount_reg(7)(31 downto 0))                       when (axi_araddr(9 downto 0)=ST_PCOUNT_CH07_LO_OFFSET) else
                (PCount_reg(7)(63 downto 32))                      when (axi_araddr(9 downto 0)=ST_PCOUNT_CH07_HI_OFFSET) else
                (PCount_reg(8)(31 downto 0))                       when (axi_araddr(9 downto 0)=ST_PCOUNT_CH08_LO_OFFSET) else
                (PCount_reg(8)(63 downto 32))                      when (axi_araddr(9 downto 0)=ST_PCOUNT_CH08_HI_OFFSET) else
                (PCount_reg(9)(31 downto 0))                       when (axi_araddr(9 downto 0)=ST_PCOUNT_CH09_LO_OFFSET) else
                (PCount_reg(9)(63 downto 32))                      when (axi_araddr(9 downto 0)=ST_PCOUNT_CH09_HI_OFFSET) else
                (PCount_reg(10)(31 downto 0))                      when (axi_araddr(9 downto 0)=ST_PCOUNT_CH10_LO_OFFSET) else
                (PCount_reg(10)(63 downto 32))                     when (axi_araddr(9 downto 0)=ST_PCOUNT_CH10_HI_OFFSET) else
                (PCount_reg(11)(31 downto 0))                      when (axi_araddr(9 downto 0)=ST_PCOUNT_CH11_LO_OFFSET) else
                (PCount_reg(11)(63 downto 32))                     when (axi_araddr(9 downto 0)=ST_PCOUNT_CH11_HI_OFFSET) else
                (PCount_reg(12)(31 downto 0))                      when (axi_araddr(9 downto 0)=ST_PCOUNT_CH12_LO_OFFSET) else
                (PCount_reg(12)(63 downto 32))                     when (axi_araddr(9 downto 0)=ST_PCOUNT_CH12_HI_OFFSET) else
                (PCount_reg(13)(31 downto 0))                      when (axi_araddr(9 downto 0)=ST_PCOUNT_CH13_LO_OFFSET) else
                (PCount_reg(13)(63 downto 32))                     when (axi_araddr(9 downto 0)=ST_PCOUNT_CH13_HI_OFFSET) else
                (PCount_reg(14)(31 downto 0))                      when (axi_araddr(9 downto 0)=ST_PCOUNT_CH14_LO_OFFSET) else
                (PCount_reg(14)(63 downto 32))                     when (axi_araddr(9 downto 0)=ST_PCOUNT_CH14_HI_OFFSET) else
                (PCount_reg(15)(31 downto 0))                      when (axi_araddr(9 downto 0)=ST_PCOUNT_CH15_LO_OFFSET) else
                (PCount_reg(15)(63 downto 32))                     when (axi_araddr(9 downto 0)=ST_PCOUNT_CH15_HI_OFFSET) else
                (PCount_reg(16)(31 downto 0))                      when (axi_araddr(9 downto 0)=ST_PCOUNT_CH16_LO_OFFSET) else
                (PCount_reg(16)(63 downto 32))                     when (axi_araddr(9 downto 0)=ST_PCOUNT_CH16_HI_OFFSET) else
                (PCount_reg(17)(31 downto 0))                      when (axi_araddr(9 downto 0)=ST_PCOUNT_CH17_LO_OFFSET) else
                (PCount_reg(17)(63 downto 32))                     when (axi_araddr(9 downto 0)=ST_PCOUNT_CH17_HI_OFFSET) else
                (PCount_reg(18)(31 downto 0))                      when (axi_araddr(9 downto 0)=ST_PCOUNT_CH18_LO_OFFSET) else
                (PCount_reg(18)(63 downto 32))                     when (axi_araddr(9 downto 0)=ST_PCOUNT_CH18_HI_OFFSET) else
                (PCount_reg(19)(31 downto 0))                      when (axi_araddr(9 downto 0)=ST_PCOUNT_CH19_LO_OFFSET) else
                (PCount_reg(19)(63 downto 32))                     when (axi_araddr(9 downto 0)=ST_PCOUNT_CH19_HI_OFFSET) else
                (PCount_reg(20)(31 downto 0))                      when (axi_araddr(9 downto 0)=ST_PCOUNT_CH20_LO_OFFSET) else
                (PCount_reg(20)(63 downto 32))                     when (axi_araddr(9 downto 0)=ST_PCOUNT_CH20_HI_OFFSET) else
                (PCount_reg(21)(31 downto 0))                      when (axi_araddr(9 downto 0)=ST_PCOUNT_CH21_LO_OFFSET) else
                (PCount_reg(21)(63 downto 32))                     when (axi_araddr(9 downto 0)=ST_PCOUNT_CH21_HI_OFFSET) else
                (PCount_reg(22)(31 downto 0))                      when (axi_araddr(9 downto 0)=ST_PCOUNT_CH22_LO_OFFSET) else
                (PCount_reg(22)(63 downto 32))                     when (axi_araddr(9 downto 0)=ST_PCOUNT_CH22_HI_OFFSET) else
                (PCount_reg(23)(31 downto 0))                      when (axi_araddr(9 downto 0)=ST_PCOUNT_CH23_LO_OFFSET) else
                (PCount_reg(23)(63 downto 32))                     when (axi_araddr(9 downto 0)=ST_PCOUNT_CH23_HI_OFFSET) else
                (PCount_reg(24)(31 downto 0))                      when (axi_araddr(9 downto 0)=ST_PCOUNT_CH24_LO_OFFSET) else
                (PCount_reg(24)(63 downto 32))                     when (axi_araddr(9 downto 0)=ST_PCOUNT_CH24_HI_OFFSET) else
                (PCount_reg(25)(31 downto 0))                      when (axi_araddr(9 downto 0)=ST_PCOUNT_CH25_LO_OFFSET) else
                (PCount_reg(25)(63 downto 32))                     when (axi_araddr(9 downto 0)=ST_PCOUNT_CH25_HI_OFFSET) else
                (PCount_reg(26)(31 downto 0))                      when (axi_araddr(9 downto 0)=ST_PCOUNT_CH26_LO_OFFSET) else
                (PCount_reg(26)(63 downto 32))                     when (axi_araddr(9 downto 0)=ST_PCOUNT_CH26_HI_OFFSET) else
                (PCount_reg(27)(31 downto 0))                      when (axi_araddr(9 downto 0)=ST_PCOUNT_CH27_LO_OFFSET) else
                (PCount_reg(27)(63 downto 32))                     when (axi_araddr(9 downto 0)=ST_PCOUNT_CH27_HI_OFFSET) else
                (PCount_reg(28)(31 downto 0))                      when (axi_araddr(9 downto 0)=ST_PCOUNT_CH28_LO_OFFSET) else
                (PCount_reg(28)(63 downto 32))                     when (axi_araddr(9 downto 0)=ST_PCOUNT_CH28_HI_OFFSET) else
                (PCount_reg(29)(31 downto 0))                      when (axi_araddr(9 downto 0)=ST_PCOUNT_CH29_LO_OFFSET) else
                (PCount_reg(29)(63 downto 32))                     when (axi_araddr(9 downto 0)=ST_PCOUNT_CH29_HI_OFFSET) else
                (PCount_reg(30)(31 downto 0))                      when (axi_araddr(9 downto 0)=ST_PCOUNT_CH30_LO_OFFSET) else
                (PCount_reg(30)(63 downto 32))                     when (axi_araddr(9 downto 0)=ST_PCOUNT_CH30_HI_OFFSET) else
                (PCount_reg(31)(31 downto 0))                      when (axi_araddr(9 downto 0)=ST_PCOUNT_CH31_LO_OFFSET) else
                (PCount_reg(31)(63 downto 32))                     when (axi_araddr(9 downto 0)=ST_PCOUNT_CH31_HI_OFFSET) else
                (PCount_reg(32)(31 downto 0))                      when (axi_araddr(9 downto 0)=ST_PCOUNT_CH32_LO_OFFSET) else
                (PCount_reg(32)(63 downto 32))                     when (axi_araddr(9 downto 0)=ST_PCOUNT_CH32_HI_OFFSET) else
                (PCount_reg(33)(31 downto 0))                      when (axi_araddr(9 downto 0)=ST_PCOUNT_CH33_LO_OFFSET) else
                (PCount_reg(33)(63 downto 32))                     when (axi_araddr(9 downto 0)=ST_PCOUNT_CH33_HI_OFFSET) else
                (PCount_reg(34)(31 downto 0))                      when (axi_araddr(9 downto 0)=ST_PCOUNT_CH34_LO_OFFSET) else
                (PCount_reg(34)(63 downto 32))                     when (axi_araddr(9 downto 0)=ST_PCOUNT_CH34_HI_OFFSET) else
                (PCount_reg(35)(31 downto 0))                      when (axi_araddr(9 downto 0)=ST_PCOUNT_CH35_LO_OFFSET) else
                (PCount_reg(35)(63 downto 32))                     when (axi_araddr(9 downto 0)=ST_PCOUNT_CH35_HI_OFFSET) else
                (PCount_reg(36)(31 downto 0))                      when (axi_araddr(9 downto 0)=ST_PCOUNT_CH36_LO_OFFSET) else
                (PCount_reg(36)(63 downto 32))                     when (axi_araddr(9 downto 0)=ST_PCOUNT_CH36_HI_OFFSET) else
                (PCount_reg(37)(31 downto 0))                      when (axi_araddr(9 downto 0)=ST_PCOUNT_CH37_LO_OFFSET) else
                (PCount_reg(37)(63 downto 32))                     when (axi_araddr(9 downto 0)=ST_PCOUNT_CH37_HI_OFFSET) else
                (PCount_reg(38)(31 downto 0))                      when (axi_araddr(9 downto 0)=ST_PCOUNT_CH38_LO_OFFSET) else
                (PCount_reg(38)(63 downto 32))                     when (axi_araddr(9 downto 0)=ST_PCOUNT_CH38_HI_OFFSET) else
                (PCount_reg(39)(31 downto 0))                      when (axi_araddr(9 downto 0)=ST_PCOUNT_CH39_LO_OFFSET) else
                (PCount_reg(39)(63 downto 32))                     when (axi_araddr(9 downto 0)=ST_PCOUNT_CH39_HI_OFFSET) else
                
                (TCount_reg(0)(31 downto 0))                       when (axi_araddr(9 downto 0)=ST_TCOUNT_CH00_LO_OFFSET) else
                (TCount_reg(0)(63 downto 32))                      when (axi_araddr(9 downto 0)=ST_TCOUNT_CH00_HI_OFFSET) else
                (TCount_reg(1)(31 downto 0))                       when (axi_araddr(9 downto 0)=ST_TCOUNT_CH01_LO_OFFSET) else
                (TCount_reg(1)(63 downto 32))                      when (axi_araddr(9 downto 0)=ST_TCOUNT_CH01_HI_OFFSET) else
                (TCount_reg(2)(31 downto 0))                       when (axi_araddr(9 downto 0)=ST_TCOUNT_CH02_LO_OFFSET) else
                (TCount_reg(2)(63 downto 32))                      when (axi_araddr(9 downto 0)=ST_TCOUNT_CH02_HI_OFFSET) else
                (TCount_reg(3)(31 downto 0))                       when (axi_araddr(9 downto 0)=ST_TCOUNT_CH03_LO_OFFSET) else
                (TCount_reg(3)(63 downto 32))                      when (axi_araddr(9 downto 0)=ST_TCOUNT_CH03_HI_OFFSET) else
                (TCount_reg(4)(31 downto 0))                       when (axi_araddr(9 downto 0)=ST_TCOUNT_CH04_LO_OFFSET) else
                (TCount_reg(4)(63 downto 32))                      when (axi_araddr(9 downto 0)=ST_TCOUNT_CH04_HI_OFFSET) else
                (TCount_reg(5)(31 downto 0))                       when (axi_araddr(9 downto 0)=ST_TCOUNT_CH05_LO_OFFSET) else
                (TCount_reg(5)(63 downto 32))                      when (axi_araddr(9 downto 0)=ST_TCOUNT_CH05_HI_OFFSET) else
                (TCount_reg(6)(31 downto 0))                       when (axi_araddr(9 downto 0)=ST_TCOUNT_CH06_LO_OFFSET) else
                (TCount_reg(6)(63 downto 32))                      when (axi_araddr(9 downto 0)=ST_TCOUNT_CH06_HI_OFFSET) else
                (TCount_reg(7)(31 downto 0))                       when (axi_araddr(9 downto 0)=ST_TCOUNT_CH07_LO_OFFSET) else
                (TCount_reg(7)(63 downto 32))                      when (axi_araddr(9 downto 0)=ST_TCOUNT_CH07_HI_OFFSET) else
                (TCount_reg(8)(31 downto 0))                       when (axi_araddr(9 downto 0)=ST_TCOUNT_CH08_LO_OFFSET) else
                (TCount_reg(8)(63 downto 32))                      when (axi_araddr(9 downto 0)=ST_TCOUNT_CH08_HI_OFFSET) else
                (TCount_reg(9)(31 downto 0))                       when (axi_araddr(9 downto 0)=ST_TCOUNT_CH09_LO_OFFSET) else
                (TCount_reg(9)(63 downto 32))                      when (axi_araddr(9 downto 0)=ST_TCOUNT_CH09_HI_OFFSET) else
                (TCount_reg(10)(31 downto 0))                      when (axi_araddr(9 downto 0)=ST_TCOUNT_CH10_LO_OFFSET) else
                (TCount_reg(10)(63 downto 32))                     when (axi_araddr(9 downto 0)=ST_TCOUNT_CH10_HI_OFFSET) else
                (TCount_reg(11)(31 downto 0))                      when (axi_araddr(9 downto 0)=ST_TCOUNT_CH11_LO_OFFSET) else
                (TCount_reg(11)(63 downto 32))                     when (axi_araddr(9 downto 0)=ST_TCOUNT_CH11_HI_OFFSET) else
                (TCount_reg(12)(31 downto 0))                      when (axi_araddr(9 downto 0)=ST_TCOUNT_CH12_LO_OFFSET) else
                (TCount_reg(12)(63 downto 32))                     when (axi_araddr(9 downto 0)=ST_TCOUNT_CH12_HI_OFFSET) else
                (TCount_reg(13)(31 downto 0))                      when (axi_araddr(9 downto 0)=ST_TCOUNT_CH13_LO_OFFSET) else
                (TCount_reg(13)(63 downto 32))                     when (axi_araddr(9 downto 0)=ST_TCOUNT_CH13_HI_OFFSET) else
                (TCount_reg(14)(31 downto 0))                      when (axi_araddr(9 downto 0)=ST_TCOUNT_CH14_LO_OFFSET) else
                (TCount_reg(14)(63 downto 32))                     when (axi_araddr(9 downto 0)=ST_TCOUNT_CH14_HI_OFFSET) else
                (TCount_reg(15)(31 downto 0))                      when (axi_araddr(9 downto 0)=ST_TCOUNT_CH15_LO_OFFSET) else
                (TCount_reg(15)(63 downto 32))                     when (axi_araddr(9 downto 0)=ST_TCOUNT_CH15_HI_OFFSET) else
                (TCount_reg(16)(31 downto 0))                      when (axi_araddr(9 downto 0)=ST_TCOUNT_CH16_LO_OFFSET) else
                (TCount_reg(16)(63 downto 32))                     when (axi_araddr(9 downto 0)=ST_TCOUNT_CH16_HI_OFFSET) else
                (TCount_reg(17)(31 downto 0))                      when (axi_araddr(9 downto 0)=ST_TCOUNT_CH17_LO_OFFSET) else
                (TCount_reg(17)(63 downto 32))                     when (axi_araddr(9 downto 0)=ST_TCOUNT_CH17_HI_OFFSET) else
                (TCount_reg(18)(31 downto 0))                      when (axi_araddr(9 downto 0)=ST_TCOUNT_CH18_LO_OFFSET) else
                (TCount_reg(18)(63 downto 32))                     when (axi_araddr(9 downto 0)=ST_TCOUNT_CH18_HI_OFFSET) else
                (TCount_reg(19)(31 downto 0))                      when (axi_araddr(9 downto 0)=ST_TCOUNT_CH19_LO_OFFSET) else
                (TCount_reg(19)(63 downto 32))                     when (axi_araddr(9 downto 0)=ST_TCOUNT_CH19_HI_OFFSET) else
                (TCount_reg(20)(31 downto 0))                      when (axi_araddr(9 downto 0)=ST_TCOUNT_CH20_LO_OFFSET) else
                (TCount_reg(20)(63 downto 32))                     when (axi_araddr(9 downto 0)=ST_TCOUNT_CH20_HI_OFFSET) else
                (TCount_reg(21)(31 downto 0))                      when (axi_araddr(9 downto 0)=ST_TCOUNT_CH21_LO_OFFSET) else
                (TCount_reg(21)(63 downto 32))                     when (axi_araddr(9 downto 0)=ST_TCOUNT_CH21_HI_OFFSET) else
                (TCount_reg(22)(31 downto 0))                      when (axi_araddr(9 downto 0)=ST_TCOUNT_CH22_LO_OFFSET) else
                (TCount_reg(22)(63 downto 32))                     when (axi_araddr(9 downto 0)=ST_TCOUNT_CH22_HI_OFFSET) else
                (TCount_reg(23)(31 downto 0))                      when (axi_araddr(9 downto 0)=ST_TCOUNT_CH23_LO_OFFSET) else
                (TCount_reg(23)(63 downto 32))                     when (axi_araddr(9 downto 0)=ST_TCOUNT_CH23_HI_OFFSET) else
                (TCount_reg(24)(31 downto 0))                      when (axi_araddr(9 downto 0)=ST_TCOUNT_CH24_LO_OFFSET) else
                (TCount_reg(24)(63 downto 32))                     when (axi_araddr(9 downto 0)=ST_TCOUNT_CH24_HI_OFFSET) else
                (TCount_reg(25)(31 downto 0))                      when (axi_araddr(9 downto 0)=ST_TCOUNT_CH25_LO_OFFSET) else
                (TCount_reg(25)(63 downto 32))                     when (axi_araddr(9 downto 0)=ST_TCOUNT_CH25_HI_OFFSET) else
                (TCount_reg(26)(31 downto 0))                      when (axi_araddr(9 downto 0)=ST_TCOUNT_CH26_LO_OFFSET) else
                (TCount_reg(26)(63 downto 32))                     when (axi_araddr(9 downto 0)=ST_TCOUNT_CH26_HI_OFFSET) else
                (TCount_reg(27)(31 downto 0))                      when (axi_araddr(9 downto 0)=ST_TCOUNT_CH27_LO_OFFSET) else
                (TCount_reg(27)(63 downto 32))                     when (axi_araddr(9 downto 0)=ST_TCOUNT_CH27_HI_OFFSET) else
                (TCount_reg(28)(31 downto 0))                      when (axi_araddr(9 downto 0)=ST_TCOUNT_CH28_LO_OFFSET) else
                (TCount_reg(28)(63 downto 32))                     when (axi_araddr(9 downto 0)=ST_TCOUNT_CH28_HI_OFFSET) else
                (TCount_reg(29)(31 downto 0))                      when (axi_araddr(9 downto 0)=ST_TCOUNT_CH29_LO_OFFSET) else
                (TCount_reg(29)(63 downto 32))                     when (axi_araddr(9 downto 0)=ST_TCOUNT_CH29_HI_OFFSET) else
                (TCount_reg(30)(31 downto 0))                      when (axi_araddr(9 downto 0)=ST_TCOUNT_CH30_LO_OFFSET) else
                (TCount_reg(30)(63 downto 32))                     when (axi_araddr(9 downto 0)=ST_TCOUNT_CH30_HI_OFFSET) else
                (TCount_reg(31)(31 downto 0))                      when (axi_araddr(9 downto 0)=ST_TCOUNT_CH31_LO_OFFSET) else
                (TCount_reg(31)(63 downto 32))                     when (axi_araddr(9 downto 0)=ST_TCOUNT_CH31_HI_OFFSET) else
                (TCount_reg(32)(31 downto 0))                      when (axi_araddr(9 downto 0)=ST_TCOUNT_CH32_LO_OFFSET) else
                (TCount_reg(32)(63 downto 32))                     when (axi_araddr(9 downto 0)=ST_TCOUNT_CH32_HI_OFFSET) else
                (TCount_reg(33)(31 downto 0))                      when (axi_araddr(9 downto 0)=ST_TCOUNT_CH33_LO_OFFSET) else
                (TCount_reg(33)(63 downto 32))                     when (axi_araddr(9 downto 0)=ST_TCOUNT_CH33_HI_OFFSET) else
                (TCount_reg(34)(31 downto 0))                      when (axi_araddr(9 downto 0)=ST_TCOUNT_CH34_LO_OFFSET) else
                (TCount_reg(34)(63 downto 32))                     when (axi_araddr(9 downto 0)=ST_TCOUNT_CH34_HI_OFFSET) else
                (TCount_reg(35)(31 downto 0))                      when (axi_araddr(9 downto 0)=ST_TCOUNT_CH35_LO_OFFSET) else
                (TCount_reg(35)(63 downto 32))                     when (axi_araddr(9 downto 0)=ST_TCOUNT_CH35_HI_OFFSET) else
                (TCount_reg(36)(31 downto 0))                      when (axi_araddr(9 downto 0)=ST_TCOUNT_CH36_LO_OFFSET) else
                (TCount_reg(36)(63 downto 32))                     when (axi_araddr(9 downto 0)=ST_TCOUNT_CH36_HI_OFFSET) else
                (TCount_reg(37)(31 downto 0))                      when (axi_araddr(9 downto 0)=ST_TCOUNT_CH37_LO_OFFSET) else
                (TCount_reg(37)(63 downto 32))                     when (axi_araddr(9 downto 0)=ST_TCOUNT_CH37_HI_OFFSET) else
                (TCount_reg(38)(31 downto 0))                      when (axi_araddr(9 downto 0)=ST_TCOUNT_CH38_LO_OFFSET) else
                (TCount_reg(38)(63 downto 32))                     when (axi_araddr(9 downto 0)=ST_TCOUNT_CH38_HI_OFFSET) else
                (TCount_reg(39)(31 downto 0))                      when (axi_araddr(9 downto 0)=ST_TCOUNT_CH39_LO_OFFSET) else
                (TCount_reg(39)(63 downto 32))                     when (axi_araddr(9 downto 0)=ST_TCOUNT_CH39_HI_OFFSET) else
                
                X"00000000";

-- Output register or memory read data
process( S_AXI_ACLK ) is
begin
  if (rising_edge (S_AXI_ACLK)) then
    if ( S_AXI_ARESETN = '0' ) then
      axi_rdata  <= (others => '0');
    else
      if (reg_rden = '1') then
        -- When there is a valid read address (S_AXI_ARVALID) with 
        -- acceptance of read address by the slave (axi_arready), 
        -- output the read dada 
        -- Read address mux
          axi_rdata <= reg_data_out; -- register read data
      end if;   
    end if;
  end if;
end process;

-- assign registers to the outputs

fan_ctrl <= not fan_ctrl_reg; -- compensate for inverter Q2 on the board
mux_a <= mux_a_reg;
mux_en <= mux_en_reg;
hvbias_en <= hvbias_en_reg;
stat_led <= stat_led_reg; -- PL general board LEDs active high
core_chan_enable <= core_enable_reg;

adhoc <= adhoc_reg;
st_config <= st_config_reg;
signal_delay <= signal_delay_reg;
threshold_xc <= threshold_xc_reg;
filter_output_selector <= filter_output_selector_reg;
reset_st_counters <= reset_st_counters_reg;
afe_comp_enable <= afe_comp_enable_reg;
invert_enable <= invert_enable_reg;
TCount_reg <= TCount;
PCount_reg <= PCount;

end stuff_arch;