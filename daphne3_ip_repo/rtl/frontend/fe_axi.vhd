-- fe_axi.vhd
-- daphne v3 front end control and status registers
-- adapted from the Vivado example/skeleton AXI-LITE interface sources
--
-- Jamieson Olsen <jamieson@fnal.gov>
--
-- all register access is 32 bit data (AXI-LITE requirement)
-- there are 13 32-bit registers here
--
-- base + 0 = Control Register R/W
--    bit 2 = idelay_en_vtc 
--    bit 1 = iserdes_reset
--    bit 0 = idelayctrl_reset

-- base + 4 = Status Register R/O
--    bit 0 = idelayctrl_ready

-- Write anything to the Trigger Register to force a momentary pulse 
-- on the TRIG output. This will force the SPY BUFFERS to capture the
-- raw input data. This register is write only and the data doesn't matter.
-- 
-- base + 8 = Trigger Register W/O 

-- IDELAY delay tap value is the lower 9 bits of these 32 bit registers
-- these registers are R/W. When any of these registers are written a momentary 
-- load pulse (two AXI clocks wide) will be generated on the corresponding
-- output idelay_load()
--
-- base + 12 = AFE0 Delay Tap Register
-- base + 16 = AFE1 Delay Tap Register
-- base + 20 = AFE2 Delay Tap Register
-- base + 24 = AFE3 Delay Tap Register
-- base + 28 = AFE4 Delay Tap Register

-- ISERDES bitslip value is the lower 4 bits of this 32 bit register it is R/W
-- 
-- base + 32 = AFE0 Bitslip Register
-- base + 36 = AFE1 Bitslip Register
-- base + 40 = AFE2 Bitslip Register
-- base + 44 = AFE3 Bitslip Register
-- base + 48 = AFE4 Bitslip Register

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

use work.daphne3_package.all;

entity fe_axi is  
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

        -- signals used by the front end, sync to S_AXI_ACLK

        idelayctrl_ready: in std_logic;
        idelay_tap: out array_5x9_type;
        idelay_load: out std_logic_vector(4 downto 0);
        iserdes_bitslip: out array_5x4_type;
        iserdes_reset: out std_logic;
        idelayctrl_reset: out std_logic;
        idelay_en_vtc: out std_logic;
        trig: out std_logic
	);
end fe_axi;

architecture fe_axi_arch of fe_axi is

	signal axi_awaddr	: std_logic_vector(31 downto 0);
	signal axi_awready	: std_logic;
	signal axi_wready	: std_logic;
	signal axi_bresp	: std_logic_vector(1 downto 0);
	signal axi_bvalid	: std_logic;
	signal axi_araddr	: std_logic_vector(31 downto 0);
	signal axi_arready	: std_logic;
	signal axi_rdata	: std_logic_vector(31 downto 0);
	signal axi_rresp	: std_logic_vector(1 downto 0);
	signal axi_rvalid	: std_logic;

	signal reg_rden: std_logic;
	signal reg_wren: std_logic;
	signal reg_data_out:std_logic_vector(31 downto 0);
	signal aw_en: std_logic;

	signal idelay_tap_reg: array_5x9_type;
    signal idelay_load0_reg, idelay_load1_reg, idelay_load2_reg: std_logic_vector(4 downto 0) := "00000";
    signal iserdes_bitslip_reg: array_5x4_type;
    signal control_reg: std_logic_vector(31 downto 0) := (others=>'0');
    signal trig_reg: std_logic_vector(5 downto 0) := "000000";

    -- register offsets are relative to the base address specified for this AXI-LITE slave instance

    constant CTRL_OFFSET: std_logic_vector(5 downto 0) := "000000";
    constant STAT_OFFSET: std_logic_vector(5 downto 0) := "000100";
    constant TRIG_OFFSET: std_logic_vector(5 downto 0) := "001000";
    constant TAP0_OFFSET: std_logic_vector(5 downto 0) := "001100";
    constant TAP1_OFFSET: std_logic_vector(5 downto 0) := "010000";
    constant TAP2_OFFSET: std_logic_vector(5 downto 0) := "010100";
    constant TAP3_OFFSET: std_logic_vector(5 downto 0) := "011000";
    constant TAP4_OFFSET: std_logic_vector(5 downto 0) := "011100";
    constant SLP0_OFFSET: std_logic_vector(5 downto 0) := "100000";
    constant SLP1_OFFSET: std_logic_vector(5 downto 0) := "100100";
    constant SLP2_OFFSET: std_logic_vector(5 downto 0) := "101000";
    constant SLP3_OFFSET: std_logic_vector(5 downto 0) := "101100";
    constant SLP4_OFFSET: std_logic_vector(5 downto 0) := "110000";

begin

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
          idelay_tap_reg(0) <= (others=>'0');
          idelay_tap_reg(1) <= (others=>'0');
          idelay_tap_reg(2) <= (others=>'0');
          idelay_tap_reg(3) <= (others=>'0');
          idelay_tap_reg(4) <= (others=>'0');
          idelay_load0_reg <= "00000";
          idelay_load1_reg <= "00000";
          idelay_load2_reg <= "00000";
          iserdes_bitslip_reg(0) <= (others=>'0');
          iserdes_bitslip_reg(1) <= (others=>'0');
          iserdes_bitslip_reg(2) <= (others=>'0');
          iserdes_bitslip_reg(3) <= (others=>'0');
          iserdes_bitslip_reg(4) <= (others=>'0');
          control_reg <= (others=>'0');
          trig_reg <= "000000";
	    else
	      if (reg_wren = '1' and S_AXI_WSTRB = "1111") then

            -- treat all of these register writes as if they are full 32 bits
            -- e.g. the four write strobe bits should be high

	        case ( axi_awaddr(5 downto 0) ) is

	          when CTRL_OFFSET => 
                control_reg <= S_AXI_WDATA;

	          when TRIG_OFFSET => 
                trig_reg(0) <= '1';

	          when TAP0_OFFSET => 
                idelay_tap_reg(0) <= S_AXI_WDATA(8 downto 0);
                idelay_load0_reg(0) <= '1';

	          when TAP1_OFFSET => 
                idelay_tap_reg(1) <= S_AXI_WDATA(8 downto 0);
                idelay_load0_reg(1) <= '1';

	          when TAP2_OFFSET => 
                idelay_tap_reg(2) <= S_AXI_WDATA(8 downto 0);
                idelay_load0_reg(2) <= '1';

	          when TAP3_OFFSET => 
                idelay_tap_reg(3) <= S_AXI_WDATA(8 downto 0);
                idelay_load0_reg(3) <= '1';

	          when TAP4_OFFSET => 
                idelay_tap_reg(4) <= S_AXI_WDATA(8 downto 0);
                idelay_load0_reg(4) <= '1';

              when SLP0_OFFSET =>
                iserdes_bitslip_reg(0) <= S_AXI_WDATA(3 downto 0);

              when SLP1_OFFSET =>
                iserdes_bitslip_reg(1) <= S_AXI_WDATA(3 downto 0);

              when SLP2_OFFSET =>
                iserdes_bitslip_reg(2) <= S_AXI_WDATA(3 downto 0);

              when SLP3_OFFSET =>
                iserdes_bitslip_reg(3) <= S_AXI_WDATA(3 downto 0);

              when SLP4_OFFSET =>
                iserdes_bitslip_reg(4) <= S_AXI_WDATA(3 downto 0);

	          when others =>
                control_reg <= control_reg;
                idelay_tap_reg(0) <= idelay_tap_reg(0);
                idelay_tap_reg(1) <= idelay_tap_reg(1);
                idelay_tap_reg(2) <= idelay_tap_reg(2);
                idelay_tap_reg(3) <= idelay_tap_reg(3);
                idelay_tap_reg(4) <= idelay_tap_reg(4);
                iserdes_bitslip_reg(0) <= iserdes_bitslip_reg(0);
                iserdes_bitslip_reg(1) <= iserdes_bitslip_reg(1);
                iserdes_bitslip_reg(2) <= iserdes_bitslip_reg(2);
                iserdes_bitslip_reg(3) <= iserdes_bitslip_reg(3);
                iserdes_bitslip_reg(4) <= iserdes_bitslip_reg(4);
	        end case;

          else 

            -- handle the momentary, self clearing outputs
            -- trigger pulse originates in AXICLK domain (100MHz) and crosses into master clock domain (62.5MHz)
            -- make this pulse FOUR AXICLKs wide just to be safe, and make it come from a single register 
            -- (not a combi function of multiple registers) to be clean...

            trig_reg(0) <= '0';
            trig_reg(1) <= trig_reg(0);
            trig_reg(2) <= trig_reg(1);
            trig_reg(3) <= trig_reg(2);
            trig_reg(4) <= trig_reg(3);
            trig_reg(5) <= trig_reg(4) or trig_reg(3) or trig_reg(2) or trig_reg(1) or trig_reg(0);

            -- idelay load pulse comes from AXICLK 100MHz and crosses into clk125 domain
            -- OK to make this two AXICLKs wide, and again, make this signal from a single register (idelay_load2_reg)
            -- and NOT a combi function of multiple registers to be cleaner.

            idelay_load2_reg <= idelay_load1_reg or idelay_load0_reg;
            idelay_load1_reg <= idelay_load0_reg;
            idelay_load0_reg <= "00000";

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

	reg_rden <= axi_arready and S_AXI_ARVALID and (not axi_rvalid) ;

    reg_data_out <= control_reg                        when (axi_araddr(5 downto 0)=CTRL_OFFSET) else
                    X"0000000" & "000" & idelayctrl_ready when (axi_araddr(5 downto 0)=STAT_OFFSET) else

                    X"00000" & "000" & idelay_tap_reg(0) when (axi_araddr(5 downto 0)=TAP0_OFFSET) else
                    X"00000" & "000" & idelay_tap_reg(1) when (axi_araddr(5 downto 0)=TAP1_OFFSET) else
                    X"00000" & "000" & idelay_tap_reg(2) when (axi_araddr(5 downto 0)=TAP2_OFFSET) else
                    X"00000" & "000" & idelay_tap_reg(3) when (axi_araddr(5 downto 0)=TAP3_OFFSET) else
                    X"00000" & "000" & idelay_tap_reg(4) when (axi_araddr(5 downto 0)=TAP4_OFFSET) else

                    X"0000000" & iserdes_bitslip_reg(0) when (axi_araddr(5 downto 0)=SLP0_OFFSET) else
                    X"0000000" & iserdes_bitslip_reg(1) when (axi_araddr(5 downto 0)=SLP1_OFFSET) else
                    X"0000000" & iserdes_bitslip_reg(2) when (axi_araddr(5 downto 0)=SLP2_OFFSET) else
                    X"0000000" & iserdes_bitslip_reg(3) when (axi_araddr(5 downto 0)=SLP3_OFFSET) else
                    X"0000000" & iserdes_bitslip_reg(4) when (axi_araddr(5 downto 0)=SLP4_OFFSET) else

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

    idelay_en_vtc <= control_reg(2);
    iserdes_reset <= control_reg(1);
    idelayctrl_reset <= control_reg(0);

    idelay_tap(0) <= idelay_tap_reg(0);
    idelay_tap(1) <= idelay_tap_reg(1);
    idelay_tap(2) <= idelay_tap_reg(2);
    idelay_tap(3) <= idelay_tap_reg(3);
    idelay_tap(4) <= idelay_tap_reg(4);

    -- the following outputs are pulse stretched to 3 AXI clocks wide and are momentary
    -- and come from a SINGLE register, as they will need to cross a clock domain and 
    -- we want to minimize chances of glitching. Xilinx UG571 says that IDELAY tap values
    -- should be stable one clk cycle before LOAD is asserted. using an extra register stage 
    -- (idelay_load2_reg) guarantees this is the case.

    trig <= trig_reg(5);
    idelay_load <= idelay_load2_reg; 

    iserdes_bitslip(0) <= iserdes_bitslip_reg(0);
    iserdes_bitslip(1) <= iserdes_bitslip_reg(1);
    iserdes_bitslip(2) <= iserdes_bitslip_reg(2);
    iserdes_bitslip(3) <= iserdes_bitslip_reg(3);
    iserdes_bitslip(4) <= iserdes_bitslip_reg(4);

end fe_axi_arch;
