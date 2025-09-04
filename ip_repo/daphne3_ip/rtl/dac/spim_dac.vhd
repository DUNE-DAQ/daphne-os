-- spim_dac.vhd
--
-- spi master for 3 DACs: U50, U53, and U5
-- AD5327BRUZ-REEL7, daisy chained, total 48 bits are shifted in. there is no readback.
--
-- These three DAC chips are daisy chained on a single SPI interface and therefore all three
-- chips must be written at once. Each DAC chip takes 16 bits. The 3 data regsters are 
-- non destructive: reading these register will return the last thing that was written.
--
-- base+0: control/status register. write anything here to initiate serial transfer to DACs (GO!)
--         read this register, LSb is set when it is busy doing SPI transaction
-- base+4:  16 bit data for first DAC chip U50 (read/write) 
-- base+8:  16 bit data for middle DAC chip U53 (read/write)
-- base+12: 16 bit data for last DAC chip U5 (read/write)
--
-- with 100MHz AXI clock this module takes about 10us to shift the data into the DACs

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity spim_dac is
generic( CLKDIV: integer := 10 ); -- SPI sclk frequency = clock frequency / CLKDIV
port(
    dac_sclk: out std_logic;
    dac_din: out std_logic;
    dac_sync_n: out std_logic;
    dac_ldac_n: out std_logic;
  
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
end spim_dac;

architecture spim_dac_arch of spim_dac is

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

signal reg_rden, reg_wren: std_logic;
signal aw_en: std_logic;
signal reg_data_out: std_logic_vector(31 downto 0);
signal dac0_reg, dac1_reg, dac2_reg: std_logic_vector(15 downto 0) := (others=>'0');

constant CTRLSTAT_OFFSET: std_logic_vector(3 downto 0) := "0000";
constant DACDATA0_OFFSET: std_logic_vector(3 downto 0) := "0100";
constant DACDATA1_OFFSET: std_logic_vector(3 downto 0) := "1000";
constant DACDATA2_OFFSET: std_logic_vector(3 downto 0) := "1100";

type state_type is (rst, idle, dhi, dlo, sync, load0, load1);
signal state: state_type;
signal din_reg: std_logic_vector(47 downto 0) := (others=>'0');
signal bit_count: integer range 0 to 63;
signal clk_count: integer range 0 to CLKDIV;
signal go_reg, busy: std_logic;

begin

-- FSM to shift serial data into the DACs

fsm_proc: process(S_AXI_ACLK) 
begin
    if rising_edge(S_AXI_ACLK) then
        if (S_AXI_ARESETN='0') then
            state <= rst;
        else
            case state is 
            
            when rst =>
                state <= idle;
            
            when idle => 
                if (go_reg='1') then
                    din_reg <= dac2_reg & dac1_reg & dac0_reg;
                    clk_count <= 0;
                    bit_count <= 47;
                    state <= dhi;
                else
                    state <= idle;  
                end if;
            
            when dhi => -- sclk high cycle
                if (clk_count=CLKDIV/2) then
                    state <= dlo;
                    clk_count <= 0;
                else
                    state <= dhi;
                    clk_count <= clk_count + 1;
                end if;
            
            when dlo => -- sclk low cycle
                if (clk_count=CLKDIV/2) then
                    din_reg <= din_reg(46 downto 0) & '0'; -- shift data register left one bit
                    if (bit_count=0) then -- we have just finished shifting out the last bit, get ready to load
                        state <= sync;
                        clk_count <= 0; 
                    else -- done with this bit, but there are more bits to send, shift data and make another sclk high pulse
                        clk_count <= 0;
                        bit_count <= bit_count - 1;
                        state <= dhi;
                    end if;
                else
                    clk_count <= clk_count + 1;
                    state <= dlo;
                end if;
            
            when sync => -- sclk is still low, let sync_n go high, then release sclk and let it go high
                if (clk_count=CLKDIV) then
                    clk_count <= 0; 
                    state <= load0;
                else
                    clk_count <= clk_count + 1;
                    state <= sync;
                end if;
            
            when load0 => -- wait here for a little while... 
                if (clk_count=CLKDIV) then
                    state <= load1;
                    clk_count <= 0;
                else
                    state <= load0;
                    clk_count <= clk_count + 1;
                end if;
            
            when load1 => -- pulse ldac_n low to load the DACs 
                if (clk_count=CLKDIV) then
                    state <= idle;
                else
                    state <= load1;
                    clk_count <= clk_count + 1;
                end if;
            
            when others =>
                state <= rst;
            
            end case;
    
        end if;
    end if;
end process fsm_proc;

-- Assign outputs

dac_ldac_n <= '0' when (state=load1) else '1';

dac_sync_n <= '0' when (state=dhi) else
              '0' when (state=dlo) else
              '1';

dac_sclk <= '0' when (state=dlo) else
            '0' when (state=sync) else 
            '1';

dac_din <= din_reg(47); -- serial data is shifted out MSb first

busy <= '0' when (state=idle) else
        '0' when (state=rst) else 
        '1';

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

process (S_AXI_ACLK)
begin
  if rising_edge(S_AXI_ACLK) then 

    if (S_AXI_ARESETN = '0') then

      dac0_reg <= (others=>'0');
      dac1_reg <= (others=>'0');
      dac2_reg <= (others=>'0');
      go_reg <= '0';

    else

      if (reg_wren = '1' and S_AXI_WSTRB = "1111") then

        -- treat all of these register writes as if they are full 32 bits
        -- e.g. the four write strobe bits should be high

        case ( axi_awaddr(3 downto 0) ) is

          when CTRLSTAT_OFFSET => 
            go_reg <= '1'; -- momentary to trigger FSM

          when DACDATA0_OFFSET => 
            dac0_reg <= S_AXI_WDATA(15 downto 0);

          when DACDATA1_OFFSET => 
            dac1_reg <= S_AXI_WDATA(15 downto 0);

          when DACDATA2_OFFSET => 
            dac2_reg <= S_AXI_WDATA(15 downto 0);

          when others =>
            null;

        end case;

      else

        go_reg <= '0';

      end if;
    end if;
  end if;                   
end process; 

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

reg_data_out <= (X"0000000" & "000" & busy) when (axi_araddr(3 downto 0)=CTRLSTAT_OFFSET) else -- status register is just busy flag in LSb
                (X"0000" & dac0_reg)        when (axi_araddr(3 downto 0)=DACDATA0_OFFSET) else
                (X"0000" & dac1_reg)        when (axi_araddr(3 downto 0)=DACDATA1_OFFSET) else
                (X"0000" & dac2_reg)        when (axi_araddr(3 downto 0)=DACDATA2_OFFSET) else
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

end spim_dac_arch;