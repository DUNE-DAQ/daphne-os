-- spybuff.vhd
--
-- DAPHNE spy buffer for one link AFE output, stores 4k 16-bit samples
-- reset only resets the trigger logic, it does not erase the buffer contents
-- triggered on low to to high pulse, then writes next 2048 words into buffer, stops and waits for next trigger
-- add delay elements to produce 64 deep delay for fixed pretrigger
--
-- The "A" port on this buffer is intended to connect to the AXI-Lite interface
--
-- Jamieson Olsen <jamieson@fnal.gov>

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

library unisim;
use unisim.vcomponents.all;

entity spybuff is
port(
    clock: in std_logic; -- master clock
    reset: in std_logic; -- active high reset async
    trig:  in std_logic; -- trigger pulse sync to clock
    data:  in std_logic_vector(15 downto 0); -- afe data sync to clock

    clka:  in  std_logic;
    addra: in  std_logic_vector(9 downto 0); -- 1k x 32 R/W
	ena:   in  std_logic;
	wea:   in  std_logic;
	dina:  in  std_logic_vector(31 downto 0);
    douta: out std_logic_vector(31 downto 0)  
  );
end spybuff;

architecture spybuff_arch of spybuff is

    signal reset_reg: std_logic;
    signal addr_reg: std_logic_vector(10 downto 0);
    signal data_reg, data_q, data_delayed: std_logic_vector(15 downto 0);
    signal we_reg:   std_logic;

    type state_type is (rst, wait4trig, store, wait4done);
    signal state: state_type;

	component spyram
	port (
			clka:  in  std_logic;
			addra: in  std_logic_vector( 9 downto 0); -- 1k x 32 R/W axi
	        dina:  in  std_logic_vector(31 downto 0);
	        ena:   in  std_logic;
	        wea:   in  std_logic;
	        douta: out std_logic_vector(31 downto 0);
	        clkb:  in  std_logic;
	        addrb: in  std_logic_vector(10 downto 0); -- 2k x 16 writeonly spybuff
	        dinb:  in  std_logic_vector(15 downto 0);
	        web:   in  std_logic
		);
	end component;

begin

    -- input delay elements for fixed pre-trigger cascade two 32 bit shift registers
	-- for a total pre-trigger delay of 64 clocks

    gendelay: for i in 15 downto 0 generate

        srlc32e_0_inst : srlc32e
        port map(
            clk => clock,
            ce => '1',
            a => "11111",
            d => data(i),
            q => open,
            q31 => data_q(i)  
        );
    
        srlc32e_1_inst : srlc32e
        port map(
            clk => clock,
            ce => '1',
            a => "11111",
            d => data_q(i),
            q => data_delayed(i),
            q31 => open  
        );

    end generate gendelay;

    -- FSM to wait for trigger pulse and drive addr_reg (write pointer) and we_reg

    fsm_proc: process(clock)
    begin
        if rising_edge(clock) then

            reset_reg <= reset; -- assume reset is async to square it up here

            if (reset_reg='1') then
                we_reg   <= '0';
                state    <= rst;
            else
                data_reg <= data_delayed;

                case state is
                    when rst =>
                        state <= wait4trig;
                    when wait4trig =>
                        if (trig='1') then
                            state <= store;
                            we_reg <= '1';
                        else
                            state <= wait4trig;
                            we_reg <= '0';
                            addr_reg <= (others=>'0');
                        end if;
                    when store =>
                        if (addr_reg="11111111111") then
                            state <= wait4done;
                            we_reg <= '0';
                        else
                            state <= store;
                            addr_reg <= std_logic_vector(unsigned(addr_reg) + 1);
                            we_reg <= '1';
                        end if;
                    when wait4done =>
                        if (trig='0') then
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

	spyram_inst: spyram
	port map(
		clka => clka, -- Port A R/W access from AXI master, 2k x 32
		addra => addra,
		dina => dina,
		ena => ena,
		wea => wea,
		douta => douta,

		clkb => clock, -- Port B written to by THIS logic
		addrb => addr_reg, -- 11 bit write address
		dinb => data_reg,
		web => we_reg
	);

end spybuff_arch;
