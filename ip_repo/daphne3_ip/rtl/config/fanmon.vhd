-- fanmon.vhd
-- monitor the fan tach signal and report the fan speed in RPM
-- assume the tach signal makes two low pulses per revolution

-- jamieson olsen <jamieson@fnal.gov>

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity fanmon is
port(
    clock: in std_logic; -- 100MHz 
    reset: in std_logic;
    tach: in std_logic; -- active low
    rpm: out std_logic_vector(11 downto 0) -- fan speed in RPM
  );
end fanmon;

architecture fanmon_arch of fanmon is

    signal count_reg: std_logic_vector(23 downto 0) := (others=>'0');
    signal tick_reg: std_logic;

    signal tach_reg: std_logic;
    signal debounce_reg: std_logic_vector(7 downto 0) := (others=>'0');

    signal pulsecount_reg: std_logic_vector(4 downto 0) := (others=>'0');
    signal rpm_reg: std_logic_vector(11 downto 0) := (others=>'0');

    type state_type is (rst, idle, pulse1, pulse0, done);
    signal state: state_type;

begin

-- make a pulse every 234.375ms
-- 234.375ms is 23437500 (0x65A0BC) clocks at 100MHz

slow_proc: process(clock)
begin
    if rising_edge(clock) then
        if (reset='1') then
            count_reg <= (others=>'0');
            tick_reg <= '0';
        else
            if (count_reg = X"65A0BC") then
                count_reg <= (others=>'0');
                tick_reg <= '1';
            else
                count_reg <= std_logic_vector( unsigned(count_reg) + 1 );
                tick_reg <= '0';
            end if;
        end if;
    end if;
end process slow_proc;

-- the fan tach signal could be really nasty so debounce it!
-- when tach signal is high debounce_reg will count up to 0xFF
-- when tach signal is low debounce_reg will count down to 0x00

debounce_proc: process(clock)
begin
    if rising_edge(clock) then
        if (reset='1') then
            --tach_reg <= '0';
            debounce_reg <= (others=>'0');
        else
            tach_reg <= tach;
            if (tach_reg='1') then
                if (debounce_reg /= X"FF") then
                    debounce_reg <= std_logic_vector( unsigned(debounce_reg) + 1 );
                end if;
            else
                if (debounce_reg /= X"00") then
                    debounce_reg <= std_logic_vector( unsigned(debounce_reg) - 1 );
                end if;
            end if;
        end if;
    end if;
end process debounce_proc;

-- count the number of low pulses in a 234ms window
-- then multiply by 256 to get RPM

-- for example: fan is 3000 RPM
-- in one second that is 50 revolutions
-- in 234ms we expect ~12 revolutions or ~24 low pulses

-- work backwards:
-- RPM = # of rotations in 234ms window * 256
-- RPM = # of low pulses in 234ms window * 128

-- use 5 bit pulse counter, if this overflows that means fan speed > 8000 RPM and we have bigger problems!

fsm_proc: process(clock)
begin
    if rising_edge(clock) then
        if (reset='1') then
            pulsecount_reg <= (others=>'0');
            rpm_reg <= (others=>'0');
        else
            tach_reg <= tach;

            case (state) is

                when rst =>
                    state <= idle;

                when idle =>
                    if (tick_reg='1') then -- window opens
                        state <= pulse1;
                        pulsecount_reg <= (others=>'0');
                    else
                        state <= idle;
                    end if;

                when pulse1 => -- wait here looking for falling edge
                    if (tick_reg='1') then
                        state <= done;
                    else
                        if (debounce_reg = X"00") then -- falling edge seen, increment pulse count
                            state <= pulse0;
                            pulsecount_reg <= std_logic_vector( unsigned(pulsecount_reg) + 1 ); -- 5 bit counter
                        else
                            state <= pulse1;
                        end if;                            
                    end if;                    

                when pulse0 => -- wait here looking for rising edge
                    if (tick_reg='1') then
                        state <= done;
                    else
                        if (debounce_reg = X"FF") then 
                            state <= pulse1;
                        else
                            state <= pulse0;
                        end if;                            
                    end if;                    

                when done => -- window closed, calc RPM, back to idle
                    rpm_reg <= pulsecount_reg & "0000000"; -- rpm = # of low pulses x 128
                    state <= idle;

                when others =>
                    state <= rst;

            end case;
        end if;
    end if;
end process fsm_proc;

rpm <= rpm_reg;

end fanmon_arch;
