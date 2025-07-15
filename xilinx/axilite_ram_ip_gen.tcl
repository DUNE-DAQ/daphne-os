# set project properties
set_part xck26-sfvc784-2LV-c
set_property BOARD_PART xilinx.com:k26c:part0:1.4 [current_project]
set_property TARGET_LANGUAGE VHDL [current_project]
set_property DEFAULT_LIB work [current_project]

# set AXI RAM IP parameters
set ramComponentVendor dune.pds
set ramComponentLibrary user
set ramComponentIdentifier outspy64_axilite
set ramComponentVersion 1.0
set axiliteRAMDescription {IP Version of AXI LITE RAM Module Firmware for the PDS in the DUNE Project}

# set repository for the AXI RAM IP
set ramIpRepoDir ../ip_repo/axilite_ram_ip

# build AXI RAM IP
set ram [ipx::create_core -set_current TRUE $ramComponentVendor $ramComponentLibrary $ramComponentIdentifier $ramComponentVersion]

# configure IP properties
set_property CORE_REVISION 1 $ram
set_property DEFINITION_SOURCE package_project $ram
set_property DESCRIPTION $axiliteRAMDescription $ram
set_property DISPLAY_NAME outspy64_axilite_v1_0 $ram
set_property ROOT_DIRECTORY $ramIpRepoDir $ram
set_property SUPPORTED_FAMILIES {zynquplus Production} $ram
set_property TAXONOMY /UserIP $ram

# create file groups for the IP

# RTL file groups
set ram_lang_synth [ipx::add_file_group xilinx_anylanguagesynthesis $ram]
set_property LANGUAGE VHDL $ram_lang_synth
set_property MODEL_NAME $ramComponentIdentifier $ram_lang_synth

# Behavioral simulation file groups
set ram_lang_sim [ipx::add_file_group xilinx_anylanguagebehavioralsimulation $ram]
set_property LANGUAGE VHDL $ram_lang_sim
set_property MODEL_NAME $ramComponentIdentifier $ram_lang_sim

# XPGUI file groups
set ram_xpgui_files [ipx::add_file_group xilinx_xpgui $ram]

# add top level file, it is VHDL!
# it is added last in order to let Vivado packager know it is top
ipx::add_file -name [file normalize "../ip_repo/axilite_ram_ip/rtl/AXI_RAM.vhd"] -file_group $ram_lang_synth
ipx::add_file -name [file normalize "../ip_repo/axilite_ram_ip/rtl/AXI_RAM.vhd"] -file_group $ram_lang_sim
# make it top in hierarchy, just in case
set_property TOP AXI_RAM [current_fileset]

# update ip checksums
ipx::update_checksums $ram 

# create the ports based on the TOP level design
set ram_ports [ipx::add_ports_from_hdl -top_level_hdl_file [file normalize "../ip_repo/axilite_ram_ip/rtl/AXI_RAM.vhd"] -top_module_name outspy64_axilite -include_dirs [file normalize "../ip_repo/axilite_ram_ip/rtl"] $ram]

# create the generic parameters of the design based on the TOP level generics
set ram_generics [ipx::add_model_parameters_from_hdl -top_level_hdl_file [file normalize "../ip_repo/axilite_ram_ip/rtl/AXI_RAM.vhd"] -top_module_name outspy64_axilite -include_dirs [file normalize "../ip_repo/axilite_ram_ip/rtl"] $ram]
set_property DISPLAY_NAME {C S Axi Addr Width} [ipx::get_hdl_parameters -of_objects $ram C_S_AXI_DATA_WIDTH]
set_property VALUE_RESOLVE_TYPE user [ipx::get_hdl_parameters -of_objects $ram C_S_AXI_DATA_WIDTH]
set_property DISPLAY_NAME {C S Axi Data Width} [ipx::get_hdl_parameters -of_objects $ram C_S_AXI_ADDR_WIDTH]
set_property VALUE_RESOLVE_TYPE user [ipx::get_hdl_parameters -of_objects $ram C_S_AXI_ADDR_WIDTH]

set data_width_param [ipx::add_user_parameter C_S_AXI_DATA_WIDTH $ram]
set_property DISPLAY_NAME {C S Axi Data Width} $data_width_param
set_property VALUE 32 $data_width_param
set_property VALUE_FORMAT long $data_width_param
set_property VALUE_RESOLVE_TYPE user $data_width_param
set_property VALUE_PERMISSION user $data_width_param

set addr_width_param [ipx::add_user_parameter C_S_AXI_ADDR_WIDTH $ram]
set_property DISPLAY_NAME {C S Axi Addr Width} $addr_width_param
set_property VALUE 32 $addr_width_param
set_property VALUE_FORMAT long $addr_width_param
set_property VALUE_RESOLVE_TYPE user $addr_width_param
set_property VALUE_PERMISSION user $addr_width_param

# list the bus names used in the core
set ram_bus_interfaces S_AXI

# list all possible ports used in AXI4 lite interface
set ram_bus_port_map {
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
set ram_port_driver {
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

# list all possible reset parameters
set ram_rst_parameters {
    POLARITY ACTIVE_LOW
}

# list all possible clock parameters
set ram_clk_parameters {
    FREQ_HZ 99999001
}

# ram PL specific clock interfaces
set ram_pl_clk_interfaces clock

# list all possible parameters for the ram PL clock interfaces
set ram_pl_clk_parameters {
    FREQ_HZ 100000000
}

# set driver property for each port in the bus interface
# change some properties that are not added by default to specific ports
foreach {ramPort ramPortVal} $ram_port_driver {
    set_property DRIVER_VALUE $ramPortVal [ipx::get_ports ${ram_bus_interfaces}_${ramPort} -of_objects $ram]
}

# create all bus interfaces with respective ports and parameters
# add bus interface
set ramBusAxi [ipx::add_bus_interface $ram_bus_interfaces $ram]

# add bus properties
set_property ABSTRACTION_TYPE_VLNV xilinx.com:interface:aximm_rtl:1.0 $ramBusAxi
set_property BUS_TYPE_VLNV xilinx.com:interface:aximm:1.0 $ramBusAxi
set_property INTERFACE_MODE slave $ramBusAxi
set_property SLAVE_MEMORY_MAP_REF $ram_bus_interfaces $ramBusAxi

# create the port map for each port of the interface
foreach ramAxiBusPortName $ram_bus_port_map {
    set ram_axi_pm [ipx::add_port_map -name $ramAxiBusPortName -bus_interface $ramBusAxi]
    set_property PHYSICAL_NAME ${ram_bus_interfaces}_${ramAxiBusPortName} $ram_axi_pm 
}

# create all reset interfaces for each bus interface
# add respective reset interface
set ramRstAxi [ipx::add_bus_interface ${ram_bus_interfaces}_ARESETN $ram]
set_property ABSTRACTION_TYPE_VLNV xilinx.com:signal:reset_rtl:1.0 $ramRstAxi
set_property BUS_TYPE_VLNV xilinx.com:signal:reset:1.0 $ramRstAxi

# create the port map for the reset interface
set ram_rst_pm [ipx::add_port_map -name RST -bus_interface $ramRstAxi]
set_property PHYSICAL_NAME ${ram_bus_interfaces}_ARESETN $ram_rst_pm 

# set reset parameters
foreach {ramRstBusParam ramRstBusParamVal} $ram_rst_parameters {
    set ram_rst_param [ipx::add_bus_parameter $ramRstBusParam $ramRstAxi]
    set_property VALUE $ramRstBusParamVal $ram_rst_param
    set_property VALUE_VALIDATION_LIST {ACTIVE_HIGH ACTIVE_LOW} $ram_rst_param
    set_property VALUE_VALIDATION_TYPE list $ram_rst_param
    set_property VALUE_RESOLVE_TYPE immediate $ram_rst_param
    set_property VALUE_FORMAT string $ram_rst_param
}

# create all clock interfaces for each bus interface
# add respective clock interface
set ramClkAxi [ipx::add_bus_interface ${ram_bus_interfaces}_ACLK $ram]
set_property ABSTRACTION_TYPE_VLNV xilinx.com:signal:clock_rtl:1.0 $ramClkAxi
set_property BUS_TYPE_VLNV xilinx.com:signal:clock:1.0 $ramClkAxi

# create the port map for the clock interface
set ram_clk_pm [ipx::add_port_map -name CLK -bus_interface $ramClkAxi]
set_property PHYSICAL_NAME ${ram_bus_interfaces}_ACLK $ram_clk_pm

# set generic clock parameters 
set ram_clk_param_bus [ipx::add_bus_parameter ASSOCIATED_BUSIF $ramClkAxi]
set_property VALUE $ram_bus_interfaces $ram_clk_param_bus
set ram_clk_param_rst [ipx::add_bus_parameter ASSOCIATED_RESET $ramClkAxi]
set_property VALUE ${ram_bus_interfaces}_ARESETN $ram_clk_param_rst

# set other clock parameters 
foreach {ramClkBusParam ramClkBusParamVal} $ram_clk_parameters {
    set ram_clk_param [ipx::add_bus_parameter $ramClkBusParam $ramClkAxi]
    set_property VALUE $ramClkBusParamVal $ram_clk_param
    set_property USAGE none $ram_clk_param
    set_property VALUE_RESOLVE_TYPE generated $ram_clk_param
    set_property VALUE_FORMAT long $ram_clk_param
}

# add respective AXI lite ram PL clock interface
set ramPLClkInFace [ipx::add_bus_interface $ram_pl_clk_interfaces $ram]
set_property ABSTRACTION_TYPE_VLNV xilinx.com:signal:clock_rtl:1.0 $ramPLClkInFace
set_property BUS_TYPE_VLNV xilinx.com:signal:clock:1.0 $ramPLClkInFace

# create the port map for the AXI lite ram PL clock interface
set ram_pl_clk_pm [ipx::add_port_map -name CLK -bus_interface $ramPLClkInFace]
set_property PHYSICAL_NAME $ram_pl_clk_interfaces $ram_pl_clk_pm 

# set AXI lite ram PL clock parameters
foreach {ramPLClkBusParam ramPLClkBusParamVal} $ram_pl_clk_parameters {
    set ramPLClk_param [ipx::add_bus_parameter $ramPLClkBusParam $ramPLClkInFace]
    set_property VALUE $ramPLClkBusParamVal $ramPLClk_param
    set_property USAGE none $ramPLClk_param
    set_property VALUE_RESOLVE_TYPE generated $ramPLClk_param
    set_property VALUE_FORMAT long $ramPLClk_param
}

# add memory maps of the module
# create a memory map for this bus interface
set ramMemMapAxi [ipx::add_memory_map $ram_bus_interfaces $ram]
set_property DISPLAY_NAME $ram_bus_interfaces $ramMemMapAxi

# set address block for this memory map
set ramAddrBlock [ipx::add_address_block reg0 $ramMemMapAxi]
set_property DISPLAY_NAME reg0 $ramAddrBlock
set_property BASE_ADDRESS 0x0 $ramAddrBlock
set_property BASE_ADDRESS_FORMAT bitString $ramAddrBlock
set_property BASE_ADDRESS_BIT_STRING_LENGTH 1 $ramAddrBlock
set_property RANGE 0x100000000 $ramAddrBlock
set_property RANGE_DEPENDENCY {pow(2,(spirit:decode(id('MODELPARAM_VALUE.C_S_AXI_ADDR_WIDTH')) - 1) - 0 + 1)} $ramAddrBlock
# set_property RANGE_DEPENDENCY "pow(2, MODELPARAM_VALUE.C_S_AXI_ADDR_WIDTH)" $ramAddrBlock
set_property RANGE_FORMAT bitString $ramAddrBlock
set_property RANGE_BIT_STRING_LENGTH 33 $ramAddrBlock
set_property RANGE_MINIMUM 4096 $ramAddrBlock
set_property RANGE_RESOLVE_TYPE dependent $ramAddrBlock
set_property USAGE register $ramAddrBlock
set_property WIDTH 32 $ramAddrBlock
set_property WIDTH_DEPENDENCY {(spirit:decode(id('MODELPARAM_VALUE.C_S_AXI_DATA_WIDTH')) - 1) - 0 + 1} $ramAddrBlock
# set_property WIDTH_DEPENDENCY "MODELPARAM_VALUE.C_S_AXI_DATA_WIDTH" $ramAddrBlock
set_property WIDTH_FORMAT long $ramAddrBlock
set_property WIDTH_RESOLVE_TYPE dependent $ramAddrBlock

# upgrade IP elements to avoid locked IPs or wrong config
ipx::upgrade_core $ram 

set RAMXGUILoc ../ip_repo/axilite_ram_ip/xgui/outspy64_axilite_v1_0.tcl
# check if XGUI file already exists
if {![file exists $RAMXGUILoc]} {
    puts "Generating XGUI file..."
    # create XGUI file
    source axilite_ram_xgui_gen.tcl
} else {
    puts "XGUI File already exists."
}

# add custom XGUI file
ipx::add_file -name [file normalize $RAMXGUILoc] -file_group $ram_xpgui_files
set_property XGUI_VERSION 2 [ipx::get_files -of_objects $ram_xpgui_files]

# update ip checksums again
ipx::update_checksums $ram

# check IP integrity, if it returns 1, we are ready to package
if {[ipx::check_integrity $ram]} {
    # save and package IP since it is properly finished
    ipx::save_core
    puts "Successfully packaged AXI Lite RAM IP."
} else {
    # there was an error!
    puts "Error detected while packaging IP."
}