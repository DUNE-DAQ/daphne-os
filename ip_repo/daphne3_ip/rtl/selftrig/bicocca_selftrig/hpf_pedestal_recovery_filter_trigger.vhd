----------------------------------------------------------------------------------
-- Company: 
-- Engineer: 
-- 
-- Create Date: 04.06.2025 10:06:14
-- Design Name: 
-- Module Name: hpf_pedestal_recovery_filter_trigger - hpf_pedestal_recovery_filter_trigger_arch
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


library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

-- Uncomment the following library declaration if instantiating
-- any Xilinx leaf cells in this code.
--library UNISIM;
--use UNISIM.VComponents.all;

entity hpf_pedestal_recovery_filter_trigger is
    port ( 
        clk : in std_logic;
        reset : in std_logic;
        enable : in std_logic;
        afe_comp_enable : in std_logic;
        invert_enable : in std_logic;
        threshold_xc : in std_logic_vector(41 downto 0);
        output_selector : in std_logic_vector(1 downto 0);
        baseline : out std_logic_vector(15 downto 0);
        x : in std_logic_vector(15 downto 0);
        trigger_output : out std_logic;
        y1 : out std_logic_vector(15 downto 0);
        y2 : out std_logic_vector(15 downto 0)
    );
end hpf_pedestal_recovery_filter_trigger;

architecture hpf_pedestal_recovery_filter_trigger_arch of hpf_pedestal_recovery_filter_trigger is

signal hpf_out, hpf_out_aux, hpf_out_xcorr: signed(15 downto 0);
signal movmean_out: signed(15 downto 0);
signal movmean_out_14: signed(13 downto 0);
signal x_i, x_delayed: signed(15 downto 0);
signal baseline_aux: signed(15 downto 0);
signal w_out: signed(15 downto 0);
signal resta_out, lpf_out, cfd_out: signed(15 downto 0);
signal suma_out: signed(15 downto 0);
--signal tm_output_selector: std_logic;
signal internal_afe_comp_enable: std_logic;
signal triggered_xc: std_logic;
signal xcorr_calc: signed(27 downto 0);

component k_low_pass_filter
    port (
        clk : in std_logic;
        reset : in std_logic;
        enable : in std_logic;
        x : in signed(15 downto 0);
        y : out signed(15 downto 0)
    ); 
end component k_low_pass_filter;

component IIRFilter_afe_integrator_optimized
    port (
        clk : in std_logic;
        reset : in std_logic;
        enable : in std_logic;
        x : in signed(15 downto 0);
        y : out signed(15 downto 0)
    ); 
end component IIRFilter_afe_integrator_optimized;

--component moving_integrator_filter
--    port (
--        clk : in std_logic;
--        reset : in std_logic;
--        enable : in std_logic;
--        x : in signed(15 downto 0);
--        y : out signed(15 downto 0);
--        x_delayed : out signed(15 downto 0)
--    ); 
--end component moving_integrator_filter;

component st_xc 
    port (     
        reset : in std_logic;
        clock : in std_logic; -- AFE clock 62.500 MHz
        enable : in std_logic;
        din : in std_logic_vector(13 downto 0); -- filtered AFE data (no baseline)
        threshold : in std_logic_vector(41 downto 0); -- matching filter trigger threshold values
        triggered : out std_logic;
        xcorr_calc : out signed(27 downto 0)
    );
end component st_xc;

component Configurable_CFD 
    port (   
        clock : in std_logic;   
        reset : in std_logic;
        enable : in std_logic;
        trigger_threshold : in std_logic;
        config_delay : in std_logic_vector(4 downto 0);
        config_sign : in std_logic;
        din : in std_logic_vector(27 downto 0);
        trigger : out std_logic
    );
end component Configurable_CFD;

begin

    lpf: k_low_pass_filter
        port map (
            clk => clk,
            reset => reset,
            enable => enable,
            x => x_i,
            y => lpf_out
        ); 
        
    hpf: IIRFilter_afe_integrator_optimized
        port map (
            clk => clk,
            reset => reset,
            enable => internal_afe_comp_enable,
            x => resta_out,
            y => hpf_out
        ); 
        
--    movmean: moving_integrator_filter
--        port map (
--            clk => clk,
--            reset => reset,
--            enable => enable,
--            x => hpf_out_xcorr,
--            y => movmean_out,
--            x_delayed => x_delayed
--        );
        
    matching_trigger: st_xc 
        port map (     
            reset => reset,
            clock => clk, -- AFE clock 62.500 MHz
            enable => enable,
            din => std_logic_vector(hpf_out_xcorr(13 downto 0)), -- filtered AFE data (no baseline)
            threshold => threshold_xc, -- matching filter trigger threshold values
            triggered => triggered_xc,
            xcorr_calc => xcorr_calc
        );
        
    cfd: Configurable_CFD
        port map (
            clock => clk,  
            reset => reset, 
            enable => enable, 
            trigger_threshold => triggered_xc, 
            config_delay => "11010", 
            config_sign => '0', 
            din => std_logic_vector(xcorr_calc), 
            trigger => trigger_output
        );
        
    enable_proc: process(enable, x_i, lpf_out, hpf_out)
    begin
        case(enable) is
            when '0' =>
                resta_out <= x_i;
                suma_out <= hpf_out;
            when '1' =>
                resta_out <= (x_i - lpf_out);
                suma_out <= (hpf_out + lpf_out);
            when others => 
                resta_out <= (others => 'X');
                suma_out <= (others => 'X');
        end case;
    end process enable_proc;    
    
    invert_enable_proc: process(invert_enable, hpf_out, lpf_out)
    begin
        case(invert_enable) is
            when '0' =>
                hpf_out_aux <= hpf_out;
                hpf_out_xcorr <= (not(hpf_out) + to_signed(1,16));
                baseline_aux <= lpf_out;
            when '1' =>
                hpf_out_aux <= (not(hpf_out) + to_signed(1,16));
                hpf_out_xcorr <= hpf_out;
                baseline_aux <= (to_signed(16384,16) - lpf_out);
            when others =>
                hpf_out_aux <= (others => '0');
                hpf_out_xcorr <= (others => '0');
                baseline_aux <= (others => 'X');
        end case;
    end process invert_enable_proc;
    
    output_selector_proc: process(output_selector, suma_out, baseline_aux, hpf_out_aux, lpf_out, xcorr_calc, x_i)
    begin
        case(output_selector) is
            when "00" =>
                w_out <= suma_out;
--                tm_output_selector <= '0';
            when "01" =>
                w_out <= (baseline_aux + hpf_out_aux);
--                tm_output_selector <= '0';
            when "10" =>
                w_out <= (lpf_out + xcorr_calc(15 downto 0));
--                tm_output_selector <= '1';
            when "11" =>
                w_out <= x_i;
--                tm_output_selector <= '0';
            when others =>
                w_out <= (others => 'X');
--                tm_output_selector <= (others => 'X');
        end case;
    end process output_selector_proc;
    
    -- assignments with inputs and outputs
    x_i <= signed(x);
    y1 <= std_logic_vector(w_out);
    y2 <= std_logic_vector(hpf_out_xcorr);
    baseline <= std_logic_vector(baseline_aux);
    internal_afe_comp_enable <= (enable AND afe_comp_enable);    

end hpf_pedestal_recovery_filter_trigger_arch;