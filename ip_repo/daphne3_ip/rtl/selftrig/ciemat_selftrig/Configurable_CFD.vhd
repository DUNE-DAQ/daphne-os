----------------------------------------------------------------------------------
-- Company:  CIEMAT
-- Engineer:  Ignacio L�pez de Rego
-- 
-- Create Date: 09.09.2024 12:21:49
-- Design Name: 
-- Module Name: Configurable_CFD - Behavioral
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
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

library unisim;
use unisim.vcomponents.all;

-- Uncomment the following library declaration if using
-- arithmetic functions with Signed or Unsigned values
--use IEEE.NUMERIC_STD.ALL;

-- Uncomment the following library declaration if instantiating
-- any Xilinx leaf cells in this code.
--library UNISIM;
--use UNISIM.VComponents.all;

------------------------- DESCRIPTION -----------------------------------
-- This Block uses Constant Fraction Discriminator Algorithm in order to reduce jitter (time walk) when working with trigger over threshold. 
--      + From "din" input singal --> Calculates the signal divided by a factor of two. 
--      + From "din" input singal --> Delays the signal X clk tics depending on "config_delay" input signal (from 1 to 32 clk tics).
--      + Calculates divided signal minus delayed signal.
--      + Looks for crossing values over 0:
--      +   *If "config_sign" input signal = '0' (POSITIVE "din" input signal)--> 0 crossing from positive to negative --> SET FLAG.
--      +   *If "config_sign" input signal = '1' (NEGATIVE "din" input signal)--> 0 crossing from negative to positive --> SET FLAG.
--      + If Crossing 0 flag = '1'  &  trigger_threshold = '1' --> trigger = '1' (With certain time constrains) 

entity Configurable_CFD is
port(
    clock:              in  std_logic;                       -- AFE clock
    reset:              in  std_logic;                       -- Reset signal. ACTIVE HIGH
    enable:             in  std_logic;                       -- Enable signal. ACTIVE HIGH
    trigger_threshold:  in  std_logic;                       -- ACTIVE HIGH when signal surpasses a threshold
    config_delay:       in  std_logic_vector(4 downto 0);    -- Delay config for the algorithm --> Delay over the original signal "din": 1 to 32 clk
                                                             -- "00000" = 0 clk
                                                             -- "11111" = 31 clk
    config_sign:        in  std_logic;                       -- Bit config describing the "din" signal --> Threshold over positive / negative signal
                                                             -- '0' --> Positive Signal
                                                             -- '1' --> Negative Signal
    din:                in  std_logic_vector(27 downto 0);   -- Input signal where the trigger over a threshold is performed
    trigger:            out std_logic                        -- Output trigger signal                                                       
    );
end Configurable_CFD;

architecture Behavioral of Configurable_CFD is

-- CONFIG registered signals 
signal config_delay_reg:                std_logic_vector(4 downto 0);
signal config_sign_reg:                 std_logic;

-- RESET & ENABLE registered signals 
signal reset_reg:                       std_logic;
signal enable_reg:                      std_logic;

-- "DIN" related signals: Delayed, Inverted 
signal din_reg, din_delay:              std_logic_vector(27 downto 0);
signal din_divided_reg, din_divided:    std_logic_vector(27 downto 0);

-- 0 CROSSING signal 
signal y_reg, y:                        std_logic_vector(27 downto 0);
signal y_sign, y_sign_delay:            std_logic;

-- THRESHOLD TRIGGER signals
signal trigger_threshold_reg:           std_logic;
signal trigger_threshold_counter:       std_logic_vector(6 downto 0);
signal trigger_threshold_counter_aux:   std_logic_vector(6 downto 0);

-- TRIGGER signals    
signal trigger_aux:                     std_logic;

begin

----------------------- GET (Synchronous) AND UPDATE CONFIGURATION PARAMETERS AND REGISTER RESET, ENABLE, DIN    -----------------------

Get_Config_Params: process(clock)
begin
    if (clock'event and clock='1') then
        config_delay_reg    <= config_delay;
        config_sign_reg     <= config_sign;
        reset_reg           <= reset;
        enable_reg          <= enable;
        din_reg             <= din;
    end if;
end process Get_Config_Params;

----------------------- GENERATE DELAY OF INPUT REGISTER SIGNAL DIN: Max delay of 32 clk tics    -----------------------

gendelay: for i in 27 downto 0 generate

        srlc32e_0_inst : srlc32e
        port map(
            clk             => clock,
            ce              => '1',
            a               => config_delay_reg, -- 
            d               => din_reg(i),       -- real time AFE data
            q               => din_delay(i),
            q31             => open 
        );

end generate gendelay;

----------------------- GENERATE ORIGINAL SIGNAL DIVIDED BY A FACTOR OF TWO     -----------------------

din_divided <=  din_reg(27) & din_reg(27 downto 1); 

Reg_Divided: process(clock)
begin
    if (clock'event and clock='1') then
        din_divided_reg     <= din_divided;
    end if;
end process Reg_Divided;

----------------------- GENERATE THE SIGNAL TO LOOK FOR THE 0 CROSSING     -----------------------
y           <=  std_logic_vector(signed(din_divided_reg) - signed(din_delay));

Zero_Crossing_Signal: process(clock)
begin
    if (clock'event and clock='1') then
        y_reg               <= y;
        y_sign_delay        <= y_sign;
        y_sign              <= y_reg(27);    
    end if;
end process Zero_Crossing_Signal;

----------------------- THRESHOLD TRIGGER REGISTER AND TIME COUNTER      -----------------------
-- Signal register is set to HIGH when threshold trigger is receivided. [Only allowed when NO reset (='0') and Enable (='1')]
-- This register remains HIGH until Zero crossing occurs, or Time Counter reaches a time limit. 

Threshold_Reg: process(clock, reset_reg, enable_reg, trigger_Threshold, trigger_aux, trigger_threshold_counter)
begin
    if (clock'event and clock='1') then
        if(reset_reg='1')then
            trigger_threshold_reg           <= '0';
        else 
            if(enable_reg='1')then
                if(trigger_Threshold='1')then
                    trigger_threshold_reg   <= '1';
                elsif ((trigger_aux='1') or (signed(trigger_threshold_counter)>100)) then 
                    trigger_threshold_reg   <= '0';
                end if;
            else 
                trigger_threshold_reg       <= '0';
            end if;
        end if;    
    end if;
end process Threshold_Reg;


trigger_threshold_counter_aux <= std_logic_vector(unsigned(trigger_threshold_counter) + to_unsigned(1,7)); 
Counter_Threshold_Reg: process(clock, trigger_threshold_reg)
begin
    if (clock'event and clock='1') then
        if(trigger_threshold_reg='1')then
            trigger_threshold_counter       <= trigger_threshold_counter_aux;
        else 
            trigger_threshold_counter       <= (others=>'0');
        end if;    
    end if;
end process Counter_Threshold_Reg;

----------------------- TRIGGER LOGIC     -----------------------
-- When threshold trigger has happenned a zero crossing is expected. If this zero crossing occurs, then trigger is set. 
-- Trigger is not allowed within few counts from Threshold trigger event to avoid noise zero crossing.

trigger_aux <= trigger_threshold_reg and (trigger_threshold_counter(6)or trigger_threshold_counter(5)or trigger_threshold_counter(4)or trigger_threshold_counter(3)or trigger_threshold_counter(2)) and ((not(config_sign_reg)and not(y_sign_delay) and y_sign) or (config_sign_reg and y_sign_delay and not(y_sign) ));
-- 1- It is mandatory trigger threshold AND
-- 2- Trigger threshold counter > 4 (this is performed by OR of MSB)  AND
-- 3- Crossing over zero must occur (Depending on positive signal or negative signal) 
----------------------- OUTPUT     ----------------------- 

trigger <= trigger_aux;
    
end Behavioral;