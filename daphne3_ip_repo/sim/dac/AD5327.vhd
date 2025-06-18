-- AD5327.vhd
-- a very basic BFM (bus functional model) for SPI DAC AD5327BRUZ-REEL7
-- Jamieson Olsen <jamieson@fnal.gov>

library ieee,std;
use ieee.std_logic_1164.all;
use std.textio;

entity AD5327 is
generic(refdes: STRING := "U?");
port(
    sclk: in std_logic;
    din: in std_logic;
    sync_n: in std_logic;
    ldac_n: in std_logic;
    sdo: out std_logic
);
end AD5327;

architecture AD5327_arch of AD5327 is

signal data_reg: std_logic_vector(15 downto 0) := (others=>'0');

begin

shift_proc: process(sclk)
begin
    if falling_edge(sclk) then
        if (sync_n='0') then
            data_reg <= data_reg(14 downto 0) & din; -- 16 bit data arrives MSb first!
        end if;
    end if;
end process shift_proc;

sdo <= data_reg(15); -- pass thru for daisy chaining multiple devices

load_proc: process(ldac_n)
begin
    if rising_edge(ldac_n) then -- the data register was just loaded

        report "DAC " & refdes & " load 0x" & to_hstring(data_reg(15 downto 0));

    end if;
end process load_proc;

end AD5327_arch;