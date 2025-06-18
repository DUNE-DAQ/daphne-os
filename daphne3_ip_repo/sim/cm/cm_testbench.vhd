-- testbench for current monitor module
-- jamieson olsen <jamieson@fnal.gov>

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

library unisim;
use unisim.vcomponents.all;

use work.daphne3_package.all;

entity cm_testbench is
end cm_testbench;

architecture cm_testbench_arch of cm_testbench is

component ADS1261 is -- simple BFM of the current monitor chip
port(
    sclk: in std_logic;
    din:  in std_logic;
    cs_n: in std_logic;
    dout: out std_logic;
    drdyn: out std_logic
);
end component;

component spim_cm -- custom SPI master logic for the current monitor
port(
    cm_sclk: out std_logic;
    cm_csn: out std_logic;
    cm_din: out std_logic;
    cm_dout: in std_logic;
    cm_drdyn: in std_logic;

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

begin

cm_inst: ADS1261
port map(
    sclk => sclk,
    din => din,
    cs_n => cs_n,
    dout => dout,
    drdyn => drdyn
);

DUT: spim_cm
port map(

    cm_sclk => sclk,
    cm_csn => cs_n,
    cm_din => din,
    cm_dout => dout,
    cm_drdyn => drdyn,

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

    wait for 300ns;
    S_AXI_ARESETN <= '1'; -- release AXI reset
    
    wait for 500ns;
    axipoke(addr => X"00000000", data => X"00000012"); -- Write 4 bytes into the input FIFO 
    wait for 500ns;
    axipoke(addr => X"00000000", data => X"00000034"); 
    wait for 500ns;
    axipoke(addr => X"00000000", data => X"00000056"); 
    wait for 500ns;
    axipoke(addr => X"00000000", data => X"00000078"); 
    
    wait for 500ns;
    axipoke(addr => X"00000004", data => X"DEADBEEF"); -- GO!
    
    wait for 5us; -- wait while SPI shifting is going on
    
    axipeek(addr => X"00000000"); -- read four bytes from the output FIFO
    wait for 300ns;
    axipeek(addr => X"00000000");
    wait for 300ns;
    axipeek(addr => X"00000000");
    wait for 400ns;
    axipeek(addr => X"00000000");

wait;
end process aximaster_proc;

end cm_testbench_arch;
