-- spim_cm.vhd
--
-- spi master for current monitor (ADS1261IRHBT)
--
-- This is kind of a strange SPI chip in that the number of bytes to transfer varies 
-- depending on the command. Most commands are 16 bits. The RREG command (40h + rrh) is 24 bits.
-- The RDATA command (12h) is 48 bits. Optionally CRC bytes can be sent along with the commands.
--
-- to handle the varible number of bytes, use a FIFO interface. There are two FIFOs. The input FIFO
-- holds the bytes to send to the SPI device. As these bytes/bits are being shifted into the SPI device
-- the bits coming out of the SPI device are collected and those bytes are stored in the OUTPUT FIFO.
-- The FIFOs should contain only data for ONE SPI sequence at a time; don't try to put multiple SPI
-- transfers in there or else the SPI device will get confused. The output FIFO is automatically flushed
-- every time a GO! is issued. AXI data width is 32 bits but only the lower 8 bits are used here when
-- reading/writing FIFOs.
--
-- Base+0: write up to 16 bytes to the INPUT FIFO
--         read up to 16 bytes from the OUTPUT FIFO
-- Base+4: write anything here to trigger an SPI transfer (GO!)
--         reading this register returns the BUSY flag in the LSb 
--
-- example: we want to write four bytes to the device and read back 4 bytes at the same time.
-- 1. write the four bytes to base+0, this is four seprate writes and the byte is in the lower 8 bits
-- 2. write to the GO register base+4
-- 3. this module shifts the X bits into (and out of) the CM device
-- 4. read base+4 and check to see if the module is still busy
-- 5. when not busy, OK to read four bytes from the output FIFO

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
Library UNISIM;
use UNISIM.vcomponents.all;
library cm;

entity spim_cm is
port(
    cm_sclk: out std_logic; -- max 10MHz
    cm_csn: out std_logic_vector (0 downto 0);
    cm_din: out std_logic;
    cm_dout: in std_logic;
    cm_drdyn: in std_logic;

    -- AXI-LITE interface

    S_AXI_ACLK	    : in std_logic; -- 100MHz
    S_AXI_ARESETN	: in std_logic;
	S_AXI_AWADDR	: in std_logic_vector(6 downto 0);
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
	S_AXI_ARADDR	: in std_logic_vector(6 downto 0);
	S_AXI_ARPROT	: in std_logic_vector(2 downto 0);
	S_AXI_ARVALID	: in std_logic;
	S_AXI_ARREADY	: out std_logic;
	S_AXI_RDATA	    : out std_logic_vector(31 downto 0);
	S_AXI_RRESP	    : out std_logic_vector(1 downto 0);
	S_AXI_RVALID	: out std_logic;
	S_AXI_RREADY	: in std_logic;
	CM_SPI_INT: OUT std_logic ;
	ip2intc_irpt: out std_logic ;
	SPI_EXT_CLK: IN STD_LOGIC   --- 25mhz clock for the axi_quad spi
  );
end spim_cm;

architecture spim_cm_arch of spim_cm is

	signal axi_awaddr: std_logic_vector(6 downto 0);
	signal axi_awready: std_logic;
	signal axi_wready: std_logic;
	signal axi_bresp: std_logic_vector(1 downto 0);
	signal axi_bvalid: std_logic;
	signal axi_araddr: std_logic_vector(6 downto 0);
	signal axi_arready: std_logic;
	signal axi_rdata: std_logic_vector(31 downto 0);
	signal axi_rresp: std_logic_vector(1 downto 0);
	signal axi_rvalid: std_logic;
	--signal axi_arready_reg: std_logic;
    signal axi_arvalid: std_logic;       
    signal cm_spi_int_reg: std_logic ;
	signal rden, wren: std_logic;
	signal aw_en: std_logic;
    signal CM_SCLK_REG: std_logic ;
    signal cm_cs_reg: std_logic_vector (0 downto 0) ;
    signal cm_dout_reg:std_logic ;
begin

-- process 1: AXI slave writes to INPUT FIFO, reads from OUTPUT FIFO. Writes to command register trigger GO pulse,
--  reads from status register return FSM BUSY status

-- while(GO=1) do:
--  Flush OUTPUT FIFO
--  Begin SPI sequence
--      While (INPUT FIFO != EMPTY) do:
--          Read a byte from INPUT FIFO
--          SPI shift 8 bits
--          Store byte in OUTPUT FIFO
--  End SPI sequence


	 axi_awaddr <= S_AXI_AWADDR;
	 S_AXI_AWREADY <= axi_awready;
	 --axi_wready
	 S_AXI_BRESP <= axi_bresp;
	 S_AXI_BVALID <= axi_bvalid;
	 axi_araddr <= S_AXI_ARADDR;
	 S_AXI_ARREADY <= axi_arready;
	 S_AXI_RDATA <= axi_rdata;
	 S_AXI_RRESP <= axi_rresp;
	 S_AXI_RVALID <= axi_rvalid;
	 --axi_arready_reg
     --axi_arvalid    
    ip2intc_irpt <=  cm_spi_int_reg;
	 --rden, wren
	 --aw_en
     cm_sclk <= CM_SCLK_REG;
    cm_csn <= cm_cs_reg;
     cm_din <= cm_dout_reg;



cm_spi_master : entity work.axi_quad_spi_0 
port map(

        ext_spi_clk => SPI_EXT_CLK,
        s_axi_aclk => S_AXI_ACLK,
        s_axi_aresetn => S_AXI_ARESETN,
        s_axi_awaddr => axi_awaddr,
       s_axi_awvalid => S_AXI_AWVALID,
       s_axi_awready => axi_awready,
       s_axi_wdata => S_AXI_WDATA,
       s_axi_wstrb => S_AXI_WSTRB,
       s_axi_wvalid => S_AXI_WVALID,
       s_axi_wready => S_AXI_WREADY,
       s_axi_bresp => axi_bresp,
       s_axi_bvalid => axi_bvalid,
       s_axi_bready => S_AXI_BREADY,
       s_axi_araddr => axi_araddr,
        s_axi_arvalid => S_AXI_ARVALID,
        s_axi_arready  => axi_arready,
        s_axi_rdata  => axi_rdata,
        s_axi_rresp => axi_rresp,
        s_axi_rvalid  => axi_rvalid,
        s_axi_rready  => S_AXI_RREADY,
       io0_i  => '0',
       io0_o  => cm_dout_reg,   -- output
       io0_t => open ,
       io1_i => cm_dout ,    -- input
       io1_o => open,
       io1_t => open ,
       sck_i  => '0',
      sck_o  =>CM_SCLK_REG,
       sck_t => open ,
       ss_i  => "0",
        ss_o  => cm_cs_reg,
      ss_t => open ,
       ip2intc_irpt => cm_spi_int_reg
       
        
 
); 


end spim_cm_arch;
