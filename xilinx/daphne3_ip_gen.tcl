# elaborated TCL script file to package DAPHNE3 sources into a Local reusable User IP
# the script generates the .xml file needed to import DAPHNE to a Block Design, within the In-Memory Project
# <daniel.avila@eia.edu.co - daniel.avila.gomez@cern.ch>

# set project properties
set_part xck26-sfvc784-2LV-c
set_property BOARD_PART xilinx.com:k26c:part0:1.4 [current_project]
set_property TARGET_LANGUAGE VHDL [current_project]
set_property DEFAULT_LIB work [current_project]

# create a proc because this same process is going to be used multiple times around the IP packaging
# proc that searches for all the files inside a directory recursively
proc get_files_recursive {dir type} {
    set results {}
    foreach file [glob -nocomplain -directory $dir *] {
        if {[file isdirectory $file]} {
            # recurse into subdirectories
            set sub_results [get_files_recursive $file $type]
            set results [concat $results $sub_results]
        } elseif {[string match $type [file tail $file]]} {
            lappend results $file
        }
    }
    return $results
}

# create a proc in order to eliminate specific files from the generated lists
# this applies currently to full file name including extension, but not full path
proc ignore_files {listToVerify itemsToIgnore} {
    # define the empty list to return with the items ignored
    set newList {}

    # populate the list based on condition
    foreach item $listToVerify {
        set skip 0
        foreach ignore $itemsToIgnore {
            if {[string match $ignore [file tail $item]]} {
                set skip 1
                break 
            }
        }
        if {!$skip} {
            lappend newList $item
        }
    }    
    return $newList
}

# create a proc in order to find the latest version of an IP definition int he catalog
# that matche the IP that is intended to be created
proc get_latest_ip_vlnv {ipSel} {
    # get all the IP definitions that match
    set ipDefs [get_ipdefs -all $ipSel]
    set latestIPVersion ""
    set latestIPvlnv ""

    # get versions and compare
    foreach ipdef $ipDefs {
        # find the version element of each IP definition that matches the search
        set ipVersion [lindex [split $ipdef ":"] 3]

        # set the latest version available for this IP
        if { $latestIPvlnv eq "" || [expr {[string compare -nocase $ipVersion $latestIPVersion] > 0}]} {
            set latestIPvlnv $ipdef
            set latestIPVersion $ipVersion
        }
    }
    return $latestIPvlnv
}

# set DAPHNE IP parameters
set componentVendor dune.pds
set componentLibrary user
set componentIdentifier DAPHNE3
set componentVersion 1.0
set daphneDescription {IP Version of DAPHNEv3 PL Firmware for the PDS in the DUNE Project}

# set repository for the DAPHNE IP
set ipRepoDir ../ip_repo/daphne3_ip

# # set repository for the AXI Quad SPI IP Unused
# set axiQuadDir ../ip_repo/daphne3_ip/ips/cm
# set axiQuadXCIDir ../ip_repo/daphne3_ip/ips/cm/axi_quad_spi_0.xci

# # set repository for the AXI IIC IP Unused
# set axiIICDir ../ip_repo/daphne3_ip/ips/i2c
# set axiIICXCIDir ../ip_repo/daphne3_ip/ips/i2c/axi_iic_0.xci

# set repository for BRAM controller IP axi4_lite_bram_ctrl_0
set bramRepoDir ../ip_repo/daphne3_ip/src/dune.daq_user_hermes_daphne_1.0/src
set bramXCIDir ../ip_repo/daphne3_ip/src/dune.daq_user_hermes_daphne_1.0/src/axi4_lite_bram_ctrl_0/axi4_lite_bram_ctrl_0.xci

# set repository for Ethernet IP
set ethernetRepoDir ../ip_repo/daphne3_ip/src/dune.daq_user_hermes_daphne_1.0/src
set ethXCIDir ../ip_repo/daphne3_ip/src/dune.daq_user_hermes_daphne_1.0/src/xxv_ethernet_0/xxv_ethernet_0.xci

# # build the internal sub IPs used in the design
# # axi quad SPI IP
# if {![file exists $axiQuadXCIDir]} {
#     puts "Creating IP AXI Quad SPI..."
#     set axiQuadIP [create_ip -vlnv xilinx.com:ip:axi_quad_spi:* -module_name axi_quad_spi_0 -dir $axiQuadDir]
#     # configure IP properties
#     set_property -dict [list \
#         CONFIG.C_NUM_TRANSFER_BITS {32} \
#         CONFIG.Async_Clk {1} \
#     ] [get_ips axi_quad_spi_0]
# } else {
#     puts "IP 'AXI Quad SPI' already exists at $axiQuadXCIDir. Skipping creation."
# }

# # axi iic IP
# if {![file exists $axiIICXCIDir]} {
#     puts "Creating IP AXI IIC..."
#     set axiIICIP [create_ip -vlnv xilinx.com:ip:axi_iic:* -module_name axi_iic_0 -dir $axiIICDir]
#     # configure IP properties
#     set_property CONFIG.AXI_ACLK_FREQ_MHZ {100} [get_ips axi_iic_0]
# } else {
#     puts "IP 'AXI IIC' already exists at $axiIICXCIDir. Skipping creation."
# }

set axi_bram_ctrl_vlnv [get_latest_ip_vlnv xilinx.com:ip:axi_bram_ctrl:*]
set xxv_ethernet_vlnv [get_latest_ip_vlnv xilinx.com:ip:xxv_ethernet:*]

# block RAM IP
if {![file exists $bramXCIDir]} {
    puts "Creating IP AXI BRAM Control..."
    set axi4LitBramIP [create_ip -vlnv $axi_bram_ctrl_vlnv -module_name axi4_lite_bram_ctrl_0 -dir $bramRepoDir]
    # configure IP properties  
    set_property -dict [list \
        CONFIG.PROTOCOL {AXI4LITE} \
        CONFIG.MEM_DEPTH {16384} \
    ] [get_ips axi4_lite_bram_ctrl_0]
    set_property GENERATE_SYNTH_CHECKPOINT FALSE $axi4LitBramIP
} else {
    puts "IP 'AXI BRAM Control' already exists at $bramXCIDir. Skipping creation."
}

# ethernet IP
if {![file exists $ethXCIDir]} {
    puts "Creating IP XXV Ethernet..."
    set xxvEthernetIP [create_ip -vlnv $xxv_ethernet_vlnv -module_name xxv_ethernet_0 -dir $ethernetRepoDir]
    # configure IP properties
    set_property -dict [list \
        CONFIG.CORE {Ethernet PCS/PMA 64-bit} \
        CONFIG.BASE_R_KR {BASE-R} \
        CONFIG.INCLUDE_AXI4_INTERFACE {0} \
        CONFIG.INCLUDE_STATISTICS_COUNTERS {0} \
        CONFIG.INCLUDE_SHARED_LOGIC {0} \
    ] [get_ips xxv_ethernet_0]
    set_property GENERATE_SYNTH_CHECKPOINT FALSE $xxvEthernetIP
} else {
    puts "IP 'XXV Ethernet' already exists at $ethXCIDir. Skipping creation."
}

# build DAPHNE IP
set daphne [ipx::create_core -set_current TRUE $componentVendor $componentLibrary $componentIdentifier $componentVersion]

# configure IP properties
# set_property AUTO_FAMILY_SUPPORT_LEVEL level_1 $daphne 
set_property CORE_REVISION 1 $daphne 
set_property DEFINITION_SOURCE package_project $daphne 
set_property DESCRIPTION $daphneDescription $daphne
# set_property DESIGN_TOOL_CONTEXTS IPI $daphne 
set_property DISPLAY_NAME DAPHNE3_v1_0 $daphne
set_property ROOT_DIRECTORY $ipRepoDir $daphne
set_property SUPPORTED_FAMILIES {zynquplus Production} $daphne 
# set_property SUPPORTS_AUTO_XDC dynamic_params $daphne 
set_property TAXONOMY /UserIP $daphne 
# set_property VENDOR_DISPLAY_NAME {Xilinx, Inc.} $daphne 
# set_property XPM_LIBRARIES {XPM_CDC XPM_FIFO XPM_MEMORY} $daphne

# create file groups for the IP

# RTL file groups
set lang_synth [ipx::add_file_group xilinx_anylanguagesynthesis $daphne]
set_property LANGUAGE VHDL $lang_synth
set_property MODEL_NAME $componentIdentifier $lang_synth

# Behavioral simulation file groups
set lang_sim [ipx::add_file_group xilinx_anylanguagebehavioralsimulation $daphne]
set_property LANGUAGE VHDL $lang_sim
set_property MODEL_NAME $componentIdentifier $lang_sim 

# # Testbench file groups (Unused, not necessary for IP packaging)
# set lang_tb [ipx::add_file_group xilinx_testbench $daphne]

# # Constraints file groups (Unused, not adequate for this IP packaging)
# set synth_constraints_files [ipx::add_file_group xilinx_synthesisconstraints $daphne] 
# set impl_constraints_files [ipx::add_file_group xilinx_implementationconstraints $daphne]

# Implementation file groups
set impl_files [ipx::add_file_group xilinx_implementation $daphne]
set_property MODEL_NAME $componentIdentifier $impl_files

# XPGUI file groups
set xpgui_files [ipx::add_file_group xilinx_xpgui $daphne]

# External files, only if want to add READMEs, Python scripts, etc.
# set miscExternalFiles [ipx::add_file_group xilinx_externalfiles $daphne]

# list IP VLNVs
set ipVlnv [list $axi_bram_ctrl_vlnv $xxv_ethernet_vlnv]

# Sub IP file groups
foreach ipChoice $ipVlnv {
    # add each IP subcore to respective file groups
    set ipChoiceSynth [ipx::add_subcore $ipChoice $lang_synth]
    set ipChoiceSim [ipx::add_subcore $ipChoice $lang_sim]
    set ipChoiceImpl [ipx::add_subcore $ipChoice $impl_files]

    # set properties, meaning we are creating the .xci files
    set_property COPY_MODE FALSE $ipChoiceSynth
    set_property COPY_MODE FALSE $ipChoiceSim
    set_property COPY_MODE FALSE $ipChoiceImpl
    set_property CREATE_MODE TRUE $ipChoiceSynth
    set_property CREATE_MODE TRUE $ipChoiceSim
    set_property CREATE_MODE TRUE $ipChoiceImpl
}

# set the path to sources
set rtlDir [file normalize "../ip_repo/daphne3_ip/rtl"]
set tbDir [file normalize "../ip_repo/daphne3_ip/sim"]
set constDir [file normalize "../ip_repo/daphne3_ip/constraints"]
set xciDir [file normalize "../ip_repo/daphne3_ip/ips"]
set rtlDAQDir [file normalize "../ip_repo/daphne3_ip/src/dune.daq_user_hermes_daphne_1.0/src"]
set constDAQDir [file normalize "../ip_repo/daphne3_ip/src/dune.daq_user_hermes_daphne_1.0/src"]
set tclConstDir [file normalize "../ip_repo/daphne3_ip/src/dune.daq_user_hermes_daphne_1.0/src"]

# obtain all of the rtl files (.vhdl .vhd .v .sv) of the project for later inclusion in the IP design

# generate file lists
set xciFiles [get_files_recursive $xciDir "*.xci"]
set xciDAQFiles_aux [get_files_recursive $rtlDAQDir "*.xci"]
set xciDAQFiles [ignore_files $xciDAQFiles_aux "xxv_ethernet_0_gt.xci"]

set vhdlFiles_aux [get_files_recursive $rtlDir "*.vhd"]
set vhdlFiles [ignore_files $vhdlFiles_aux {"daphne3.vhd" "auto_afe.vhd" "auto_fsm.vhd" "i2cm.vhd" "spim_cm.vhd" "DAQ_CLOCKS.vhd" }]
set verilogFiles [get_files_recursive $rtlDir "*.v"]

set tbFilesVhdl [get_files_recursive $tbDir "*.vhd"]
set tbFilesVerilog [get_files_recursive $tbDir "*.v"]

set vhdlDAQFiles [get_files_recursive $rtlDAQDir "*.vhd"]
set verilogDAQFiles [get_files_recursive $rtlDAQDir "*.v"]
# define the vhdl sources that use vhdl Source by default as type, the rest use whdl source 2008 version
set wibTypeExceptionList {
    "freq_ctr_div.vhd"
    "ipbus_package.vhd"
    "ipbus_axi4lite_decl.vhd"
    "ipbus_clock_div.vhd"
    "ipbus_reg_types.vhd"
    "ipbus_ctrlreg_v.vhd"
    "ipbus_fabric_sel.vhd"
    "ipbus_freq_ctr.vhd"
    "ipbus_roreg_v.vhd"
    "ipbus_trans_decl.vhd"
    "transactor_if.vhd"
    "transactor_sm.vhd"
    "transactor_cfg.vhd"
    "transactor.vhd"
}

set constraintsFiles_aux [get_files_recursive $constDir "*.xdc"]
set constraintsFiles [ignore_files $constraintsFiles_aux "DAPHNE_V3_PIN_MAP.xdc"]
set constraintsDAQFiles [get_files_recursive $constDAQDir "*.tcl"]

set tclFiles [get_files_recursive $tclConstDir "*.tcl"]

# add each file to its respective category in the IP core
# start with constraints, then .tcl files, then .xci files, and at alst, .vhd .v .sv sources

# # Constraints files (They seem to not be used by the project at all, must check later)
# foreach constraint $constraintsFiles {
#     ipx::add_file -name $constraint -file_group $lang_synth
# }

# TCL Constraints files
foreach tclSource $tclFiles {
    ipx::add_file -name $tclSource -file_group $impl_files
}

# IP XCI files
foreach ipType $xciFiles {
    ipx::add_file -name $ipType -file_group $lang_synth
    ipx::add_file -name $ipType -file_group $lang_sim
}

# 10Gig Sender XCI files
foreach daqIPType $xciDAQFiles {
    ipx::add_file -name $daqIPType -file_group $lang_synth
    ipx::add_file -name $daqIPType -file_group $lang_sim
}

# ethernet sub core must be in implementation files group
ipx::add_file -name [file normalize "../ip_repo/daphne3_ip/src/dune.daq_user_hermes_daphne_1.0/src/xxv_ethernet_0/xxv_ethernet_0.xci"] -file_group $impl_files

# # obtain the specific .xci files
set anylanguageSynthFg [ipx::get_file_groups xilinx_anylanguagesynthesis -of_objects $daphne]
set anybehavioralSynthFg [ipx::get_file_groups xilinx_anylanguagebehavioralsimulation -of_objects $daphne]
set implFg [ipx::get_file_groups xilinx_implementation -of_objects $daphne]
set ethFileObjLan [ipx::get_files "src/dune.daq_user_hermes_daphne_1.0/src/xxv_ethernet_0/xxv_ethernet_0.xci" -of_objects $anylanguageSynthFg]
set bramFileObjLan [ipx::get_files "src/dune.daq_user_hermes_daphne_1.0/src/axi4_lite_bram_ctrl_0/axi4_lite_bram_ctrl_0.xci" -of_objects $anylanguageSynthFg]
set ethFileObjSim [ipx::get_files "src/dune.daq_user_hermes_daphne_1.0/src/xxv_ethernet_0/xxv_ethernet_0.xci" -of_objects $anybehavioralSynthFg]
set bramFileObjSim [ipx::get_files "src/dune.daq_user_hermes_daphne_1.0/src/axi4_lite_bram_ctrl_0/axi4_lite_bram_ctrl_0.xci" -of_objects $anybehavioralSynthFg]
set implFileObj [ipx::get_files "src/dune.daq_user_hermes_daphne_1.0/src/xxv_ethernet_0/xxv_ethernet_0.xci" -of_objects $implFg]

# set property for cell name
set_property CELL_NAME core_inst/daphne_top_inst/mux/pcs_pma/phy_gen[0].phy_10gbe $ethFileObjLan
set_property CELL_NAME core_inst/daphne_top_inst/ipb_ctrl/ipbus_transport_axil/axi_bram_ctrl $bramFileObjLan
set_property CELL_NAME core_inst/daphne_top_inst/mux/pcs_pma/phy_gen[0].phy_10gbe $ethFileObjSim
set_property CELL_NAME core_inst/daphne_top_inst/ipb_ctrl/ipbus_transport_axil/axi_bram_ctrl $bramFileObjSim
set_property CELL_NAME core_inst/daphne_top_inst/mux/pcs_pma/phy_gen[0].phy_10gbe $implFileObj

# VHDL files
foreach vhdlType $vhdlFiles {
    ipx::add_file -name $vhdlType -file_group $lang_synth
    ipx::add_file -name $vhdlType -file_group $lang_sim
}

# Verilog files
foreach verilogType $verilogFiles {
    ipx::add_file -name $verilogType -file_group $lang_synth
    ipx::add_file -name $verilogType -file_group $lang_sim
}

# 10Gig Sender VHDL files
foreach daqVhdlType $vhdlDAQFiles {
    set fileObjSynth [ipx::add_file -name $daqVhdlType -file_group $lang_synth]
    set fileObjSim [ipx::add_file -name $daqVhdlType -file_group $lang_sim]
    
    # obtain only the file name of the file that was added
    set fileName [file tail $daqVhdlType]

    # if it is not in the exception list, set its property to vhdl 2008
    if {[lsearch -exact $wibTypeExceptionList $fileName] == -1} {
        set_property TYPE {vhdlSource-2008} $fileObjSynth 
        set_property TYPE {vhdlSource-2008} $fileObjSim
    }
}

# 10Gig Sender Verilog files
foreach daqVerilogType $verilogDAQFiles {
    ipx::add_file -name $daqVerilogType -file_group $lang_synth
    ipx::add_file -name $daqVerilogType -file_group $lang_sim
}

# # VHDL Testbench files (Unused files, not needed for IP packaging)
# foreach vhdlTb $tbFilesVhdl {
#     ipx::add_file -name $vhdlTb -file_group $lang_tb
#     ipx::add_file -name $vhdlTb -file_group $lang_sim
# }

# # Verilog Testbench files (Unused files, not needed for IP packaging)
# foreach verilogTb $tbFilesVerilog {
#     ipx::add_file -name $verilogTb -file_group $lang_tb
#     ipx::add_file -name $verilogTb -file_group $lang_sim
# }

# remember DAPHNE's top file is VHDL!
# must be added last in order to let Vivado packager know it is top
ipx::add_file -name [file normalize "../ip_repo/daphne3_ip/rtl/daphne3.vhd"] -file_group $lang_synth
ipx::add_file -name [file normalize "../ip_repo/daphne3_ip/rtl/daphne3.vhd"] -file_group $lang_sim
# make it top in hierarchy, just in case
set_property TOP daphne3 [current_fileset]

# update ip checksums 
ipx::update_checksums $daphne

# create the ports based on the TOP level design and the subcores
set daphne_ports [ipx::add_ports_from_hdl -top_level_hdl_file [file normalize "../ip_repo/daphne3_ip/rtl/daphne3.vhd"] -top_module_name DAPHNE3 -include_dirs [file normalize "../ip_repo/daphne3_ip/rtl"] $daphne]

# create the generic parameters of the design based on the TOP level generic
set daphne_generics [ipx::add_model_parameters_from_hdl -top_level_hdl_file [file normalize "../ip_repo/daphne3_ip/rtl/daphne3.vhd"] -top_module_name DAPHNE3 -include_dirs [file normalize "../ip_repo/daphne3_ip/rtl"] $daphne]
set_property DISPLAY_NAME Version [ipx::get_hdl_parameters -of_objects $daphne]
set_property VALUE_RESOLVE_TYPE user [ipx::get_hdl_parameters -of_objects $daphne]

set version_param [ipx::add_user_parameter version $daphne]
set_property DISPLAY_NAME Version $version_param
set_property VALUE 0x1234567 $version_param
set_property VALUE_BIT_STRING_LENGTH 28 $version_param
set_property VALUE_FORMAT bitString $version_param
set_property VALUE_RESOLVE_TYPE user $version_param
set_property VALUE_PERMISSION user $version_param

# list all the bus names used in the core
set daphne_bus_interfaces {
    AFE_SPI_S_AXI
    END_P_S_AXI
    FRONT_END_S_AXI
    SPI_DAC_S_AXI
    SPY_BUF_S_S_AXI
    STUFF_S_AXI
    TRIRG_S_AXI
}

# list all possible ports used in axi4 lite interface
set daphne_bus_port_map {
    AWADDR
    AWPROT
    AWVALID 
    AWREADY 
    WDATA 
    WSTRB 
    WVALID 
    WREADY 
    BRESP 
    BVALID 
    BREADY 
    ARADDR 
    ARPROT 
    ARVALID 
    ARREADY 
    RDATA 
    RRESP 
    RVALID 
    RREADY
}

# set specific driver values for AXI interface's ports
set daphne_port_driver {
    AWADDR 0
    AWPROT 0
    AWVALID 0
    WDATA 0
    WSTRB 1
    WVALID 0
    BREADY 0
    ARADDR 0
    ARPROT 0
    ARVALID 0
    RREADY 0
}

# list all possible parameters for each bus interface
set daphne_bus_parameters {
    DATA_WIDTH 32 
    PROTOCOL AXI4LITE
    FREQ_HZ 99999001
    ID_WIDTH 0
    ADDR_WIDTH 32
    AWUSER_WIDTH 0
    ARUSER_WIDTH 0
    WUSER_WIDTH 0
    RUSER_WIDTH 0
    BUSER_WIDTH 0
    READ_WRITE_MODE READ_WRITE
    HAS_BURST 0
    HAS_LOCK 0
    HAS_PROT 1
    HAS_CACHE 0
    HAS_QOS 0
    HAS_REGION 0
    HAS_WSTRB 1
    HAS_BRESP 1
    HAS_RRESP 1
    SUPPORTS_NARROW_BURST 0
    NUM_READ_OUTSTANDING 1
    NUM_WRITE_OUTSTANDING 1
    MAX_BURST_LENGTH 1
    PHASE 0.0
    CLK_DOMAIN DAPHNE_V3_F4_3_zynq_ultra_ps_e_0_0_pl_clk0
    NUM_READ_THREADS 1
    NUM_WRITE_THREADS 1
    RUSER_BITS_PER_BYTE 0
    WUSER_BITS_PER_BYTE 0
    INSERT_VIP 0
}

# list all possible reset parameters
set daphne_rst_parameters {
    POLARITY ACTIVE_LOW
}
# set daphne_rst_parameters {
#     POLARITY ACTIVE_LOW
#     INSERT_VIP 0
# }

# list all possible clock parameters
set daphne_clk_parameters {
    FREQ_HZ 99999001
}
# set daphne_clk_parameters {
#     FREQ_HZ 99999001
#     FREQ_TOLERANCE_HZ 0
#     PHASE 0.0
#     CLK_DOMAIN DAPNHE_V3_F4_3_zynq_ultra_ps_e_0_0_pl_clk0
#     ASSOCIATED_PORT {}
#     INSERT_VIP 0
# }

# daphne PL specific clock interfaces
set daphne_pl_clk_interfaces {
    afe_clk_n
    afe_clk_p
    eth_clk_n
    eth_clk_p
}

# list all possible parameters for the daphne PL clock interfaces
set daphne_pl_clk_parameters {
    FREQ_HZ 100000000
}
# set daphne_pl_clk_parameters {
#     FREQ_HZ 100000000
#     FREQ_TOLERANCE_HZ 0
#     PHASE 0.0
#     CLK_DOMAIN DAPHNE_V3_F4_3_DAPHNE3_0_0
#     ASSOCIATED_BUSIF {}
#     ASSOCIATED_PORT {}
#     ASSOCIATED_RESET {}
#     INSERT_VIP 0
# }

# set driver property for each port in each interface
foreach daphneInterfaceName $daphne_bus_interfaces {
    # change some properties that are not added by default to specific ports
    foreach {daphnePort daphnePortVal} $daphne_port_driver {
        set_property DRIVER_VALUE $daphnePortVal [ipx::get_ports ${daphneInterfaceName}_${daphnePort} -of_objects $daphne]
    }
}

# create all bus interfaces with respective ports and parameters
foreach axiBusInterface $daphne_bus_interfaces {
    # add bus interface
    set busAxi [ipx::add_bus_interface $axiBusInterface $daphne]

    # add bus properties
    set_property ABSTRACTION_TYPE_VLNV xilinx.com:interface:aximm_rtl:1.0 $busAxi
    set_property BUS_TYPE_VLNV xilinx.com:interface:aximm:1.0 $busAxi
    set_property INTERFACE_MODE slave $busAxi
    set_property SLAVE_MEMORY_MAP_REF $axiBusInterface $busAxi

    # create the port map for each port of the interface
    foreach axiBusPortName $daphne_bus_port_map {
        set axi_pm [ipx::add_port_map -name $axiBusPortName -bus_interface $busAxi]
        set_property PHYSICAL_NAME ${axiBusInterface}_${axiBusPortName} $axi_pm
    }

    # # set the bus parameters
    # foreach {axiBusParam axiBusParamVal} $daphne_bus_parameters {
    #     set axi_param [ipx::add_bus_parameter $axiBusParam $busAxi]
    #     set_property VALUE $axiBusParamVal $axi_param   

    #     # configure USAGE and VALUE_RESOLVE_TYPE properties, they are almost all the same unless for the INSERT_VIP parameter
    #     if {$axiBusParam eq "INSERT_VIP"} {
    #         set_property USAGE simulation.rtl $axi_param
    #         set_property VALUE_RESOLVE_TYPE user $axi_param
    #     } else {
    #         set_property USAGE none $axi_param
    #         set_property VALUE_RESOLVE_TYPE generated $axi_param
    #     }

    #     # configure VALUE_FORMAT property, if the value is a string, do not change the property, if it is an integer set long, 
    #     # if is a real set float
    #     if {[string is integer -strict $axiBusParamVal]} {
    #         set_property VALUE_FORMAT long $axi_param
    #     } elseif {[string is double -strict $axiBusParamVal]} {
    #         set_property VALUE_FORMAT float $axi_param
    #     } else {
    #         set_property VALUE_FORMAT string $axi_param
    #     }
    # }
}

# create all reset interfaces for each bus interface
foreach axiBusInterface_rst $daphne_bus_interfaces {
    # add respective reset interface
    set rstAxi [ipx::add_bus_interface ${axiBusInterface_rst}_ARESETN $daphne]
    set_property ABSTRACTION_TYPE_VLNV xilinx.com:signal:reset_rtl:1.0 $rstAxi
    set_property BUS_TYPE_VLNV xilinx.com:signal:reset:1.0 $rstAxi

    # create the port map for the reset interface
    set rst_pm [ipx::add_port_map -name RST -bus_interface $rstAxi]
    set_property PHYSICAL_NAME ${axiBusInterface_rst}_ARESETN $rst_pm

    # set reset parameters
    foreach {rstBusParam rstBusParamVal} $daphne_rst_parameters {
        set rst_param [ipx::add_bus_parameter $rstBusParam $rstAxi]
        set_property VALUE $rstBusParamVal $rst_param
        set_property VALUE_VALIDATION_LIST {ACTIVE_HIGH ACTIVE_LOW} $rst_param
        set_property VALUE_VALIDATION_TYPE list $rst_param

        # configure VALUE_RESOLVE_TYPE properties, they are almost all the same unless for the INSERT_VIP parameter, 
        # which includes changes in USAGE too
        if {$rstBusParam eq "INSERT_VIP"} {
            set_property USAGE simulation.rtl $rst_param
            set_property VALUE_RESOLVE_TYPE user $rst_param
        } else {
            set_property VALUE_RESOLVE_TYPE immediate $rst_param
        }

        # configure VALUE_FORMAT property, if the value is a string, do not change the property, if it is an integer set long, 
        # if is a real set float
        if {[string is integer -strict $rstBusParamVal]} {
            set_property VALUE_FORMAT long $rst_param
        } elseif {[string is double -strict $rstBusParamVal]} {
            set_property VALUE_FORMAT float $rst_param
        } else {
            set_property VALUE_FORMAT string $rst_param
        }
    }
}

# generate the afe reset interface which has special conditions
set afeRst [ipx::add_bus_interface afe_rst $daphne]
set_property ABSTRACTION_TYPE_VLNV xilinx.com:signal:reset_rtl:1.0 $afeRst
set_property BUS_TYPE_VLNV xilinx.com:signal:reset:1.0 $afeRst
set_property INTERFACE_MODE master $afeRst

# create the port map for the afe reset interface
set rst_afe [ipx::add_port_map -name RST -bus_interface $afeRst]
set_property PHYSICAL_NAME afe_rst $rst_afe

# # configure parameters for this interface
# set rst_afe_param_0 [ipx::add_bus_parameter POLARITY $afeRst]
# set_property USAGE none $rst_afe_param_0
# set_property VALUE ACTIVE_LOW $rst_afe_param_0
# set_property VALUE_RESOLVE_TYPE generated $rst_afe_param_0
# set rst_afe_param_1 [ipx::add_bus_parameter INSERT_VIP $afeRst]
# set_property USAGE simulation.rtl $rst_afe_param_1
# set_property VALUE 0 $rst_afe_param_1
# set_property VALUE_RESOLVE_TYPE user $rst_afe_param_1
# set_property VALUE_FORMAT long $rst_afe_param_1

# create all clock interfaces for each bus interface
foreach axiBusInterface_clk $daphne_bus_interfaces {
    # add respective clock interface
    set clkAxi [ipx::add_bus_interface ${axiBusInterface_clk}_ACLK $daphne]
    set_property ABSTRACTION_TYPE_VLNV xilinx.com:signal:clock_rtl:1.0 $clkAxi
    set_property BUS_TYPE_VLNV xilinx.com:signal:clock:1.0 $clkAxi

    # create the port map for the clock interface
    set clk_pm [ipx::add_port_map -name CLK -bus_interface $clkAxi]
    set_property PHYSICAL_NAME ${axiBusInterface_clk}_ACLK $clk_pm

    # set generic clock parameters 
    set clk_param_bus [ipx::add_bus_parameter ASSOCIATED_BUSIF $clkAxi]
    set_property VALUE $axiBusInterface_clk $clk_param_bus
    set clk_param_rst [ipx::add_bus_parameter ASSOCIATED_RESET $clkAxi]
    set_property VALUE ${axiBusInterface_clk}_ARESETN $clk_param_rst

    # set clock parameters
    foreach {clkBusParam clkBusParamVal} $daphne_clk_parameters {
        if {[llength $clkBusParamVal] == 0} {
            # the parameter has an empty value, therefore we need special treatment for it
            set clk_param [ipx::add_bus_parameter $clkBusParam $clkAxi]
            set_property USAGE none $clk_param
            set_property VALUE_RESOLVE_TYPE generated $clk_param
        } else {
            # the parameter does not have an empty value, do stuff normally
            set clk_param [ipx::add_bus_parameter $clkBusParam $clkAxi]
            set_property VALUE $clkBusParamVal $clk_param

            # configure VALUE_RESOLVE_TYPE properties, they are almost all the same unless for the INSERT_VIP parameter, 
            # which includes changes in USAGE too
            if {$clkBusParam eq "INSERT_VIP"} {
                set_property USAGE simulation.rtl $clk_param
                set_property VALUE_RESOLVE_TYPE user $clk_param
            } else {
                set_property USAGE none $clk_param
                set_property VALUE_RESOLVE_TYPE generated $clk_param
            }

            # configure VALUE_FORMAT property, if the value is a string, do not change the property, if it is an integer set long,
            # if is a real set float
            if {[string is integer -strict $clkBusParamVal]} {
                set_property VALUE_FORMAT long $clk_param
            } elseif {[string is double -strict $clkBusParamVal]} {
                set_property VALUE_FORMAT float $clk_param
            } else {
                set_property VALUE_FORMAT string $clk_param
            }
        }
    }
}

foreach plClkInterface $daphne_pl_clk_interfaces {
    # add respective daphne PL clock interface
    set plClkInFace [ipx::add_bus_interface $plClkInterface $daphne]
    set_property ABSTRACTION_TYPE_VLNV xilinx.com:signal:clock_rtl:1.0 $plClkInFace
    set_property BUS_TYPE_VLNV xilinx.com:signal:clock:1.0 $plClkInFace

    # create the port map for the daphne PL clock interface
    set pl_clk_pm [ipx::add_port_map -name CLK -bus_interface $plClkInFace]
    set_property PHYSICAL_NAME $plClkInterface $pl_clk_pm

    # set proper direction of interface for output ports
    if {[string match "afe_clk_*" $plClkInterface]} {
        set_property INTERFACE_MODE master $plClkInFace
    }

    # set daphne PL clock parameters 
    foreach {plClkBusParam plClkBusParamVal} $daphne_pl_clk_parameters {
        if {[llength $plClkBusParamVal] == 0} {
            # the parameter has an empty value, therefore we need special treatment for it
            set plClk_param [ipx::add_bus_parameter $plClkBusParam $plClkInFace]
            set_property USAGE none $plClk_param
            set_property VALUE_RESOLVE_TYPE generated $plClk_param
        } else {
            # the parameter does not have an empty value, do stuff normally
            set plClk_param [ipx::add_bus_parameter $plClkBusParam $plClkInFace]

            # configure the clock domain name properly, which changes from other interfaces
            if {$plClkBusParam eq "CLK_DOMAIN"} {
                if {[string match "eth_clk_n" $plClkInterface]} {
                    set_property VALUE DAPHNE_V3_F4_3_GTH0_REFCLK_N $plClk_param
                } elseif {[string match "eth_clk_p" $plClkInterface]} {
                    set_property VALUE DAPHNE_V3_F4_3_GTH0_REFCLK_P $plClk_param
                } else {
                    set_property VALUE ${plClkBusParamVal}_${plClkInterface} $plClk_param
                }
            } else {
                set_property VALUE $plClkBusParamVal $plClk_param
            }

            # configure VALUE_RESOLVE_TYPE properties, they are almost all the same unless for the INSERT_VIP parameter, 
            # which includes changes in USAGE too
            if {$plClkBusParam eq "INSERT_VIP"} {
                set_property USAGE simulation.rtl $plClk_param
                set_property VALUE_RESOLVE_TYPE user $plClk_param
            } else {
                set_property USAGE none $plClk_param
                set_property VALUE_RESOLVE_TYPE generated $plClk_param
            }

            # configure VALUE_FORMAT property, if the value is a string, do not change the property, if it is an integer set long,
            # if is a real set float
            if {[string is integer -strict $plClkBusParamVal]} {
                set_property VALUE_FORMAT long $plClk_param
            } elseif {[string is double -strict $plClkBusParamVal]} {
                set_property VALUE_FORMAT float $plClk_param
            } else {
                set_property VALUE_FORMAT string $plClk_param
            }
        }
    }
}

# add memory maps of the module
foreach memoryMapBus $daphne_bus_interfaces {
    # create a memory map for this bus interface
    set memMapAxi [ipx::add_memory_map $memoryMapBus $daphne]
    set_property DISPLAY_NAME $memoryMapBus $memMapAxi

    # set address block for this memory map
    set addrBlock [ipx::add_address_block reg0 $memMapAxi]
    set_property DISPLAY_NAME reg0 $addrBlock
    set_property BASE_ADDRESS 0x0 $addrBlock
    set_property BASE_ADDRESS_FORMAT bitString $addrBlock
    set_property BASE_ADDRESS_BIT_STRING_LENGTH 1 $addrBlock
    set_property RANGE 0x100000000 $addrBlock
    set_property RANGE_FORMAT bitString $addrBlock
    set_property RANGE_BIT_STRING_LENGTH 33 $addrBlock
    set_property RANGE_MINIMUM 4096 $addrBlock
    set_property USAGE register $addrBlock
    set_property WIDTH 32 $addrBlock
    set_property WIDTH_FORMAT long $addrBlock
}

# upgrade IP elements to avoid locked IPs or wrong config
ipx::upgrade_core $daphne

set XGUILoc ../ip_repo/daphne3_ip/xgui/DAPHNE3_v1_0.tcl
# check if XGUI file already exists
if {![file exists $XGUILoc]} {
    puts "Generating XGUI file..."
    # create XGUI file
    source daphne3_xgui_gen.tcl
} else {
    puts "XGUI File already exists."
}

# add custom XGUI file
ipx::add_file -name [file normalize $XGUILoc] -file_group $xpgui_files
set_property XGUI_VERSION 2 [ipx::get_files -of_objects $xpgui_files]

# update ip checksums again
ipx::update_checksums $daphne

# check IP integrity, if it returns 1, we are ready to package
if {[ipx::check_integrity $daphne]} {
    # save and package IP since it is properly finished
    ipx::save_core
    puts "Successfully packaged DAPHNE3 IP."
} else {
    # there was an error!
    puts "Error detected while packaging IP."
}
