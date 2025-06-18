-- baseline.vhd
--
-- compute average baseline level over N consecutive samples
-- note that after reset baseline will default to maximum (0x3FFF) until
-- N samples have been analyzed, then it will take on a 
-- regular real average value.
--

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity baseline is
generic( runlength: integer := 256 ); -- must be power of 2: 32, 64, 128, or 256
port(
    clock: in  std_logic;
    reset: in  std_logic;
    din:   in  std_logic_vector(13 downto 0);
    bline: out std_logic_vector(13 downto 0)
);
end baseline;

architecture baseline_arch of baseline is

    signal baseline_reg: std_logic_vector(13 downto 0) := (others=>'1');
    signal sum_reg: std_logic_vector(21 downto 0) := (others=>'0');
    signal count_reg: std_logic_vector(7 downto 0) := X"00";

begin

    -- On each clock cycle add din to sum_reg. after N cycles, 
    -- copy sum_reg/N into baseline_reg and clear sum_reg. repeat forever.

    process(clock)
    begin
        if rising_edge(clock) then
            if (reset='1') then
                count_reg <= X"00";
                sum_reg <= (others=>'0');
                baseline_reg <= (others=>'1');
            else
                case (runlength) is
                    when 32 =>
                        if (count_reg=X"1F") then
                            sum_reg <= "00000000" & din;
                            count_reg <= (others=>'0');
                            baseline_reg <= sum_reg(18 downto 5); -- sum/32
                        else
                            sum_reg <= std_logic_vector( unsigned(sum_reg) + unsigned(din) );
                            count_reg <= std_logic_vector( unsigned(count_reg) + 1 );
                        end if; 
                    when 64 => 
                        if (count_reg=X"3F") then
                            sum_reg <= "00000000" & din;
                            count_reg <= (others=>'0');
                            baseline_reg <= sum_reg(19 downto 6); -- sum/64
                        else
                            sum_reg <= std_logic_vector( unsigned(sum_reg) + unsigned(din) );
                            count_reg <= std_logic_vector( unsigned(count_reg) + 1 );
                        end if; 
                    when 128 => 
                        if (count_reg=X"7F") then
                            sum_reg <= "00000000" & din;
                            count_reg <= (others=>'0');
                            baseline_reg <= sum_reg(20 downto 7); -- sum/128
                        else
                            sum_reg <= std_logic_vector( unsigned(sum_reg) + unsigned(din) );
                            count_reg <= std_logic_vector( unsigned(count_reg) + 1 );
                        end if; 
                    when others => -- default is 256
                        if (count_reg=X"FF") then
                            sum_reg <= "00000000" & din;
                            count_reg <= (others=>'0');
                            baseline_reg <= sum_reg(21 downto 8); -- sum/256
                        else
                            sum_reg <= std_logic_vector( unsigned(sum_reg) + unsigned(din) );
                            count_reg <= std_logic_vector( unsigned(count_reg) + 1 );
                        end if;
                    end case;
            end if;
        end if;
    end process;

    bline <= baseline_reg;

end baseline_arch;
