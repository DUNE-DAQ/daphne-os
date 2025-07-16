-- dsp_xc.vhd
-- dsp module for cross correlation operation
--
-- This module instantiates a DSP48E2 slice made specifically for UltraScale architectures
-- meant to be used in the design to avoid Vivado inferring the same structures with more 
-- logic than it should, allowing for resource optimization
--
-- Daniel Avila Gomez <daniel.avila@eia.edu.co>

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

library unisim;
use unisim.vcomponents.all;

entity dsp_xc is
--    generic (
--        creg_param : integer := 0
--    );
    port ( 
        -- module inputs
    ----------------------------------------------------------------------------------------------------------------------------------------------
        rst : in std_logic;
        clk : in std_logic;
        num_a : in std_logic_vector(13 downto 0);
        num_b : in std_logic_vector(13 downto 0);
        num_add : in std_logic_vector(47 downto 0);
        
        -- module outputs
    ----------------------------------------------------------------------------------------------------------------------------------------------
        res : out std_logic_vector(47 downto 0)
    );
end dsp_xc;

architecture dsp_xc_arch of dsp_xc is

-- interconnect auxiliary signals
--------------------------------------------------------------------------------------------------------------------------------------------------
signal a_in : std_logic_vector(29 downto 0) := (others => '0');
signal b_in : std_logic_vector(17 downto 0) := (others => '0');
signal c_clken : std_logic := '0';
signal c_rst : std_logic := '0';

begin

    -- resize the inputs and sign extend them for proper dsp operation
--------------------------------------------------------------------------------------------------------------------------------------------------
    a_in <= std_logic_vector(resize(signed(num_a),30));
    b_in <= std_logic_vector(resize(signed(num_b),18));
    
--    -- set clock enable and reset control por C input, according to the amount of registers 
--    -- to be used. This amount is set using the creg_param generic value
--    c_clken <= '1' when (creg_param=1) else '0';
--    c_rst <= rst when (creg_param=1) else '0';
    
    -- instantiate the dsp
--------------------------------------------------------------------------------------------------------------------------------------------------
    dsp48e2_inst : DSP48E2
        generic map (
            -- Register Control Attributes: Pipeline Register Configuration
            ACASCREG => 0,                     -- Number of pipeline stages between A/ACIN and ACOUT (0-2)
            ALUMODEREG => 0,                   -- Pipeline stages for ALUMODE (0-1)
            AREG => 0,                         -- Pipeline stages for A (0-2)
            BCASCREG => 0,                     -- Number of pipeline stages between B/BCIN and BCOUT (0-2)
            BREG => 0,                         -- Pipeline stages for B (0-2)
            CARRYINSELREG => 0,                -- Pipeline stages for CARRYINSEL (0-1)
--            CREG => creg_param,                         -- Pipeline stages for C (0-1)
            OPMODEREG => 0                    -- Pipeline stages for OPMODE (0-1)
        )
        port map (
            -- Cascade outputs: Cascade Ports
            ACOUT => open,                   -- 30-bit output: A port cascade
            BCOUT => open,                   -- 18-bit output: B cascade
            CARRYCASCOUT => open,     -- 1-bit output: Cascade carry
            MULTSIGNOUT => open,       -- 1-bit output: Multiplier sign cascade
            PCOUT => open,                   -- 48-bit output: Cascade output
            -- Control outputs: Control Inputs/Status Bits
            OVERFLOW => open,             -- 1-bit output: Overflow in add/acc
            PATTERNBDETECT => open, -- 1-bit output: Pattern bar detect
            PATTERNDETECT => open,   -- 1-bit output: Pattern detect
            UNDERFLOW => open,           -- 1-bit output: Underflow in add/acc
            -- Data outputs: Data Ports
            CARRYOUT => open,             -- 4-bit output: Carry
            P => res,                           -- 48-bit output: Primary data
            XOROUT => open,                 -- 8-bit output: XOR data
            -- Cascade inputs: Cascade Ports
            ACIN => (others => '1'),                     -- 30-bit input: A cascade data
            BCIN => (others => '1'),                     -- 18-bit input: B cascade
            CARRYCASCIN => '1',       -- 1-bit input: Cascade carry
            MULTSIGNIN => '1',         -- 1-bit input: Multiplier sign cascade
            PCIN => (others => '1'),                     -- 48-bit input: P cascade
            -- Control inputs: Control Inputs/Status Bits
            ALUMODE => "0000",               -- 4-bit input: ALU control
            CARRYINSEL => "000",         -- 3-bit input: Carry select
            CLK => clk,                       -- 1-bit input: Clock
            INMODE => "00000",                 -- 5-bit input: INMODE control
            OPMODE => "000110101",                 -- 9-bit input: Operation mode
            -- Data inputs: Data Ports
            A => a_in,                           -- 30-bit input: A data
            B => b_in,                           -- 18-bit input: B data
            C => num_add,                           -- 48-bit input: C data
            CARRYIN => '0',               -- 1-bit input: Carry-in
            D => (others => '1'),                           -- 27-bit input: D data
            -- Reset/Clock Enable inputs: Reset/Clock Enable Inputs
            CEA1 => '0',                     -- 1-bit input: Clock enable for 1st stage AREG
            CEA2 => '0',                     -- 1-bit input: Clock enable for 2nd stage AREG
            CEAD => '0',                     -- 1-bit input: Clock enable for ADREG
            CEALUMODE => '0',           -- 1-bit input: Clock enable for ALUMODE
            CEB1 => '0',                     -- 1-bit input: Clock enable for 1st stage BREG
            CEB2 => '0',                     -- 1-bit input: Clock enable for 2nd stage BREG
--            CEC => c_clken,                       -- 1-bit input: Clock enable for CREG
            CEC => '1',                       -- 1-bit input: Clock enable for CREG
            CECARRYIN => '0',           -- 1-bit input: Clock enable for CARRYINREG
            CECTRL => '0',                 -- 1-bit input: Clock enable for OPMODEREG and CARRYINSELREG
            CED => '0',                       -- 1-bit input: Clock enable for DREG
            CEINMODE => '0',             -- 1-bit input: Clock enable for INMODEREG
            CEM => '1',                       -- 1-bit input: Clock enable for MREG
            CEP => '1',                       -- 1-bit input: Clock enable for PREG
            RSTA => '0',                     -- 1-bit input: Reset for AREG
            RSTALLCARRYIN => '0',   -- 1-bit input: Reset for CARRYINREG
            RSTALUMODE => '0',         -- 1-bit input: Reset for ALUMODEREG
            RSTB => '0',                     -- 1-bit input: Reset for BREG
--            RSTC => c_rst,                     -- 1-bit input: Reset for CREG
            RSTC => rst,                     -- 1-bit input: Reset for CREG
            RSTCTRL => '0',               -- 1-bit input: Reset for OPMODEREG and CARRYINSELREG
            RSTD => '0',                     -- 1-bit input: Reset for DREG and ADREG
            RSTINMODE => '0',           -- 1-bit input: Reset for INMODEREG
            RSTM => rst,                     -- 1-bit input: Reset for MREG
            RSTP => rst                      -- 1-bit input: Reset for PREG
        );

end dsp_xc_arch;