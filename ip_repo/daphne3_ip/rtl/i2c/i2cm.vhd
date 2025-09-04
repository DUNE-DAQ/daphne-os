-- i2cm.vhd
--
-- i2c master for PL DAPHNE3

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
library i2c;
Library UNISIM;
use UNISIM.vcomponents.all;
entity i2cm is
port(

    pl_sda_i: in std_logic;
    pl_scl_i: in std_logic;
    pl_sda_o: out std_logic;
    pl_scl_o: out std_logic;
    pl_sda_t: out std_logic;
    pl_scl_t: out std_logic;
  
    -- AXI-LITE interface
    iic2intc_irpt : out std_logic;
	S_AXI_ACLK	    : in std_logic; -- 100MHz
	S_AXI_ARESETN	: in std_logic;
	S_AXI_AWADDR	: in std_logic_vector(8 downto 0);
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
	S_AXI_ARADDR	: in std_logic_vector(8 downto 0);
	S_AXI_ARPROT	: in std_logic_vector(2 downto 0);
	S_AXI_ARVALID	: in std_logic;
	S_AXI_ARREADY	: out std_logic;
	S_AXI_RDATA	    : out std_logic_vector(31 downto 0);
	S_AXI_RRESP	    : out std_logic_vector(1 downto 0);
	S_AXI_RVALID	: out std_logic;
	S_AXI_RREADY	: in std_logic
  );
end i2cm;

architecture i2cm_arch of i2cm is






	signal axi_awaddr: std_logic_vector(8 downto 0);
	signal axi_awready: std_logic;
	signal axi_wready: std_logic;
	signal axi_bresp: std_logic_vector(1 downto 0);
	signal axi_bvalid: std_logic;
	signal axi_araddr: std_logic_vector(8 downto 0);
	signal axi_arready: std_logic;
	signal axi_rdata: std_logic_vector(31 downto 0);
	signal axi_rresp: std_logic_vector(1 downto 0);
	signal axi_rvalid: std_logic;
	signal axi_arready_reg: std_logic;
    signal axi_arvalid: std_logic;       
    signal axi_iic_int: std_logic;
	signal rden, wren: std_logic;
	signal aw_en: std_logic;
    signal addra: std_logic_vector(10 downto 0);
    
    
    signal pl_sda_o_reg:  std_logic;
    signal pl_scl_o_reg: std_logic;
    signal pl_sda_t_reg:  std_logic;
    signal pl_scl_t_reg:  std_logic;

begin


	 axi_awaddr <= S_AXI_AWADDR;
	 S_AXI_AWREADY <=  axi_awready;
	 S_AXI_WREADY <= axi_wready;
	 --axi_bresp
	 --axi_bvalid
	 axi_araddr <= S_AXI_ARADDR;
	-- axi_arready
	 --axi_rdata
	 S_AXI_RRESP <= axi_rresp;
	 S_AXI_RVALID <= axi_rvalid;
	 S_AXI_ARREADY <= axi_arready_reg;
     axi_arvalid  <= S_AXI_ARVALID;
     iic2intc_irpt <= axi_iic_int;
     pl_sda_o <= pl_sda_o_reg;
     pl_scl_o <= pl_scl_o_reg;
     pl_sda_t <= pl_sda_t_reg;
     pl_scl_t <= pl_scl_t_reg;

-- Xilinx IP core for I2C master goes here...
iic_master : entity work.axi_iic_0 
        port map(
         s_axi_aclk => S_AXI_ACLK,
        s_axi_aresetn =>  S_AXI_ARESETN,
        iic2intc_irpt =>  axi_iic_int,
        s_axi_awaddr =>  axi_awaddr,
        s_axi_awvalid =>  S_AXI_AWVALID,
        s_axi_awready =>  axi_awready,
        s_axi_wdata =>  S_AXI_WDATA,
        s_axi_wstrb => S_AXI_WSTRB, 
        s_axi_wvalid =>  S_AXI_WVALID,
        s_axi_wready =>  axi_wready,
        s_axi_bresp =>  S_AXI_BRESP,
        s_axi_bvalid =>  S_AXI_BVALID,
        s_axi_bready =>  S_AXI_BREADY,
        s_axi_araddr =>  axi_araddr,
        s_axi_arvalid =>  axi_arvalid,
        s_axi_arready =>  axi_arready_reg,
        s_axi_rdata =>  S_AXI_RDATA,
        s_axi_rresp =>  axi_rresp,
        s_axi_rvalid =>  axi_rvalid,
        s_axi_rready =>   S_AXI_RREADY,
        sda_t =>  pl_sda_t_reg,
        scl_t =>  pl_scl_t_reg,
       
        sda_i => pl_sda_i ,
        sda_o => pl_sda_o_reg ,
        scl_i => pl_scl_i  ,
        scl_o => pl_scl_o_reg,
        gpo => open   
        );

end i2cm_arch;
