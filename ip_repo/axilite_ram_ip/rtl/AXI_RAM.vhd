-- DAPHNE output spy buffer module
-- waits for trigger, stores 1024 64-bit words, including 64 pre-trigger words
-- axi-lite reads 32 bits at a time
-- axi address 0 = captured data word 0, bits 31..0
-- axi address 4 = captured data word 1, bits 31..0
-- axi address 8 = captured data word 2, bits 31..0
-- ...
-- axi address 4092 = captured data word 1023, bits 31..0
-- axi address 4096 = captured data word 0, bits 63..32
-- axi address 5000 = captured data word 1, bits 63..32
-- ...
-- axi address 8188 = captured data word 1023, bits 63..32
--
-- from the AXI side this module appears as a 2k x 32 memory and is R/W
-- AXI uses BYTE addressing, so the first 32-bit word is address 0, 
-- the next 32 bit word is address 4, and so on up to address 8188.

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

library unisim;
use unisim.vcomponents.all;

entity outspy64_axilite is
	generic (
		C_S_AXI_DATA_WIDTH	: integer	:= 32;
		C_S_AXI_ADDR_WIDTH	: integer	:= 32
	);
	port (
	    clock: IN std_logic ;
	    trig: in std_logic ;
	    data_in: in std_logic_vector (63 downto 0);
	    FORCE_TRIG: out std_logic ;
	    Valid: in std_logic ;
	    last: in std_logic ;
	    S_AXI_ACLK	    : in std_logic;
		S_AXI_ARESETN	: in std_logic;
		S_AXI_AWADDR	: in std_logic_vector(C_S_AXI_ADDR_WIDTH-1 downto 0);
		S_AXI_AWPROT	: in std_logic_vector(2 downto 0);
		S_AXI_AWVALID	: in std_logic;
		S_AXI_AWREADY	: out std_logic;
		S_AXI_WDATA	    : in std_logic_vector(C_S_AXI_DATA_WIDTH-1 downto 0);
		S_AXI_WSTRB	    : in std_logic_vector((C_S_AXI_DATA_WIDTH/8)-1 downto 0); -- 32 bits writes only
		S_AXI_WVALID	: in std_logic;
		S_AXI_WREADY	: out std_logic;
		S_AXI_BRESP	    : out std_logic_vector(1 downto 0);
		S_AXI_BVALID	: out std_logic;
		S_AXI_BREADY	: in std_logic;
		S_AXI_ARADDR	: in std_logic_vector(C_S_AXI_ADDR_WIDTH-1 downto 0);
		S_AXI_ARPROT	: in std_logic_vector(2 downto 0);
		S_AXI_ARVALID	: in std_logic;
		S_AXI_ARREADY	: out std_logic;
		S_AXI_RDATA	    : out std_logic_vector(C_S_AXI_DATA_WIDTH-1 downto 0);
		S_AXI_RRESP	    : out std_logic_vector(1 downto 0);
		S_AXI_RVALID	: out std_logic;
		S_AXI_RREADY	: in std_logic
	);
end outspy64_axilite;

architecture outspy64_axilite_arch of outspy64_axilite is

	signal axi_awaddr	: std_logic_vector(C_S_AXI_ADDR_WIDTH-1 downto 0);
	signal axi_awready	: std_logic;
	signal axi_wready	: std_logic;
	signal axi_bresp	: std_logic_vector(1 downto 0);
	signal axi_bvalid	: std_logic;
	signal axi_araddr	: std_logic_vector(C_S_AXI_ADDR_WIDTH-1 downto 0);
	signal axi_arready	: std_logic;
	signal axi_rdata	: std_logic_vector(C_S_AXI_DATA_WIDTH-1 downto 0);
	signal axi_rresp	: std_logic_vector(1 downto 0);
	signal axi_rvalid	: std_logic;
    signal bit_count_reg : unsigned(5 downto 0) := (others => '0');
	signal axi_arready_reg	: std_logic; -- need to add 1 wait state for blockram
    signal axi_arvalid: std_logic;   
    
	signal rden, wren: std_logic;
	signal ram0_wea, ram1_wea: std_logic_vector(3 downto 0);
	signal ram0_ena, ram1_ena: std_logic;
	signal aw_en: std_logic;
    signal ram0_douta, ram1_douta, ram_dout: std_logic_vector(31 downto 0);

    signal addra, addrb: std_logic_vector(14 downto 0);
    signal reset_reg, we_reg: std_logic;   
    type state_type is (rst, wait4trig, store, wait4done);
    signal state: state_type;
    signal data_q0, data_delayed: std_logic_vector(63 downto 0);
    signal trig_d, trig_reg: std_logic:= '0' ;
begin

	-- I/O Connections assignments
	
	--reset_reg <= not S_AXI_ARESETN;
	
    --RAM1_DIN <= data_in (63 downto 32);
	S_AXI_AWREADY	<= axi_awready;
	S_AXI_WREADY	<= axi_wready;
	S_AXI_BRESP	    <= axi_bresp;
	S_AXI_BVALID	<= axi_bvalid;
	-- S_AXI_ARREADY	<= axi_arready;
    S_AXI_ARREADY	<= axi_arready_reg;
	S_AXI_RDATA	    <= axi_rdata;
	S_AXI_RRESP	    <= axi_rresp;
	S_AXI_RVALID	<= axi_rvalid;

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

	wren <= axi_wready and S_AXI_WVALID and axi_awready and S_AXI_AWVALID ;

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
	      elsif (S_AXI_BREADY = '1' and axi_bvalid = '1') then -- check if bready is asserted while bvalid is high)
	        axi_bvalid <= '0';                                 -- (there is a possibility that bready is always asserted high)
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
          axi_arready_reg <= '0';
	      axi_araddr  <= (others => '1');
	      axi_arvalid <= '0';
	    else
		  axi_arvalid <= S_AXI_ARVALID;
          if (axi_arready='0' and axi_arready_reg='0' and S_AXI_ARVALID='1') then
	        -- indicates that the slave has acceped the valid read address
	        axi_arready <= '1';
			axi_arready_reg <= axi_arready;
	        -- Read Address latching 
	        axi_araddr  <= S_AXI_ARADDR;           
	      else
	        axi_arready <= '0';
            axi_arready_reg <= axi_arready;
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
	      -- if (axi_arready = '1' and S_AXI_ARVALID = '1' and axi_rvalid = '0') then
          if (axi_arready_reg = '1' and S_AXI_ARVALID = '1' and axi_rvalid = '0') then
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

	rden <= axi_arready_reg and S_AXI_ARVALID and (not axi_rvalid) ;

	-- Output register or memory read data
    -- When there is a valid read address (S_AXI_ARVALID) with 
    -- acceptance of read address by the slave (axi_arready), 
    -- output the read data, read address mux

	process( S_AXI_ACLK ) is
	begin
	  if (rising_edge (S_AXI_ACLK)) then
	    if ( S_AXI_ARESETN = '0' ) then
	      axi_rdata  <= (others => '0');
	    else
	      if ( rden='1' ) then
	          axi_rdata <= ram_dout;
	      end if;   
	    end if;
	  end if;
	end process;


-- delay the data by 64 samples
                              
gendelay: for i in 63 downto 0 generate

    srlc32e_0_inst : srlc32e
    port map(
        clk => clock,
        ce => '1',
        a => "11111",
        d => data_in(i),
        q => open,
        q31 => data_q0(i)  
    );

    srlc32e_1_inst : srlc32e
    port map(
        clk => clock,
        ce => '1',
        a => "11111",
        d => data_q0(i),
        q => data_delayed(i),
        q31 => open  
    );

end generate gendelay;

-- FSM waits for trigger, writes 1024 words into blockram port B, then waits for the next trigger

 fsm_proc: process(clock)
    begin
        if rising_edge(clock) then
            trig_d <= trig;
            trig_reg <= trig and not trig_d;
            reset_reg <= not S_AXI_ARESETN; -- assume reset is async to square it up here

            if (reset_reg='1') then
                we_reg   <= '0';
                state    <= rst;
                addrb <= (others=>'0');

            else

                case state is

                    when rst =>
                        state <= wait4trig;

                    when wait4trig =>
                        if (Valid ='1') then
                            state <= store;
                            we_reg <= '1';
                            addrb <= (others=>'0');
                        else
                            state <= wait4trig;
                            we_reg <= '0';
                            addrb <= (others=>'0');
                        end if;
 
                    when store => 
                        if (addrb ="111111111100000") then
                            state <= wait4done;
                            we_reg <= '0';
                            trig_reg <= '0';
                        else
                            state <= store;
                            we_reg <= '1';
                            addrb <= std_logic_vector(unsigned(addrb) + 32); -- remember, addrb is the BIT address 
                        end if;

                    when wait4done =>
                        if (last = '1')  then
                            state <= wait4trig;
                        else
                            state <= wait4done;
                        end if;

                    when others => 
                        state <= rst;    
    
                end case;
            end if;
        end if;
    end process fsm_proc;

-- OK fun with address spaces...	
	
-- NOTE: we have TWO address pointers in AXI: a 32 bit write address pointer
-- (axi_awaddr) and a 32 bit read address pointer (axi_araddr). The issue here is that
-- our RAMs have only ONE address port (addra), so we need to switch between these two
-- address pointers depending on whether the AXI master is trying to write to the memory
-- or read from it.

-- AXI addresses (31..0) refer to BYTES! (shift left 2 bits to get 32 bit words)
-- BlockRAM addresses (14..0) refer to BITS! (shift left 5 bits to get 32 bit words)

addra <= (axi_awaddr(11 downto 2) & "00000") when (wren='1') else 
	     (axi_araddr(11 downto 2) & "00000");

-- when accessing these blockRAMs 32 bits at a time:

-- addrb = 0000000000 00000 is the address of word0
-- addrb = 0000000001 00000 is the address of word1
-- addrb = 0000000010 00000 is the address of word2

-- BlockRAM general enables

ram0_ena <= '1' when ( axi_arvalid='1' and axi_araddr(12)='0' ) else 
		    '1' when ( wren='1'        and axi_awaddr(12)='0' ) else 
            '0';
	
ram1_ena <= '1' when ( axi_arvalid='1' and axi_araddr(12)='1' ) else
		    '1' when ( wren='1'        and axi_awaddr(12)='1' ) else 
            '0';

-- BlockRAM write enables

ram0_wea <= "1111" when ( wren='1' and axi_awaddr(12)='0' ) else "0000";

ram1_wea <= "1111" when ( wren='1' and axi_awaddr(12)='1' ) else "0000";
	
-- When the AXI master tries to read from this module choose which RAM to send back based on the address range

ram_dout <= ram0_douta when (axi_araddr(12)='0') else 
            ram1_douta when (axi_araddr(12)='1') else 
            (others =>'Z');

-- RAMB36E2: 36K-bit Configurable Synchronous Block RAM
--           UltraScale
-- Xilinx HDL Language Template, version 2023.2
--
-- each blockram is 1024 x 32, single port, no output register, 

RAMB36E2_0_inst : RAMB36E2 -- LOW RAM BLOCK
generic map (
   -- CASCADE_ORDER_A, CASCADE_ORDER_B: "FIRST", "MIDDLE", "LAST", "NONE"
   CASCADE_ORDER_A => "NONE",
   CASCADE_ORDER_B => "NONE",
   -- CLOCK_DOMAINS: "COMMON", "INDEPENDENT"
   CLOCK_DOMAINS => "INDEPENDENT",
   -- Collision check: "ALL", "GENERATE_X_ONLY", "NONE", "WARNING_ONLY"
   SIM_COLLISION_CHECK => "ALL",
   -- DOA_REG, DOB_REG: Optional output register (0, 1)
   DOA_REG => 0,
   DOB_REG => 0,
   -- ENADDRENA/ENADDRENB: Address enable pin enable, "TRUE", "FALSE"
   ENADDRENA => "FALSE",
   ENADDRENB => "FALSE",
   -- EN_ECC_PIPE: ECC pipeline register, "TRUE"/"FALSE"
   EN_ECC_PIPE => "FALSE",
   -- EN_ECC_READ: Enable ECC decoder, "TRUE"/"FALSE"
   EN_ECC_READ => "FALSE",
   -- EN_ECC_WRITE: Enable ECC encoder, "TRUE"/"FALSE"
   EN_ECC_WRITE => "FALSE",
   -- INIT_A, INIT_B: Initial values on output ports
   INIT_A => X"000000000",
   INIT_B => X"000000000",
   -- Initialization File: RAM initialization file
   INIT_FILE => "NONE",
   -- Programmable Inversion Attributes: Specifies the use of the built-in programmable inversion
   IS_CLKARDCLK_INVERTED => '0',
   IS_CLKBWRCLK_INVERTED => '0',
   IS_ENARDEN_INVERTED => '0',
   IS_ENBWREN_INVERTED => '0',
   IS_RSTRAMARSTRAM_INVERTED => '0',
   IS_RSTRAMB_INVERTED => '0',
   IS_RSTREGARSTREG_INVERTED => '0',
   IS_RSTREGB_INVERTED => '0',
   -- RDADDRCHANGE: Disable memory access when output value does not change ("TRUE", "FALSE")
   RDADDRCHANGEA => "FALSE",
   RDADDRCHANGEB => "FALSE",
   -- READ_WIDTH_A/B, WRITE_WIDTH_A/B: Read/write width per port
   READ_WIDTH_A => 36,                                                       -- 0-9
   WRITE_WIDTH_A => 36,                                                      -- 0-9
   READ_WIDTH_B => 36,                                                        -- 0-9
   WRITE_WIDTH_B => 36,                                                       -- 0-9
   -- RSTREG_PRIORITY_A, RSTREG_PRIORITY_B: Reset or enable priority ("RSTREG", "REGCE")
   RSTREG_PRIORITY_A => "RSTREG",
   RSTREG_PRIORITY_B => "RSTREG",
   -- SRVAL_A, SRVAL_B: Set/reset value for output
   SRVAL_A => X"000000000",
   SRVAL_B => X"000000000",
   -- Sleep Async: Sleep function asynchronous or synchronous ("TRUE", "FALSE")
   SLEEP_ASYNC => "FALSE",
   -- WriteMode: "WRITE_FIRST", "NO_CHANGE", "READ_FIRST"
   WRITE_MODE_A => "NO_CHANGE",
   WRITE_MODE_B => "NO_CHANGE"
)
port map (
   -- no cascade, no parity, no error injection...
   CASDOUTA => open,              -- 32-bit output: Port A cascade output data
   CASDOUTB => open,              -- 32-bit output: Port B cascade output data
   CASDOUTPA => open,             -- 4-bit output: Port A cascade output parity data
   CASDOUTPB => open,             -- 4-bit output: Port B cascade output parity data
   CASOUTDBITERR => open,         -- 1-bit output: DBITERR cascade output
   CASOUTSBITERR => open,         -- 1-bit output: SBITERR cascade output
   DBITERR => open,               -- 1-bit output: Double bit error status
   ECCPARITY => open,             -- 8-bit output: Generated error correction parity
   RDADDRECC => open,             -- 9-bit output: ECC Read Address
   SBITERR => open,               -- 1-bit output: Single bit error status
   CASDIMUXA => '0',             -- 1-bit input: Port A input data (0=DINA, 1=CASDINA)
   CASDIMUXB => '0',             -- 1-bit input: Port B input data (0=DINB, 1=CASDINB)
   CASDINA => X"00000000",                 -- 32-bit input: Port A cascade input data
   CASDINB => X"00000000",                 -- 32-bit input: Port B cascade input data
   CASDINPA => "0000",               -- 4-bit input: Port A cascade input parity data
   CASDINPB => "0000",               -- 4-bit input: Port B cascade input parity data
   CASDOMUXA => '0',             -- 1-bit input: Port A unregistered data (0=BRAM data, 1=CASDINA)
   CASDOMUXB => '0',             -- 1-bit input: Port B unregistered data (0=BRAM data, 1=CASDINB)
   CASDOMUXEN_A => '0',       -- 1-bit input: Port A unregistered output data enable
   CASDOMUXEN_B => '0',       -- 1-bit input: Port B unregistered output data enable
   CASINDBITERR => '0',       -- 1-bit input: DBITERR cascade input
   CASINSBITERR => '0',       -- 1-bit input: SBITERR cascade input
   CASOREGIMUXA => '0',       -- 1-bit input: Port A registered data (0=BRAM data, 1=CASDINA)
   CASOREGIMUXB => '0',       -- 1-bit input: Port B registered data (0=BRAM data, 1=CASDINB)
   CASOREGIMUXEN_A => '0', -- 1-bit input: Port A registered output data enable
   CASOREGIMUXEN_B => '0', -- 1-bit input: Port B registered output data enable
   ECCPIPECE => '0',             -- 1-bit input: ECC Pipeline Register Enable
   INJECTDBITERR => '0',     -- 1-bit input: Inject a double-bit error
   INJECTSBITERR => '0',

   -- Port A is used for AXI R/W
   DOUTADOUT => ram0_douta,            -- 32-bit output: Port A Data/LSB data
   DOUTPADOUTP => open,                -- 4-bit output: Port A parity/LSB parity
   ADDRARDADDR => addra,               -- 15-bit input: A/Read port address
   ADDRENA => '0',                     -- 1-bit input: Active-High A/Read port address enable
   CLKARDCLK => S_AXI_ACLK,            -- 1-bit input: A/Read port clock
   ENARDEN => ram0_ena,                -- 1-bit input: Port A enable/Read enable
   REGCEAREGCE => '1',                 -- 1-bit input: Port A register enable/Register enable
   RSTRAMARSTRAM => '0',               -- 1-bit input: Port A set/reset
   RSTREGARSTREG => '0',               -- 1-bit input: Port A register set/reset
   SLEEP => '0',                       -- 1-bit input: Sleep Mode
   WEA => ram0_wea,                    -- 4-bit input: Port A write enable
   DINADIN => S_AXI_WDATA,             -- 32-bit input: Port A data/LSB data
   DINPADINP => "0000",                -- 4-bit input: Port A parity/LSB parity

   -- Port B is SPY BUFF WRITING ONLY
   DOUTBDOUT => open,              -- 32-bit output: Port B data/MSB data
   DOUTPBDOUTP => open,            -- 4-bit output: Port B parity/MSB parity
   ADDRBWRADDR => addrb,           -- 15-bit input: B/Write port address
   ADDRENB => '0',                 -- 1-bit input: Active-High B/Write port address enable
   CLKBWRCLK => clock,              -- 1-bit input: B/Write port clock
   ENBWREN => we_reg,                 -- 1-bit input: Port B enable/Write enable
   REGCEB => '0',                  -- 1-bit input: Port B register enable
   RSTRAMB => '0',                 -- 1-bit input: Port B set/reset
   RSTREGB => '0',                 -- 1-bit input: Port B register set/reset
   WEBWE => "11111111",            -- 8-bit input: Port B write enable/Write enable
   DINBDIN => data_delayed(31 downto 0),         -- 32-bit input: Port B data/MSB data
   DINPBDINP => "0000"             -- 4-bit input: Port B parity/MSB parity

);

RAMB36E2_1_inst : RAMB36E2  -- HIGH RAM block
generic map (
   -- CASCADE_ORDER_A, CASCADE_ORDER_B: "FIRST", "MIDDLE", "LAST", "NONE"
   CASCADE_ORDER_A => "NONE",
   CASCADE_ORDER_B => "NONE",
   -- CLOCK_DOMAINS: "COMMON", "INDEPENDENT"
   CLOCK_DOMAINS => "INDEPENDENT",
   -- Collision check: "ALL", "GENERATE_X_ONLY", "NONE", "WARNING_ONLY"
   SIM_COLLISION_CHECK => "ALL",
   -- DOA_REG, DOB_REG: Optional output register (0, 1)
   DOA_REG => 0,
   DOB_REG => 0,
   -- ENADDRENA/ENADDRENB: Address enable pin enable, "TRUE", "FALSE"
   ENADDRENA => "FALSE",
   ENADDRENB => "FALSE",
   -- EN_ECC_PIPE: ECC pipeline register, "TRUE"/"FALSE"
   EN_ECC_PIPE => "FALSE",
   -- EN_ECC_READ: Enable ECC decoder, "TRUE"/"FALSE"
   EN_ECC_READ => "FALSE",
   -- EN_ECC_WRITE: Enable ECC encoder, "TRUE"/"FALSE"
   EN_ECC_WRITE => "FALSE",
   -- INIT_A, INIT_B: Initial values on output ports
   INIT_A => X"000000000",
   INIT_B => X"000000000",
   -- Initialization File: RAM initialization file
   INIT_FILE => "NONE",
   -- Programmable Inversion Attributes: Specifies the use of the built-in programmable inversion
   IS_CLKARDCLK_INVERTED => '0',
   IS_CLKBWRCLK_INVERTED => '0',
   IS_ENARDEN_INVERTED => '0',
   IS_ENBWREN_INVERTED => '0',
   IS_RSTRAMARSTRAM_INVERTED => '0',
   IS_RSTRAMB_INVERTED => '0',
   IS_RSTREGARSTREG_INVERTED => '0',
   IS_RSTREGB_INVERTED => '0',
   -- RDADDRCHANGE: Disable memory access when output value does not change ("TRUE", "FALSE")
   RDADDRCHANGEA => "FALSE",
   RDADDRCHANGEB => "FALSE",
   -- READ_WIDTH_A/B, WRITE_WIDTH_A/B: Read/write width per port
   READ_WIDTH_A => 36,                                                              -- 0-9
   WRITE_WIDTH_A => 36,                                                             -- 0-9
   READ_WIDTH_B => 36,                                                               -- 0-9
   WRITE_WIDTH_B => 36,                                                              -- 0-9
   -- RSTREG_PRIORITY_A, RSTREG_PRIORITY_B: Reset or enable priority ("RSTREG", "REGCE")
   RSTREG_PRIORITY_A => "RSTREG",
   RSTREG_PRIORITY_B => "RSTREG",
   -- SRVAL_A, SRVAL_B: Set/reset value for output
   SRVAL_A => X"000000000",
   SRVAL_B => X"000000000",
   -- Sleep Async: Sleep function asynchronous or synchronous ("TRUE", "FALSE")
   SLEEP_ASYNC => "FALSE",
   -- WriteMode: "WRITE_FIRST", "NO_CHANGE", "READ_FIRST"
   WRITE_MODE_A => "NO_CHANGE",
   WRITE_MODE_B => "NO_CHANGE"
)
port map (
   -- no cascade, no parity, no error injection...
   CASDOUTA => open,          -- 32-bit output: Port A cascade output data
   CASDOUTB => open,          -- 32-bit output: Port B cascade output data
   CASDOUTPA => open,         -- 4-bit output: Port A cascade output parity data
   CASDOUTPB => open,         -- 4-bit output: Port B cascade output parity data
   CASOUTDBITERR => open,     -- 1-bit output: DBITERR cascade output
  CASOUTSBITERR => open,     -- 1-bit output: SBITERR cascade output
   DBITERR => open,           -- 1-bit output: Double bit error status
   ECCPARITY => open,         -- 8-bit output: Generated error correction parity
   RDADDRECC => open,         -- 9-bit output: ECC Read Address
   SBITERR => open,           -- 1-bit output: Single bit error status
  CASDIMUXA => '0',          -- 1-bit input: Port A input data (0=DINA, 1=CASDINA)
   CASDIMUXB => '0',          -- 1-bit input: Port B input data (0=DINB, 1=CASDINB)
   CASDINA => X"00000000",    -- 32-bit input: Port A cascade input data
   CASDINB => X"00000000",    -- 32-bit input: Port B cascade input data
   CASDINPA => "0000",        -- 4-bit input: Port A cascade input parity data
   CASDINPB => "0000",        -- 4-bit input: Port B cascade input parity data
   CASDOMUXA => '0',          -- 1-bit input: Port A unregistered data (0=BRAM data, 1=CASDINA)
   CASDOMUXB => '0',          -- 1-bit input: Port B unregistered data (0=BRAM data, 1=CASDINB)
   CASDOMUXEN_A => '0',       -- 1-bit input: Port A unregistered output data enable
   CASDOMUXEN_B => '0',       -- 1-bit input: Port B unregistered output data enable
   CASINDBITERR => '0',       -- 1-bit input: DBITERR cascade input
   CASINSBITERR => '0',       -- 1-bit input: SBITERR cascade input
   CASOREGIMUXA => '0',       -- 1-bit input: Port A registered data (0=BRAM data, 1=CASDINA)
   CASOREGIMUXB => '0',       -- 1-bit input: Port B registered data (0=BRAM data, 1=CASDINB)
   CASOREGIMUXEN_A => '0',    -- 1-bit input: Port A registered output data enable
  CASOREGIMUXEN_B => '0',    -- 1-bit input: Port B registered output data enable
   ECCPIPECE => '0',          -- 1-bit input: ECC Pipeline Register Enable
   INJECTDBITERR => '0',      -- 1-bit input: Inject a double-bit error
   INJECTSBITERR => '0',

   -- Port A is for AXI R/W
   DOUTADOUT => ram1_douta,   -- 32-bit output: Port A Data/LSB data
   DOUTPADOUTP => open,       -- 4-bit output: Port A parity/LSB parity
   ADDRARDADDR => addra,               -- 15-bit input: A/Read port address
   ADDRENA => '0',                     -- 1-bit input: Active-High A/Read port address enable
   CLKARDCLK => S_AXI_ACLK,            -- 1-bit input: A/Read port clock
   ENARDEN => ram1_ena,                -- 1-bit input: Port A enable/Read enable
   REGCEAREGCE => '1',                 -- 1-bit input: Port A register enable/Register enable
   RSTRAMARSTRAM => '0',               -- 1-bit input: Port A set/reset
   RSTREGARSTREG => '0',               -- 1-bit input: Port A register set/reset
   SLEEP => '0',                       -- 1-bit input: Sleep Mode
   WEA => ram1_wea ,                    -- 4-bit input: Port A write enable
   DINADIN => S_AXI_WDATA,             -- 32-bit input: Port A data/LSB data
   DINPADINP => "0000",                -- 4-bit input: Port A parity/LSB parity

   -- Port B is SPY BUFF WRITING
   DOUTBDOUT => open,             -- 32-bit output: Port B data/MSB data
   DOUTPBDOUTP => open,              -- 4-bit output: Port B parity/MSB parity
   ADDRBWRADDR => addrb,           -- 15-bit input: B/Write port address
   ADDRENB => '0',                 -- 1-bit input: Active-High B/Write port address enable
   CLKBWRCLK => clock,              -- 1-bit input: B/Write port clock
   ENBWREN => we_reg,                 -- 1-bit input: Port B enable/Write enable
   REGCEB => '0',                  -- 1-bit input: Port B register enable
   RSTRAMB => '0',                 -- 1-bit input: Port B set/reset
   RSTREGB => '0',                 -- 1-bit input: Port B register set/reset
   WEBWE => "11111111",            -- 8-bit input: Port B write enable/Write enable
   DINBDIN => data_delayed(63 downto 32), -- 32-bit input: Port B data/MSB data
   DINPBDINP => "0000"              -- 4-bit input: Port B parity/MSB parity

);

-- addr_debu <= addrb;
FORCE_TRIG <= trig_reg;
end outspy64_axilite_arch;