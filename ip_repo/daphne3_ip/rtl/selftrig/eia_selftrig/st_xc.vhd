-- st_xc.vhd
-- self trigger using matching filter for single-double-triple PE detection
--
-- This module implements a cross correlation matching filter that uses the 
-- data coming from one channel in order to generate a self trigger signal output
-- whenever simple events occur. This matching filter is capable of detecting
-- Single PhotonElectrons, Double PhotonElectrons, Triple PhotonElectrons 
--
-- Daniel Avila Gomez <daniel.avila@eia.edu.co> & Edgar Rincon Gil <edgar.rincon.g@gmail.com>

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use ieee.std_logic_signed.all;

library unisim;
use unisim.vcomponents.all;

entity st_xc is
port (     
    reset : in std_logic;
    clock : in std_logic; -- AFE clock 62.500 MHz
    enable : in std_logic;
    din : in std_logic_vector(13 downto 0); -- filtered AFE data (no baseline)
    threshold : in std_logic_vector(41 downto 0); -- matching filter trigger threshold values
    triggered : out std_logic;
    xcorr_calc : out signed(27 downto 0)
);
end st_xc;

architecture st_xc_arch of st_xc is

-- threshold signals (threshold window)
--------------------------------------------------------------------------------------------------------------------------------------------------
signal s_threshold: signed(27 downto 0);
--signal en_threshold: signed(13 downto 0);

-- cross correlator specific signals
--------------------------------------------------------------------------------------------------------------------------------------------------
type type_r_st_xc is array (0 to 32) of std_logic_vector(47 downto 0);
signal r_st_xc: type_r_st_xc:= (others => (others => '0'));
signal xcorr, xcorr_reg0, xcorr_reg1: signed(27 downto 0) := (others => '0');
signal s_r_st_xc: signed(47 downto 0) := (others => '0');

-- matching filter template
--------------------------------------------------------------------------------------------------------------------------------------------------
type template is array (0 to 31) of std_logic_vector(13 downto 0);
constant template_xc: template := (
    std_logic_vector(to_signed(1,14)),
    std_logic_vector(to_signed(0,14)),
    std_logic_vector(to_signed(0,14)),
    std_logic_vector(to_signed(0,14)),
    std_logic_vector(to_signed(0,14)),
    std_logic_vector(to_signed(0,14)),
    std_logic_vector(to_signed(-1,14)),
    std_logic_vector(to_signed(-1,14)),
    std_logic_vector(to_signed(-1,14)),
    std_logic_vector(to_signed(-1,14)),
    std_logic_vector(to_signed(-1,14)),
    std_logic_vector(to_signed(-2,14)),
    std_logic_vector(to_signed(-2,14)),
    std_logic_vector(to_signed(-3,14)),
    std_logic_vector(to_signed(-4,14)),
    std_logic_vector(to_signed(-4,14)),
    std_logic_vector(to_signed(-5,14)),
    std_logic_vector(to_signed(-5,14)),
    std_logic_vector(to_signed(-6,14)),
    std_logic_vector(to_signed(-7,14)),
    std_logic_vector(to_signed(-6,14)),
    std_logic_vector(to_signed(-7,14)),
    std_logic_vector(to_signed(-7,14)),
    std_logic_vector(to_signed(-7,14)),
    std_logic_vector(to_signed(-7,14)),
    std_logic_vector(to_signed(-6,14)),
    std_logic_vector(to_signed(-5,14)),
    std_logic_vector(to_signed(-4,14)),
    std_logic_vector(to_signed(-3,14)),
    std_logic_vector(to_signed(-2,14)),
    std_logic_vector(to_signed(-1,14)),
    std_logic_vector(to_signed(0,14))
);

-- dsp dedicated module
--------------------------------------------------------------------------------------------------------------------------------------------------
component dsp_xc 
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
end component dsp_xc;

begin

    -- define the configuration of the trigger
--------------------------------------------------------------------------------------------------------------------------------------------------
    -- trigger threshold to ignore larger events
--    en_threshold <= signed(threshold(41 downto 28));

    -- trigger modification to compare the cross correlation output
    s_threshold <= signed(threshold(27 downto 0));

    -- instantiate all the necessary DSPs
--------------------------------------------------------------------------------------------------------------------------------------------------
    st_xc_mult_gen: for i in 0 to 31 generate
        -- generate operations to multiply the data with its respective coefficients, and add the results
        
        st_xc_mult_0: if (template_xc(i)=X"0000000") generate
            -- if the multiplication is done with a coefficient that is equal to zero, then we must
            -- avoid implementing it with DSPs, and only use mere registers to properly fit this
            -- design structure
            reg_block: block
                signal local_reg: std_logic_vector(47 downto 0) := (others => '0');
            begin
                st_xc_reg_proc: process(clock, reset, r_st_xc, local_reg)
                begin
                    if rising_edge(clock) then
                        if (reset='1') then
                            r_st_xc(i) <= (others => '0');
                            local_reg <= (others => '0');
                        elsif (enable='1') then
                            local_reg <= r_st_xc(i+1);
                            r_st_xc(i) <= local_reg;
                        end if;
                    end if;
                end process st_xc_reg_proc;
            end block;
        end generate st_xc_mult_0;
        
        st_xc_mult_dsp: if (template_xc(i)/=X"0000000") generate
            -- instantiate the respective DSP
            dsp_com: dsp_xc
                port map (
                    rst => reset,
                    clk => clock,
                    num_a => din,
                    num_b => template_xc(i),
                    num_add => r_st_xc(i+1),
                    res => r_st_xc(i)
                );
        end generate st_xc_mult_dsp;        
    end generate st_xc_mult_gen;
    
    -- generate a clocked process to register the output of the cross correlation
--------------------------------------------------------------------------------------------------------------------------------------------------
    xcorr_reg: process(clock, reset, enable, r_st_xc, s_r_st_xc, xcorr, xcorr_reg0)
    begin
        if rising_edge(clock) then
            if (reset='1') then
                -- set them to 0 whenever reset is asserted
                s_r_st_xc <= (others => '0');
                xcorr <= (others => '0');
                xcorr_reg0 <= (others => '0');
                xcorr_reg1 <= (others => '0');
            elsif (enable='1') then
                -- register the old values to keep track of how the calculation is behaving
                -- do it only if the module is enabled to trigger
                s_r_st_xc <= signed(r_st_xc(0));
                xcorr <= resize(s_r_st_xc,28);
                xcorr_reg0 <= xcorr;
                xcorr_reg1 <= xcorr_reg0;
            end if;
        end if;
    end process xcorr_reg;

    -- trigger and peak detector simple logic 
-------------------------------------------------------------------------------------------------------------------
    -- this logic uses the cross correlation output to determine when a self trigger must be 
    -- asserted. If this condition is met, it triggers a pulse one clock cycle wide
    trig_proc: process(clock, reset, enable, r_st_xc, xcorr_reg0, xcorr_reg1, s_threshold) 
    begin
        if rising_edge(clock) then
            if (reset='1') then
                triggered <= '0';
            else
                if ( ( enable='1' ) and ( xcorr>s_threshold ) 
                    and ( xcorr_reg0>s_threshold ) and ( xcorr_reg1<s_threshold or xcorr_reg1=s_threshold ) ) then 
                    triggered <= '1';
                else
                    triggered <= '0';
                end if;
            end if;
        end if;
    end process trig_proc;
    
    -- cross correlation output 
-------------------------------------------------------------------------------------------------------------------
    xcorr_calc <= xcorr; 
    
end st_xc_arch;