----------------------------------------------------------------------------------
-- Company: CIEMAT
-- Engineer: Ignacio L�pez de Rego
-- 
-- Create Date: 25.04.2024 14:10:45
-- Design Name: 
-- Module Name: Self_Trigger_Primitive_Calculation - Behavioral
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

entity Self_Trigger_Primitive_Calculation is
port(
    clock:                          in  std_logic;                                              -- AFE clock
    reset:                          in  std_logic;                                              -- Reset signal. ACTIVE HIGH
    din:                            in  std_logic_vector(13 downto 0);                          -- Data coming from the Filter Block / Raw data from AFEs
    Config_Param:                   in  std_logic_vector(13 downto 0);                          -- Configure parameters for filtering & self-trigger bloks
    Ext_Self_Trigger:               in  std_logic;                                              -- External Self-Trigger coming from another block
    Match_with_Frame:               in  std_logic;                                              -- External signal that allows being matched with the frame construction.
    Self_trigger:                   out std_logic;                                              -- Self-Trigger signal comming from the Self-Trigger block
    Data_Available:                 out std_logic;                                              -- ACTIVE HIGH when LOCAL primitives are calculated
    Time_Peak:                      out std_logic_vector(8 downto 0);                           -- Time in Samples to achieve de Max peak
    Time_Over_Baseline:             out std_logic_vector(8 downto 0);                           -- Time in Samples of the light pulse signal is UNDER BASELINE (without undershoot)
    Time_Start:                     out std_logic_vector(9 downto 0);                           -- Time in Samples of the light pulse signal is OVER BASELINE (undershoot)
    ADC_Peak:                       out std_logic_vector(13 downto 0);                          -- Amplitude in ADC counts od the peak
    ADC_Integral:                   out std_logic_vector(22 downto 0);                          -- Charge of the light pulse (without undershoot) in ADC*samples
    Number_Peaks:                   out std_logic_vector(3 downto 0);                           -- Number of peaks detected when signal is UNDER BASELINE (without undershoot).  
    --filtered_dout:                  out std_logic_vector (13 downto 0);                         -- HIGH PASS Filtered signal
    Baseline:                       in std_logic_vector(13 downto 0);                          -- Real Time calculated BASELINE
    Amplitude:                      out std_logic_vector(14 downto 0);                          -- Real Time calculated AMPLITUDE
    Peak_Current:                   out std_logic;                                              -- ACTIVE HIGH when a peak is detected
    Slope_Current:                  out std_logic_vector(13 downto 0);                          -- Real Time calculated SLOPE
    Slope_Threshold:                out std_logic_vector(6 downto 0);                           -- Threshold over the slope to detect Peaks
    Detection:                      out std_logic;                                              -- ACTIVE HIGH when primitives are being calculated (during light pulse)
    Sending:                        out std_logic;                                              -- ACTIVE HIGH when colecting data for self-trigger frame
    Info_Previous:                  out std_logic;                                              -- ACTIVE HIGH when self-trigger is produced by a waveform between two frames 
    Data_Available_Trailer:         out std_logic;                                              -- ACTIVE HIGH when metadata is ready
    Trailer_Word_0:                 out std_logic_vector(31 downto 0);                          -- TRAILER WORD with metada (Local Trigger Primitives)
    Trailer_Word_1:                 out std_logic_vector(31 downto 0);                          -- TRAILER WORD with metada (Local Trigger Primitives)
    Trailer_Word_2:                 out std_logic_vector(31 downto 0);                          -- TRAILER WORD with metada (Local Trigger Primitives)
    Trailer_Word_3:                 out std_logic_vector(31 downto 0);                          -- TRAILER WORD with metada (Local Trigger Primitives)
    Trailer_Word_4:                 out std_logic_vector(31 downto 0);                          -- TRAILER WORD with metada (Local Trigger Primitives)
    Trailer_Word_5:                 out std_logic_vector(31 downto 0);                          -- TRAILER WORD with metada (Local Trigger Primitives)
    Trailer_Word_6:                 out std_logic_vector(31 downto 0);                          -- TRAILER WORD with metada (Local Trigger Primitives)
    Trailer_Word_7:                 out std_logic_vector(31 downto 0);                          -- TRAILER WORD with metada (Local Trigger Primitives)
    Trailer_Word_8:                 out std_logic_vector(31 downto 0);                          -- TRAILER WORD with metada (Local Trigger Primitives)
    Trailer_Word_9:                 out std_logic_vector(31 downto 0);                          -- TRAILER WORD with metada (Local Trigger Primitives)
    Trailer_Word_10:                out std_logic_vector(31 downto 0);                          -- TRAILER WORD with metada (Local Trigger Primitives)
    Trailer_Word_11:                out std_logic_vector(31 downto 0)                           -- TRAILER WORD with metada (Local Trigger Primitives)
);
end Self_Trigger_Primitive_Calculation;

architecture Behavioral of Self_Trigger_Primitive_Calculation is

--COMPONENT Filter_CIEMAT IS 
--  PORT (  
--    clock:          in  std_logic;                          -- AFE clock
--    reset:          in  std_logic;                          -- Reset signal. ACTIVE HIGH 
--    din:            in  std_logic_vector(13 downto 0);      -- Raw AFE data
--    Config_Param:   in std_logic_vector(3 downto 0);        -- Config_Param[0] --> 1 = ENABLE filtering / 0 = DISABLE filtering 
--                                                           -- Config_Param[1] --> '0' = 1 LSB truncated / '1' = 2 LSBs truncated 
--                                                            -- Config_Param[3 downto 2] --> '00' = 4 Samples Window / '01' = 8 Samples Window / '10' = 16 Samples Window / '11' = 32 Samples Window
--    filtered_dout:  out  std_logic_vector(13 downto 0));    -- Raw AFE data
--  END component;
    
 COMPONENT PeakDetector_SelfTrigger_CIEMAT IS 
  PORT (  
    clock:                          in  std_logic;                      -- AFE clock
    reset:                          in  std_logic;                      -- Reset signal. ACTIVE HIGH 
    din:                            in  std_logic_vector(13 downto 0);  -- Data coming from the Filter Block / Raw data from AFEs
    Sending_Data:                   in  std_logic;                      -- DATA is being sent. ACTIVE HIGH
    Config_Param:                   in  std_logic_vector(9 downto 0);   -- Config_Param[0] --> '0' = Peak detector as self-trigger  / '1' = Main detection as Self-Trigger (Undershoot peaks will not trigger)
                                                                        -- Config_Param[1] --> '0' = NOT ALLOWED  Self-Trigger with light pulse between 2 data adquisition frames   
                                                                        --                 --> '1' = ALLOWED Self-Trigger with light pulse between 2 data adquisition frames
                                                                        -- Config_Param[2] --> '0' = Slope calculation with 2 consecutive samples --> x(n) - x(n-1)  / '1' = Slope calculation with 3 consecutive samples --> [x(n) - x(n-2)] / 2 
                                                                        -- Config_Param[9 downto 3] --> Slope_Threshold (signed) 1(sign) + 6 bits, must be negative.
    Interface_LOCAL_Primitves_IN:   in  std_logic_vector(23 downto 0);   -- Interface with Local Primitives calculation BLOCK --> DEPENDS ON SELF-TRIGGER ALGORITHM 
    Interface_LOCAL_Primitves_OUT:  out std_logic_vector(23 downto 0);   -- Interface with Local Primitives calculation BLOCK --> DEPENDS ON SELF-TRIGGER ALGORITHM 
    Self_trigger:                   out std_logic);                       -- ACTIVE HIGH when a Self-trigger events occurs
END component;

COMPONENT LocalPrimitives_CIEMAT IS 
  PORT (  
    clock:                          in  std_logic;                                              -- AFE clock
    reset:                          in  std_logic;                                              -- Reset signal. ACTIVE HIGH
    Self_trigger:                   in  std_logic;                                              -- Self-Trigger signal comming from the Self-Trigger block
    din:                            in  std_logic_vector(13 downto 0);                          -- Data coming from the Filter Block / Raw data from AFEs
    Interface_LOCAL_Primitves_IN:   in  std_logic_vector(23 downto 0);                          -- Interface with Local Primitives calculation BLOCK --> DEPENDS ON SELF-TRIGGER ALGORITHM 
    Interface_LOCAL_Primitves_OUT:  out std_logic_vector(23 downto 0);                          -- Interface with Local Primitives calculation BLOCK --> DEPENDS ON SELF-TRIGGER ALGORITHM 
    Data_Available:                 out std_logic;                                              -- ACTIVE HIGH when LOCAL primitives are calculated
    Time_Peak:                      out std_logic_vector(8 downto 0);                           -- Time in Samples to achieve de Max peak
    Time_Over_Baseline:             out std_logic_vector(8 downto 0);                           -- Time in Samples of the light pulse signal is UNDER BASELINE (without undershoot)
    ADC_Peak:                       out std_logic_vector(13 downto 0);                          -- Amplitude in ADC counts od the peak
    ADC_Integral:                   out std_logic_vector(22 downto 0);                          -- Charge of the light pulse (without undershoot) in ADC*samples
    Number_Peaks:                   out std_logic_vector(3 downto 0);                           -- Number of peaks detected when signal is UNDER BASELINE (without undershoot).  
    Baseline:                       in std_logic_vector(13 downto 0);                            -- TO BE REMOVED AFTER DEBUGGING
    Amplitude:                      out std_logic_vector(14 downto 0);                            -- TO BE REMOVED AFTER DEBUGGING
    High_Freq_Noise:                out std_logic);                                                 -- ACTIVE HIGH when high freq noise is detected 
END component;

-- Common signals for three blocks
SIGNAL clock_aux : std_logic;
SIGNAL reset_aux : std_logic;
SIGNAL Config_Param_Reg: std_logic_vector (13 downto 0);

-- FILTER SIGNALS
SIGNAL din_aux : std_logic_vector(13 downto 0):= "00000000000000";
SIGNAL Config_Param_FILTER_aux: std_logic_vector(3 downto 0);
SIGNAL filtered_dout_aux: std_logic_vector(13 downto 0);
SIGNAL filtered_dout_aux_delay_32, filtered_dout_aux_delay_64, filtered_dout_aux_delay_96, filtered_dout_aux_delay_128, filtered_dout_aux_delay_160, filtered_dout_aux_delay_Extra : std_logic_vector(13 downto 0);

-- SELF TRIGGER SIGNALS
SIGNAL Config_Param_SELF_aux: std_logic_vector(9 downto 0);
--SIGNAL Sending_Data_aux : std_logic;
SIGNAL Interface_LOCAL_Primitves_IN_aux: std_logic_vector(23 downto 0);
SIGNAL Interface_LOCAL_Primitves_OUT_aux: std_logic_vector(23 downto 0);
SIGNAL Self_trigger_aux: std_logic;
SIGNAL Self_trigger_out_aux: std_logic;
SIGNAL triggered_dly32_i: std_logic;
SIGNAL Noise_aux: std_logic; 
SIGNAL Trigger_dly53: bit_vector(53 downto 0):=(others=>'0');
signal Noise_OR: bit:='0';

-- LOCAL TRIGGER SIGNALS
SIGNAL Ext_Self_Trigger_Match:             std_logic;                                              -- ACTIVE HIGH when ext_self_trigger and allowed to calculate TPs 
SIGNAL Data_Available_aux:                 std_logic;                                              -- ACTIVE HIGH when LOCAL primitives are calculated
SIGNAL Time_Peak_aux:                      std_logic_vector(8 downto 0);                           -- Time in Samples to achieve de Max peak
SIGNAL Time_Over_Baseline_aux:             std_logic_vector(8 downto 0);                           -- Time in Samples of the light pulse signal is UNDER BASELINE (without undershoot)
SIGNAL ADC_Peak_aux:                       std_logic_vector(13 downto 0);                          -- Amplitude in ADC counts od the peak
SIGNAL ADC_Integral_aux:                   std_logic_vector(22 downto 0);                          -- Charge of the light pulse (without undershoot) in ADC*samples
SIGNAL Number_Peaks_aux:                   std_logic_vector(3 downto 0);                           -- Number of peaks detected when signal is UNDER BASELINE (without undershoot).  
SIGNAL Baseline_aux:                       std_logic_vector(14 downto 0);                            -- TO BE REMOVED AFTER DEBUGGING
SIGNAL Amplitude_aux:                      std_logic_vector(14 downto 0);                            -- TO BE REMOVED AFTER DEBUGGING
SIGNAL Time_Start_aux:                     std_logic_vector(9 downto 0);                           -- Time from TIME STAMP where the hit starts

-- LOCAL TRIGGER SIGNALS registers
SIGNAL Data_Available_reg:                 std_logic;                                              -- ACTIVE HIGH when LOCAL primitives are calculated
SIGNAL Time_Peak_reg:                      std_logic_vector(8 downto 0);                           -- Time in Samples to achieve de Max peak
SIGNAL Time_Over_Baseline_reg:             std_logic_vector(8 downto 0);                           -- Time in Samples of the light pulse signal is UNDER BASELINE (without undershoot)
SIGNAL ADC_Peak_reg:                       std_logic_vector(13 downto 0);                          -- Amplitude in ADC counts od the peak
SIGNAL ADC_Integral_reg:                   std_logic_vector(22 downto 0);                          -- Charge of the light pulse (without undershoot) in ADC*samples
SIGNAL Number_Peaks_reg:                   std_logic_vector(3 downto 0);                           -- Number of peaks detected when signal is UNDER BASELINE (without undershoot).  
SIGNAL Time_Start_reg,Time_Start_reg2:     std_logic_vector(9 downto 0);                           -- Time from TIME STAMP where the hit starts

-- TRAILER WORDS registers
SIGNAL Trailer_Word_0_reg:                 std_logic_vector(31 downto 0);
SIGNAL Trailer_Word_1_reg:                 std_logic_vector(31 downto 0);
SIGNAL Trailer_Word_2_reg:                 std_logic_vector(31 downto 0);
SIGNAL Trailer_Word_3_reg:                 std_logic_vector(31 downto 0);
SIGNAL Trailer_Word_4_reg:                 std_logic_vector(31 downto 0);
SIGNAL Trailer_Word_5_reg:                 std_logic_vector(31 downto 0);
SIGNAL Trailer_Word_6_reg:                 std_logic_vector(31 downto 0);
SIGNAL Trailer_Word_7_reg:                 std_logic_vector(31 downto 0);
SIGNAL Trailer_Word_8_reg:                 std_logic_vector(31 downto 0);
SIGNAL Trailer_Word_9_reg:                 std_logic_vector(31 downto 0);
SIGNAL Trailer_Word_10_reg:                 std_logic_vector(31 downto 0);
SIGNAL Trailer_Word_11_reg:                 std_logic_vector(31 downto 0);
                            
-- Sending Data control Signal 
signal Data_Sent_Count: integer:=0; -- 1024 total samples - 64 pretrigger samples
CONSTANT Frame_Size : integer := 960; -- 1024 total samples - 64 pretrigger samples
type Data_State is   (Not_Sending_Data, Sending_Data);
signal CurrentState_Data, NextState_Data: Data_State;
signal Sending_Data_aux: std_logic:='0'; -- ACTIVE HIGH when data is being sent

-- SIGNALS WITH IMPORTANT INFO
SIGNAL Slope_Current_aux: std_logic_vector(13 downto 0):=(others=>'0');
SIGNAL Slope_Threshold_aux: std_logic_vector(6 downto 0):=(others=>'0');
SIGNAL Peak_Current_aux: std_logic:='0';
SIGNAL Detection_aux: std_logic:='0';
SIGNAL Allow_Previous_Info: std_logic:='0';
SIGNAL Info_Previous_reg: std_logic:='0';

-- SELF-TRIGGER FRAME FORMAT signals
type Frame_State is   (Idle, One, Two, Three, Four, Five, No_More_Peaks, Data);
signal CurrentState_Frame, NextState_Frame: Frame_State;

-- Self-Trigger DELAY 
SIGNAL Trigger_Delay: std_logic_vector(4 downto 0):=(others=>'0');

begin

--UUT1 : Filter_CIEMAT 
--      PORT MAP (
--      clock         => clock_aux,
--      reset         => reset_aux,      
--      din           => din_aux,
--      Config_Param  => Config_Param_FILTER_aux, 
--      filtered_dout => filtered_dout_aux);
      
UUT2 : PeakDetector_SelfTrigger_CIEMAT 
      PORT MAP (
      clock         => clock_aux,
      reset         => reset_aux,      
      din           => din_aux,
      Sending_Data  => Sending_Data_aux, 
      Config_Param  => Config_Param_SELF_aux, 
      Interface_LOCAL_Primitves_IN => Interface_LOCAL_Primitves_IN_aux,
      Interface_LOCAL_Primitves_OUT => Interface_LOCAL_Primitves_OUT_aux,
      Self_trigger => open);

Ext_Self_Trigger_Match <= Ext_Self_Trigger and (Match_with_Frame or Sending_Data_aux); 
      
UUT3 : LocalPrimitives_CIEMAT
    PORT MAP ( 
    clock =>  clock_aux,                                                -- AFE clock
    reset=>  reset_aux,                                                 -- Reset signal. ACTIVE HIGH
    Self_trigger=> Ext_Self_Trigger_Match,                                    -- Self-Trigger signal comming from the Self-Trigger block
    din=>  filtered_dout_aux_delay_Extra,                               -- Data coming from the Filter Block / Raw data from AFEs
    Interface_LOCAL_Primitves_IN=>  Interface_LOCAL_Primitves_OUT_aux,   -- Interface with Local Primitives calculation BLOCK --> DEPENDS ON SELF-TRIGGER ALGORITHM 
    Interface_LOCAL_Primitves_OUT=>  Interface_LOCAL_Primitves_IN_aux, -- Interface with Local Primitives calculation BLOCK --> DEPENDS ON SELF-TRIGGER ALGORITHM 
    Data_Available=>  Data_Available_aux,                               -- ACTIVE HIGH when LOCAL primitives are calculated
    Time_Peak=>  Time_Peak_aux,                                         -- Time in Samples to achieve de Max peak
    Time_Over_Baseline=>  Time_Over_Baseline_aux,                                 -- Time in Samples of the light pulse signal is UNDER BASELINE (without undershoot)
    ADC_Peak=>  ADC_Peak_aux,                                           -- Amplitude in ADC counts od the peak
    ADC_Integral=>  ADC_Integral_aux,                                               -- Charge of the light pulse (without undershoot) in ADC*samples
    Number_Peaks=>  Number_Peaks_aux,                             -- Number of peaks detected when signal is UNDER BASELINE (without undershoot).  
    Baseline=>  Baseline,                                           -- TO BE REMOVED AFTER DEBUGGING
    Amplitude=>  Amplitude_aux,                                        -- TO BE REMOVED AFTER DEBUGGING
    High_Freq_Noise=> Noise_aux);

---------------------- GET (Synchronous) AND UPDATE CONFIGURATION PARAMETERS     -----------------------

Get_Config_Params: process(clock)
begin
    if (clock'event and clock='1') then
        Config_Param_Reg <= Config_Param;
    end if;
end process Get_Config_Params;

-- Config_Param_FILTER[0] --> 1 = ENABLE filtering / 0 = DISABLE filtering 
-- Config_Param_FILTER[1] --> '0' = 1 LSB truncated / '1' = 2 LSBs truncated 
-- Config_Param_FILTER[3 downto 2] --> '00' = 4 Samples Window / '01' = 8 Samples Window / '10' = 16 Samples Window / '11' = 32 Samples Window
Config_Param_FILTER_aux             <= Config_Param_Reg(3 downto 0);

-- Config_Param_SELF[0] --> '0' = Peak detector as self-trigger  / '1' = Main detection as Self-Trigger (Undershoot peaks will not trigger)
-- Config_Param_SELF[1] --> '0' = NOT ALLOWED  Self-Trigger with light pulse between 2 data adquisition frames   
--                 --> '1' = ALLOWED Self-Trigger with light pulse between 2 data adquisition frames
-- Config_Param_SELF[2] --> '0' = Slope calculation with 2 consecutive samples --> x(n) - x(n-1)  / '1' = Slope calculation with 3 consecutive samples --> [x(n) - x(n-2)] / 2 
-- Config_Param_SELF[9 downto 3] --> Slope_Threshold (signed) 1(sign) + 6 bits, must be negative.
Config_Param_SELF_aux               <= Config_Param_Reg(13 downto 4);

---------------------- REGISTER THE VALUES OF A WAVEFORM TO FILL THE TRAILER WORDS     -----------------------

Get_Local_Primitives_Params: process(clock_aux, reset_aux, Data_Available_aux)
begin
    if (clock_aux'event and clock_aux='1') then
        if (reset_aux='1') then
            Time_Peak_reg <= (others=>'1');
            Time_Over_Baseline_reg <= (others=>'1');
            ADC_Peak_reg <= (others=>'1');
            ADC_Integral_reg <= (others=>'1');
            Number_Peaks_reg <= (others=>'1');
        elsif (Data_Available_aux = '1') then
            Time_Peak_reg <= Time_Peak_aux;
            Time_Over_Baseline_reg <= Time_Over_Baseline_aux;
            ADC_Peak_reg <= ADC_Peak_aux;
            ADC_Integral_reg <= ADC_Integral_aux;
            Number_Peaks_reg <= Number_Peaks_aux;
        end if; 
    end if;
end process Get_Local_Primitives_Params;

---------------------- ACTIVATING OF PREVIOUS INFO BIT (Indicates that a waveform is between 2 self-trigger frames     -----------------------
Previous_Bit: process(Allow_Previous_Info, Sending_Data_aux,Detection_aux, reset_aux, clock_aux)
begin
    if (clock_aux'event and clock_aux='1') then
        if ((Allow_Previous_Info='1') and (Sending_Data_aux='0') and(Detection_aux='1') and (Info_Previous_reg = '0')) then
            Info_Previous_reg <= '1';
        elsif (((Sending_Data_aux='0') and (Info_Previous_reg='1') )or (reset_aux = '1')) then
            Info_Previous_reg <= '0';      
        end if;
    end if; 
end process Previous_Bit;

Info_Previous <= Info_Previous_reg;

------------ VARIABLES WITH IMPORTANT INFO ------------------------
Peak_Current_aux    <= Interface_LOCAL_Primitves_OUT_aux(0);
Slope_Current_aux   <= Interface_LOCAL_Primitves_OUT_aux(14 downto 1);
Slope_Threshold_aux <= Config_Param_SELF_aux(9 downto 3);
Detection_aux       <= Interface_LOCAL_Primitves_IN_aux(0);
Allow_Previous_Info <= Config_Param_SELF_aux(1);

----------------------- DATA SENDING CONTROL    -----------------------

-- FSM SENDING DATA CONTROL. 
-- This Finite Sate controls when data is being sent 
--      * Not_Sending Data --> Data is not being sent 
--      * Sending_Data --> Remeains in this state for Framse_Size tics when a self-trigger event has occured
Next_State_Sending: process(CurrentState_Data,Ext_Self_Trigger, Data_Sent_Count,Noise_aux)
begin
    case CurrentState_Data is
        when Not_Sending_Data =>
            if((Ext_Self_Trigger = '1')and (Match_with_Frame ='1')) then
                NextState_Data <= Sending_Data;
            else
                NextState_Data <= Not_Sending_Data; 
            end if;
        when Sending_Data =>
            if(Data_Sent_Count >= Frame_Size) then
                NextState_Data <= Not_Sending_Data;
            else
                NextState_Data <= Sending_Data;
            end if;        
    end case;
end process Next_State_Sending;

FFs_Sending: process(clock_aux, reset_aux)
begin
    if (reset_aux='1')  then
        CurrentState_Data <= Not_Sending_Data;
        Data_Sent_Count <= 0;
    elsif(clock_aux'event and clock_aux='1') then
        CurrentState_Data <= NextState_Data;
        if (CurrentState_Data=Not_Sending_Data) then               
            Data_Sent_Count <= 0;
        else
            Data_Sent_Count <= Data_Sent_Count + 1;
        end if;
    end if;
end process FFs_Sending;

Output_Sending: process(CurrentState_Data)
begin
    case CurrentState_Data is
        when Not_Sending_Data => 
            Sending_Data_aux <= '0';
        when Sending_Data =>        
            Sending_Data_aux <= '1';        
    end case;
end process Output_Sending;

----------------------- FILLING TRAILER WORDS WITH META DATA    -----------------------

-- FSM FRAME FORMAT: This Finite Sate Machine fills the trailer words from self-trigger frame format v1.5
--      * IDLE          --> IDLE state, resets Trailer word registers 
--      * ONE           --> One peak detected
--      * TWO           --> Two peaks detected
--      * THREE         --> Three peaks detected
--      * FOUR          --> Four peaks detected 
--      * FIVE          --> Five peaks detected
--      * NO_MORE_PEAKS --> Self-Trigger Frame Format only allows info of FIVE different peaks
--      * DATA          --> Trailer words are ready (only 1 clk)  


Next_State_FrameFormat: process(CurrentState_Frame, Sending_Data_aux, Data_available_aux)
begin
    case CurrentState_Frame is
        when Idle =>
            if((Sending_Data_aux='1') and (Data_Available_aux='1'))then
                NextState_Frame <= one;
            else
                NextState_Frame <= idle; 
            end if;
        when One =>
            if((Sending_Data_aux='1') and (Data_Available_aux='1'))then
                NextState_Frame <= Two;
            elsif (Sending_Data_aux='0') then
                NextState_Frame <= Data;
            else
                NextState_Frame <= One;
            end if;
        when Two =>
            if((Sending_Data_aux='1') and (Data_Available_aux='1'))then
                NextState_Frame <= Three;
            elsif (Sending_Data_aux='0') then
                NextState_Frame <= Data;
            else
                NextState_Frame <= Two;
            end if;
        when Three =>
            if((Sending_Data_aux='1') and (Data_Available_aux='1'))then
                NextState_Frame <= Four;
            elsif (Sending_Data_aux='0') then
                NextState_Frame <= Data;
            else
                NextState_Frame <= Three; 
            end if;
        when Four =>
            if((Sending_Data_aux='1') and (Data_Available_aux='1'))then
                NextState_Frame <= Five;
            elsif (Sending_Data_aux='0') then
                NextState_Frame <= Data;
            else
                NextState_Frame <= Four; 
            end if;
        when Five =>
            if((Sending_Data_aux='1') and (Data_Available_aux='1'))then
                NextState_Frame <= No_More_Peaks;
            elsif (Sending_Data_aux='0') then
                NextState_Frame <= Data;
            else
                NextState_Frame <= Five; 
            end if;
        when No_More_Peaks =>
            if (Sending_Data_aux='0') then
                NextState_Frame <= Data;
            else
                NextState_Frame <= No_More_Peaks; 
            end if;
        when Data =>
                NextState_Frame <= Idle;               
    end case;
end process Next_State_FrameFormat;

FFs_FrameFormat: process(clock_aux, reset_aux)
begin
    if (reset_aux='1')  then
        CurrentState_Frame      <= Idle;
        Trailer_Word_0_reg      <= X"7FFFFFFF";
        Trailer_Word_1_reg      <= X"FFFFFFFF";
        Trailer_Word_2_reg      <= X"7FFFFFFF";
        Trailer_Word_3_reg      <= X"FFFFFFFF";
        Trailer_Word_4_reg      <= X"7FFFFFFF";
        Trailer_Word_5_reg      <= X"FFFFFFFF";
        Trailer_Word_6_reg      <= X"7FFFFFFF";
        Trailer_Word_7_reg      <= X"FFFFFFFF";
        Trailer_Word_8_reg      <= X"7FFFFFFF";
        Trailer_Word_9_reg      <= X"FFFFFFFF";
        Trailer_Word_10_reg     <= X"FFFFFFFF";
        Trailer_Word_11_reg     <= X"FFFFFFFF";
                        
    elsif(clock_aux'event and clock_aux='1') then
        CurrentState_Frame <= NextState_Frame;
        if (CurrentState_Frame=Idle) then               
            Trailer_Word_0_reg      <= X"7FFFFFFF";
            Trailer_Word_1_reg      <= X"FFFFFFFF";
            Trailer_Word_2_reg      <= X"7FFFFFFF";
            Trailer_Word_3_reg      <= X"FFFFFFFF";
            Trailer_Word_4_reg      <= X"7FFFFFFF";
            Trailer_Word_5_reg      <= X"FFFFFFFF";
            Trailer_Word_6_reg      <= X"7FFFFFFF";
            Trailer_Word_7_reg      <= X"FFFFFFFF";
            Trailer_Word_8_reg      <= X"7FFFFFFF";
            Trailer_Word_9_reg      <= X"FFFFFFFF";
            Trailer_Word_10_reg     <= X"FFFFFFFF";
            Trailer_Word_11_reg     <= X"FFFFFFFF";
        elsif(CurrentState_Frame=One) then
            Trailer_Word_0_reg      <= ('1' & ADC_Integral_reg & "1111" & Number_Peaks_reg); 
            Trailer_Word_1_reg      <= (Time_Over_Baseline_reg & Time_Peak_reg & ADC_Peak_reg);
            Trailer_Word_10_reg(31 downto 22)       <= (Time_Start_reg2); 
        elsif(CurrentState_Frame=Two) then
            Trailer_Word_2_reg      <= ('1' & ADC_Integral_reg & "1111" & Number_Peaks_reg); 
            Trailer_Word_3_reg      <= (Time_Over_Baseline_reg & Time_Peak_reg & ADC_Peak_reg);
            Trailer_Word_10_reg(21 downto 12)       <= (Time_Start_reg2);  
        elsif(CurrentState_Frame=Three) then
            Trailer_Word_4_reg      <= ('1' & ADC_Integral_reg & "1111" & Number_Peaks_reg);  
            Trailer_Word_5_reg      <= (Time_Over_Baseline_reg & Time_Peak_reg & ADC_Peak_reg);
            Trailer_Word_10_reg(11 downto 2)       <= (Time_Start_reg2);  
        elsif(CurrentState_Frame=Four) then
            Trailer_Word_6_reg      <= ('1' & ADC_Integral_reg & "1111" & Number_Peaks_reg); 
            Trailer_Word_7_reg      <= (Time_Over_Baseline_reg & Time_Peak_reg & ADC_Peak_reg);
            Trailer_Word_11_reg(31 downto 22)       <= (Time_Start_reg2);         
        elsif(CurrentState_Frame=Five) then
            Trailer_Word_8_reg      <= ('1' & ADC_Integral_reg & "1111" & Number_Peaks_reg);  
            Trailer_Word_9_reg      <= (Time_Over_Baseline_reg & Time_Peak_reg & ADC_Peak_reg);
            Trailer_Word_11_reg(21 downto 12)       <= (Time_Start_reg2);                 
        else
            Trailer_Word_0_reg      <= Trailer_Word_0_reg;
            Trailer_Word_1_reg      <= Trailer_Word_1_reg;
            Trailer_Word_2_reg      <= Trailer_Word_2_reg;
            Trailer_Word_3_reg      <= Trailer_Word_3_reg;
            Trailer_Word_4_reg      <= Trailer_Word_4_reg;
            Trailer_Word_5_reg      <= Trailer_Word_5_reg;
            Trailer_Word_6_reg      <= Trailer_Word_6_reg;
            Trailer_Word_7_reg      <= Trailer_Word_7_reg;
            Trailer_Word_8_reg      <= Trailer_Word_8_reg;
            Trailer_Word_9_reg      <= Trailer_Word_9_reg;
            Trailer_Word_10_reg     <= Trailer_Word_10_reg;
            Trailer_Word_11_reg     <= Trailer_Word_11_reg;

        end if;
    end if;
end process FFs_FrameFormat;

Output_FrameFormat: process(CurrentState_Frame, Trailer_Word_0_reg, Trailer_Word_1_reg, Trailer_Word_2_reg, Trailer_Word_3_reg, Trailer_Word_4_reg, Trailer_Word_5_reg, Trailer_Word_6_reg, Trailer_Word_7_reg, Trailer_Word_8_reg, Trailer_Word_9_reg, Trailer_Word_10_reg, Trailer_Word_11_reg)
begin
    case CurrentState_Frame is
        when Idle => 
            Data_Available_Trailer  <= '0';
            Trailer_Word_0          <= (others=>'0');
            Trailer_Word_1          <= (others=>'0');
            Trailer_Word_2          <= (others=>'0');
            Trailer_Word_3          <= (others=>'0');
            Trailer_Word_4          <= (others=>'0');
            Trailer_Word_5          <= (others=>'0');
            Trailer_Word_6          <= (others=>'0');
            Trailer_Word_7          <= (others=>'0');
            Trailer_Word_8          <= (others=>'0');
            Trailer_Word_9          <= (others=>'0');
            Trailer_Word_10         <= (others=>'0');
            Trailer_Word_11         <= (others=>'0'); 
        when One =>        
            Data_Available_Trailer  <= '0';
            Trailer_Word_0          <= (others=>'0');
            Trailer_Word_1          <= (others=>'0');
            Trailer_Word_2          <= (others=>'0');
            Trailer_Word_3          <= (others=>'0');
            Trailer_Word_4          <= (others=>'0');
            Trailer_Word_5          <= (others=>'0');
            Trailer_Word_6          <= (others=>'0');
            Trailer_Word_7          <= (others=>'0');
            Trailer_Word_8          <= (others=>'0');
            Trailer_Word_9          <= (others=>'0');
            Trailer_Word_10         <= (others=>'0');
            Trailer_Word_11         <= (others=>'0');  
        when Two =>        
            Data_Available_Trailer  <= '0';
            Trailer_Word_0          <= (others=>'0');
            Trailer_Word_1          <= (others=>'0');
            Trailer_Word_2          <= (others=>'0');
            Trailer_Word_3          <= (others=>'0');
            Trailer_Word_4          <= (others=>'0');
            Trailer_Word_5          <= (others=>'0');
            Trailer_Word_6          <= (others=>'0');
            Trailer_Word_7          <= (others=>'0');
            Trailer_Word_8          <= (others=>'0');
            Trailer_Word_9          <= (others=>'0');
            Trailer_Word_10         <= (others=>'0');
            Trailer_Word_11         <= (others=>'0');              
        when Three =>        
            Data_Available_Trailer  <= '0';
            Trailer_Word_0          <= (others=>'0');
            Trailer_Word_1          <= (others=>'0');
            Trailer_Word_2          <= (others=>'0');
            Trailer_Word_3          <= (others=>'0');
            Trailer_Word_4          <= (others=>'0');
            Trailer_Word_5          <= (others=>'0');
            Trailer_Word_6          <= (others=>'0');
            Trailer_Word_7          <= (others=>'0');
            Trailer_Word_8          <= (others=>'0');
            Trailer_Word_9          <= (others=>'0');
            Trailer_Word_10         <= (others=>'0');
            Trailer_Word_11         <= (others=>'0');              
        when Four => 
            Data_Available_Trailer  <= '0';
            Trailer_Word_0          <= (others=>'0');
            Trailer_Word_1          <= (others=>'0');
            Trailer_Word_2          <= (others=>'0');
            Trailer_Word_3          <= (others=>'0');
            Trailer_Word_4          <= (others=>'0');
            Trailer_Word_5          <= (others=>'0');
            Trailer_Word_6          <= (others=>'0');
            Trailer_Word_7          <= (others=>'0');
            Trailer_Word_8          <= (others=>'0');
            Trailer_Word_9          <= (others=>'0');
            Trailer_Word_10         <= (others=>'0');
            Trailer_Word_11         <= (others=>'0');             
        when Five =>        
            Data_Available_Trailer  <= '0';
            Trailer_Word_0          <= (others=>'0');
            Trailer_Word_1          <= (others=>'0');
            Trailer_Word_2          <= (others=>'0');
            Trailer_Word_3          <= (others=>'0');
            Trailer_Word_4          <= (others=>'0');
            Trailer_Word_5          <= (others=>'0');
            Trailer_Word_6          <= (others=>'0');
            Trailer_Word_7          <= (others=>'0');
            Trailer_Word_8          <= (others=>'0');
            Trailer_Word_9          <= (others=>'0');
            Trailer_Word_10         <= (others=>'0');
            Trailer_Word_11         <= (others=>'0');              
        when No_More_Peaks =>        
            Data_Available_Trailer  <= '0';
            Trailer_Word_0          <= (others=>'0');
            Trailer_Word_1          <= (others=>'0');
            Trailer_Word_2          <= (others=>'0');
            Trailer_Word_3          <= (others=>'0');
            Trailer_Word_4          <= (others=>'0');
            Trailer_Word_5          <= (others=>'0');
            Trailer_Word_6          <= (others=>'0');
            Trailer_Word_7          <= (others=>'0');
            Trailer_Word_8          <= (others=>'0');
            Trailer_Word_9          <= (others=>'0');
            Trailer_Word_10         <= (others=>'0');
            Trailer_Word_11         <= (others=>'0');              
        when Data =>        
            Data_Available_Trailer  <= '1';
            Trailer_Word_0          <= Trailer_Word_0_reg;
            Trailer_Word_1          <= Trailer_Word_1_reg;
            Trailer_Word_2          <= Trailer_Word_2_reg;
            Trailer_Word_3          <= Trailer_Word_3_reg;
            Trailer_Word_4          <= Trailer_Word_4_reg;
            Trailer_Word_5          <= Trailer_Word_5_reg;
            Trailer_Word_6          <= Trailer_Word_6_reg;
            Trailer_Word_7          <= Trailer_Word_7_reg;
            Trailer_Word_8          <= Trailer_Word_8_reg;
            Trailer_Word_9          <= Trailer_Word_9_reg;
            Trailer_Word_10         <= Trailer_Word_10_reg;
            Trailer_Word_11         <= Trailer_Word_11_reg;    
    end case;
end process Output_FrameFormat;


---- TIME START For hits within the frame
Time_Start_aux <= std_logic_vector(to_unsigned(Data_Sent_Count + 64,10));
Proc_Time_Start: process(clock_aux, Ext_Self_Trigger_Match, Data_Available_aux)
begin
    if(clock_aux'event and clock_aux='1') then
        if (Ext_Self_Trigger_Match='1') then               
            Time_Start_reg <= Time_Start_aux;
        elsif (Data_Available_aux='1') then               
            Time_Start_reg2 <= Time_Start_reg;            
        end if;
    end if;
end process Proc_Time_Start;
------- add in some fake/synthetic latency, adjust it so total trigger latency is 64 clocks -----------

--Select_Delay: process(Config_Param_FILTER_aux (0)) -- While filtering delay is bigger 
--begin
--    if (Config_Param_FILTER_aux (0)='0') then
--        Trigger_Delay <= "10100"; -- 11 clk
--    else
--        Trigger_Delay <= "10000"; -- 8 clk
--    end if;
--end process Select_Delay;

--srlc32e_0_inst : srlc32e
--port map(
--    clk => clock_aux,
--    ce  => '1',
--    a   => "11111",
--    d   => Self_trigger_aux,
--    q   => open,
--    q31 => triggered_dly32_i
--);

--srlc32e_1_inst : srlc32e
--port map(
--    clk => clock_aux,
--    ce  => '1',
--    a   => Trigger_Delay,  -- adjust this delay to make overall latency = 64
--    d   => triggered_dly32_i,
--    q   => Self_trigger_out_aux,
--    q31 => open
--);

Trigger_Propagation: process(clock, Noise_aux, Self_trigger_aux)
begin
    if (clock'event and clock='1') then
        if (Self_trigger_aux = '1') then
            Trigger_dly53 <= Trigger_dly53 sll 1;
            Trigger_dly53(0) <= '1';
        elsif ((Noise_aux='1') and (Config_Param_SELF_aux(0)='1')) then -- only main detections use the noise check 
            Trigger_dly53 <= (others => '0');
        else
            Trigger_dly53 <= Trigger_dly53 sll 1;
        end if;    
    end if;
end process Trigger_Propagation;
--Noise_OR <= Noise_64(0) or Noise_64(1) or Noise_64(2) or Noise_64(3) or Noise_64(4) or Noise_64(5) or Noise_64(6) or Noise_64(7) or Noise_64(8) or Noise_64(9) or Noise_64(10) or Noise_64(11) or Noise_64(12) or Noise_64(13) or Noise_64(14) or Noise_64(15) or Noise_64(16) or Noise_64(17) or Noise_64(18) or Noise_64(19) or Noise_64(20) or Noise_64(21) or Noise_64(22) or Noise_64(23) or Noise_64(24) or Noise_64(25) or Noise_64(26) or Noise_64(27) or Noise_64(28) or Noise_64(29) or Noise_64(30) or Noise_64(31) or Noise_64(32) or Noise_64(33) or Noise_64(34) or Noise_64(35) or Noise_64(36) or Noise_64(37) or Noise_64(38) or Noise_64(39) or Noise_64(40) or Noise_64(41) or Noise_64(42) or Noise_64(43) or Noise_64(44) or Noise_64(45) or Noise_64(46) or Noise_64(47) or Noise_64(48) or Noise_64(49) or Noise_64(50) or Noise_64(51) or Noise_64(52) or Noise_64(53) or Noise_64(54) or Noise_64(55) or Noise_64(56) or Noise_64(57) or Noise_64(58) or Noise_64(59) or Noise_64(60) or Noise_64(61) or Noise_64(62) or Noise_64(63);  
Self_trigger_out_aux <= to_stdulogic(Trigger_dly53(53)); 

----------------------- GENERATE DELAY FOR FILTERED SIGNAL (Takes into account delay of trigger, for primitve calculation)   -----------------------
gendelay: for i in 13 downto 0 generate
        srlc32e_0_inst : srlc32e
        port map(
            clk => clock_aux,
            ce => '1',
            a => "11111",
            d => din_aux(i), -- real time filtered data
            q => open, 
            q31 => filtered_dout_aux_delay_32(i) -- DIN data 32 clocks ago 
        );
        
        srlc32e_1_inst : srlc32e
        port map(
            clk => clock_aux,
            ce => '1',
            a => "11111",
            d => filtered_dout_aux_delay_32(i),
            q => open,
            q31 => filtered_dout_aux_delay_64(i) -- DIN data 64 clocks ago
        );
        
        srlc32e_2_inst : srlc32e
        port map(
            clk => clock_aux,
            ce => '1',
            a => "11111",
            d => filtered_dout_aux_delay_64(i),
            q => open,
            q31 => filtered_dout_aux_delay_96(i) -- DIN data 96 clocks ago
        );

        srlc32e_3_inst : srlc32e
        port map(
            clk => clock_aux,
            ce => '1',
            a => "11111",
            d => filtered_dout_aux_delay_96(i),
            q => open,
            q31 => filtered_dout_aux_delay_128(i) -- DIN data 128 clocks ago
        );

        srlc32e_4_inst : srlc32e
        port map(
            clk => clock_aux,
            ce => '1',
            a => "11111",
            d => filtered_dout_aux_delay_128(i),
            q => open,
            q31 => filtered_dout_aux_delay_160(i) -- DIN data 160 clocks ago
        );

       srlc32e_5_inst : srlc32e
        port map(
            clk => clock_aux,
            ce => '1',
            a => "10000",
            d => filtered_dout_aux_delay_160(i),
            q => filtered_dout_aux_delay_Extra(i), -- DIN data 192 clocks ago
            q31 => open 
        );
end generate gendelay;
----------------------- INPUT SIGNALS   -----------------------
clock_aux           <= clock;
reset_aux           <= reset;
din_aux             <= din;

----------------------- OUTPUT SIGNALS   -----------------------
Self_trigger        <= Self_trigger_out_aux;                   
Data_Available      <= Data_Available_aux;      
Time_Peak           <= Time_Peak_aux;                       
Time_Over_Baseline  <= Time_Over_Baseline_aux;                   
Time_Start          <= Time_Start_reg2;                  
ADC_Peak            <= ADC_Peak_aux;                        
ADC_Integral        <= ADC_Integral_aux;                          
Number_Peaks        <= Number_Peaks_aux;                 
--filtered_dout       <= filtered_dout_aux;                  
--Baseline            <= Baseline_aux;                        
Amplitude           <= Amplitude_aux;                       
Peak_Current        <= Peak_Current_aux;                   
Slope_Current       <= Slope_Current_aux;                  
Slope_Threshold     <= Slope_Threshold_aux;                 
Detection           <= Detection_aux; 
Sending             <= Sending_Data_aux;                      

end Behavioral;