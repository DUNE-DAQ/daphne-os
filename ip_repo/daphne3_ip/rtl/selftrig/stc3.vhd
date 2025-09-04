-- stc3.vhd
-- self triggered channel machine for ONE DAPHNE channel
--
-- updated again: the backend FIFO returns! The merge logic has been removed from
-- Adam's 10G sender and is now under control in the DAPHNE core logic.
-- 
-- This module watches one channel data bus and computes the average signal level 
-- (baseline.vhd) based on the last N samples. When it detects a trigger condition
-- (defined in trig.vhd) it then begins assemblying the output frame in the output FIFO.
-- The output FIFO is UltraRAM based and is a single clock domain.

-- the trigger module provided here is very basic and is intended as a placeholder
-- to simulate a more advanced trigger which has a total latency of 64 clock cycles.

-- Jamieson Olsen <jamieson@fnal.gov>

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

library unisim;
use unisim.vcomponents.all;

library xpm;
use xpm.vcomponents.all;

entity stc3 is
-- generic( baseline_runlength: integer := 256 ); -- options 32, 64, 128, or 256
port(
    link_id: std_logic_vector(5 downto 0);
    ch_id: std_logic_vector(7 downto 0);
    version: std_logic_vector(3 downto 0);
    slot_id: std_logic_vector(3 downto 0);
    crate_id: std_logic_vector(9 downto 0);
    detector_id: std_logic_vector(5 downto 0);
    version_id: std_logic_vector(5 downto 0);
    -- threshold: std_logic_vector(9 downto 0); -- counts relative calculated avg baseline

    clock: in std_logic; -- master clock 62.5MHz
    reset: in std_logic;
    enable: in std_logic;
    adhoc: in std_logic_vector(7 downto 0); -- command for adhoc trigger
    st_config: in std_logic_vector(13 downto 0); -- Config param for Self-Trigger and Local Primitive Calculation, CIEMAT (Nacho)
    signal_delay: in std_logic_vector(4 downto 0);
    threshold_xc: in std_logic_vector(41 downto 0); -- cross correlation trigger threshold 
    filter_output_selector: in std_logic_vector(1 downto 0); --Esteban
    ti_trigger: in std_logic_vector(7 downto 0); -------------------------
    ti_trigger_stbr: in std_logic;  -------------------------
    reset_st_counters: in std_logic;
    forcetrig: in std_logic; -- force a trigger
    timestamp: in std_logic_vector(63 downto 0);
	din: in std_logic_vector(13 downto 0); -- aligned AFE data
    afe_comp_enable: in std_logic;
    invert_enable: in std_logic;
    st_afe_dat_filtered: out std_logic_vector(13 downto 0); -- aligned AFE data filtered
    trigger_signal: out std_logic;
    ready: out std_logic; -- i have something!
    rd_en: in std_logic; -- output FIFO read enable
    dout: out std_logic_vector(71 downto 0); -- output FIFO data
    TCount: out std_logic_vector(63 downto 0);
    PCount: out std_logic_vector(63 downto 0)
);
end stc3;

architecture stc3_arch of stc3 is

type array_10x14_type is array(9 downto 0) of std_logic_vector(13 downto 0);
signal din_delay: array_10x14_type;

signal R0, R1, R2, R3, R4, R5: std_logic_vector(13 downto 0);
signal block_count: integer range 0 to 31 := 0;

type state_type is (rst, wait4trig, w0, w1, w2, w3, h0, h1, h2, h3, h4, h5, h6, h7, h8, 
                    d0, d1, d2, d3, d4, d5, d6, d7, d8, d9, d10, d11, d12, d13, d14, d15, 
                    d16, d17, d18, d19, d20, d21, d22, d23, d24, d25, d26, d27, d28, d29, d30, d31);
signal state: state_type;

type trigger_counter_state_type is (rst_trggr, wait4trig_trggr, rising_triggered);
signal trigger_counter_state: trigger_counter_state_type;

signal trig_sample_ts, sample0_ts: std_logic_vector(63 downto 0) := (others=>'0');
signal calculated_baseline, trig_sample_dat: std_logic_vector(13 downto 0) := (others=>'0');
signal triggered, forcetrig_reg: std_logic := '0';
signal FIFO_din: std_logic_vector(71 downto 0) := (others=>'0');
signal FIFO_wr_en, FIFO_sleep: std_logic := '0';
signal marker: std_logic_vector(7 downto 0) := X"00";
signal prog_empty: std_logic;
signal fifo_word_count: std_logic_vector(12 downto 0);

signal triggered_bicocca: std_logic := '0';
signal afe_dat_filtered: std_logic_vector(13 downto 0);
signal afe_dat_filtered_TP: std_logic_vector(13 downto 0);
signal trigCount: unsigned(63 downto 0) := (others => '0');
signal packCount: unsigned(63 downto 0) := (others => '0');

signal Data_Available_aux: std_logic; -- ACTIVE HIGH when Frame Finite State Machine is in WaitingFor Trig MODE
signal Match_TP_With_FRAME: std_logic; -- ACTIVE HIGH when LOCAL primitives are calculated
signal Time_Peak_aux: std_logic_vector(8 downto 0); -- Time in Samples to achieve de Max peak
signal Time_Pulse_UB_aux: std_logic_vector(8 downto 0); -- Time in Samples of the light pulse signal is UNDER BASELINE (without undershoot)
signal Time_Pulse_OB_aux: std_logic_vector(9 downto 0); -- Time in Samples of the light pulse signal is OVER BASELINE (undershoot)
signal Max_Peak_aux: std_logic_vector(13 downto 0); -- Amplitude in ADC counts od the peak
signal Charge_aux: std_logic_vector(22 downto 0); -- Charge of the light pulse (without undershoot) in ADC*samples
signal Number_Peaks_UB_aux: std_logic_vector(3 downto 0); -- Number of peaks detected when signal is UNDER BASELINE (without undershoot).  
signal Number_Peaks_OB_aux: std_logic_vector(3 downto 0); -- Number of peaks detected when signal is OVER BASELINE (undershoot).  
signal Amplitude_aux: std_logic_vector(14 downto 0); -- Real Time calculated AMPLITUDE
signal Peak_Current_aux: std_logic; -- ACTIVE HIGH when a peak is detected
signal Slope_Current_aux: std_logic_vector(13 downto 0); -- Real Time calculated SLOPE
signal Slope_Threshold_aux: std_logic_vector(6 downto 0); -- Threshold over the slope to detect Peaks
signal Detection_aux: std_logic; -- ACTIVE HIGH when primitives are being calculated (during light pulse)
signal Sending_aux: std_logic; -- ACTIVE HIGH when colecting data for self-trigger frame
signal Info_Previous_aux: std_logic; -- ACTIVE HIGH when self-trigger is produced by a waveform between two frames 
signal Data_Available_Trailer_aux: std_logic; -- ACTIVE HIGH when metadata is ready
signal Trailer_Word_0_aux: std_logic_vector(31 downto 0); -- TRAILER WORD with metada (Local Trigger Primitives)
signal Trailer_Word_1_aux: std_logic_vector(31 downto 0); -- TRAILER WORD with metada (Local Trigger Primitives)
signal Trailer_Word_2_aux: std_logic_vector(31 downto 0); -- TRAILER WORD with metada (Local Trigger Primitives)
signal Trailer_Word_3_aux: std_logic_vector(31 downto 0); -- TRAILER WORD with metada (Local Trigger Primitives)
signal Trailer_Word_4_aux: std_logic_vector(31 downto 0); -- TRAILER WORD with metada (Local Trigger Primitives)
signal Trailer_Word_5_aux: std_logic_vector(31 downto 0); -- TRAILER WORD with metada (Local Trigger Primitives)
signal Trailer_Word_6_aux: std_logic_vector(31 downto 0); -- TRAILER WORD with metada (Local Trigger Primitives)
signal Trailer_Word_7_aux: std_logic_vector(31 downto 0); -- TRAILER WORD with metada (Local Trigger Primitives)
signal Trailer_Word_8_aux: std_logic_vector(31 downto 0); -- TRAILER WORD with metada (Local Trigger Primitives)
signal Trailer_Word_9_aux: std_logic_vector(31 downto 0); -- TRAILER WORD with metada (Local Trigger Primitives)
signal Trailer_Word_10_aux: std_logic_vector(31 downto 0); -- TRAILER WORD with metada (Local Trigger Primitives)
signal Trailer_Word_11_aux: std_logic_vector(31 downto 0); -- TRAILER WORD with metada (Local Trigger Primitives)
signal Trailer_Word_0_reg: std_logic_vector(31 downto 0); -- TRAILER WORD with metada (Local Trigger Primitives) REGISTER
signal Trailer_Word_1_reg: std_logic_vector(31 downto 0); -- TRAILER WORD with metada (Local Trigger Primitives) REGISTER
signal Trailer_Word_2_reg: std_logic_vector(31 downto 0); -- TRAILER WORD with metada (Local Trigger Primitives) REGISTER
signal Trailer_Word_3_reg: std_logic_vector(31 downto 0); -- TRAILER WORD with metada (Local Trigger Primitives) REGISTER
signal Trailer_Word_4_reg: std_logic_vector(31 downto 0); -- TRAILER WORD with metada (Local Trigger Primitives) REGISTER
signal Trailer_Word_5_reg: std_logic_vector(31 downto 0); -- TRAILER WORD with metada (Local Trigger Primitives) REGISTER
signal Trailer_Word_6_reg: std_logic_vector(31 downto 0); -- TRAILER WORD with metada (Local Trigger Primitives) REGISTER
signal Trailer_Word_7_reg: std_logic_vector(31 downto 0); -- TRAILER WORD with metada (Local Trigger Primitives) REGISTER
signal Trailer_Word_8_reg: std_logic_vector(31 downto 0); -- TRAILER WORD with metada (Local Trigger Primitives) REGISTER
signal Trailer_Word_9_reg: std_logic_vector(31 downto 0); -- TRAILER WORD with metada (Local Trigger Primitives) REGISTER
signal Trailer_Word_10_reg: std_logic_vector(31 downto 0); -- TRAILER WORD with metada (Local Trigger Primitives) REGISTER
signal Trailer_Word_11_reg: std_logic_vector(31 downto 0); -- TRAILER WORD with metada (Local Trigger Primitives) REGISTER    

-- component baseline
-- generic( baseline_runlength: integer := 256 );
-- port(
--     clock: in std_logic;
--     reset: in std_logic;
--     din: in std_logic_vector(13 downto 0);
--     bline: out std_logic_vector(13 downto 0));
-- end component;

-- component trig
-- port(
--     clock: in std_logic;
--     din: in std_logic_vector(13 downto 0);
--     ts: in std_logic_vector(63 downto 0);
--     baseline: in std_logic_vector(13 downto 0);
--     threshold: in std_logic_vector(9 downto 0);
--     trig: out std_logic;
--     trig_sample_dat: out std_logic_vector(13 downto 0);
--     trig_sample_ts: out std_logic_vector(63 downto 0)
-- );
-- end component;

component trig_xc
port(
    clock: in std_logic;
    reset: in std_logic; 
    din: in std_logic_vector(13 downto 0); -- raw AFE data aligned to clock
    enable: in std_logic;
    afe_comp_enable: in std_logic;
    invert_enable: in std_logic;
    adhoc: in std_logic_vector(7 downto 0); -- command value for adhoc trigger
    filter_output_selector: in std_logic_vector(1 downto 0);
    ti_trigger: in std_logic_vector(7 downto 0); -- adhoc trigger signals
    ti_trigger_stbr: in std_logic; -- adhoc trigger signals
    threshold_xc: in std_logic_vector(41 downto 0); -- trigger threshold relative to cross correlation value
    ts: in std_logic_vector(63 downto 0); -- timestamp
    baseline: out std_logic_vector(13 downto 0); -- baseline 300mHz LPF output
    dout1: out std_logic_vector(13 downto 0); -- Filtered AFE data: selected data. To see filter process
    dout2: out std_logic_vector(13 downto 0); -- Filtered AFE data: movmean data. To use with Nacho's module 
    trig_sample_dat: out std_logic_vector(13 downto 0); -- the sample that caused the trigger
    trig_sample_ts:  out std_logic_vector(63 downto 0); -- the timestamp of the sample that caused the trigger
    trig: out std_logic -- trigger pulse (after latency delay)
);
end component;

component Self_Trigger_Primitive_Calculation 
port (
    clock                           : in std_logic;                                                 -- AFE clock
    reset                           : in std_logic;                                                 -- Reset signal. ACTIVE HIGH
    din                             : in std_logic_vector(13 downto 0);                             -- Data coming from the Filter Block / Raw data from AFEs
    Config_Param                    : in std_logic_vector(13 downto 0);                             -- Configure parameters for filtering & self-trigger bloks
    Ext_Self_Trigger                : in std_logic;                                                 -- External Self-Trigger coming from another block
    Match_with_Frame                : in std_logic;                                                 -- External signal that allows being matched with the frame construction.
    Self_Trigger                    : out std_logic;                                                -- Self-Trigger signal comming from the Self-Trigger block
    Data_Available                  : out std_logic;                                                -- ACTIVE HIGH when LOCAL primitives are calculated
    Time_Peak                       : out std_logic_vector(8 downto 0);                             -- Time in Samples to achieve de Max peak
    Time_Over_Baseline              : out std_logic_vector(8 downto 0);                             -- Time in Samples of the light pulse signal is UNDER BASELINE (without undershoot)
    Time_Start                      : out std_logic_vector(9 downto 0);                             -- Time in Samples of the light pulse signal is OVER BASELINE (undershoot)
    ADC_Peak                        : out std_logic_vector(13 downto 0);                            -- Amplitude in ADC counts od the peak
    ADC_Integral                    : out std_logic_vector(22 downto 0);                            -- Charge of the light pulse (without undershoot) in ADC*samples
    Number_Peaks                    : out std_logic_vector(3 downto 0);                             -- Number of peaks detected when signal is UNDER BASELINE (without undershoot).  
    Baseline                        : in std_logic_vector(13 downto 0);                             -- Real Time calculated BASELINE
    Amplitude                       : out std_logic_vector(14 downto 0);                            -- Real Time calculated AMPLITUDE
    Peak_Current                    : out std_logic;                                                -- ACTIVE HIGH when a peak is detected
    Slope_Current                   : out std_logic_vector(13 downto 0);                            -- Real Time calculated SLOPE
    Slope_Threshold                 : out std_logic_vector(6 downto 0);                             -- Threshold over the slope to detect Peaks
    Detection                       : out std_logic;                                                -- ACTIVE HIGH when primitives are being calculated (during light pulse)
    Sending                         : out std_logic;                                                -- ACTIVE HIGH when colecting data for self-trigger frame
    Info_Previous                   : out std_logic;                                                -- ACTIVE HIGH when self-trigger is produced by a waveform between two frames 
    Data_Available_Trailer          : out std_logic;                                                -- ACTIVE HIGH when metadata is ready
    Trailer_Word_0                  : out std_logic_vector(31 downto 0);                            -- TRAILER WORD with metada (Local Trigger Primitives)
    Trailer_Word_1                  : out std_logic_vector(31 downto 0);                            -- TRAILER WORD with metada (Local Trigger Primitives)
    Trailer_Word_2                  : out std_logic_vector(31 downto 0);                            -- TRAILER WORD with metada (Local Trigger Primitives)
    Trailer_Word_3                  : out std_logic_vector(31 downto 0);                            -- TRAILER WORD with metada (Local Trigger Primitives)
    Trailer_Word_4                  : out std_logic_vector(31 downto 0);                            -- TRAILER WORD with metada (Local Trigger Primitives)
    Trailer_Word_5                  : out std_logic_vector(31 downto 0);                            -- TRAILER WORD with metada (Local Trigger Primitives)
    Trailer_Word_6                  : out std_logic_vector(31 downto 0);                            -- TRAILER WORD with metada (Local Trigger Primitives)
    Trailer_Word_7                  : out std_logic_vector(31 downto 0);                            -- TRAILER WORD with metada (Local Trigger Primitives)
    Trailer_Word_8                  : out std_logic_vector(31 downto 0);                            -- TRAILER WORD with metada (Local Trigger Primitives)
    Trailer_Word_9                  : out std_logic_vector(31 downto 0);                            -- TRAILER WORD with metada (Local Trigger Primitives)
    Trailer_Word_10                 : out std_logic_vector(31 downto 0);                            -- TRAILER WORD with metada (Local Trigger Primitives)
    Trailer_Word_11                 : out std_logic_vector(31 downto 0)                             -- TRAILER WORD with metada (Local Trigger Primitives)
);
end component;

begin

-- assume trigger latency is 192 clocks
-- + 64 pre-trigger samples = total delay is ~256 clocks
-- use 32 bit shift register primitives (srlc32e) for this

din_delay(0) <= din;

gen_delay_bit: for b in 13 downto 0 generate
    gen_delay_srlc: for s in 7 downto 0 generate

        srlc32e_0_inst : srlc32e
        port map(
            clk => clock,
            ce => '1',
            a => signal_delay,
            d => din_delay(s)(b),
            q => open,
            q31 => din_delay(s+1)(b) -- fixed delay 32
        );

    end generate gen_delay_srlc;
end generate gen_delay_bit;

-- din_delay(0) = din live no delay
-- din_delay(1) = din delayed by 32 clocks
-- din_delay(2) = din delayed by 64 clocks
-- din_delay(3) = din delayed by 96 clocks
-- din_delay(4) = din delayed by 128 clocks
-- din_delay(5) = din delayed by 160 clocks
-- din_delay(6) = din delayed by 192 clocks
-- din_delay(7) = din delayed by 224 clocks
-- din_delay(8) = din delayed by 256 clocks

-- the last delay segment needs to be fine tuned to line up with FSM d* states

gen_delay2_bit: for b in 13 downto 0 generate

    last_srlc32e_inst : srlc32e
    port map(
        clk => clock,
        ce => '1',
        a => "01001", -- fine tune this delay 
        d => din_delay(8)(b),
        q => din_delay(9)(b),
        q31 => open
    );

end generate gen_delay2_bit;

-- now compute the average signal baseline level over the last N samples

-- baseline_inst: baseline
-- generic map ( baseline_runlength => baseline_runlength ) -- must be 32, 64, 128, or 256
-- port map(
--     clock => clock,
--     reset => reset,
--     din => din_delay(0), -- this looks at LIVE AFE data, not the delayed data
--     bline => calculated_baseline
-- );

-- trig may be an async signal, clean it up here

trig_proc: process(clock)
begin
    if rising_edge(clock) then
        forcetrig_reg <= forcetrig;
    end if;
end process trig_proc;        

-- trig_inst: trig
-- port map(
--      clock => clock,
--      din => din_delay(0), -- watching live AFE data
--      ts => timestamp,
--      baseline => calculated_baseline,
--      threshold => threshold,
--      trig => triggered,
--      trig_sample_dat => trig_sample_dat, 
--      trig_sample_ts => trig_sample_ts 
-- );        

bicocca_eia_trig_inst: trig_xc
port map(
    clock => clock,
    reset => reset, 
    din => din_delay(0), -- watching live AFE data
    enable => enable,
    afe_comp_enable => afe_comp_enable,
    invert_enable => invert_enable,
    adhoc => adhoc,
    filter_output_selector => filter_output_selector,
    ti_trigger => ti_trigger,
    ti_trigger_stbr => ti_trigger_stbr,
    threshold_xc => threshold_xc, -- cross correlatio trigger threshold  
    ts => timestamp,
    baseline => calculated_baseline,
    dout1 => afe_dat_filtered,
    dout2 => afe_dat_filtered_TP,
    trig_sample_dat => trig_sample_dat, 
    trig_sample_ts => trig_sample_ts,
    trig => triggered_bicocca
);

-- assign trigger signal
triggered <= triggered_bicocca;

------------------- SELF-TRIGGER AND LOCAL PRIMITIVE CALCULATION DEVELOPED AT CIEMAT -------------------
-- reset_ciemat <= '1' when (reset='1' or state=wait4trig) else '0';
ciemat_trig_inst: Self_Trigger_Primitive_Calculation
port map (
    clock                           => clock,                                           -- AFE clock
    reset                           => reset,                                           -- Reset signal. ACTIVE HIGH
    din                             => afe_dat_filtered_TP,                             -- Data coming from the Filter Block / Raw data from AFEs
    Config_Param                    => st_config,                                       -- Configure parameters for filtering & self-trigger bloks
    Ext_Self_Trigger                => triggered_bicocca,                               -- External Self-Trigger coming from another block
    Match_with_Frame                => Match_TP_With_FRAME,                             -- External signal that allows being matched with the frame construction.
    Self_Trigger                    => open,                                            -- Self-Trigger signal comming from the Self-Trigger block
    Data_Available                  => open,                                            -- ACTIVE HIGH when LOCAL primitives are calculated
    Time_Peak                       => open,                                            -- Time in Samples to achieve de Max peak
    Time_Over_Baseline              => open,                                            -- Time in Samples of the light pulse signal is UNDER BASELINE (without undershoot)
    Time_Start                      => open,                                            -- Time in Samples of the light pulse signal is OVER BASELINE (undershoot)
    ADC_Peak                        => open,                                            -- Amplitude in ADC counts od the peak
    ADC_Integral                    => open,                                            -- Charge of the light pulse (without undershoot) in ADC*samples
    Number_Peaks                    => open,                                            -- Number of peaks detected when signal is UNDER BASELINE (without undershoot).  
    Baseline                        => calculated_baseline,                             -- Real Time calculated BASELINE
    Amplitude                       => open,                                            -- Real Time calculated AMPLITUDE
    Peak_Current                    => open,                                            -- ACTIVE HIGH when a peak is detected
    Slope_Current                   => open,                                            -- Real Time calculated SLOPE
    Slope_Threshold                 => open,                                            -- Threshold over the slope to detect Peaks
    Detection                       => open,                                            -- ACTIVE HIGH when primitives are being calculated (during light pulse)
    Sending                         => open,                                            -- ACTIVE HIGH when colecting data for self-trigger frame
    Info_Previous                   => Info_Previous_aux,                               -- ACTIVE HIGH when self-trigger is produced by a waveform between two frames 
    Data_Available_Trailer          => Data_Available_Trailer_aux,                      -- ACTIVE HIGH when metadata is ready
    Trailer_Word_0                  => Trailer_Word_0_aux,                              -- TRAILER WORD with metada (Local Trigger Primitives)
    Trailer_Word_1                  => Trailer_Word_1_aux,                              -- TRAILER WORD with metada (Local Trigger Primitives)
    Trailer_Word_2                  => Trailer_Word_2_aux,                              -- TRAILER WORD with metada (Local Trigger Primitives)
    Trailer_Word_3                  => Trailer_Word_3_aux,                              -- TRAILER WORD with metada (Local Trigger Primitives)
    Trailer_Word_4                  => Trailer_Word_4_aux,                              -- TRAILER WORD with metada (Local Trigger Primitives)
    Trailer_Word_5                  => Trailer_Word_5_aux,                              -- TRAILER WORD with metada (Local Trigger Primitives)
    Trailer_Word_6                  => Trailer_Word_6_aux,                              -- TRAILER WORD with metada (Local Trigger Primitives)
    Trailer_Word_7                  => Trailer_Word_7_aux,                              -- TRAILER WORD with metada (Local Trigger Primitives)
    Trailer_Word_8                  => Trailer_Word_8_aux,                              -- TRAILER WORD with metada (Local Trigger Primitives)
    Trailer_Word_9                  => Trailer_Word_9_aux,                              -- TRAILER WORD with metada (Local Trigger Primitives)
    Trailer_Word_10                 => Trailer_Word_10_aux,                             -- TRAILER WORD with metada (Local Trigger Primitives)
    Trailer_Word_11                 => Trailer_Word_11_aux                              -- TRAILER WORD with metada (Local Trigger Primitives)
);
-- prepare data for data format
Local_primitives_frame: process(clock, reset, Data_Available_Trailer_aux)
begin 
    if rising_edge(clock) then
        if (reset='1') then
            Trailer_Word_0_reg <= (others => '0');
            Trailer_Word_1_reg <= (others => '0');
            Trailer_Word_2_reg <= (others => '0');
            Trailer_Word_3_reg <= (others => '0');
            Trailer_Word_4_reg <= (others => '0');
            Trailer_Word_5_reg <= (others => '0');
            Trailer_Word_6_reg <= (others => '0');
            Trailer_Word_7_reg <= (others => '0');
            Trailer_Word_8_reg <= (others => '0');
            Trailer_Word_9_reg <= (others => '0');
            Trailer_Word_10_reg <= (others => '0');
            Trailer_Word_11_reg <= (others => '0');
        elsif (Data_Available_Trailer_aux='1') then
            Trailer_Word_0_reg <= Trailer_Word_0_aux;
            Trailer_Word_1_reg <= Trailer_Word_1_aux;
            Trailer_Word_2_reg <= Trailer_Word_2_aux;
            Trailer_Word_3_reg <= Trailer_Word_3_aux;
            Trailer_Word_4_reg <= Trailer_Word_4_aux;
            Trailer_Word_5_reg <= Trailer_Word_5_aux;
            Trailer_Word_6_reg <= Trailer_Word_6_aux;
            Trailer_Word_7_reg <= Trailer_Word_7_aux;
            Trailer_Word_8_reg <= Trailer_Word_8_aux;
            Trailer_Word_9_reg <= Trailer_Word_9_aux;
            Trailer_Word_10_reg <= Trailer_Word_10_aux;
            Trailer_Word_11_reg <= Trailer_Word_11_aux;
        end if;
    end if;
end process Local_primitives_frame;

Match_Process: process(reset, state)
begin 
    if (reset='1') then
        Match_TP_With_FRAME <= '0';
    else
        if (state=wait4trig) then
            Match_TP_With_FRAME <= '1';
        else
            Match_TP_With_FRAME <= '0';
        end if;
    end if;
end process Match_Process;

count_proc: process(clock)
begin
    if rising_edge(clock) then
        if ( reset='1' or reset_st_counters='1' or enable='0') then
            trigCount <= (others => '0');
            trigger_counter_state <= rst_trggr;
        else
            case(trigger_counter_state) is
                when rst_trggr =>
                    trigger_counter_state <= wait4trig_trggr;
                when wait4trig_trggr =>
                    if ( triggered='1') then
                        trigCount <= trigCount + 1;
                        trigger_counter_state <= rising_triggered;
                    else
                        trigger_counter_state <= wait4trig_trggr;
                    end if;
                when rising_triggered =>
                    if ( triggered='1') then
                        trigger_counter_state <= rising_triggered;
                    else
                        trigger_counter_state <= wait4trig_trggr;
                    end if;
                when others =>
                    trigger_counter_state <= rst_trggr;
                end case; 
        end if;
    end if;
end process count_proc;


-- for dense data packing 14 bit samples into 64 bit words,
-- we need to access up to last 6 samples at once...

pack_proc: process(clock)
begin
    if rising_edge(clock) then
        R0 <= din_delay(9);
        R1 <= R0;
        R2 <= R1;
        R3 <= R2;
        R4 <= R3;
        R5 <= R4;
    end if;
end process pack_proc;    

-- big FSM waits for trigger condition then dense pack assembly of the output frame 
-- as it is being written to the output FIFO *IN ORDER* (there is no "jumping back" to update
-- the header!)

-- one BLOCK = 32 14-bit samples DENSE PACKED into 7 64-bit words
-- one SUPERBLOCK = 32 blocks = 1024 samples = 224 64 bit words

-- sample0 is the first sample packed into the output record
-- sample0...sample63 = pretrigger
-- sample64 = trigger sample
-- sample65...sample1023 = post trigger
-- the timestamp value recorded in the output record corresponds to sample0 NOT the trigger sample!

builder_fsm_proc: process(clock)
begin
    if rising_edge(clock) then
        if (reset='1' or reset_st_counters='1') then
            state <= rst;
            packCount <= (others => '0');
        else
            case(state) is
                when rst =>
                    state <= wait4trig;
                when wait4trig => 
                    if ((triggered='1' or forcetrig_reg='1') and enable='1') then -- start packing
                        block_count <= 0;
                        packCount <= packCount + 1;
                        state <= w0; 
                    else
                        state <= wait4trig;
                    end if;

                when w0 => state <= w1; -- a few wait states while the FIFO wakes up from sleep mode...
                when w1 => state <= w2;
                when w2 => state <= w3;
                when w3 => state <= h0;                   

                -- begin assembly of output record 
                -- the output buffer is a FIFO so this MUST be done IN ORDER!

                when h0 => state <= h1; -- header words
                when h1 => state <= h2;
                when h2 => state <= h3;
                when h3 => state <= h4;
                when h4 => state <= h5;
                when h5 => state <= h6;
                when h6 => state <= h7;
                when h7 => state <= h8;
                when h8 => state <= d0;

                when d0 => state <= d1; -- begin dense pack data block
                when d1 => state <= d2;
                when d2 => state <= d3;
                when d3 => state <= d4;
                when d4 => state <= d5; 
                when d5 => state <= d6;
                when d6 => state <= d7;
                when d7 => state <= d8;
                when d8 => state <= d9; 
                when d9 => state <= d10;
                when d10 => state <= d11;
                when d11 => state <= d12;
                when d12 => state <= d13;
                when d13 => state <= d14; 
                when d14 => state <= d15;
                when d15 => state <= d16;
                when d16 => state <= d17;
                when d17 => state <= d18; 
                when d18 => state <= d19;
                when d19 => state <= d20;
                when d20 => state <= d21;
                when d21 => state <= d22;
                when d22 => state <= d23;
                when d23 => state <= d24;
                when d24 => state <= d25;
                when d25 => state <= d26;
                when d26 => state <= d27;
                when d27 => state <= d28;
                when d28 => state <= d29;
                when d29 => state <= d30;
                when d30 => state <= d31;

                when d31 =>
                    if (block_count=31) then -- done with packing data samples, return to idle
                        state <= wait4trig;
                    else
                        block_count <= block_count + 1;
                        state <= d0;
                    end if;

                when others => 
                    state <= rst;
            end case;
        end if;
    end if;
end process builder_fsm_proc;

-- the timestamp encoded in the output record header corresponds to sample0, NOT the trigger sample!
-- since there are 64 pre-trigger samples, this difference is fixed at ~64.

sample0_ts <= std_logic_vector( unsigned(trig_sample_ts) - 64 );

-- the upper byte of the FIFO is used for a marker to indicate the first and last words of the 
-- output record. this is done to make the next stage selector logic easier.

marker <= X"BE" when (state=h1) else  -- mark first word
          X"ED" when (state=d27 and block_count=31) else -- mark the last word
          X"00";

-- mux to determine what is written into the output FIFO, note this is 72 bits to match ultraram bus
-- this output FIFO is deep enough to hold MANY output records.

FIFO_din <= --marker & X"00000000" & link_id & slot_id & crate_id & detector_id & version_id when (state=h0) else
            marker & sample0_ts when (state=h1) else -- timestamp of sample0 (NOT the trigger sample!)
            marker & ch_id(7 downto 0) & version(3 downto 0) & "000000" & calculated_baseline(13 downto 0) & "00" & threshold_xc(13 downto 0) & "00" & trig_sample_dat(13 downto 0) when (state=h2) else
            -- marker & X"000000000000" & "000" & fifo_word_count when (state=h3) else -- report how many words are currently in the FIFO
            marker & Trailer_Word_1_reg(31 downto 0) & Trailer_Word_0_reg(31 downto 0) when (state=h3) else -- reserved for header 3 (trigger primitives)
            marker & Trailer_Word_3_reg(31 downto 0) & Trailer_Word_2_reg(31 downto 0) when (state=h4) else -- reserved for header 4 (trigger primitives)
            marker & Trailer_Word_5_reg(31 downto 0) & Trailer_Word_4_reg(31 downto 0) when (state=h5) else -- reserved for header 5 (trigger primitives)
            marker & Trailer_Word_7_reg(31 downto 0) & Trailer_Word_6_reg(31 downto 0) when (state=h6) else -- reserved for header 6 (trigger primitives)
            marker & Trailer_Word_9_reg(31 downto 0) & Trailer_Word_8_reg(31 downto 0) when (state=h7) else -- reserved for header 7 (trigger primitives)
            marker & Trailer_Word_11_reg(31 downto 0) & Trailer_Word_10_reg(31 downto 0) when (state=h8) else -- reserved for header 8 (trigger primitives)
            marker & R0(7 downto 0) & R1 & R2 & R3 & R4                    when (state=d0) else -- sample4l ... sample0
            marker & R0(1 downto 0) & R1 & R2 & R3 & R4 & R5(13 downto 8)  when (state=d5) else -- sample9l ... sample4h
            marker & R0(9 downto 0) & R1 & R2 & R3 & R4(13 downto 2)       when (state=d9) else -- sample13l ... sample9h
            marker & R0(3 downto 0) & R1 & R2 & R3 & R4 & R5(13 downto 10) when (state=d14) else -- sample18l ... sample13h
            marker & R0(11 downto 0) & R1 & R2 & R3 & R4(13 downto 4)      when (state=d18) else -- sample22l ... sample18h
            marker & R0(5 downto 0) & R1 & R2 & R3 & R4 & R5(13 downto 12) when (state=d23) else -- sample27l ... sample22h
            marker & R0 & R1 & R2 & R3 & R4(13 downto 6)                   when (state=d27) else -- sample31 ... sample27h
            X"000000000000000000";

-- output FIFO write enable

FIFO_wr_en <= -- '1' when (state=h0) else  
              '1' when (state=h1) else
              '1' when (state=h2) else
              '1' when (state=h3) else
              '1' when (state=h4) else
              '1' when (state=h5) else
              '1' when (state=h6) else
              '1' when (state=h7) else
              '1' when (state=h8) else
              '1' when (state=d0) else
              '1' when (state=d5) else
              '1' when (state=d9) else
              '1' when (state=d14) else
              '1' when (state=d18) else
              '1' when (state=d23) else
              '1' when (state=d27) else -- note no trailer words!
              '0';

FIFO_sleep <= '1' when (state=rst) else
              '1' when (state=wait4trig) else
              '0';

-- UltraRAM sync FIFO macro
-- 4k words deep x 72 bits wide (this is enough to hold 17 hits!)
-- first word fall through (FWFT)

-- writes into the output FIFO are not continuous; they stutter due to the 
-- dense packing cadence (d0, d5, d9) and are on average active only 1 out
-- of every 5 clocks. this means that the downstream logic reading from 
-- this FIFO needs to hold off, and let this output FIFO really fill up
-- before starting to read it out. in other words, the output FIFO should
-- continue to report that it is empty until it has nearly all of an
-- output record stored in it.

-- if another trigger occurs while this FSM is busy, it will be IGNORED!
-- triggers are ONLY monitored when the FSM is in the "wait4trig" state!

output_fifo_inst : xpm_fifo_sync
generic map (
   CASCADE_HEIGHT => 0,
   DOUT_RESET_VALUE => "0",
   ECC_MODE => "no_ecc",
   EN_SIM_ASSERT_ERR => "warning",
   FIFO_MEMORY_TYPE => "ultra", -- use UltraRAM blocks
   FIFO_READ_LATENCY => 0,  -- FWFT
   FIFO_WRITE_DEPTH => 4096,
   FULL_RESET_VALUE => 0,
   PROG_EMPTY_THRESH => 220, -- let it fill up nearly all the way!
   PROG_FULL_THRESH => 10,
   RD_DATA_COUNT_WIDTH => 13,
   READ_DATA_WIDTH => 72,
   READ_MODE => "fwft",
   SIM_ASSERT_CHK => 0,
   USE_ADV_FEATURES => "0707",
   WAKEUP_TIME => 0, -- 0=No Sleep (till Brooklyn), 2=use sleep pin
   WRITE_DATA_WIDTH => 72,
   WR_DATA_COUNT_WIDTH => 13
)
port map (
   almost_empty => open,
   almost_full => open,
   data_valid => open,
   dbiterr => open,
   dout => dout,
   empty => open,
   full => open,
   overflow => open,
   prog_empty => prog_empty, -- let it fill up
   prog_full => open,
   rd_data_count => open,
   rd_rst_busy => open,
   sbiterr => open,
   underflow => open,
   wr_ack => open,
   wr_data_count => fifo_word_count, -- number of words in the FIFO
   wr_rst_busy => open,
   din => FIFO_din,
   injectdbiterr => '0',
   injectsbiterr => '0',
   rd_en => rd_en,
   rst => reset,
   sleep => FIFO_sleep,
   wr_clk => clock,
   wr_en => FIFO_wr_en
);

ready <= not prog_empty;
trigger_signal <= triggered_bicocca;
st_afe_dat_filtered <= din_delay(9);
TCount <= std_logic_vector(trigCount); 
Pcount <= std_logic_vector(packCount); 

end stc3_arch;
