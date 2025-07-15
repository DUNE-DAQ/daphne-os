-- spim_afe.vhd
--
-- spi master for AFE chips and associated offset and trim DACs
-- this module contains three independent SPI masters attached to a single AXI-LITE interface
-- 
-- afe0 = 1 AFE + 2 trim DACs + 2 offset DACs
-- afe12 = 2 AFEs + 4 trim DACs + 4 offset DACs
-- afe34 = 2 AFEs + 4 trim DACs + 4 offset DACs
-- 
-- AFE = AFE5808AZCF and DAC = AD5327BRUZ-REEL7
--
-- AFEs are 24 bit transfers and support readback.
-- DACs are daisy chained in pairs, 16 bits each, 32 bits total, no read back, both must be written together.
--
-- base+0:  afe global control status register
--          bit 4 = AFE34 interface busy R/O
--          bit 3 = AFE12 interface busy R/O
--          bit 2 = AFE0 interface busy R/O
--          bit 1 = AFE power down R/W
--          bit 0 = AFE hard reset R/W
-- base+4:  afe0 data, 24 bits, R/W
-- base+8:  afe0 trim DAC data, 32 bits, W/O
-- base+12: afe0 offset DAC data, 32 bits, W/O
-- base+16: afe1 data 24 bits, R/W
-- base+20: afe1 trim DAC data, 32 bits, W/O
-- base+24: afe1 offset DAC data, 32 bits, W/O
-- base+28: afe2 data 24 bits, R/W
-- base+32: afe2 trim DAC data, 32 bits, W/O
-- base+36: afe2 offset DAC data, 32 bits, W/O
-- base+40: afe3 data 24 bits, R/W 
-- base+44: afe3 trim DAC data, 32 bits, W/O
-- base+48: afe3 offset DAC data, 32 bits, W/O
-- base+52: afe4 data 24 bits, R/W
-- base+56: afe4 trim DAC data, 32 bits, W/O
-- base+60: afe4 offset DAC data, 32 bits, W/O
--
-- take a modular approach here: make a small module that talks to a single AFE
-- make another module that talks to a pair of daisy chained DACs
-- then combine them to make the three SPI interfaces
--
-- after the AXI master writes to one of the data registers, the corresponding module will be BUSY
-- for SOME TIME while it is shifting that data through the SPI interface. It is the responsibility of the 
-- user to FIRST CHECK that these modules are NOT BUSY before attempting to write stuff!

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity spim_afe is
port(

    afe_rst: out std_logic; -- high = hard reset all AFEs
    afe_pdn: out std_logic; -- low = power down all AFEs

    afe0_miso: in std_logic;
    afe0_sclk: out std_logic;
    afe0_mosi: out std_logic;

    afe12_miso: in std_logic;
    afe12_sclk: out std_logic;
    afe12_mosi: out std_logic;

    afe34_miso: in std_logic;
    afe34_sclk: out std_logic;
    afe34_mosi: out std_logic;

    afe_sen: out std_logic_vector(4 downto 0);
    trim_sync_n: out std_logic_vector(4 downto 0);
    trim_ldac_n: out std_logic_vector(4 downto 0);
    offset_sync_n: out std_logic_vector(4 downto 0);
    offset_ldac_n: out std_logic_vector(4 downto 0);

    -- AXI-LITE interface

	S_AXI_ACLK	    : in std_logic; -- 100MHz
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
end spim_afe;

architecture spim_afe_arch of spim_afe is

component spim_dac2 is
generic( CLKDIV: integer := 8 );
port(
    clock: in std_logic;
    reset: in std_logic;
    din: in std_logic_vector(31 downto 0);
    we: in std_logic;
    busy: out std_logic;

    sclk: out std_logic;
    mosi: out std_logic;
    ldac_n: out std_logic;
    sync_n: out std_logic
);
end component;

component spim_afe1
generic( CLKDIV: integer := 8 );
port(
    clock: in std_logic;
    reset: in std_logic;
    din: in std_logic_vector(23 downto 0);
    we: in std_logic;
    dout: out std_logic_vector(23 downto 0);
    busy: out std_logic;

    sclk: out std_logic;
    sen:  out std_logic;
    mosi: out std_logic;
    miso: in std_logic
);
end component;

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
signal axi_arvalid: std_logic;    
signal reg_rden, reg_wren: std_logic;
signal aw_en: std_logic;
signal reg_data_out: std_logic_vector(31 downto 0);

signal reset: std_logic;
signal afe_we, afe_sclk, afe_mosi, afe_miso, afe_busy: std_logic_vector(4 downto 0);
signal trim_we, trim_sclk, trim_mosi, trim_busy: std_logic_vector(4 downto 0);
signal offset_we, offset_sclk, offset_mosi, offset_busy: std_logic_vector(4 downto 0);
type array_5x24_type is array(4 downto 0) of std_logic_vector(23 downto 0);
signal afe_dout: array_5x24_type;
signal busy0, busy12, busy34: std_logic;
signal afe_rst_reg, afe_pd_reg: std_logic := '0';

constant CTRLSTAT_OFFSET: std_logic_vector(5 downto 0) := "000000"; -- base + 0

constant AFE0_OFFSET:     std_logic_vector(5 downto 0) := std_logic_vector( to_unsigned( 4,6) ); -- base + 4
constant TRIM0_OFFSET:    std_logic_vector(5 downto 0) := std_logic_vector( to_unsigned( 8,6) ); -- base + 12
constant OFFS0_OFFSET:    std_logic_vector(5 downto 0) := std_logic_vector( to_unsigned(12,6) ); -- base + 8

constant AFE1_OFFSET:     std_logic_vector(5 downto 0) := std_logic_vector( to_unsigned(16,6) );
constant TRIM1_OFFSET:    std_logic_vector(5 downto 0) := std_logic_vector( to_unsigned(20,6) );
constant OFFS1_OFFSET:    std_logic_vector(5 downto 0) := std_logic_vector( to_unsigned(24,6) );

constant AFE2_OFFSET:     std_logic_vector(5 downto 0) := std_logic_vector( to_unsigned(28,6) );
constant TRIM2_OFFSET:    std_logic_vector(5 downto 0) := std_logic_vector( to_unsigned(32,6) );
constant OFFS2_OFFSET:    std_logic_vector(5 downto 0) := std_logic_vector( to_unsigned(36,6) );

constant AFE3_OFFSET:     std_logic_vector(5 downto 0) := std_logic_vector( to_unsigned(40,6) );
constant TRIM3_OFFSET:    std_logic_vector(5 downto 0) := std_logic_vector( to_unsigned(44,6) );
constant OFFS3_OFFSET:    std_logic_vector(5 downto 0) := std_logic_vector( to_unsigned(48,6) );

constant AFE4_OFFSET:     std_logic_vector(5 downto 0) := std_logic_vector( to_unsigned(52,6) );
constant TRIM4_OFFSET:    std_logic_vector(5 downto 0) := std_logic_vector( to_unsigned(56,6) );
constant OFFS4_OFFSET:    std_logic_vector(5 downto 0) := std_logic_vector( to_unsigned(60,6) );

begin

reset <= not S_AXI_ARESETN;

GenSpim: for i in 4 downto 0 generate

    afe_inst: spim_afe1 -- SPI master for AFE
    generic map( CLKDIV => 8 )
    port map( clock => S_AXI_ACLK, reset => reset, din => S_AXI_WDATA(23 downto 0), we => afe_we(i), dout => afe_dout(i), busy => afe_busy(i),
              sclk => afe_sclk(i), sen => afe_sen(i), mosi => afe_mosi(i), miso => afe_miso(i) );
    
    afe_trim_inst: spim_dac2 -- SPI master for 2 trim DACs
    generic map( CLKDIV => 8 )
    port map( clock => S_AXI_ACLK, reset => reset, din => S_AXI_WDATA, we => trim_we(i), busy => trim_busy(i),
              sclk => trim_sclk(i), mosi => trim_mosi(i), ldac_n => trim_ldac_n(i), sync_n => trim_sync_n(i) );
    
    afe_offset_inst: spim_dac2 -- SPI master for 2 offset DACs
    generic map( CLKDIV => 8 )
    port map( clock => S_AXI_ACLK, reset => reset, din => S_AXI_WDATA, we => offset_we(i), busy => offset_busy(i),
              sclk => offset_sclk(i), mosi => offset_mosi(i), ldac_n => offset_ldac_n(i), sync_n => offset_sync_n(i) );

end generate GenSpim;

afe0_sclk <= afe_sclk(0) and trim_sclk(0) and offset_sclk(0);
afe0_mosi <= afe_mosi(0) or  trim_mosi(0) or  offset_mosi(0);
afe_miso(0) <= afe0_miso;
busy0 <= afe_busy(0) or trim_busy(0) or offset_busy(0);

afe12_sclk <= afe_sclk(1) and trim_sclk(1) and offset_sclk(1) and afe_sclk(2) and trim_sclk(2) and offset_sclk(2);
afe12_mosi <= afe_mosi(1) or  trim_mosi(1) or  offset_mosi(1) or  afe_mosi(2) or  trim_mosi(2) or  offset_mosi(2);
afe_miso(1) <= afe12_miso;
afe_miso(2) <= afe12_miso;
busy12 <= afe_busy(1) or trim_busy(1) or offset_busy(1) or afe_busy(2) or trim_busy(2) or offset_busy(2);

afe34_sclk <= afe_sclk(3) and trim_sclk(3) and offset_sclk(3) and afe_sclk(4) and trim_sclk(4) and offset_sclk(4);
afe34_mosi <= afe_mosi(3) or  trim_mosi(3) or  offset_mosi(3) or  afe_mosi(4) or  trim_mosi(4) or  offset_mosi(4);
afe_miso(3) <= afe34_miso;
afe_miso(4) <= afe34_miso;
busy34 <= afe_busy(3) or trim_busy(3) or offset_busy(3) or afe_busy(4) or trim_busy(4) or offset_busy(4);

-- AXI LITE slave logic (adapted from Xilinx IP generator AXI-LITE slave example)

S_AXI_AWREADY <= axi_awready;
S_AXI_WREADY <= axi_wready;
S_AXI_BRESP	<= axi_bresp;
S_AXI_BVALID <= axi_bvalid;
S_AXI_ARREADY <= axi_arready;
S_AXI_RDATA	<= axi_rdata;
S_AXI_RRESP	<= axi_rresp;
S_AXI_RVALID <= axi_rvalid;

process (S_AXI_ACLK)
begin
  if rising_edge(S_AXI_ACLK) then 
    if S_AXI_ARESETN = '0' then
      axi_awready <= '0';
      aw_en <= '1';
    else
      if (axi_awready = '0' and S_AXI_AWVALID = '1' and S_AXI_WVALID = '1' and aw_en = '1') then
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

process (S_AXI_ACLK)
begin
  if rising_edge(S_AXI_ACLK) then 
    if S_AXI_ARESETN = '0' then
      axi_wready <= '0';
    else
      if (axi_wready = '0' and S_AXI_WVALID = '1' and S_AXI_AWVALID = '1' and aw_en = '1') then
        
          axi_wready <= '1';
      else
        axi_wready <= '0';
      end if;
    end if;
  end if;
end process; 

reg_wren <= axi_wready and S_AXI_WVALID and axi_awready and S_AXI_AWVALID ;

process (S_AXI_ACLK) -- register write logic
begin
  if rising_edge(S_AXI_ACLK) then 
    if (S_AXI_ARESETN = '0') then
      afe_rst_reg <= '0';
      afe_pd_reg <= '0';
    else
      if (reg_wren = '1' and S_AXI_WSTRB = "1111") then
        -- treat all of these register writes as if they are full 32 bits
        -- e.g. the four write strobe bits should be high
        case ( axi_awaddr(5 downto 0) ) is
          when CTRLSTAT_OFFSET => 
            afe_rst_reg <= S_AXI_WDATA(0); 
            afe_pd_reg <= S_AXI_WDATA(1); 
          when others =>
            null;
        end case;
      end if;
    end if;
  end if;                   
end process;

-- make the write enable signals for various modules. this is similar to writing to a simple register

afe_we(0) <= '1' when (reg_wren='1' and S_AXI_WSTRB="1111" and axi_awaddr(5 downto 0)=AFE0_OFFSET) else '0';
afe_we(1) <= '1' when (reg_wren='1' and S_AXI_WSTRB="1111" and axi_awaddr(5 downto 0)=AFE1_OFFSET) else '0';
afe_we(2) <= '1' when (reg_wren='1' and S_AXI_WSTRB="1111" and axi_awaddr(5 downto 0)=AFE2_OFFSET) else '0';
afe_we(3) <= '1' when (reg_wren='1' and S_AXI_WSTRB="1111" and axi_awaddr(5 downto 0)=AFE3_OFFSET) else '0';
afe_we(4) <= '1' when (reg_wren='1' and S_AXI_WSTRB="1111" and axi_awaddr(5 downto 0)=AFE4_OFFSET) else '0';

offset_we(0) <= '1' when (reg_wren='1' and S_AXI_WSTRB="1111" and axi_awaddr(5 downto 0)=OFFS0_OFFSET) else '0';
offset_we(1) <= '1' when (reg_wren='1' and S_AXI_WSTRB="1111" and axi_awaddr(5 downto 0)=OFFS1_OFFSET) else '0';
offset_we(2) <= '1' when (reg_wren='1' and S_AXI_WSTRB="1111" and axi_awaddr(5 downto 0)=OFFS2_OFFSET) else '0';
offset_we(3) <= '1' when (reg_wren='1' and S_AXI_WSTRB="1111" and axi_awaddr(5 downto 0)=OFFS3_OFFSET) else '0';
offset_we(4) <= '1' when (reg_wren='1' and S_AXI_WSTRB="1111" and axi_awaddr(5 downto 0)=OFFS4_OFFSET) else '0';

trim_we(0) <= '1' when (reg_wren='1' and S_AXI_WSTRB="1111" and axi_awaddr(5 downto 0)=TRIM0_OFFSET) else '0';
trim_we(1) <= '1' when (reg_wren='1' and S_AXI_WSTRB="1111" and axi_awaddr(5 downto 0)=TRIM1_OFFSET) else '0';
trim_we(2) <= '1' when (reg_wren='1' and S_AXI_WSTRB="1111" and axi_awaddr(5 downto 0)=TRIM2_OFFSET) else '0';
trim_we(3) <= '1' when (reg_wren='1' and S_AXI_WSTRB="1111" and axi_awaddr(5 downto 0)=TRIM3_OFFSET) else '0';
trim_we(4) <= '1' when (reg_wren='1' and S_AXI_WSTRB="1111" and axi_awaddr(5 downto 0)=TRIM4_OFFSET) else '0';

process (S_AXI_ACLK)
begin
  if rising_edge(S_AXI_ACLK) then 
    if S_AXI_ARESETN = '0' then
      axi_bvalid  <= '0';
      axi_bresp   <= "00"; 
    else
      if (axi_awready = '1' and S_AXI_AWVALID = '1' and axi_wready = '1' and S_AXI_WVALID = '1' and axi_bvalid = '0'  ) then
        axi_bvalid <= '1';
        axi_bresp  <= "00"; 
      elsif (S_AXI_BREADY = '1' and axi_bvalid = '1') then
        axi_bvalid <= '0';
      end if;
    end if;
  end if;                   
end process; 

process (S_AXI_ACLK)
begin
  if rising_edge(S_AXI_ACLK) then 
    if S_AXI_ARESETN = '0' then
      axi_arready <= '0';
      axi_araddr  <= (others => '1');
    else
      if (axi_arready = '0' and S_AXI_ARVALID = '1') then
        axi_arready <= '1';
        axi_araddr  <= S_AXI_ARADDR;           
      else
        axi_arready <= '0';
      end if;
    end if;
  end if;                   
end process; 

process (S_AXI_ACLK)
begin
  if rising_edge(S_AXI_ACLK) then
    if S_AXI_ARESETN = '0' then
      axi_rvalid <= '0';
      axi_rresp  <= "00";
    else
      if (axi_arready = '1' and S_AXI_ARVALID = '1' and axi_rvalid = '0') then
        axi_rvalid <= '1';
        axi_rresp  <= "00"; 
      elsif (axi_rvalid = '1' and S_AXI_RREADY = '1') then
        axi_rvalid <= '0';
      end if;            
    end if;
  end if;
end process;

reg_rden <= axi_arready and S_AXI_ARVALID and (not axi_rvalid) ;

-- note DAC registers are write only, will return 0 if attempt to read back.

reg_data_out <= (X"000000" & "000" & busy34 & busy12 & busy0 & afe_pd_reg & afe_rst_reg) when (axi_araddr(5 downto 0)=CTRLSTAT_OFFSET) else 
                (X"00" & afe_dout(0)) when (axi_araddr(5 downto 0)=AFE0_OFFSET) else
                (X"00" & afe_dout(1)) when (axi_araddr(5 downto 0)=AFE1_OFFSET) else
                (X"00" & afe_dout(2)) when (axi_araddr(5 downto 0)=AFE2_OFFSET) else
                (X"00" & afe_dout(3)) when (axi_araddr(5 downto 0)=AFE3_OFFSET) else
                (X"00" & afe_dout(4)) when (axi_araddr(5 downto 0)=AFE4_OFFSET) else
                X"00000000";

process( S_AXI_ACLK ) is
begin
  if (rising_edge (S_AXI_ACLK)) then
    if ( S_AXI_ARESETN = '0' ) then
      axi_rdata  <= (others => '0');
    else
      if (reg_rden = '1') then
          axi_rdata <= reg_data_out;
      end if;   
    end if;
  end if;
end process;

afe_rst <= afe_rst_reg; 
afe_pdn <= not afe_pd_reg;

end spim_afe_arch;