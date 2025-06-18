# create XGUI file generator
# describes the proper ipgui commands in order to properly modify parameters from the IP
# this is not the best solution at the moment,
# so it hopes for DAPHNE to not have more parameters in the near future!
# <daniel.avila@eia.edu.co - daniel.avila.gomez@cern.ch>

# create the folder where the file will be located
file mkdir ../daphne3_ip_repo/xgui

# set the file path
set xgui_file_path "../daphne3_ip_repo/xgui/DAPHNE3_v1_0.tcl"

# create/open the file 
set fileId [open $xgui_file_path "w"]

# write the gui content
puts $fileId {# Definitional proc to organize widgets for parameters.
proc init_gui { IPINST } {
  ipgui::add_param $IPINST -name "Component_Name"
  #Adding Page
  set Page_0 [ipgui::add_page $IPINST -name "Page 0"]
  ipgui::add_param $IPINST -name "version" -parent ${Page_0}


}

proc update_PARAM_VALUE.version { PARAM_VALUE.version } {
	# Procedure called to update version when any of the dependent parameters in the arguments change
}

proc validate_PARAM_VALUE.version { PARAM_VALUE.version } {
	# Procedure called to validate version
	return true
}


proc update_MODELPARAM_VALUE.version { MODELPARAM_VALUE.version PARAM_VALUE.version } {
	# Procedure called to set VHDL generic/Verilog parameter value(s) based on TCL parameter value
	set_property value [get_property value ${PARAM_VALUE.version}] ${MODELPARAM_VALUE.version}
}
}

# close the file
close $fileId