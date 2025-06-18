-- testbench for SPI serial DACs
-- jamieson olsen <jamieson@fnal.gov>

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

library unisim;
use unisim.vcomponents.all;

use work.daphne3_package.all;

entity spim_dac_testbench is
end spim_dac_testbench;

architecture spim_dac_testbench_arch of spim_dac_testbench is

component AD5327 is
generic(refdes: STRING := "U?");
port(
    sclk: in std_logic; -- 30MHz max
    din: in std_logic;
    sync_n: in std_logic;
    ldac_n: in std_logic;
    sdo: out std_logic
);
end component;

component spim_dac
generic( CLKDIV: integer := 8 );
port(
    dac_sclk: out std_logic;
    dac_din: out std_logic;
    dac_sync_n: out std_logic;
    dac_ldac_n: out std_logic;

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
end component;

signal sclk, cs_n, din, dout, drdyn: std_logic;

-- AXI master -> slave signals

signal S_AXI_ACLK: std_logic := '0';
constant S_AXI_ACLK_period: time := 10.0ns;  -- 100 MHz

signal S_AXI_ARESETN: std_logic := '0'; -- start off with AXI bus in reset
signal S_AXI_AWADDR: std_logic_vector(31 downto 0) := (others=>'0');
signal S_AXI_AWPROT: std_logic_vector(2 downto 0) := (others=>'0');
signal S_AXI_AWVALID: std_logic := '0';
signal S_AXI_WDATA: std_logic_vector(31 downto 0) := (others=>'0');
signal S_AXI_WSTRB: std_logic_vector(3 downto 0) := (others=>'0');
signal S_AXI_WVALID: std_logic := '0';
signal S_AXI_BREADY: std_logic := '0';
signal S_AXI_ARADDR: std_logic_vector(31 downto 0) := (others=>'0');
signal S_AXI_ARPROT: std_logic_vector(2 downto 0) := (others=>'0');
signal S_AXI_ARVALID: std_logic := '0';
signal S_AXI_RREADY: std_logic := '0';

-- AXI slave -> master signals

signal S_AXI_AWREADY: std_logic;
signal S_AXI_WREADY: std_logic;
signal S_AXI_BRESP: std_logic_vector(1 downto 0);
signal S_AXI_BVALID: std_logic;
signal S_AXI_ARREADY: std_logic;
signal S_AXI_RDATA: std_logic_vector(31 downto 0);
signal S_AXI_RRESP: std_logic_vector(1 downto 0);
signal S_AXI_RVALID: std_logic;

signal din0, din1, din2: std_logic;
signal sync_n, ldac_n: std_logic;

begin

-- three serial DAC chips daisy chained...

firstdac_inst: AD5327
generic map(refdes => "U50")
port map(
    sclk => sclk,
    din => din0,
    sync_n => sync_n,
    ldac_n => ldac_n,
    sdo => din1
);

middledac_inst: AD5327
generic map(refdes => "U53")
port map(
    sclk => sclk,
    din => din1,
    sync_n => sync_n,
    ldac_n => ldac_n,
    sdo => din2
);

lastdac_inst: AD5327
generic map(refdes => "U5")
port map(
    sclk => sclk,
    din => din2,
    sync_n => sync_n,
    ldac_n => ldac_n,
    sdo => open
);

DUT: spim_dac
generic map( CLKDIV => 8 ) -- SCLK is 100MHz/8 = 12.5MHz OK
port map(

    dac_sclk => sclk,
    dac_din => din0,
    dac_sync_n => sync_n,
    dac_ldac_n => ldac_n,

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
    S_AXI_RREADY => S_AXI_RREADY
  );

-- now we simulate the AXI-LITE master doing reads and writes...

S_AXI_ACLK <= not S_AXI_ACLK after S_AXI_ACLK_period/2;

aximaster_proc: process

procedure axipoke( constant addr: in std_logic_vector;
                   constant data: in std_logic_vector ) is
begin
    wait until rising_edge(S_AXI_ACLK);
    S_AXI_AWADDR <= addr;
    S_AXI_AWVALID <= '1';
    S_AXI_WDATA <= data;
    S_AXI_WVALID <= '1';
    S_AXI_BREADY <= '1';
    S_AXI_WSTRB <= "1111";
    wait until (rising_edge(S_AXI_ACLK) and S_AXI_AWREADY='1' and S_AXI_WREADY='1');
    S_AXI_AWADDR <= X"00000000";
    S_AXI_AWVALID <= '0';
    S_AXI_WDATA <= X"00000000";
    S_AXI_AWVALID <= '0';
    S_AXI_WSTRB <= "0000";
    wait until (rising_edge(S_AXI_ACLK) and S_AXI_BVALID='1');
    S_AXI_BREADY <= '0';
end procedure axipoke;

procedure axipeek( constant addr: in std_logic_vector ) is
begin
    wait until rising_edge(S_AXI_ACLK);
    S_AXI_ARADDR <= addr;
    S_AXI_ARVALID <= '1';
    S_AXI_RREADY <= '1';
    wait until (rising_edge(S_AXI_ACLK) and S_AXI_ARREADY='1');
    S_AXI_ARADDR <= X"00000000";
    S_AXI_ARVALID <= '0';
    wait until (rising_edge(S_AXI_ACLK) and S_AXI_RVALID='1');
    S_AXI_RREADY <= '0';
end procedure axipeek;

begin

wait for 500ns;
S_AXI_ARESETN <= '1'; -- release AXI reset

wait for 500ns;
axipoke(addr => X"00000004", data => X"00005050"); -- data to sent to first DAC U50
wait for 500ns;
axipoke(addr => X"00000008", data => X"00005353"); -- data to sent to middle DAC U53
wait for 500ns;
axipoke(addr => X"0000000C", data => X"0000DAC5"); -- data to sent to last DAC U5

wait for 500ns;
axipoke(addr => X"00000000", data => X"DEADBEEF");  -- write anything to CTRL register... GO!

wait;
end process aximaster_proc;

end spim_dac_testbench_arch;
