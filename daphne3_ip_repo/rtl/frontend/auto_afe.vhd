-- feafe.vhd
-- alignment for one AFE chip (fclk + 8 data)
-- 
-- the automatic adjustments of the IDELAY and ISERDES is done with an FSM 
-- which is watching the "FCLK" output of the AFE device. This AFE output is treated just 
-- like a data bit which *always* sends the same pattern: "11111110000000" therefore it
-- is used for training and automatic alignment. the other 8 data outputs of the AFE
-- also have IDELAY and ISERDES, and these get the same adjustments that the "FCLK" channels gets
-- the assumption here is that on the PCB the FCLK and 8 DATA LVDS pairs are matched length 
-- diff pairs, so timing differences between LVDS WITHIN AN AFE CHIP are negligable.
-- 
-- Jamieson Olsen <jamieson@fnal.gov>

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

use work.daphne3_package.all;

entity feafe is
port(

    afe_p: in std_logic_vector(8 downto 0); -- FCLK marker is bit 8
    afe_n: in std_logic_vector(8 downto 0);

    clock:   in  std_logic;  -- master clock 62.5MHz
    clock7x: in  std_logic;  -- 7 x master clock = 437.5MHz
    reset:   in  std_logic;  -- sync to clock
    done:    out std_logic;  -- fsm has completed the auto alignment procedure
    warn:    out std_logic;  -- momentary pulse to indicate a bit error on the FCLK pattern
    errcnt:  out std_logic_vector(7 downto 0); -- count the number of errors observed on the FCLK pattern
    dout:    out array_9x14_type
  );
end feafe;

architecture feafe_arch of feafe is

    component febit3
    port(
        din_p:     in std_logic;
        din_n:     in std_logic;
        clock:     in std_logic;
        clock7x:   in std_logic;
        reset:     in std_logic;
        bitslip:   in std_logic;
        load:      in std_logic;
        cntvalue:  in std_logic_vector(4 downto 0);
        q:         out std_logic_vector(13 downto 0)
      );
    end component;

    component auto_fsm 
    port(
        reset: in std_logic;
        clock: in std_logic;
        d: in std_logic_vector(13 downto 0); -- parallel word from ISERDES
        bitslip: out std_logic; -- bitslip the ISERDES
        cntvalue: out std_logic_vector(4 downto 0); -- the delay tap value to write into IDELAY
        load: out std_logic; -- load cntvalue into IDELAY
        done: out std_logic;
        warn: out std_logic;
        errcnt: out std_logic_vector(7 downto 0)
      );
    end component;

    signal cntvalue: std_logic_vector(4 downto 0);
    signal fclk_patt: std_logic_vector(13 downto 0);
    signal bitslip, load: std_logic;

begin

    ffebit_inst: febit
    port map(
        din_p => afe_p(8),
        din_n => afe_n(8),
        clock => clock,
        clock7x => clock7x,
        reset => reset,
        bitslip => bitslip,
        load => load,
        cntvalue => cntvalue,
        q => fclk_patt
    );

    genfebit: for i in 7 downto 0 generate
        dfebit_inst: febit
        port map(
            din_p => afe_p(i),
            din_n => afe_n(i),
            clock => clock,
            clock7x => clock7x,
            reset => reset,
            bitslip => bitslip,
            load => load,
            cntvalue => cntvalue,
            q => dout(i)
        );
    end generate genfebit;
    
    auto_fsm_inst: auto_fsm 
    port map(
        reset => reset,
        clock => clock,
        d => fclk_patt,
        bitslip => bitslip,
        cntvalue => cntvalue,
        load => load,
        done => done,
        warn => warn, 
        errcnt => errcnt
    );

    dout(8) <= fclk_patt;

end feafe_arch;