-- auto_fsm.vhd
-- FSM to control alignment of serial ADC data using IDELAY and ISERDES
-- Jamieson Olsen <jamieson@fnal.gov>

-- The width of the data eye is approximately 14 IDELAY taps (each 78ps)
-- 
-- first, the fine adjustment: increment the tap value for IDELAY, each time storing the output
-- word from ISERDES. Compare the old and new words and when it changes, 
-- that indicates that the current sample point is at the edge of the eye! 
-- increment (or decrement) IDELAY by 7 and that will put the sample point in the CENTER of the eye.
--
-- now the coarse adjustment. sample D. if it is the training pattern "11111110000000" then we're done, 
-- otherwise, assert BITSLIP, wait, check again, repeat....

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity auto_fsm is
port(
    reset: in std_logic; -- sync to clock
    clock: in std_logic;
    d: in std_logic_vector(13 downto 0); -- parallel word from ISERDES
    bitslip: out std_logic; -- bitslip the ISERDES
    cntvalue: out std_logic_vector(4 downto 0); -- the delay tap value to write into IDELAY
    load: out std_logic; -- load cntvalue into IDELAY
    done: out std_logic;  -- FSM has completed the alignment process
    warn: out std_logic;  -- pulse high momentary if "FCLK" bit error is detected in the done state
    errcnt: out std_logic_vector(7 downto 0) -- count the number of bit errors detected in FCLK pattern
);
end auto_fsm;

architecture auto_fsm_arch of auto_fsm is
   
    type state_type is (rst, load_cntvalue_init, wait_cntvalue_init, sample_init, 
                        load_cntvalue, wait_cntvalue, edge_check, load_cntvalue_final, wait_cntvalue_final, 
                        chk_frame, slipit, wait_slip, aligned);
    signal state: state_type;

    signal old_reg, new_reg: std_logic_vector(13 downto 0);
    signal count_reg: std_logic_vector(7 downto 0);
    signal cntvalue_reg: std_logic_vector(4 downto 0);
    signal done_reg, warn_reg: std_logic;
    signal errcnt_reg: std_logic_vector(7 downto 0);

begin
 
    fsm_proc: process(clock)
    begin
        if rising_edge(clock) then
            if (reset='1') then
                state <= rst;
            else
                case(state) is

when rst =>
    cntvalue_reg <= "00000";
    state <= load_cntvalue_init;

when load_cntvalue_init =>  -- load IDELAY for first time tap value = 0
    count_reg <= X"00";
    state <= wait_cntvalue_init;

when wait_cntvalue_init => -- wait here while IDELAY settles out...
    if (count_reg = X"FF") then
        state <= sample_init;
    else
        count_reg <= std_logic_vector(unsigned(count_reg)+1);
        state <= wait_cntvalue_init;
    end if;

when sample_init => -- get initial sample for tap value 0
    new_reg <= d;
    state <= load_cntvalue;

when load_cntvalue => -- write tap value to IDELAY
    count_reg <= X"00";    
    state <= wait_cntvalue;

when wait_cntvalue => -- wait while IDELAY settles out
    if (count_reg = X"FF") then
        old_reg <= new_reg;  -- store the parallel word for the OLD tap value
        new_reg <= d;        -- store the parallel word for the NEW tap value
        state <= edge_check;
    else
        count_reg <= std_logic_vector(unsigned(count_reg)+1);
        state <= wait_cntvalue;
    end if;

when edge_check => 
    if (old_reg /= new_reg) then -- it changed, thus we found ONE edge of the eye!
        if (cntvalue_reg >= "10000") then -- increment or decrement the tap count by 7 to determine the center of the eye
            cntvalue_reg <= std_logic_vector(unsigned(cntvalue_reg) - 7);
        else
            cntvalue_reg <= std_logic_vector(unsigned(cntvalue_reg) + 7);
        end if;
        state <= load_cntvalue_final;
    else -- nope, the old/new values match, we have NOT found the edge of the eye yet...
        cntvalue_reg <= std_logic_vector(unsigned(cntvalue_reg) + 1); -- increment tap value and try again...
        state <= load_cntvalue;
    end if;

when load_cntvalue_final => -- store the final "center of eye" tap value in IDELAY...
    count_reg <= X"00";    
    state <= wait_cntvalue_final;

when wait_cntvalue_final => -- wait for awhile....
    if (count_reg = X"FF") then
        state <= chk_frame;
    else
        count_reg <= std_logic_vector(unsigned(count_reg)+1);
        state <= wait_cntvalue_final;
    end if;

-- this is the "coarse" automatic adjustment stuff....

when chk_frame => -- is the training pattern received correctly?
    if (d = "11111110000000") then
        state <= aligned; -- yes! we're done!
    else
        state <= slipit; -- no, we need to bitslip the ISERDES
    end if;

when slipit => -- assert bitslip for ONE clock
    count_reg <= X"00";
    state <= wait_slip;

when wait_slip => -- wait for awhile...
    if (count_reg = X"FF") then
        state <= chk_frame; -- time's up, check again...
    else
        count_reg <= std_logic_vector(unsigned(count_reg)+1);
        state <= wait_slip;
    end if;

when aligned => 
    state <= aligned; -- yeah stay here forever or maybe do another check?

when others => 
    state <= rst;

end case;
            end if;
        end if;
    end process fsm_proc;

cntvalue <= cntvalue_reg;

load <=  '1' when (state=load_cntvalue_init) else 
                '1' when (state=load_cntvalue) else 
                '1' when (state=load_cntvalue_final) else 
                '0';

bitslip <= '1' when (state=slipit) else '0';

-- register the DONE and WARN outputs since these may be sampled in another clock domain

stat_proc: process(clock) 
begin
    if rising_edge(clock) then
        if (state=aligned) then
            done_reg <= '1';
            if (d /= "11111110000000") then -- observed bit error on the "FCLK" pattern
                warn_reg <= '1'; -- pulse the WARN output
                if (errcnt_reg /= X"FF") then -- and increment errcnt up to 255
                    errcnt_reg <= std_logic_vector(unsigned(errcnt_reg)+1);
                end if;
            else
                warn_reg <= '0';
            end if;
        else
            errcnt_reg <= X"00";
            done_reg <= '0';
            warn_reg <= '0';
        end if;
    end if;
end process stat_proc;

done <= done_reg;
warn <= warn_reg;
errcnt <= errcnt_reg;

end auto_fsm_arch;