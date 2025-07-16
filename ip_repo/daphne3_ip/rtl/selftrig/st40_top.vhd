-- st40_top.vhd
-- DAPHNE core logic, top level, self triggered mode sender
-- all 40 AFE channels -> one output link to DAQ
-- 
-- Jamieson Olsen <jamieson@fnal.gov>

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

library unisim;
use unisim.vcomponents.all;

library work;
use work.daphne3_package.all;

entity st40_top is
-- generic( baseline_runlength: integer := 256 ); -- options 32, 64, 128, or 256
port(
    link_id: std_logic_vector(5 downto 0);
    slot_id: in std_logic_vector(3 downto 0);
    crate_id: in std_logic_vector(9 downto 0);
    detector_id: in std_logic_vector(5 downto 0);
    version_id: in std_logic_vector(5 downto 0);
    -- threshold: in std_logic_vector(9 downto 0); -- counts relative to the calculated baseline

    clock: in std_logic; -- main clock 62.5 MHz
    reset: in std_logic;
    timestamp: in std_logic_vector(63 downto 0);
    enable: in std_logic_vector(39 downto 0);
    forcetrig: in std_logic;
	din: in array_40x14_type; -- ALL AFE channels feed into this module
    adhoc: in std_logic_vector(7 downto 0); -- command for adhoc trigger
    st_config: in std_logic_vector(13 downto 0); -- Config param for Self-Trigger and Local Primitive Calculation, CIEMAT (Nacho)
    signal_delay: in std_logic_vector(4 downto 0);
    threshold_xc: in std_logic_vector(41 downto 0); -- cross correlation trigger threshold 
    filter_output_selector: in std_logic_vector(1 downto 0); --Esteban 
    ti_trigger: in std_logic_vector(7 downto 0); -------------------------
    ti_trigger_stbr: in std_logic;  -------------------------
    reset_st_counters: in std_logic;
    afe_comp_enable: in std_logic_vector(39 downto 0);
    invert_enable: in std_logic_vector(39 downto 0);
    afe_dat_filtered: out array_40x14_type; -- aligned AFE data filtered
    TCount: out array_40x64_type;
    Pcount: out array_40x64_type;

    d0: out std_logic_vector(63 downto 0); -- output to single channel 10G sender
    d0_valid: out std_logic;
    d0_last:  out std_logic
);
end st40_top;

architecture st40_top_arch of st40_top is
 
    type state_type is (rst, scan, dump, pause);
    signal state: state_type;
    signal sel: integer range 0 to 39;
    signal fifo_rd_en: std_logic_vector(39 downto 0) := (others=>'0');
    signal ready: std_logic_vector(39 downto 0) := (others=>'0');
    type array_40x72_type is array(39 downto 0) of std_logic_vector(71 downto 0);
    signal fifo_dout: array_40x72_type;
    signal fifo_dout_mux: std_logic_vector(71 downto 0);

    component stc3 is
    -- generic( baseline_runlength: integer := 256 ); -- options 32, 64, 128, or 256
    port(
        link_id: std_logic_vector(5 downto 0);
        ch_id: std_logic_vector(5 downto 0);
        slot_id: std_logic_vector(3 downto 0);
        crate_id: std_logic_vector(9 downto 0);
        detector_id: std_logic_vector(5 downto 0);
        version_id: std_logic_vector(5 downto 0);
        -- threshold: std_logic_vector(9 downto 0); -- trig threshold relative to calculated baseline

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
        rd_en: in std_logic; -- output FIFO read enable
        dout: out std_logic_vector(71 downto 0); -- output FIFO data
        ready: out std_logic; -- got something in the output FIFO yo
        TCount: out std_logic_vector(63 downto 0);
        PCount: out std_logic_vector(63 downto 0)
    );
    end component;

begin

    -- make 40 self-trigger-channel (STC) machines...

    gen_stc: for i in 39 downto 0 generate

            stc3_inst: stc3
            -- generic map ( baseline_runlength => baseline_runlength )
            port map(   
                link_id => link_id,
                ch_id => std_logic_vector( to_unsigned(i,6) ),
                slot_id => slot_id,
                crate_id => crate_id,
                detector_id => detector_id,
                version_id => version_id,
                -- threshold => threshold,

                clock => clock,
                reset => reset,
                enable => enable(i),
                adhoc => adhoc, -- command for adhoc trigger
                st_config => st_config, -- Config param for Self-Trigger and Local Primitive Calculation, CIEMAT (Nacho)
                signal_delay => signal_delay,
                threshold_xc => threshold_xc, -- cross correlation trigger threshold 
                filter_output_selector => filter_output_selector, --Esteban
                ti_trigger => ti_trigger, -------------------------
                ti_trigger_stbr => ti_trigger_stbr,  -------------------------
                reset_st_counters => reset_st_counters,
                forcetrig => forcetrig,
                timestamp => timestamp,
            	din => din(i),
                afe_comp_enable => afe_comp_enable(i),
                invert_enable => invert_enable(i),
                st_afe_dat_filtered => afe_dat_filtered(i), -- aligned AFE data filtered
                trigger_signal => open,
                rd_en => fifo_rd_en(i),
                dout => fifo_dout(i),
                ready => ready(i),
                TCount => TCount(i),
                PCount => PCount(i)
              );

    end generate gen_stc;

    -- generate the read enables for the 40 channel FIFOs

    gen_rden: for i in 39 downto 0 generate
        fifo_rd_en(i) <= '1' when (sel=i and state=dump) else '0';
    end generate gen_rden;

    -- FSM scans the STC machines looking for a machine with a NON-EMPTY output FIFO. When it finds
    -- one it dumps one complete output record, then goes idle for one clock, then moves on to the next channel 
    -- and resumes scanning (round robin).

    fsm_proc: process(clock)
    begin
        if rising_edge(clock) then
            if (reset='1') then
                state <= rst;
            else
                case(state) is

                    when rst =>
                        sel <= 0;
                        state <= scan;

                    when scan => 
                        if ( ready(sel)='1' ) then -- current channel gots something to send, lets dump a whole record
                            state <= dump;
                        else
                            if (sel = 39) then -- otherwise, move on to next channel (round robin)
                                sel <= 0;
                            else
                                sel <= sel + 1;
                            end if;
                            state <= scan;
                        end if;

                    when dump => -- dump one entire output record to the output
                        if ( fifo_dout_mux(71 downto 64)=X"ED" ) then -- this the marker for the LAST word of record
                            state <= pause;
                        else
                            state <= dump;
                        end if;

                    when pause => -- pause for 1 clock, increment ch_select & resume scanning...
                        if (sel = 39) then
                            sel <= 0;
                        else
                            sel <= sel + 1;
                        end if;
                        state <= scan;

                    when others => 
                        state <= rst;
                end case;
            end if;
        end if;
    end process fsm_proc;

    -- big output data mux 40:1

    outmux_proc: process(sel,fifo_dout)
    begin
        fifo_dout_mux <= fifo_dout(sel);
    end process outmux_proc;
     
    -- register the outputs

    outreg_proc: process(clock)
    begin
        if rising_edge(clock) then
            d0 <= fifo_dout_mux(63 downto 0); -- strip off marker byte

            if ( state=dump ) then
                d0_valid <= '1';
            else
                d0_valid <= '0';
            end if;

        end if;
    end process outreg_proc;

    d0_last <= '1' when (state=pause) else '0';

end st40_top_arch;