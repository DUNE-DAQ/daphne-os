# DAPHNE3 PL TIMING constraints

# # define primary clocks...

# create_clock -name sysclk100    -period 10.000  [get_ports sysclk100]
# create_clock -name rx_tmg_clk   -period 16.000  [get_ports rx0_tmg_p]
# create_clock -name sb_axi_clk   -period 5.000   [get_ports SB_AXI_CLK]
# create_clock -name fe_axi_clk   -period 5.000   [get_ports FE_AXI_CLK]
# create_clock -name ep_axi_clk   -period 5.000   [get_ports EP_AXI_CLK]

# # rename the auto-generated clocks...

# create_generated_clock -name local_clk62p5  [get_pins -hierarchical -quiet *mmcm0_inst/CLKOUT0]
# create_generated_clock -name clk100         [get_pins endpoint_inst/mmcm0_inst/CLKOUT2]
# create_generated_clock -name mmcm0_clkfbout [get_pins endpoint_inst/mmcm0_inst/CLKFBOUT]

# create_generated_clock -name ep_clk62p5  [get_pins -hierarchical -quiet *mmcm/CLKOUT0]
# create_generated_clock -name ep_clk4x    [get_pins endpoint_inst/pdts_endpoint_inst/pdts_endpoint_inst/rxcdr/mmcm/CLKOUT1]
# create_generated_clock -name ep_clk2x    [get_pins endpoint_inst/pdts_endpoint_inst/pdts_endpoint_inst/rxcdr/mmcm/CLKOUT1]
# create_generated_clock -name ep_clkfbout [get_pins endpoint_inst/pdts_endpoint_inst/pdts_endpoint_inst/rxcdr/mmcm/CLKFBOUT] 

# create_generated_clock -name clk500_0        -master_clock ep_clk62p5 [get_pins endpoint_inst/mmcm1_inst/CLKOUT0]
# create_generated_clock -name clock_0         -master_clock ep_clk62p5 [get_pins endpoint_inst/mmcm1_inst/CLKOUT1]
# create_generated_clock -name clk125_0        -master_clock ep_clk62p5 [get_pins endpoint_inst/mmcm1_inst/CLKOUT2]
# create_generated_clock -name mmcm1_clkfbout0 -master_clock ep_clk62p5 [get_pins endpoint_inst/mmcm1_inst/CLKFBOUT]

# create_generated_clock -name clk500_1        -master_clock local_clk62p5 [get_pins endpoint_inst/mmcm1_inst/CLKOUT0]
# create_generated_clock -name clock_1         -master_clock local_clk62p5 [get_pins endpoint_inst/mmcm1_inst/CLKOUT1]
# create_generated_clock -name clk125_1        -master_clock local_clk62p5 [get_pins endpoint_inst/mmcm1_inst/CLKOUT2]
# create_generated_clock -name mmcm1_clkfbout1 -master_clock local_clk62p5 [get_pins endpoint_inst/mmcm1_inst/CLKFBOUT]

# define clock groups this is how we tell vivado which clocks are related and which are NOT

# set_clock_groups -name async_groups -asynchronous \
# -group {sysclk100 clk100 mmcm0_clkfbout} \
# -group {sb_axi_clk fe_axi_clk ep_axi_clk} \
# -group {local_clk62p5} \
# -group {clk500_0 clock_0 clk125_0 mmcm1_clkfbout0} \
# -group {clk500_1 clock_1 clk125_1 mmcm1_clkfbout1} \
# -group {ep_clk62p5 ep_clk4x ep_clk2x ep_clkfbout} \
# -group {rx_tmg_clk} 

# tell vivado about places where signals cross clock domains so timing can be ignored here...

#set_false_path -from [get_pins fe_inst/gen_afe[*].afe_inst/auto_fsm_inst/done_reg_reg/C]      
#set_false_path -from [get_pins fe_inst/gen_afe[*].afe_inst/auto_fsm_inst/warn_reg_reg/C]      
#set_false_path -from [get_pins fe_inst/gen_afe[*].afe_inst/auto_fsm_inst/errcnt_reg_reg[*]/C] 
#set_false_path -from [get_pins trig_gbe*_reg_reg/C] -to [get_pins trig_sync_reg/D]
#set_false_path -to [get_pins led0_reg_reg[*]/C]
#set_false_path -from [get_pins test_reg_reg[*]/C]
#set_false_path -from [get_ports gbe_sfp_??s]
#set_false_path -from [get_ports cdr_sfp_??s]
#set_false_path -from [get_ports daq?_sfp_??s]
#set_false_path -from [get_pins st_enable_reg_reg[*]/C]
#set_false_path -from [get_pins outmode_reg_reg[*]/C]
#set_false_path -from [get_pins threshold_reg_reg[*]/C]
#set_false_path -from [get_pins daq_out_param_reg_reg[*]/C]
#set_false_path -from [get_pins core_inst/input_inst/*select_reg_reg*/C]

##################################################################################################################################################
# ORIGINAL VERSION
##################################################################################################################################################

# DAPHNE3 PL TIMING constraints

# define primary clocks...

create_clock -name sysclk100    -period 10.000  [get_ports sysclk100]
create_clock -name rx_tmg_clk   -period 16.000  [get_ports rx0_tmg_p]
create_clock -name sb_axi_clk   -period 5.000   [get_ports SB_AXI_CLK]
create_clock -name fe_axi_clk   -period 5.000   [get_ports FE_AXI_CLK]
create_clock -name ep_axi_clk   -period 5.000   [get_ports EP_AXI_CLK]

# rename the auto-generated clocks...

create_generated_clock -name local_clk62p5  [get_pins endpoint_inst/mmcm0_inst/CLKOUT0]
create_generated_clock -name clk100         [get_pins endpoint_inst/mmcm0_inst/CLKOUT2]
create_generated_clock -name mmcm0_clkfbout [get_pins endpoint_inst/mmcm0_inst/CLKFBOUT]

create_generated_clock -name ep_clk62p5  [get_pins endpoint_inst/pdts_endpoint_inst/pdts_endpoint_inst/rxcdr/mmcm/CLKOUT0]
create_generated_clock -name ep_clk4x    [get_pins endpoint_inst/pdts_endpoint_inst/pdts_endpoint_inst/rxcdr/mmcm/CLKOUT1]
create_generated_clock -name ep_clk2x    [get_pins endpoint_inst/pdts_endpoint_inst/pdts_endpoint_inst/rxcdr/mmcm/CLKOUT1]
create_generated_clock -name ep_clkfbout [get_pins endpoint_inst/pdts_endpoint_inst/pdts_endpoint_inst/rxcdr/mmcm/CLKFBOUT] 

create_generated_clock -name clk500_0        -master_clock ep_clk62p5 [get_pins endpoint_inst/mmcm1_inst/CLKOUT0]
create_generated_clock -name clock_0         -master_clock ep_clk62p5 [get_pins endpoint_inst/mmcm1_inst/CLKOUT1]
create_generated_clock -name clk125_0        -master_clock ep_clk62p5 [get_pins endpoint_inst/mmcm1_inst/CLKOUT2]
create_generated_clock -name mmcm1_clkfbout0 -master_clock ep_clk62p5 [get_pins endpoint_inst/mmcm1_inst/CLKFBOUT]

create_generated_clock -name clk500_1        -master_clock local_clk62p5 [get_pins endpoint_inst/mmcm1_inst/CLKOUT0]
create_generated_clock -name clock_1         -master_clock local_clk62p5 [get_pins endpoint_inst/mmcm1_inst/CLKOUT1]
create_generated_clock -name clk125_1        -master_clock local_clk62p5 [get_pins endpoint_inst/mmcm1_inst/CLKOUT2]
create_generated_clock -name mmcm1_clkfbout1 -master_clock local_clk62p5 [get_pins endpoint_inst/mmcm1_inst/CLKFBOUT]

# define clock groups this is how we tell vivado which clocks are related and which are NOT

set_clock_groups -name async_groups -asynchronous \
-group {sysclk100 clk100 mmcm0_clkfbout} \
-group {sb_axi_clk fe_axi_clk ep_axi_clk} \
-group {local_clk62p5} \
-group {clk500_0 clock_0 clk125_0 mmcm1_clkfbout0} \
-group {clk500_1 clock_1 clk125_1 mmcm1_clkfbout1} \
-group {ep_clk62p5 ep_clk4x ep_clk2x ep_clkfbout} \
-group {rx_tmg_clk} 

# tell vivado about places where signals cross clock domains so timing can be ignored here...

#set_false_path -from [get_pins fe_inst/gen_afe[*].afe_inst/auto_fsm_inst/done_reg_reg/C]      
#set_false_path -from [get_pins fe_inst/gen_afe[*].afe_inst/auto_fsm_inst/warn_reg_reg/C]      
#set_false_path -from [get_pins fe_inst/gen_afe[*].afe_inst/auto_fsm_inst/errcnt_reg_reg[*]/C] 
#set_false_path -from [get_pins trig_gbe*_reg_reg/C] -to [get_pins trig_sync_reg/D]
#set_false_path -to [get_pins led0_reg_reg[*]/C]
#set_false_path -from [get_pins test_reg_reg[*]/C]
#set_false_path -from [get_ports gbe_sfp_??s]
#set_false_path -from [get_ports cdr_sfp_??s]
#set_false_path -from [get_ports daq?_sfp_??s]
#set_false_path -from [get_pins st_enable_reg_reg[*]/C]
#set_false_path -from [get_pins outmode_reg_reg[*]/C]
#set_false_path -from [get_pins threshold_reg_reg[*]/C]
#set_false_path -from [get_pins daq_out_param_reg_reg[*]/C]
#set_false_path -from [get_pins core_inst/input_inst/*select_reg_reg*/C]

