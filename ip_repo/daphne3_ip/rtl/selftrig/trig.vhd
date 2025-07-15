-- trig.vhd
-- an EXAMPLE of a very SIMPLE trigger algorithm for the DAPHNE3/DAPHNE_MEZZ self triggered mode
--
-- baseline, threshold, din are UNSIGNED 
--
-- In this EXAMPLE the trigger algorithm is VERY simple and requires only a few clock cycles
-- however, this module ADDS extra pipeline stages so that the overall latency 
-- is 64 clocks. this is done to allow for more advanced triggers. If a more advanced trigger
-- is used in place of this module, the overall latency MUST match this module, since the 
-- rest of the self-triggered sender logic depends on it. This module assumes that the pulse is 
-- POSITIVE going. So the trigger threshold specifies the number of counts ABOVE the calculated
-- baseline. the trigger condition is "rising edge" detection: 1 sample BELOW the threshold
-- followed by one sample ABOVE the threshold.

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

library unisim;
use unisim.vcomponents.all;

entity trig is
port(
    clock: in std_logic;
    din: in std_logic_vector(13 downto 0); -- raw AFE data aligned to clock
    ts: in std_logic_vector(63 downto 0); -- timestamp
    threshold: in std_logic_vector(9 downto 0); -- counts relative to the baseline
    baseline: in std_logic_vector(13 downto 0); -- average signal level computed over past N samples
    trig_sample_dat: out std_logic_vector(13 downto 0); -- the sample that caused the trigger
    trig_sample_ts:  out std_logic_vector(63 downto 0); -- the timestamp of the sample that caused the trigger
    trig: out std_logic -- trigger pulse (after latency delay)
);
end trig;

architecture trig_arch of trig is

    signal current_sample: std_logic_vector(13 downto 0) := (others=>'0');
    signal prev_sample: std_logic_vector(13 downto 0) := (others=>'1');
    signal trig_thresh, trig_sample_reg: std_logic_vector(13 downto 0) := (others=>'0');
    signal ts_reg, ts2_reg, trig_ts_reg: std_logic_vector(63 downto 0) := (others=>'0');
    signal triggered_i: std_logic := '0';
    signal triggered_dly32_i: std_logic := '0';

begin

    trig_pipeline_proc: process(clock)
    begin
        if rising_edge(clock) then
            current_sample <= din;
            prev_sample <= current_sample; 
            ts_reg <= ts;
            ts2_reg <= ts_reg;
        end if;
    end process trig_pipeline_proc;

    -- user-specified threshold is RELATIVE to the calculated average baseline level
    -- NOTE that the trigger pulse is POSITIVE going! We want to ADD the relative 
    -- threshold from the calculated average baseline level.

    trig_thresh <= std_logic_vector( unsigned(baseline) + unsigned(threshold) );

    -- For this EXAMPLE our super simple basic trigger condition is this "rising edge":
    -- current_sample ABOVE trig_thresh
    -- prev_sample BELOW trig_thresh

    triggered_i <= '1' when ( current_sample>trig_thresh and prev_sample<trig_thresh ) else '0';

    -- add in some fake/synthetic latency, adjust it so total trigger latency is 64 clocks

    srlc32e_0_inst : srlc32e
    port map(
        clk => clock,
        ce  => '1',
        a   => "11111",
        d   => triggered_i,
        q   => open,
        q31 => triggered_dly32_i
    );

    srlc32e_1_inst : srlc32e
    port map(
        clk => clock,
        ce  => '1',
        a   => "11111",
        d   => triggered_dly32_i,
        q   => open,
        q31 => trig
    );

    -- store the sample and timestamp that caused the trigger 

    samplecap_proc: process(clock)
    begin
        if rising_edge(clock) then
            if (triggered_i='1') then
                trig_sample_reg <= current_sample;
                trig_ts_reg     <= ts_reg;
            end if;
        end if;    
    end process samplecap_proc;

    trig_sample_dat <= trig_sample_reg;
    trig_sample_ts  <= trig_ts_reg;

end trig_arch;