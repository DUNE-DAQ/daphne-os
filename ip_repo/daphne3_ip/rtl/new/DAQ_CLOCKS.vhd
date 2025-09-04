----------------------------------------------------------------------------------
-- Company: 
-- Engineer: 
-- 
-- Create Date: 09/26/2024 03:09:31 PM
-- Design Name: 
-- Module Name: DAQ_CLOCKS - Behavioral
-- Project Name: 
-- Target Devices: 
-- Tool Versions: 
-- Description: 
-- 
-- Dependencies: 
-- 
-- Revision:
-- Revision 0.01 - File Created
-- Additional Comments:
-- 
----------------------------------------------------------------------------------


library IEEE;
use IEEE.STD_LOGIC_1164.ALL;

-- Uncomment the following library declaration if using
-- arithmetic functions with Signed or Unsigned values
--use IEEE.NUMERIC_STD.ALL;

-- Uncomment the following library declaration if instantiating
-- any Xilinx leaf cells in this code.
library UNISIM;
use UNISIM.VComponents.all;

entity DAQ_CLOCKS is
    Port ( CLK_IN : in STD_LOGIC;
           CLK_P : out STD_LOGIC;
           CLK_N : out STD_LOGIC);
end DAQ_CLOCKS;

architecture Behavioral of DAQ_CLOCKS is

begin
   OBUFDS_GTE4_inst : OBUFDS_GTE4
 --  generic map (
     -- REFCLK_EN_TX_PATH => '1',   -- Refer to Transceiver User Guide.
     -- REFCLK_ICNTL_TX => "00000"  -- Refer to Transceiver User Guide.
   --)
   port map (
      O => CLK_P,     -- 1-bit output: Refer to Transceiver User Guide.
      OB => CLK_N,   -- 1-bit output: Refer to Transceiver User Guide.
      CEB => '0', -- 1-bit input: Refer to Transceiver User Guide.
      I => CLK_IN      -- 1-bit input: Refer to Transceiver User Guide.
   );


end Behavioral;
