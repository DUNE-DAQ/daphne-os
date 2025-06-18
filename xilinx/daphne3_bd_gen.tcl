# elaborated TCL script file to create DAPHNE3's block design
# the script generates the .bd file needed to build DAPHNE3's .bit file, within the In-Memory Project
# <daniel.avila@eia.edu.co - daniel.avila.gomez@cern.ch>

# general setup stuff
set blockDesignDir ../bd
file mkdir $blockDesignDir 

# configure the current in-memory project
set_part xck26-sfvc784-2LV-c
set_property BOARD_PART xilinx.com:k26c:part0:1.4 [current_project]
set_property TARGET_LANGUAGE VHDL [current_project]
set_property DEFAULT_LIB work [current_project]

# make sure to add the new DAPHNE3 IP before generating the Block Design
# this helps to avoid errors or not finding the IP
source daphne3_ip_gen.tcl

# set design name here
variable designName 
set designName DAPHNE_V3_F4_3

# set variables to control errors
set errMsg ""
set nRet 0

set cur_design [current_bd_design -quiet]
set list_cells [get_bd_cells -quiet]

if {${designName} eq ""} {
    # when the design name is not set
    set errMsg "Please set the variable <designName> to a non-empty value."
    set nRet 1
} elseif {${cur_design} ne "" && ${list_cells} eq ""} {
    # when the design is opened and is empty and names same
    # when the design is opened and is empty, but the names are different, and the designName is not in the proejct
    # when the design is opened and is empty, but the names are different, and the designName exists in the project
    if {$cur_design ne $designName} {
        puts "Changing value of <designName> from <$designName> to <$cur_design> since current design is empty."
        set designName [get_property NAME $cur_design]
    }
    puts "Constructing design in IPI design <$cur_design>..."
} elseif {${cur_design} ne "" && $list_cells ne "" && $cur_design eq $designName} {
    # when the design is opened and has components and same names
    set errMsg "Design <$designName> already exists in your project, please set the variable <designName> to another value."
    set nRet 1
} elseif {[get_files -quiet ${designName}.bd] ne ""} {
    # when current opened design, it has components, but different names and the designName already exists in project
    # when there is no opened design, but the designName exists in project
    set errMsg "Design <$designName> already exists in your project, please set the variable <designName> to another value."
    set nRet 2
} else {
    # when no opened design, designName not in project
    # when current design is openes, has components, but different names, and the designName is not in the project
    puts "Currently there is no design <$designName> in project, so creating one..."

    # command to create the block design
    create_bd_design -dir $blockDesignDir $designName

    puts "Making design <$designName> as current_bd_design."
    current_bd_design $designName
}

# inform the user of the name of the design
puts "Currently the variable <designName> is equal to \"$designName\"."

if {$nRet != 0} {
    catch {common::send_gid_msg -ssname BD::TCL -id 2006 -severity "ERROR" $errMsg}
    return $nRet
}

# check the IPs in the directory
set bCheckIPsPassed 1
set bCheckIPs 1
if {$bCheckIPs == 1} {
    set list_check_ips "\
xilinx.com:ip:zynq_ultra_ps_e:3.5\
xilinx.com:ip:smartconnect:1.0\
xilinx.com:ip:proc_sys_reset:5.0\
xilinx.com:ip:axi_iic:2.1\
xilinx.com:ip:axi_quad_spi:3.2\
xilinx.com:ip:axi_intc:4.1\
xilinx.com:ip:xlconcat:2.1\
xilinx.com:ip:ila:6.2\
dune.pds:user:DAPHNE3:1.0\
"
    set list_ips_missing ""
    puts "Checking if the following IPs exist in the project's IP catalog: $list_check_ips ."

    foreach ipVlnv $list_check_ips {
        set ip_obj [get_ipdefs -all $ipVlnv]
        if {$ip_obj eq ""} {
            lappend list_ips_missing $ipVlnv
        }
    }

    if {$list_ips_missing ne ""} {
        catch {common::send_gid_msg -ssname BD::TCL -id 2012 -severity "ERROR" "The following IPs are not found in the IP Catalog:\n  $list_ips_missing\n\nResolution: Please add the repository containing the IP(s) to the project." }
        set bCheckIPsPassed 0
    }
}

# start building the Block Design

# create interface ports
set IIC_0 [create_bd_intf_port -mode Master -vlnv xilinx.com:interface:iic_rtl:1.0 IIC_0]

# create ports 
# inputs
set afe0_n [create_bd_port -dir I -from 8 -to 0 afe0_n]
set afe0_p [create_bd_port -dir I -from 8 -to 0 afe0_p]
set afe1_n [create_bd_port -dir I -from 8 -to 0 afe1_n]
set afe1_p [create_bd_port -dir I -from 8 -to 0 afe1_p]
set afe2_n [create_bd_port -dir I -from 8 -to 0 afe2_n]
set afe2_p [create_bd_port -dir I -from 8 -to 0 afe2_p]
set afe3_n [create_bd_port -dir I -from 8 -to 0 afe3_n]
set afe3_p [create_bd_port -dir I -from 8 -to 0 afe3_p]
set afe4_n [create_bd_port -dir I -from 8 -to 0 afe4_n]
set afe4_p [create_bd_port -dir I -from 8 -to 0 afe4_p]
set fan_tach [create_bd_port -dir I -from 1 -to 0 fan_tach]
set rx0_tmg_n [create_bd_port -dir I rx0_tmg_n]
set rx0_tmg_p [create_bd_port -dir I rx0_tmg_p]
set sfp_tmg_los [create_bd_port -dir I sfp_tmg_los]
set CM_DOUT [create_bd_port -dir I CM_DOUT]
set AFE0_MISO [create_bd_port -dir I AFE0_MISO]
set AFE12_AFE_MISO [create_bd_port -dir I AFE12_AFE_MISO]
set AFE34_AFE_MISO [create_bd_port -dir I AFE34_AFE_MISO]
set trig_IN [create_bd_port -dir I trig_IN]
set GTH0_REFCLK_N [create_bd_port -dir I -type clk GTH0_REFCLK_N]
set GTH0_REFCLK_P [create_bd_port -dir I -type clk GTH0_REFCLK_P]
set RX0_GTH_N [create_bd_port -dir I RX0_GTH_N]
set RX0_GTH_P [create_bd_port -dir I RX0_GTH_P]
# outputs
set FAN_CONTROL [create_bd_port -dir O FAN_CONTROL]
set VBIAS_EN [create_bd_port -dir O VBIAS_EN]
set MUX_EN [create_bd_port -dir O -from 1 -to 0 MUX_EN]
set MUXA [create_bd_port -dir O -from 1 -to 0 MUXA]
set sfp_tmg_tx_dis [create_bd_port -dir O sfp_tmg_tx_dis]
set tx0_tmg_n [create_bd_port -dir O tx0_tmg_n]
set tx0_tmg_p [create_bd_port -dir O tx0_tmg_p]
set afe_clk_n [create_bd_port -dir O -type clk afe_clk_n]
set afe_clk_p [create_bd_port -dir O -type clk afe_clk_p]
set AFE12_SDATA [create_bd_port -dir O AFE12_SDATA]
set AFE12_SCLK [create_bd_port -dir O AFE12_SCLK]
set AFE34_SCLK [create_bd_port -dir O AFE34_SCLK]
set AFE34_SDATA [create_bd_port -dir O AFE34_SDATA]
set CM_SCLK [create_bd_port -dir O CM_SCLK]
set CM_DIN [create_bd_port -dir O CM_DIN]
set DACS_SCLK [create_bd_port -dir O DACS_SCLK]
set DACS_MOSI [create_bd_port -dir O DACS_MOSI]
set DACS_CS [create_bd_port -dir O DACS_CS]
set DACS_LDACN [create_bd_port -dir O DACS_LDACN]
set AFE_PD [create_bd_port -dir O AFE_PD]
set AFE_RST [create_bd_port -dir O -type rst AFE_RST]
set AFE0_SCLK [create_bd_port -dir O AFE0_SCLK]
set AFE0_SDATA [create_bd_port -dir O AFE0_SDATA]
set afe_sen [create_bd_port -dir O -from 4 -to 0 afe_sen]
set trim_sync_n [create_bd_port -dir O -from 4 -to 0 trim_sync_n]
set trim_ldac_n [create_bd_port -dir O -from 4 -to 0 trim_ldac_n]
set offset_sync_n [create_bd_port -dir O -from 4 -to 0 offset_sync_n]
set offset_ldac_n [create_bd_port -dir O -from 4 -to 0 offset_ldac_n]
set TX0_GTH_P [create_bd_port -dir O TX0_GTH_P]
set TX0_GTH_N [create_bd_port -dir O TX0_GTH_N]
set SFP_GTH0_TX_DIS [create_bd_port -dir O SFP_GTH0_TX_DIS]
set CM_CSn [create_bd_port -dir O -from 0 -to 0 CM_CSn]


# Create all the cell instances used by the design

# create instance: zynq_ultra_ps_e_0, and set its properties
set zynq_ultra_ps_e_0 [create_bd_cell -vlnv xilinx.com:ip:zynq_ultra_ps_e:3.5 -type IP zynq_ultra_ps_e_0]
set_property -dict [list \
    CONFIG.PSU_BANK_0_IO_STANDARD {LVCMOS18} \
    CONFIG.PSU_BANK_1_IO_STANDARD {LVCMOS18} \
    CONFIG.PSU_BANK_2_IO_STANDARD {LVCMOS18} \
    CONFIG.PSU_BANK_3_IO_STANDARD {LVCMOS18} \
    CONFIG.PSU_DDR_RAM_HIGHADDR {0xFFFFFFFF} \
    CONFIG.PSU_DDR_RAM_HIGHADDR_OFFSET {0x800000000} \
    CONFIG.PSU_DDR_RAM_LOWADDR_OFFSET {0x80000000} \
    CONFIG.PSU_MIO_0_DRIVE_STRENGTH {4} \
    CONFIG.PSU_MIO_0_SLEW {slow} \
    CONFIG.PSU_MIO_10_DRIVE_STRENGTH {4} \
    CONFIG.PSU_MIO_10_SLEW {slow} \
    CONFIG.PSU_MIO_11_DRIVE_STRENGTH {4} \
    CONFIG.PSU_MIO_11_SLEW {slow} \
    CONFIG.PSU_MIO_12_DRIVE_STRENGTH {4} \
    CONFIG.PSU_MIO_12_POLARITY {Default} \
    CONFIG.PSU_MIO_12_SLEW {slow} \
    CONFIG.PSU_MIO_13_DRIVE_STRENGTH {4} \
    CONFIG.PSU_MIO_13_SLEW {slow} \
    CONFIG.PSU_MIO_14_DRIVE_STRENGTH {4} \
    CONFIG.PSU_MIO_14_SLEW {slow} \
    CONFIG.PSU_MIO_15_DRIVE_STRENGTH {4} \
    CONFIG.PSU_MIO_15_SLEW {slow} \
    CONFIG.PSU_MIO_16_DRIVE_STRENGTH {4} \
    CONFIG.PSU_MIO_16_SLEW {slow} \
    CONFIG.PSU_MIO_17_DRIVE_STRENGTH {4} \
    CONFIG.PSU_MIO_17_SLEW {slow} \
    CONFIG.PSU_MIO_18_DRIVE_STRENGTH {4} \
    CONFIG.PSU_MIO_18_SLEW {slow} \
    CONFIG.PSU_MIO_19_DRIVE_STRENGTH {4} \
    CONFIG.PSU_MIO_19_SLEW {slow} \
    CONFIG.PSU_MIO_1_DRIVE_STRENGTH {4} \
    CONFIG.PSU_MIO_1_SLEW {slow} \
    CONFIG.PSU_MIO_20_DRIVE_STRENGTH {4} \
    CONFIG.PSU_MIO_20_SLEW {slow} \
    CONFIG.PSU_MIO_21_DRIVE_STRENGTH {4} \
    CONFIG.PSU_MIO_21_SLEW {slow} \
    CONFIG.PSU_MIO_22_DRIVE_STRENGTH {4} \
    CONFIG.PSU_MIO_22_SLEW {slow} \
    CONFIG.PSU_MIO_23_DRIVE_STRENGTH {4} \
    CONFIG.PSU_MIO_23_SLEW {slow} \
    CONFIG.PSU_MIO_24_DRIVE_STRENGTH {4} \
    CONFIG.PSU_MIO_24_SLEW {slow} \
    CONFIG.PSU_MIO_25_DRIVE_STRENGTH {4} \
    CONFIG.PSU_MIO_25_SLEW {slow} \
    CONFIG.PSU_MIO_27_DRIVE_STRENGTH {4} \
    CONFIG.PSU_MIO_27_SLEW {slow} \
    CONFIG.PSU_MIO_29_DRIVE_STRENGTH {4} \
    CONFIG.PSU_MIO_29_SLEW {slow} \
    CONFIG.PSU_MIO_2_DRIVE_STRENGTH {4} \
    CONFIG.PSU_MIO_2_SLEW {slow} \
    CONFIG.PSU_MIO_32_DRIVE_STRENGTH {4} \
    CONFIG.PSU_MIO_32_SLEW {slow} \
    CONFIG.PSU_MIO_33_DRIVE_STRENGTH {4} \
    CONFIG.PSU_MIO_33_SLEW {slow} \
    CONFIG.PSU_MIO_34_DIRECTION {inout} \
    CONFIG.PSU_MIO_34_DRIVE_STRENGTH {4} \
    CONFIG.PSU_MIO_34_SLEW {slow} \
    CONFIG.PSU_MIO_35_DRIVE_STRENGTH {4} \
    CONFIG.PSU_MIO_35_SLEW {slow} \
    CONFIG.PSU_MIO_36_DRIVE_STRENGTH {4} \
    CONFIG.PSU_MIO_36_SLEW {slow} \
    CONFIG.PSU_MIO_38_DRIVE_STRENGTH {4} \
    CONFIG.PSU_MIO_38_SLEW {slow} \
    CONFIG.PSU_MIO_39_DRIVE_STRENGTH {4} \
    CONFIG.PSU_MIO_39_SLEW {slow} \
    CONFIG.PSU_MIO_3_DRIVE_STRENGTH {4} \
    CONFIG.PSU_MIO_3_SLEW {slow} \
    CONFIG.PSU_MIO_40_DRIVE_STRENGTH {4} \
    CONFIG.PSU_MIO_40_SLEW {slow} \
    CONFIG.PSU_MIO_41_DRIVE_STRENGTH {4} \
    CONFIG.PSU_MIO_41_SLEW {slow} \
    CONFIG.PSU_MIO_42_DRIVE_STRENGTH {4} \
    CONFIG.PSU_MIO_42_SLEW {slow} \
    CONFIG.PSU_MIO_43_DIRECTION {inout} \
    CONFIG.PSU_MIO_43_DRIVE_STRENGTH {4} \
    CONFIG.PSU_MIO_43_SLEW {slow} \
    CONFIG.PSU_MIO_44_DIRECTION {inout} \
    CONFIG.PSU_MIO_44_DRIVE_STRENGTH {4} \
    CONFIG.PSU_MIO_44_SLEW {slow} \
    CONFIG.PSU_MIO_46_DRIVE_STRENGTH {4} \
    CONFIG.PSU_MIO_46_SLEW {slow} \
    CONFIG.PSU_MIO_47_DRIVE_STRENGTH {4} \
    CONFIG.PSU_MIO_47_SLEW {slow} \
    CONFIG.PSU_MIO_48_DRIVE_STRENGTH {4} \
    CONFIG.PSU_MIO_48_SLEW {slow} \
    CONFIG.PSU_MIO_49_DRIVE_STRENGTH {4} \
    CONFIG.PSU_MIO_49_SLEW {slow} \
    CONFIG.PSU_MIO_4_DRIVE_STRENGTH {4} \
    CONFIG.PSU_MIO_4_SLEW {slow} \
    CONFIG.PSU_MIO_50_DRIVE_STRENGTH {4} \
    CONFIG.PSU_MIO_50_SLEW {slow} \
    CONFIG.PSU_MIO_51_DRIVE_STRENGTH {4} \
    CONFIG.PSU_MIO_51_SLEW {slow} \
    CONFIG.PSU_MIO_54_DRIVE_STRENGTH {4} \
    CONFIG.PSU_MIO_54_SLEW {slow} \
    CONFIG.PSU_MIO_56_DRIVE_STRENGTH {4} \
    CONFIG.PSU_MIO_56_SLEW {slow} \
    CONFIG.PSU_MIO_57_DRIVE_STRENGTH {4} \
    CONFIG.PSU_MIO_57_SLEW {slow} \
    CONFIG.PSU_MIO_58_DRIVE_STRENGTH {4} \
    CONFIG.PSU_MIO_58_SLEW {slow} \
    CONFIG.PSU_MIO_59_DRIVE_STRENGTH {4} \
    CONFIG.PSU_MIO_59_SLEW {slow} \
    CONFIG.PSU_MIO_5_DRIVE_STRENGTH {4} \
    CONFIG.PSU_MIO_5_SLEW {slow} \
    CONFIG.PSU_MIO_60_DRIVE_STRENGTH {4} \
    CONFIG.PSU_MIO_60_SLEW {slow} \
    CONFIG.PSU_MIO_61_DRIVE_STRENGTH {4} \
    CONFIG.PSU_MIO_61_SLEW {slow} \
    CONFIG.PSU_MIO_62_DRIVE_STRENGTH {4} \
    CONFIG.PSU_MIO_62_SLEW {slow} \
    CONFIG.PSU_MIO_63_DRIVE_STRENGTH {4} \
    CONFIG.PSU_MIO_63_SLEW {slow} \
    CONFIG.PSU_MIO_64_DRIVE_STRENGTH {4} \
    CONFIG.PSU_MIO_64_SLEW {slow} \
    CONFIG.PSU_MIO_65_DRIVE_STRENGTH {4} \
    CONFIG.PSU_MIO_65_SLEW {slow} \
    CONFIG.PSU_MIO_66_DRIVE_STRENGTH {4} \
    CONFIG.PSU_MIO_66_SLEW {slow} \
    CONFIG.PSU_MIO_67_DRIVE_STRENGTH {4} \
    CONFIG.PSU_MIO_67_SLEW {slow} \
    CONFIG.PSU_MIO_68_DRIVE_STRENGTH {4} \
    CONFIG.PSU_MIO_68_SLEW {slow} \
    CONFIG.PSU_MIO_69_DRIVE_STRENGTH {4} \
    CONFIG.PSU_MIO_69_SLEW {slow} \
    CONFIG.PSU_MIO_6_DRIVE_STRENGTH {4} \
    CONFIG.PSU_MIO_6_SLEW {slow} \
    CONFIG.PSU_MIO_76_DRIVE_STRENGTH {4} \
    CONFIG.PSU_MIO_76_SLEW {slow} \
    CONFIG.PSU_MIO_77_DRIVE_STRENGTH {4} \
    CONFIG.PSU_MIO_77_SLEW {slow} \
    CONFIG.PSU_MIO_7_DRIVE_STRENGTH {4} \
    CONFIG.PSU_MIO_7_INPUT_TYPE {cmos} \
    CONFIG.PSU_MIO_7_POLARITY {Default} \
    CONFIG.PSU_MIO_7_SLEW {slow} \
    CONFIG.PSU_MIO_8_DRIVE_STRENGTH {4} \
    CONFIG.PSU_MIO_8_POLARITY {Default} \
    CONFIG.PSU_MIO_8_SLEW {slow} \
    CONFIG.PSU_MIO_9_DRIVE_STRENGTH {4} \
    CONFIG.PSU_MIO_9_SLEW {slow} \
    CONFIG.PSU_MIO_TREE_PERIPHERALS {Quad SPI Flash#Quad SPI Flash#Quad SPI Flash#Quad SPI Flash#Quad SPI Flash#Quad SPI Flash#SPI 1#GPIO0 MIO#GPIO0 MIO#SPI 1#SPI 1#SPI 1#GPIO0 MIO#SD 0#SD 0#SD 0#SD 0#SD\
0#SD 0#SD 0#SD 0#SD 0#SD 0#SD 0#I2C 1#I2C 1#PMU GPI 0#DPAUX#DPAUX#DPAUX#DPAUX#PMU GPI 5####PMU GPO 3##########################################} \
    CONFIG.PSU_MIO_TREE_SIGNALS {sclk_out#miso_mo1#mo2#mo3#mosi_mi0#n_ss_out#sclk_out#gpio0[7]#gpio0[8]#n_ss_out[0]#miso#mosi#gpio0[12]#sdio0_data_out[0]#sdio0_data_out[1]#sdio0_data_out[2]#sdio0_data_out[3]#sdio0_data_out[4]#sdio0_data_out[5]#sdio0_data_out[6]#sdio0_data_out[7]#sdio0_cmd_out#sdio0_clk_out#sdio0_bus_pow#scl_out#sda_out#gpi[0]#dp_aux_data_out#dp_hot_plug_detect#dp_aux_data_oe#dp_aux_data_in#gpi[5]####gpo[3]##########################################}\
\
    CONFIG.PSU_SD0_INTERNAL_BUS_WIDTH {8} \
    CONFIG.PSU__ACT_DDR_FREQ_MHZ {1066.656006} \
    CONFIG.PSU__CAN1__PERIPHERAL__ENABLE {0} \
    CONFIG.PSU__CRF_APB__ACPU_CTRL__ACT_FREQMHZ {1333.333008} \
    CONFIG.PSU__CRF_APB__ACPU_CTRL__FREQMHZ {1333.333} \
    CONFIG.PSU__CRF_APB__ACPU_CTRL__SRCSEL {APLL} \
    CONFIG.PSU__CRF_APB__ACPU__FRAC_ENABLED {1} \
    CONFIG.PSU__CRF_APB__APLL_CTRL__FRACFREQ {1333.333} \
    CONFIG.PSU__CRF_APB__APLL_CTRL__SRCSEL {PSS_REF_CLK} \
    CONFIG.PSU__CRF_APB__APLL_FRAC_CFG__ENABLED {1} \
    CONFIG.PSU__CRF_APB__DBG_FPD_CTRL__ACT_FREQMHZ {249.997498} \
    CONFIG.PSU__CRF_APB__DBG_FPD_CTRL__FREQMHZ {250} \
    CONFIG.PSU__CRF_APB__DBG_FPD_CTRL__SRCSEL {IOPLL} \
    CONFIG.PSU__CRF_APB__DBG_TRACE_CTRL__FREQMHZ {250} \
    CONFIG.PSU__CRF_APB__DBG_TRACE_CTRL__SRCSEL {IOPLL} \
    CONFIG.PSU__CRF_APB__DBG_TSTMP_CTRL__ACT_FREQMHZ {249.997498} \
    CONFIG.PSU__CRF_APB__DBG_TSTMP_CTRL__FREQMHZ {250} \
    CONFIG.PSU__CRF_APB__DBG_TSTMP_CTRL__SRCSEL {IOPLL} \
    CONFIG.PSU__CRF_APB__DDR_CTRL__ACT_FREQMHZ {533.328003} \
    CONFIG.PSU__CRF_APB__DDR_CTRL__FREQMHZ {1200} \
    CONFIG.PSU__CRF_APB__DDR_CTRL__SRCSEL {DPLL} \
    CONFIG.PSU__CRF_APB__DPDMA_REF_CTRL__ACT_FREQMHZ {444.444336} \
    CONFIG.PSU__CRF_APB__DPDMA_REF_CTRL__FREQMHZ {600} \
    CONFIG.PSU__CRF_APB__DPDMA_REF_CTRL__SRCSEL {APLL} \
    CONFIG.PSU__CRF_APB__DPLL_CTRL__SRCSEL {PSS_REF_CLK} \
    CONFIG.PSU__CRF_APB__DP_AUDIO_REF_CTRL__ACT_FREQMHZ {24.999750} \
    CONFIG.PSU__CRF_APB__DP_AUDIO_REF_CTRL__SRCSEL {RPLL} \
    CONFIG.PSU__CRF_APB__DP_AUDIO__FRAC_ENABLED {0} \
    CONFIG.PSU__CRF_APB__DP_STC_REF_CTRL__ACT_FREQMHZ {26.315527} \
    CONFIG.PSU__CRF_APB__DP_STC_REF_CTRL__SRCSEL {RPLL} \
    CONFIG.PSU__CRF_APB__DP_VIDEO_REF_CTRL__ACT_FREQMHZ {299.997009} \
    CONFIG.PSU__CRF_APB__DP_VIDEO_REF_CTRL__SRCSEL {VPLL} \
    CONFIG.PSU__CRF_APB__DP_VIDEO__FRAC_ENABLED {0} \
    CONFIG.PSU__CRF_APB__GDMA_REF_CTRL__ACT_FREQMHZ {533.328003} \
    CONFIG.PSU__CRF_APB__GDMA_REF_CTRL__FREQMHZ {600} \
    CONFIG.PSU__CRF_APB__GDMA_REF_CTRL__SRCSEL {DPLL} \
    CONFIG.PSU__CRF_APB__GPU_REF_CTRL__ACT_FREQMHZ {499.994995} \
    CONFIG.PSU__CRF_APB__GPU_REF_CTRL__FREQMHZ {600} \
    CONFIG.PSU__CRF_APB__GPU_REF_CTRL__SRCSEL {IOPLL} \
    CONFIG.PSU__CRF_APB__TOPSW_LSBUS_CTRL__ACT_FREQMHZ {99.999001} \
    CONFIG.PSU__CRF_APB__TOPSW_LSBUS_CTRL__FREQMHZ {100} \
    CONFIG.PSU__CRF_APB__TOPSW_LSBUS_CTRL__SRCSEL {IOPLL} \
    CONFIG.PSU__CRF_APB__TOPSW_MAIN_CTRL__ACT_FREQMHZ {533.328003} \
    CONFIG.PSU__CRF_APB__TOPSW_MAIN_CTRL__FREQMHZ {533.33} \
    CONFIG.PSU__CRF_APB__TOPSW_MAIN_CTRL__SRCSEL {DPLL} \
    CONFIG.PSU__CRF_APB__VPLL_CTRL__SRCSEL {PSS_REF_CLK} \
    CONFIG.PSU__CRL_APB__ADMA_REF_CTRL__ACT_FREQMHZ {499.994995} \
    CONFIG.PSU__CRL_APB__ADMA_REF_CTRL__FREQMHZ {500} \
    CONFIG.PSU__CRL_APB__ADMA_REF_CTRL__SRCSEL {IOPLL} \
    CONFIG.PSU__CRL_APB__AMS_REF_CTRL__ACT_FREQMHZ {49.999500} \
    CONFIG.PSU__CRL_APB__CAN1_REF_CTRL__FREQMHZ {100} \
    CONFIG.PSU__CRL_APB__CAN1_REF_CTRL__SRCSEL {IOPLL} \
    CONFIG.PSU__CRL_APB__CPU_R5_CTRL__ACT_FREQMHZ {499.994995} \
    CONFIG.PSU__CRL_APB__CPU_R5_CTRL__FREQMHZ {533.333} \
    CONFIG.PSU__CRL_APB__CPU_R5_CTRL__SRCSEL {RPLL} \
    CONFIG.PSU__CRL_APB__DBG_LPD_CTRL__ACT_FREQMHZ {249.997498} \
    CONFIG.PSU__CRL_APB__DBG_LPD_CTRL__FREQMHZ {250} \
    CONFIG.PSU__CRL_APB__DBG_LPD_CTRL__SRCSEL {IOPLL} \
    CONFIG.PSU__CRL_APB__DLL_REF_CTRL__ACT_FREQMHZ {1499.984985} \
    CONFIG.PSU__CRL_APB__GEM3_REF_CTRL__FREQMHZ {125} \
    CONFIG.PSU__CRL_APB__GEM3_REF_CTRL__SRCSEL {IOPLL} \
    CONFIG.PSU__CRL_APB__I2C0_REF_CTRL__ACT_FREQMHZ {99.999001} \
    CONFIG.PSU__CRL_APB__I2C0_REF_CTRL__FREQMHZ {100} \
    CONFIG.PSU__CRL_APB__I2C0_REF_CTRL__SRCSEL {IOPLL} \
    CONFIG.PSU__CRL_APB__I2C1_REF_CTRL__ACT_FREQMHZ {99.999001} \
    CONFIG.PSU__CRL_APB__I2C1_REF_CTRL__FREQMHZ {100} \
    CONFIG.PSU__CRL_APB__I2C1_REF_CTRL__SRCSEL {IOPLL} \
    CONFIG.PSU__CRL_APB__IOPLL_CTRL__SRCSEL {PSS_REF_CLK} \
    CONFIG.PSU__CRL_APB__IOU_SWITCH_CTRL__ACT_FREQMHZ {249.997498} \
    CONFIG.PSU__CRL_APB__IOU_SWITCH_CTRL__FREQMHZ {250} \
    CONFIG.PSU__CRL_APB__IOU_SWITCH_CTRL__SRCSEL {IOPLL} \
    CONFIG.PSU__CRL_APB__LPD_LSBUS_CTRL__ACT_FREQMHZ {99.999001} \
    CONFIG.PSU__CRL_APB__LPD_LSBUS_CTRL__FREQMHZ {100} \
    CONFIG.PSU__CRL_APB__LPD_LSBUS_CTRL__SRCSEL {IOPLL} \
    CONFIG.PSU__CRL_APB__LPD_SWITCH_CTRL__ACT_FREQMHZ {499.994995} \
    CONFIG.PSU__CRL_APB__LPD_SWITCH_CTRL__FREQMHZ {500} \
    CONFIG.PSU__CRL_APB__LPD_SWITCH_CTRL__SRCSEL {IOPLL} \
    CONFIG.PSU__CRL_APB__PCAP_CTRL__ACT_FREQMHZ {187.498123} \
    CONFIG.PSU__CRL_APB__PCAP_CTRL__FREQMHZ {200} \
    CONFIG.PSU__CRL_APB__PCAP_CTRL__SRCSEL {IOPLL} \
    CONFIG.PSU__CRL_APB__PL0_REF_CTRL__ACT_FREQMHZ {99.999001} \
    CONFIG.PSU__CRL_APB__PL0_REF_CTRL__FREQMHZ {100} \
    CONFIG.PSU__CRL_APB__PL0_REF_CTRL__SRCSEL {IOPLL} \
    CONFIG.PSU__CRL_APB__PL1_REF_CTRL__ACT_FREQMHZ {24.999750} \
    CONFIG.PSU__CRL_APB__PL1_REF_CTRL__FREQMHZ {25} \
    CONFIG.PSU__CRL_APB__PL1_REF_CTRL__SRCSEL {IOPLL} \
    CONFIG.PSU__CRL_APB__PL2_REF_CTRL__ACT_FREQMHZ {499.994995} \
    CONFIG.PSU__CRL_APB__PL2_REF_CTRL__FREQMHZ {500} \
    CONFIG.PSU__CRL_APB__PL2_REF_CTRL__SRCSEL {RPLL} \
    CONFIG.PSU__CRL_APB__PL3_REF_CTRL__ACT_FREQMHZ {99.999001} \
    CONFIG.PSU__CRL_APB__PL3_REF_CTRL__FREQMHZ {100} \
    CONFIG.PSU__CRL_APB__PL3_REF_CTRL__SRCSEL {IOPLL} \
    CONFIG.PSU__CRL_APB__QSPI_REF_CTRL__ACT_FREQMHZ {124.998749} \
    CONFIG.PSU__CRL_APB__QSPI_REF_CTRL__FREQMHZ {125} \
    CONFIG.PSU__CRL_APB__QSPI_REF_CTRL__SRCSEL {IOPLL} \
    CONFIG.PSU__CRL_APB__RPLL_CTRL__SRCSEL {PSS_REF_CLK} \
    CONFIG.PSU__CRL_APB__SDIO0_REF_CTRL__ACT_FREQMHZ {187.498123} \
    CONFIG.PSU__CRL_APB__SDIO0_REF_CTRL__FREQMHZ {200} \
    CONFIG.PSU__CRL_APB__SDIO0_REF_CTRL__SRCSEL {IOPLL} \
    CONFIG.PSU__CRL_APB__SDIO1_REF_CTRL__FREQMHZ {200} \
    CONFIG.PSU__CRL_APB__SDIO1_REF_CTRL__SRCSEL {IOPLL} \
    CONFIG.PSU__CRL_APB__SPI1_REF_CTRL__ACT_FREQMHZ {187.498123} \
    CONFIG.PSU__CRL_APB__SPI1_REF_CTRL__SRCSEL {IOPLL} \
    CONFIG.PSU__CRL_APB__TIMESTAMP_REF_CTRL__ACT_FREQMHZ {99.999001} \
    CONFIG.PSU__CRL_APB__TIMESTAMP_REF_CTRL__FREQMHZ {100} \
    CONFIG.PSU__CRL_APB__TIMESTAMP_REF_CTRL__SRCSEL {IOPLL} \
    CONFIG.PSU__CRL_APB__UART0_REF_CTRL__FREQMHZ {100} \
    CONFIG.PSU__CRL_APB__UART0_REF_CTRL__SRCSEL {IOPLL} \
    CONFIG.PSU__CRL_APB__UART1_REF_CTRL__FREQMHZ {100} \
    CONFIG.PSU__CRL_APB__UART1_REF_CTRL__SRCSEL {IOPLL} \
    CONFIG.PSU__CRL_APB__USB0_BUS_REF_CTRL__FREQMHZ {250} \
    CONFIG.PSU__CRL_APB__USB0_BUS_REF_CTRL__SRCSEL {IOPLL} \
    CONFIG.PSU__CRL_APB__USB3_DUAL_REF_CTRL__FREQMHZ {20} \
    CONFIG.PSU__CRL_APB__USB3_DUAL_REF_CTRL__SRCSEL {IOPLL} \
    CONFIG.PSU__CSUPMU__PERIPHERAL__VALID {1} \
    CONFIG.PSU__DDRC__BG_ADDR_COUNT {1} \
    CONFIG.PSU__DDRC__BRC_MAPPING {ROW_BANK_COL} \
    CONFIG.PSU__DDRC__BUS_WIDTH {64 Bit} \
    CONFIG.PSU__DDRC__CL {16} \
    CONFIG.PSU__DDRC__CLOCK_STOP_EN {0} \
    CONFIG.PSU__DDRC__COMPONENTS {Components} \
    CONFIG.PSU__DDRC__CWL {14} \
    CONFIG.PSU__DDRC__DDR4_ADDR_MAPPING {0} \
    CONFIG.PSU__DDRC__DDR4_CAL_MODE_ENABLE {0} \
    CONFIG.PSU__DDRC__DDR4_CRC_CONTROL {0} \
    CONFIG.PSU__DDRC__DDR4_T_REF_MODE {0} \
    CONFIG.PSU__DDRC__DDR4_T_REF_RANGE {Normal (0-85)} \
    CONFIG.PSU__DDRC__DEVICE_CAPACITY {8192 MBits} \
    CONFIG.PSU__DDRC__DM_DBI {DM_NO_DBI} \
    CONFIG.PSU__DDRC__DRAM_WIDTH {16 Bits} \
    CONFIG.PSU__DDRC__ECC {Disabled} \
    CONFIG.PSU__DDRC__FGRM {1X} \
    CONFIG.PSU__DDRC__LP_ASR {manual normal} \
    CONFIG.PSU__DDRC__MEMORY_TYPE {DDR 4} \
    CONFIG.PSU__DDRC__PARITY_ENABLE {0} \
    CONFIG.PSU__DDRC__PER_BANK_REFRESH {0} \
    CONFIG.PSU__DDRC__PHY_DBI_MODE {0} \
    CONFIG.PSU__DDRC__RANK_ADDR_COUNT {0} \
    CONFIG.PSU__DDRC__ROW_ADDR_COUNT {16} \
    CONFIG.PSU__DDRC__SELF_REF_ABORT {0} \
    CONFIG.PSU__DDRC__SPEED_BIN {DDR4_2400R} \
    CONFIG.PSU__DDRC__STATIC_RD_MODE {0} \
    CONFIG.PSU__DDRC__TRAIN_DATA_EYE {1} \
    CONFIG.PSU__DDRC__TRAIN_READ_GATE {1} \
    CONFIG.PSU__DDRC__TRAIN_WRITE_LEVEL {1} \
    CONFIG.PSU__DDRC__T_FAW {30.0} \
    CONFIG.PSU__DDRC__T_RAS_MIN {33} \
    CONFIG.PSU__DDRC__T_RC {47.06} \
    CONFIG.PSU__DDRC__T_RCD {16} \
    CONFIG.PSU__DDRC__T_RP {16} \
    CONFIG.PSU__DDRC__VREF {1} \
    CONFIG.PSU__DDR_HIGH_ADDRESS_GUI_ENABLE {1} \
    CONFIG.PSU__DDR__INTERFACE__FREQMHZ {600.000} \
    CONFIG.PSU__DISPLAYPORT__LANE0__ENABLE {0} \
    CONFIG.PSU__DISPLAYPORT__LANE1__ENABLE {0} \
    CONFIG.PSU__DISPLAYPORT__PERIPHERAL__ENABLE {1} \
    CONFIG.PSU__DLL__ISUSED {1} \
    CONFIG.PSU__DPAUX__PERIPHERAL__ENABLE {1} \
    CONFIG.PSU__DPAUX__PERIPHERAL__IO {MIO 27 .. 30} \
    CONFIG.PSU__DP__LANE_SEL {None} \
    CONFIG.PSU__FPD_SLCR__WDT1__ACT_FREQMHZ {99.999001} \
    CONFIG.PSU__FPGA_PL0_ENABLE {1} \
    CONFIG.PSU__FPGA_PL1_ENABLE {1} \
    CONFIG.PSU__FPGA_PL2_ENABLE {1} \
    CONFIG.PSU__FPGA_PL3_ENABLE {1} \
    CONFIG.PSU__GPIO0_MIO__IO {MIO 0 .. 25} \
    CONFIG.PSU__GPIO0_MIO__PERIPHERAL__ENABLE {1} \
    CONFIG.PSU__GPIO_EMIO_WIDTH {1} \
    CONFIG.PSU__GPIO_EMIO__WIDTH {[93:0]} \
    CONFIG.PSU__GT__LINK_SPEED {HBR} \
    CONFIG.PSU__GT__PRE_EMPH_LVL_4 {0} \
    CONFIG.PSU__GT__VLT_SWNG_LVL_4 {0} \
    CONFIG.PSU__I2C0__PERIPHERAL__ENABLE {0} \
    CONFIG.PSU__I2C1__PERIPHERAL__ENABLE {1} \
    CONFIG.PSU__I2C1__PERIPHERAL__IO {MIO 24 .. 25} \
    CONFIG.PSU__IOU_SLCR__IOU_TTC_APB_CLK__TTC0_SEL {APB} \
    CONFIG.PSU__IOU_SLCR__IOU_TTC_APB_CLK__TTC1_SEL {APB} \
    CONFIG.PSU__IOU_SLCR__IOU_TTC_APB_CLK__TTC2_SEL {APB} \
    CONFIG.PSU__IOU_SLCR__IOU_TTC_APB_CLK__TTC3_SEL {APB} \
    CONFIG.PSU__IOU_SLCR__TTC0__ACT_FREQMHZ {100.000000} \
    CONFIG.PSU__IOU_SLCR__TTC1__ACT_FREQMHZ {100.000000} \
    CONFIG.PSU__IOU_SLCR__TTC2__ACT_FREQMHZ {100.000000} \
    CONFIG.PSU__IOU_SLCR__TTC3__ACT_FREQMHZ {100.000000} \
    CONFIG.PSU__IOU_SLCR__WDT0__ACT_FREQMHZ {99.999001} \
    CONFIG.PSU__LPD_SLCR__CSUPMU__ACT_FREQMHZ {100.000000} \
    CONFIG.PSU__MAXIGP2__DATA_WIDTH {32} \
    CONFIG.PSU__NUM_FABRIC_RESETS {2} \
    CONFIG.PSU__OVERRIDE__BASIC_CLOCK {0} \
    CONFIG.PSU__PL_CLK0_BUF {TRUE} \
    CONFIG.PSU__PL_CLK1_BUF {TRUE} \
    CONFIG.PSU__PL_CLK2_BUF {TRUE} \
    CONFIG.PSU__PL_CLK3_BUF {TRUE} \
    CONFIG.PSU__PMU_COHERENCY {0} \
    CONFIG.PSU__PMU__AIBACK__ENABLE {0} \
    CONFIG.PSU__PMU__EMIO_GPI__ENABLE {0} \
    CONFIG.PSU__PMU__EMIO_GPO__ENABLE {0} \
    CONFIG.PSU__PMU__GPI0__ENABLE {1} \
    CONFIG.PSU__PMU__GPI0__IO {MIO 26} \
    CONFIG.PSU__PMU__GPI1__ENABLE {0} \
    CONFIG.PSU__PMU__GPI2__ENABLE {0} \
    CONFIG.PSU__PMU__GPI3__ENABLE {0} \
    CONFIG.PSU__PMU__GPI4__ENABLE {0} \
    CONFIG.PSU__PMU__GPI5__ENABLE {1} \
    CONFIG.PSU__PMU__GPI5__IO {MIO 31} \
    CONFIG.PSU__PMU__GPO0__ENABLE {0} \
    CONFIG.PSU__PMU__GPO1__ENABLE {0} \
    CONFIG.PSU__PMU__GPO2__ENABLE {0} \
    CONFIG.PSU__PMU__GPO3__ENABLE {1} \
    CONFIG.PSU__PMU__GPO3__IO {MIO 35} \
    CONFIG.PSU__PMU__GPO3__POLARITY {low} \
    CONFIG.PSU__PMU__GPO4__ENABLE {0} \
    CONFIG.PSU__PMU__GPO5__ENABLE {0} \
    CONFIG.PSU__PMU__PERIPHERAL__ENABLE {1} \
    CONFIG.PSU__PMU__PLERROR__ENABLE {0} \
    CONFIG.PSU__PRESET_APPLIED {1} \
    CONFIG.PSU__PROTECTION__MASTERS {USB1:NonSecure;0|USB0:NonSecure;0|S_AXI_LPD:NA;0|S_AXI_HPC1_FPD:NA;0|S_AXI_HPC0_FPD:NA;0|S_AXI_HP3_FPD:NA;0|S_AXI_HP2_FPD:NA;0|S_AXI_HP1_FPD:NA;0|S_AXI_HP0_FPD:NA;0|S_AXI_ACP:NA;0|S_AXI_ACE:NA;0|SD1:NonSecure;0|SD0:NonSecure;1|SATA1:NonSecure;0|SATA0:NonSecure;0|RPU1:Secure;1|RPU0:Secure;1|QSPI:NonSecure;1|PMU:NA;1|PCIe:NonSecure;0|NAND:NonSecure;0|LDMA:NonSecure;1|GPU:NonSecure;1|GEM3:NonSecure;0|GEM2:NonSecure;0|GEM1:NonSecure;0|GEM0:NonSecure;0|FDMA:NonSecure;1|DP:NonSecure;1|DAP:NA;1|Coresight:NA;1|CSU:NA;1|APU:NA;1}\
\
    CONFIG.PSU__PROTECTION__SLAVES {LPD;USB3_1_XHCI;FE300000;FE3FFFFF;0|LPD;USB3_1;FF9E0000;FF9EFFFF;0|LPD;USB3_0_XHCI;FE200000;FE2FFFFF;0|LPD;USB3_0;FF9D0000;FF9DFFFF;0|LPD;UART1;FF010000;FF01FFFF;0|LPD;UART0;FF000000;FF00FFFF;0|LPD;TTC3;FF140000;FF14FFFF;1|LPD;TTC2;FF130000;FF13FFFF;1|LPD;TTC1;FF120000;FF12FFFF;1|LPD;TTC0;FF110000;FF11FFFF;1|FPD;SWDT1;FD4D0000;FD4DFFFF;1|LPD;SWDT0;FF150000;FF15FFFF;1|LPD;SPI1;FF050000;FF05FFFF;1|LPD;SPI0;FF040000;FF04FFFF;0|FPD;SMMU_REG;FD5F0000;FD5FFFFF;1|FPD;SMMU;FD800000;FDFFFFFF;1|FPD;SIOU;FD3D0000;FD3DFFFF;1|FPD;SERDES;FD400000;FD47FFFF;1|LPD;SD1;FF170000;FF17FFFF;0|LPD;SD0;FF160000;FF16FFFF;1|FPD;SATA;FD0C0000;FD0CFFFF;0|LPD;RTC;FFA60000;FFA6FFFF;1|LPD;RSA_CORE;FFCE0000;FFCEFFFF;1|LPD;RPU;FF9A0000;FF9AFFFF;1|LPD;R5_TCM_RAM_GLOBAL;FFE00000;FFE3FFFF;1|LPD;R5_1_Instruction_Cache;FFEC0000;FFECFFFF;1|LPD;R5_1_Data_Cache;FFED0000;FFEDFFFF;1|LPD;R5_1_BTCM_GLOBAL;FFEB0000;FFEBFFFF;1|LPD;R5_1_ATCM_GLOBAL;FFE90000;FFE9FFFF;1|LPD;R5_0_Instruction_Cache;FFE40000;FFE4FFFF;1|LPD;R5_0_Data_Cache;FFE50000;FFE5FFFF;1|LPD;R5_0_BTCM_GLOBAL;FFE20000;FFE2FFFF;1|LPD;R5_0_ATCM_GLOBAL;FFE00000;FFE0FFFF;1|LPD;QSPI_Linear_Address;C0000000;DFFFFFFF;1|LPD;QSPI;FF0F0000;FF0FFFFF;1|LPD;PMU_RAM;FFDC0000;FFDDFFFF;1|LPD;PMU_GLOBAL;FFD80000;FFDBFFFF;1|FPD;PCIE_MAIN;FD0E0000;FD0EFFFF;0|FPD;PCIE_LOW;E0000000;EFFFFFFF;0|FPD;PCIE_HIGH2;8000000000;BFFFFFFFFF;0|FPD;PCIE_HIGH1;600000000;7FFFFFFFF;0|FPD;PCIE_DMA;FD0F0000;FD0FFFFF;0|FPD;PCIE_ATTRIB;FD480000;FD48FFFF;0|LPD;OCM_XMPU_CFG;FFA70000;FFA7FFFF;1|LPD;OCM_SLCR;FF960000;FF96FFFF;1|OCM;OCM;FFFC0000;FFFFFFFF;1|LPD;NAND;FF100000;FF10FFFF;0|LPD;MBISTJTAG;FFCF0000;FFCFFFFF;1|LPD;LPD_XPPU_SINK;FF9C0000;FF9CFFFF;1|LPD;LPD_XPPU;FF980000;FF98FFFF;1|LPD;LPD_SLCR_SECURE;FF4B0000;FF4DFFFF;1|LPD;LPD_SLCR;FF410000;FF4AFFFF;1|LPD;LPD_GPV;FE100000;FE1FFFFF;1|LPD;LPD_DMA_7;FFAF0000;FFAFFFFF;1|LPD;LPD_DMA_6;FFAE0000;FFAEFFFF;1|LPD;LPD_DMA_5;FFAD0000;FFADFFFF;1|LPD;LPD_DMA_4;FFAC0000;FFACFFFF;1|LPD;LPD_DMA_3;FFAB0000;FFABFFFF;1|LPD;LPD_DMA_2;FFAA0000;FFAAFFFF;1|LPD;LPD_DMA_1;FFA90000;FFA9FFFF;1|LPD;LPD_DMA_0;FFA80000;FFA8FFFF;1|LPD;IPI_CTRL;FF380000;FF3FFFFF;1|LPD;IOU_SLCR;FF180000;FF23FFFF;1|LPD;IOU_SECURE_SLCR;FF240000;FF24FFFF;1|LPD;IOU_SCNTRS;FF260000;FF26FFFF;1|LPD;IOU_SCNTR;FF250000;FF25FFFF;1|LPD;IOU_GPV;FE000000;FE0FFFFF;1|LPD;I2C1;FF030000;FF03FFFF;1|LPD;I2C0;FF020000;FF02FFFF;0|FPD;GPU;FD4B0000;FD4BFFFF;1|LPD;GPIO;FF0A0000;FF0AFFFF;1|LPD;GEM3;FF0E0000;FF0EFFFF;0|LPD;GEM2;FF0D0000;FF0DFFFF;0|LPD;GEM1;FF0C0000;FF0CFFFF;0|LPD;GEM0;FF0B0000;FF0BFFFF;0|FPD;FPD_XMPU_SINK;FD4F0000;FD4FFFFF;1|FPD;FPD_XMPU_CFG;FD5D0000;FD5DFFFF;1|FPD;FPD_SLCR_SECURE;FD690000;FD6CFFFF;1|FPD;FPD_SLCR;FD610000;FD68FFFF;1|FPD;FPD_DMA_CH7;FD570000;FD57FFFF;1|FPD;FPD_DMA_CH6;FD560000;FD56FFFF;1|FPD;FPD_DMA_CH5;FD550000;FD55FFFF;1|FPD;FPD_DMA_CH4;FD540000;FD54FFFF;1|FPD;FPD_DMA_CH3;FD530000;FD53FFFF;1|FPD;FPD_DMA_CH2;FD520000;FD52FFFF;1|FPD;FPD_DMA_CH1;FD510000;FD51FFFF;1|FPD;FPD_DMA_CH0;FD500000;FD50FFFF;1|LPD;EFUSE;FFCC0000;FFCCFFFF;1|FPD;Display\
Port;FD4A0000;FD4AFFFF;1|FPD;DPDMA;FD4C0000;FD4CFFFF;1|FPD;DDR_XMPU5_CFG;FD050000;FD05FFFF;1|FPD;DDR_XMPU4_CFG;FD040000;FD04FFFF;1|FPD;DDR_XMPU3_CFG;FD030000;FD03FFFF;1|FPD;DDR_XMPU2_CFG;FD020000;FD02FFFF;1|FPD;DDR_XMPU1_CFG;FD010000;FD01FFFF;1|FPD;DDR_XMPU0_CFG;FD000000;FD00FFFF;1|FPD;DDR_QOS_CTRL;FD090000;FD09FFFF;1|FPD;DDR_PHY;FD080000;FD08FFFF;1|DDR;DDR_LOW;0;7FFFFFFF;1|DDR;DDR_HIGH;800000000;87FFFFFFF;1|FPD;DDDR_CTRL;FD070000;FD070FFF;1|LPD;Coresight;FE800000;FEFFFFFF;1|LPD;CSU_DMA;FFC80000;FFC9FFFF;1|LPD;CSU;FFCA0000;FFCAFFFF;1|LPD;CRL_APB;FF5E0000;FF85FFFF;1|FPD;CRF_APB;FD1A0000;FD2DFFFF;1|FPD;CCI_REG;FD5E0000;FD5EFFFF;1|LPD;CAN1;FF070000;FF07FFFF;0|LPD;CAN0;FF060000;FF06FFFF;0|FPD;APU;FD5C0000;FD5CFFFF;1|LPD;APM_INTC_IOU;FFA20000;FFA2FFFF;1|LPD;APM_FPD_LPD;FFA30000;FFA3FFFF;1|FPD;APM_5;FD490000;FD49FFFF;1|FPD;APM_0;FD0B0000;FD0BFFFF;1|LPD;APM2;FFA10000;FFA1FFFF;1|LPD;APM1;FFA00000;FFA0FFFF;1|LPD;AMS;FFA50000;FFA5FFFF;1|FPD;AFI_5;FD3B0000;FD3BFFFF;1|FPD;AFI_4;FD3A0000;FD3AFFFF;1|FPD;AFI_3;FD390000;FD39FFFF;1|FPD;AFI_2;FD380000;FD38FFFF;1|FPD;AFI_1;FD370000;FD37FFFF;1|FPD;AFI_0;FD360000;FD36FFFF;1|LPD;AFIFM6;FF9B0000;FF9BFFFF;1|FPD;ACPU_GIC;F9010000;F907FFFF;1}\
\
    CONFIG.PSU__PSS_REF_CLK__FREQMHZ {33.333} \
    CONFIG.PSU__QSPI_COHERENCY {0} \
    CONFIG.PSU__QSPI_ROUTE_THROUGH_FPD {0} \
    CONFIG.PSU__QSPI__GRP_FBCLK__ENABLE {0} \
    CONFIG.PSU__QSPI__PERIPHERAL__DATA_MODE {x4} \
    CONFIG.PSU__QSPI__PERIPHERAL__ENABLE {1} \
    CONFIG.PSU__QSPI__PERIPHERAL__IO {MIO 0 .. 5} \
    CONFIG.PSU__QSPI__PERIPHERAL__MODE {Single} \
    CONFIG.PSU__SD0_COHERENCY {0} \
    CONFIG.PSU__SD0_ROUTE_THROUGH_FPD {0} \
    CONFIG.PSU__SD0__CLK_200_SDR_OTAP_DLY {0x3} \
    CONFIG.PSU__SD0__CLK_50_DDR_ITAP_DLY {0x12} \
    CONFIG.PSU__SD0__CLK_50_DDR_OTAP_DLY {0x6} \
    CONFIG.PSU__SD0__CLK_50_SDR_ITAP_DLY {0x15} \
    CONFIG.PSU__SD0__CLK_50_SDR_OTAP_DLY {0x6} \
    CONFIG.PSU__SD0__DATA_TRANSFER_MODE {8Bit} \
    CONFIG.PSU__SD0__GRP_POW__ENABLE {1} \
    CONFIG.PSU__SD0__GRP_POW__IO {MIO 23} \
    CONFIG.PSU__SD0__PERIPHERAL__ENABLE {1} \
    CONFIG.PSU__SD0__PERIPHERAL__IO {MIO 13 .. 22} \
    CONFIG.PSU__SD0__RESET__ENABLE {1} \
    CONFIG.PSU__SD0__SLOT_TYPE {eMMC} \
    CONFIG.PSU__SPI1__GRP_SS0__IO {MIO 9} \
    CONFIG.PSU__SPI1__GRP_SS1__ENABLE {0} \
    CONFIG.PSU__SPI1__GRP_SS2__ENABLE {0} \
    CONFIG.PSU__SPI1__PERIPHERAL__ENABLE {1} \
    CONFIG.PSU__SPI1__PERIPHERAL__IO {MIO 6 .. 11} \
    CONFIG.PSU__SWDT0__CLOCK__ENABLE {0} \
    CONFIG.PSU__SWDT0__PERIPHERAL__ENABLE {1} \
    CONFIG.PSU__SWDT0__RESET__ENABLE {0} \
    CONFIG.PSU__SWDT1__CLOCK__ENABLE {0} \
    CONFIG.PSU__SWDT1__PERIPHERAL__ENABLE {1} \
    CONFIG.PSU__SWDT1__RESET__ENABLE {0} \
    CONFIG.PSU__TTC0__CLOCK__ENABLE {0} \
    CONFIG.PSU__TTC0__PERIPHERAL__ENABLE {1} \
    CONFIG.PSU__TTC0__WAVEOUT__ENABLE {0} \
    CONFIG.PSU__TTC1__CLOCK__ENABLE {0} \
    CONFIG.PSU__TTC1__PERIPHERAL__ENABLE {1} \
    CONFIG.PSU__TTC1__WAVEOUT__ENABLE {0} \
    CONFIG.PSU__TTC2__CLOCK__ENABLE {0} \
    CONFIG.PSU__TTC2__PERIPHERAL__ENABLE {1} \
    CONFIG.PSU__TTC2__WAVEOUT__ENABLE {0} \
    CONFIG.PSU__TTC3__CLOCK__ENABLE {0} \
    CONFIG.PSU__TTC3__PERIPHERAL__ENABLE {1} \
    CONFIG.PSU__TTC3__WAVEOUT__ENABLE {0} \
    CONFIG.PSU__USE__APU_LEGACY_INTERRUPT {0} \
    CONFIG.PSU__USE__IRQ0 {1} \
    CONFIG.PSU__USE__IRQ1 {1} \
    CONFIG.PSU__USE__M_AXI_GP0 {0} \
    CONFIG.PSU__USE__M_AXI_GP1 {0} \
    CONFIG.PSU__USE__M_AXI_GP2 {1} \
    CONFIG.PSU__USE__RPU_LEGACY_INTERRUPT {0} \
 ] $zynq_ultra_ps_e_0

# create instance: DAPHNE3_0
set daphneVlnv dune.pds:user:DAPHNE3:1.0
set block_cell_name DAPHNE3
if {[catch {set DAPHNE3_0 [create_bd_cell -vlnv $daphneVlnv -type IP $block_cell_name]} errmsg]} {
    puts "ERROR: Failed to add block <$block_cell_name>. Please ensure it is defined and sourced properly before running this script."
    return 1
} elseif { $DAPHNE3_0 eq ""} {
    puts "ERROR: Block <$block_cell_name> could not be found after creation attempt. Check if the IP is available."
    return 1
}
# pass the git commit number as the version value for the configuration of the IP block
set_property CONFIG.version $v_git_sha $DAPHNE3_0

# create instance: smartconnect_0, and set its properties
set smartconnect_0 [create_bd_cell -vlnv xilinx.com:ip:smartconnect:1.0 -type IP smartconnect_0]
set_property -dict [list \
    CONFIG.NUM_CLKS {2} \
    CONFIG.NUM_MI {10} \
    CONFIG.NUM_SI {1} \
] $smartconnect_0

# create instance: SYSTEM_RESET
set SYSTEM_RESET [create_bd_cell -vlnv xilinx.com:ip:proc_sys_reset:5.0 -type IP SYSTEM_RESET]

# create instance: IIC_RESET
set IIC_RESET [create_bd_cell -vlnv xilinx.com:ip:proc_sys_reset:5.0 -type IP IIC_RESET]

# create instance: axi_iic_0
set axi_iic_0 [create_bd_cell -vlnv xilinx.com:ip:axi_iic:2.1 -type IP axi_iic_0]

# create instance: axi_quad_spi_0, and set its properties
set axi_quad_spi_0 [create_bd_cell -vlnv xilinx.com:ip:axi_quad_spi:3.2 -type ip axi_quad_spi_0]
set_property CONFIG.C_BYTE_LEVEL_INTERRUPT_EN {0} $axi_quad_spi_0

# create instance: axi_intc_0, and set its properties
set axi_intc_0 [create_bd_cell -vlnv xilinx.com:ip:axi_intc:4.1 -type IP axi_intc_0]
set_property CONFIG.C_IRQ_CONNECTION {1} $axi_intc_0 

# create instance: xlconcat_0
set xlconcat_0 [create_bd_cell -vlnv xilinx.com:ip:xlconcat:2.1 -type IP xlconcat_0]

# create instance: ila_0, and set its properties
set ila_0 [create_bd_cell -vlnv xilinx.com:ip:ila:6.2 -type IP ila_0]
set_property CONFIG.C_MONITOR_TYPE {Native} $ila_0

# now, connect everything

# start with the interface connections
connect_bd_intf_net -intf_net axi_iic_0_IIC [get_bd_intf_ports IIC_0] [get_bd_intf_pins axi_iic_0/IIC]
connect_bd_intf_net -intf_net smartconnect_0_M00_AXI [get_bd_intf_pins smartconnect_0/M00_AXI] [get_bd_intf_pins DAPHNE3/AFE_SPI_S_AXI]
connect_bd_intf_net -intf_net smartconnect_0_M01_AXI [get_bd_intf_pins smartconnect_0/M01_AXI] [get_bd_intf_pins axi_iic_0/S_AXI]
connect_bd_intf_net -intf_net smartconnect_0_M02_AXI [get_bd_intf_pins smartconnect_0/M02_AXI] [get_bd_intf_pins DAPHNE3/END_P_S_AXI]
connect_bd_intf_net -intf_net smartconnect_0_M03_AXI [get_bd_intf_pins smartconnect_0/M03_AXI] [get_bd_intf_pins DAPHNE3/FRONT_END_S_AXI]
connect_bd_intf_net -intf_net smartconnect_0_M04_AXI [get_bd_intf_pins smartconnect_0/M04_AXI] [get_bd_intf_pins axi_quad_spi_0/AXI_LITE]
connect_bd_intf_net -intf_net smartconnect_0_M05_AXI [get_bd_intf_pins smartconnect_0/M05_AXI] [get_bd_intf_pins DAPHNE3/SPI_DAC_S_AXI]
connect_bd_intf_net -intf_net smartconnect_0_M06_AXI [get_bd_intf_pins smartconnect_0/M06_AXI] [get_bd_intf_pins DAPHNE3/SPY_BUF_S_S_AXI]
connect_bd_intf_net -intf_net smartconnect_0_M07_AXI [get_bd_intf_pins smartconnect_0/M07_AXI] [get_bd_intf_pins DAPHNE3/STUFF_S_AXI]
connect_bd_intf_net -intf_net smartconnect_0_M08_AXI [get_bd_intf_pins smartconnect_0/M08_AXI] [get_bd_intf_pins DAPHNE3/TRIRG_S_AXI]
connect_bd_intf_net -intf_net smartconnect_0_M09_AXI [get_bd_intf_pins axi_intc_0/s_axi] [get_bd_intf_pins smartconnect_0/M09_AXI]
connect_bd_intf_net -intf_net zynq_ultra_ps_e_0_M_AXI_HPM0_LPD [get_bd_intf_pins smartconnect_0/S00_AXI] [get_bd_intf_pins zynq_ultra_ps_e_0/M_AXI_HPM0_LPD]

# and finish connecting the rest of the ports
connect_bd_net -net DAPHNE3_afe0_mosi [get_bd_pins DAPHNE3/afe0_mosi] [get_bd_ports AFE0_SDATA]
connect_bd_net -net DAPHNE3_afe0_sclk [get_bd_pins DAPHNE3/afe0_sclk] [get_bd_ports AFE0_SCLK]
connect_bd_net -net DAPHNE3_afe12_mosi [get_bd_pins DAPHNE3/afe12_mosi] [get_bd_ports AFE12_SDATA]
connect_bd_net -net DAPHNE3_afe12_sclk [get_bd_pins DAPHNE3/afe12_sclk] [get_bd_ports AFE12_SCLK]
connect_bd_net -net DAPHNE3_afe34_mosi [get_bd_pins DAPHNE3/afe34_mosi] [get_bd_ports AFE34_SDATA]
connect_bd_net -net DAPHNE3_afe34_sclk [get_bd_pins DAPHNE3/afe34_sclk] [get_bd_ports AFE34_SCLK]
connect_bd_net -net DAPHNE3_afe_clk_n [get_bd_pins DAPHNE3/afe_clk_n] [get_bd_ports afe_clk_n]
connect_bd_net -net DAPHNE3_afe_clk_p [get_bd_pins DAPHNE3/afe_clk_p] [get_bd_ports afe_clk_p]
connect_bd_net -net DAPHNE3_afe_pdn [get_bd_pins DAPHNE3/afe_pdn] [get_bd_ports AFE_PD]
connect_bd_net -net DAPHNE3_afe_rst [get_bd_pins DAPHNE3/afe_rst] [get_bd_ports AFE_RST]
connect_bd_net -net DAPHNE3_afe_sen [get_bd_pins DAPHNE3/afe_sen] [get_bd_ports afe_sen]
connect_bd_net -net DAPHNE3_cm_csn [get_bd_pins axi_quad_spi_0/ss_o] [get_bd_ports CM_CSn]
connect_bd_net -net DAPHNE3_cm_din [get_bd_pins axi_quad_spi_0/io0_o] [get_bd_ports CM_DIN]
connect_bd_net -net DAPHNE3_cm_sclk [get_bd_pins axi_quad_spi_0/sck_o] [get_bd_ports CM_SCLK]
connect_bd_net -net DAPHNE3_dac_din [get_bd_pins DAPHNE3/dac_din] [get_bd_ports DACS_MOSI]
connect_bd_net -net DAPHNE3_dac_ldac_n [get_bd_pins DAPHNE3/dac_ldac_n] [get_bd_ports DACS_LDACN]
connect_bd_net -net DAPHNE3_dac_sclk [get_bd_pins DAPHNE3/dac_sclk] [get_bd_ports DACS_SCLK]
connect_bd_net -net DAPHNE3_dac_sync_n [get_bd_pins DAPHNE3/dac_sync_n] [get_bd_ports DACS_CS]
connect_bd_net -net DAPHNE3_eth0_tx_dis [get_bd_pins DAPHNE3/eth0_tx_dis] [get_bd_ports SFP_GTH0_TX_DIS]
connect_bd_net -net DAPHNE3_eth0_tx_n [get_bd_pins DAPHNE3/eth0_tx_n] [get_bd_ports TX0_GTH_N]
connect_bd_net -net DAPHNE3_eth0_tx_p [get_bd_pins DAPHNE3/eth0_tx_p] [get_bd_ports TX0_GTH_P]
connect_bd_net -net DAPHNE3_fan_ctrl [get_bd_pins DAPHNE3/fan_ctrl] [get_bd_ports FAN_CONTROL]
connect_bd_net -net DAPHNE3_gth0_debut [get_bd_pins DAPHNE3/gth0_debut] [get_bd_pins ila_0/probe0]
connect_bd_net -net DAPHNE3_hvbias_en [get_bd_pins DAPHNE3/hvbias_en] [get_bd_ports VBIAS_EN]
connect_bd_net -net DAPHNE3_mux_a [get_bd_pins DAPHNE3/mux_a] [get_bd_ports MUXA]
connect_bd_net -net DAPHNE3_mux_en [get_bd_pins DAPHNE3/mux_en] [get_bd_ports MUX_EN]
connect_bd_net -net DAPHNE3_offset_ldac_n [get_bd_pins DAPHNE3/offset_ldac_n] [get_bd_ports offset_ldac_n]
connect_bd_net -net DAPHNE3_offset_sync_n [get_bd_pins DAPHNE3/offset_sync_n] [get_bd_ports offset_sync_n]
connect_bd_net -net DAPHNE3_sfp_tmg_tx_dis [get_bd_pins DAPHNE3/sfp_tmg_tx_dis] [get_bd_ports sfp_tmg_tx_dis]
connect_bd_net -net DAPHNE3_trim_ldac_n [get_bd_pins DAPHNE3/trim_ldac_n] [get_bd_ports trim_ldac_n]
connect_bd_net -net DAPHNE3_trim_sync_n [get_bd_pins DAPHNE3/trim_sync_n] [get_bd_ports trim_sync_n]
connect_bd_net -net DAPHNE3_tx0_tmg_n [get_bd_pins DAPHNE3/tx0_tmg_n] [get_bd_ports tx0_tmg_n]
connect_bd_net -net DAPHNE3_tx0_tmg_p [get_bd_pins DAPHNE3/tx0_tmg_p] [get_bd_ports tx0_tmg_p]
connect_bd_net -net IIC_RESET_peripheral_aresetn [get_bd_pins IIC_RESET/peripheral_aresetn] [get_bd_pins axi_iic_0/s_axi_aresetn]
connect_bd_net -net Net1 [get_bd_pins SYSTEM_RESET/peripheral_aresetn] [get_bd_pins smartconnect_0/aresetn] [get_bd_pins axi_quad_spi_0/s_axi_aresetn] [get_bd_pins axi_intc_0/s_axi_aresetn] [get_bd_pins DAPHNE3/FRONT_END_S_AXI_ARESETN] [get_bd_pins DAPHNE3/SPY_BUF_S_S_AXI_ARESETN] [get_bd_pins DAPHNE3/END_P_S_AXI_ARESETN] [get_bd_pins DAPHNE3/SPI_DAC_S_AXI_ARESETN] [get_bd_pins DAPHNE3/AFE_SPI_S_AXI_ARESETN] [get_bd_pins DAPHNE3/TRIRG_S_AXI_ARESETN] [get_bd_pins DAPHNE3/STUFF_S_AXI_ARESETN]
connect_bd_net -net afe0_miso_0_1 [get_bd_ports AFE0_MISO] [get_bd_pins DAPHNE3/afe0_miso]
connect_bd_net -net afe0_n_0_1 [get_bd_ports afe0_n] [get_bd_pins DAPHNE3/afe0_n]
connect_bd_net -net afe0_p_0_1 [get_bd_ports afe0_p] [get_bd_pins DAPHNE3/afe0_p]
connect_bd_net -net afe12_miso_0_1 [get_bd_ports AFE12_AFE_MISO] [get_bd_pins DAPHNE3/afe12_miso]
connect_bd_net -net afe1_n_0_1 [get_bd_ports afe1_n] [get_bd_pins DAPHNE3/afe1_n]
connect_bd_net -net afe1_p_0_1 [get_bd_ports afe1_p] [get_bd_pins DAPHNE3/afe1_p]
connect_bd_net -net afe2_n_0_1 [get_bd_ports afe2_n] [get_bd_pins DAPHNE3/afe2_n]
connect_bd_net -net afe2_p_0_1 [get_bd_ports afe2_p] [get_bd_pins DAPHNE3/afe2_p]
connect_bd_net -net afe34_miso_0_1 [get_bd_ports AFE34_AFE_MISO] [get_bd_pins DAPHNE3/afe34_miso]
connect_bd_net -net afe3_n_0_1 [get_bd_ports afe3_n] [get_bd_pins DAPHNE3/afe3_n]
connect_bd_net -net afe3_p_0_1 [get_bd_ports afe3_p] [get_bd_pins DAPHNE3/afe3_p]
connect_bd_net -net afe4_n_0_1 [get_bd_ports afe4_n] [get_bd_pins DAPHNE3/afe4_n]
connect_bd_net -net afe4_p_0_1 [get_bd_ports afe4_p] [get_bd_pins DAPHNE3/afe4_p]
connect_bd_net -net axi_iic_0_iic2intc_irpt [get_bd_pins axi_iic_0/iic2intc_irpt] [get_bd_pins xlconcat_0/In0]
connect_bd_net -net axi_intc_0_irq [get_bd_pins axi_intc_0/irq] [get_bd_pins zynq_ultra_ps_e_0/pl_ps_irq0]
connect_bd_net -net axi_quad_spi_0_ip2intc_irpt [get_bd_pins axi_quad_spi_0/ip2intc_irpt] [get_bd_pins xlconcat_0/In1]
connect_bd_net -net cm_dout_0_1 [get_bd_ports CM_DOUT] [get_bd_pins axi_quad_spi_0/io1_i]
connect_bd_net -net eth0_rx_n_0_1 [get_bd_ports RX0_GTH_N] [get_bd_pins DAPHNE3/eth0_rx_n]
connect_bd_net -net eth0_rx_p_0_1 [get_bd_ports RX0_GTH_P] [get_bd_pins DAPHNE3/eth0_rx_p]
connect_bd_net -net eth_clk_n_0_1 [get_bd_ports GTH0_REFCLK_N] [get_bd_pins DAPHNE3/eth_clk_n]
connect_bd_net -net eth_clk_p_0_1 [get_bd_ports GTH0_REFCLK_P] [get_bd_pins DAPHNE3/eth_clk_p]
connect_bd_net -net fan_tach_0_1 [get_bd_ports fan_tach] [get_bd_pins DAPHNE3/fan_tach]
connect_bd_net -net rx0_tmg_n_0_1 [get_bd_ports rx0_tmg_n] [get_bd_pins DAPHNE3/rx0_tmg_n]
connect_bd_net -net rx0_tmg_p_0_1 [get_bd_ports rx0_tmg_p] [get_bd_pins DAPHNE3/rx0_tmg_p]
connect_bd_net -net sfp_tmg_los_0_1 [get_bd_ports sfp_tmg_los] [get_bd_pins DAPHNE3/sfp_tmg_los]
connect_bd_net -net trig_IN_0_1 [get_bd_ports trig_IN] [get_bd_pins DAPHNE3/trig_IN]
connect_bd_net -net xlconcat_0_dout [get_bd_pins xlconcat_0/dout] [get_bd_pins axi_intc_0/intr]
connect_bd_net -net zynq_ultra_ps_e_0_pl_clk0 [get_bd_pins zynq_ultra_ps_e_0/pl_clk0] [get_bd_pins SYSTEM_RESET/slowest_sync_clk] [get_bd_pins smartconnect_0/aclk] [get_bd_pins zynq_ultra_ps_e_0/maxihpm0_lpd_aclk] [get_bd_pins axi_quad_spi_0/s_axi_aclk] [get_bd_pins axi_intc_0/s_axi_aclk] [get_bd_pins DAPHNE3/FRONT_END_S_AXI_ACLK] [get_bd_pins DAPHNE3/SPY_BUF_S_S_AXI_ACLK] [get_bd_pins DAPHNE3/END_P_S_AXI_ACLK] [get_bd_pins DAPHNE3/SPI_DAC_S_AXI_ACLK] [get_bd_pins DAPHNE3/AFE_SPI_S_AXI_ACLK] [get_bd_pins DAPHNE3/TRIRG_S_AXI_ACLK] [get_bd_pins DAPHNE3/STUFF_S_AXI_ACLK]
connect_bd_net -net zynq_ultra_ps_e_0_pl_clk1 [get_bd_pins zynq_ultra_ps_e_0/pl_clk1] [get_bd_pins smartconnect_0/aclk1] [get_bd_pins IIC_RESET/slowest_sync_clk] [get_bd_pins axi_iic_0/s_axi_aclk] [get_bd_pins axi_quad_spi_0/ext_spi_clk]
connect_bd_net -net zynq_ultra_ps_e_0_pl_clk2 [get_bd_pins zynq_ultra_ps_e_0/pl_clk2] [get_bd_pins ila_0/clk]
connect_bd_net -net zynq_ultra_ps_e_0_pl_clk3 [get_bd_pins zynq_ultra_ps_e_0/pl_clk3] [get_bd_pins DAPHNE3/sysclk100]
connect_bd_net -net zynq_ultra_ps_e_0_pl_resetn0 [get_bd_pins zynq_ultra_ps_e_0/pl_resetn0] [get_bd_pins SYSTEM_RESET/ext_reset_in]
connect_bd_net -net zynq_ultra_ps_e_0_pl_resetn1 [get_bd_pins zynq_ultra_ps_e_0/pl_resetn1] [get_bd_pins IIC_RESET/ext_reset_in]

# create address segments
assign_bd_address -offset 0x80000000 -range 0x04000000 -target_address_space [get_bd_addr_spaces zynq_ultra_ps_e_0/Data] [get_bd_addr_segs DAPHNE3/AFE_SPI_S_AXI/reg0] -force
assign_bd_address -offset 0x84000000 -range 0x04000000 -with_name SEG_DAPHNE3_reg0_1 -target_address_space [get_bd_addr_spaces zynq_ultra_ps_e_0/Data] [get_bd_addr_segs DAPHNE3/END_P_S_AXI/reg0] -force
assign_bd_address -offset 0x88000000 -range 0x04000000 -with_name SEG_DAPHNE3_reg0_2 -target_address_space [get_bd_addr_spaces zynq_ultra_ps_e_0/Data] [get_bd_addr_segs DAPHNE3/FRONT_END_S_AXI/reg0] -force
assign_bd_address -offset 0x8C000000 -range 0x04000000 -with_name SEG_DAPHNE3_reg0_3 -target_address_space [get_bd_addr_spaces zynq_ultra_ps_e_0/Data] [get_bd_addr_segs DAPHNE3/SPI_DAC_S_AXI/reg0] -force
assign_bd_address -offset 0x90000000 -range 0x04000000 -with_name SEG_DAPHNE3_reg0_4 -target_address_space [get_bd_addr_spaces zynq_ultra_ps_e_0/Data] [get_bd_addr_segs DAPHNE3/SPY_BUF_S_S_AXI/reg0] -force
assign_bd_address -offset 0x94000000 -range 0x04000000 -with_name SEG_DAPHNE3_reg0_5 -target_address_space [get_bd_addr_spaces zynq_ultra_ps_e_0/Data] [get_bd_addr_segs DAPHNE3/STUFF_S_AXI/reg0] -force
assign_bd_address -offset 0x98000000 -range 0x04000000 -with_name SEG_DAPHNE3_reg0_6 -target_address_space [get_bd_addr_spaces zynq_ultra_ps_e_0/Data] [get_bd_addr_segs DAPHNE3/TRIRG_S_AXI/reg0] -force
assign_bd_address -offset 0x9C000000 -range 0x00010000 -target_address_space [get_bd_addr_spaces zynq_ultra_ps_e_0/Data] [get_bd_addr_segs axi_iic_0/S_AXI/Reg] -force
assign_bd_address -offset 0x9C010000 -range 0x00010000 -target_address_space [get_bd_addr_spaces zynq_ultra_ps_e_0/Data] [get_bd_addr_segs axi_intc_0/S_AXI/Reg] -force
assign_bd_address -offset 0x9C020000 -range 0x00010000 -target_address_space [get_bd_addr_spaces zynq_ultra_ps_e_0/Data] [get_bd_addr_segs axi_quad_spi_0/AXI_LITE/Reg] -force

# create PFM attributes
set_property PFM_NAME {xilinx:k26c:name:0.0} [get_files [current_bd_design].bd]
set_property PFM.AXI_PORT {M_AXI_HPM1_FPD { memport "M_AXI_GP" sptag "" memory "" is_range "false" } S_AXI_HP0_FPD { memport "S_AXI_HP" sptag "HP0" memory "" is_range "false" } S_AXI_HP1_FPD { memport "S_AXI_HP" sptag "HP1" memory "" is_range "false" } S_AXI_HP2_FPD { memport "S_AXI_HP" sptag "HP2" memory "" is_range "false" } S_AXI_HP3_FPD { memport "S_AXI_HP" sptag "HP3" memory "" is_range "false" } S_AXI_HPC0_FPD { memport "S_AXI_HPC" sptag "HPC0" memory "" is_range "false" } S_AXI_HPC1_FPD { memport "S_AXI_HPC" sptag "HPC1" memory "" is_range "false" } S_AXI_LPD { memport "MIG" sptag "" memory "" is_range "false" } } [get_bd_cells /zynq_ultra_ps_e_0]
set_property PFM.CLOCK {pl_clk0 {id "2" is_default "true" proc_sys_reset "/SYSTEM_RESET" status "fixed" freq_hz "99999001"}} [get_bd_cells /zynq_ultra_ps_e_0]

# once done, regenerate layout so that it looks clean
regenerate_bd_layout

# check the integrity of the block design
validate_bd_design 

# store it
save_bd_design