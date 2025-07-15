# create XGUI file generator
# describes the proper ipgui commands in order to properly modify parameters from the IP
# this is not the best solution at the moment,
# so it hopes for DAPHNE to not have more parameters in the near future!
# <daniel.avila@eia.edu.co - daniel.avila.gomez@cern.ch>

# create the folder where the file will be located
file mkdir ../ip_repo/daphne3_ip/xgui

# set the file path
set xgui_file_path "../ip_repo/daphne3_ip/xgui/DAPHNE3_v1_0.tcl"

# create/open the file 
set fileId [open $xgui_file_path "w"]

# write the gui content
puts $fileId {# Definitional proc to organize widgets for parameters.
proc init_gui { IPINST } {
  ipgui::add_param $IPINST -name "Component_Name"
  #Adding Page
  set Page_0 [ipgui::add_page $IPINST -name "Page 0"]
  ipgui::add_param $IPINST -name "version" -parent ${Page_0}
  ipgui::add_param $IPINST -name "link_id" -parent ${Page_0}
  ipgui::add_param $IPINST -name "slot_id" -parent ${Page_0}
  ipgui::add_param $IPINST -name "crate_id" -parent ${Page_0}
  ipgui::add_param $IPINST -name "detector_id" -parent ${Page_0}
  ipgui::add_param $IPINST -name "threshold" -parent ${Page_0}
  ipgui::add_param $IPINST -name "version_id" -parent ${Page_0}


}

proc update_PARAM_VALUE.version { PARAM_VALUE.version } {
	# Procedure called to update version when any of the dependent parameters in the arguments change
}

proc validate_PARAM_VALUE.version { PARAM_VALUE.version } {
	# Procedure called to validate version
	return true
}

proc update_PARAM_VALUE.link_id { PARAM_VALUE.link_id } {
	# Procedure called to update link_id when any of the dependent parameters in the arguments change
}

proc validate_PARAM_VALUE.link_id { PARAM_VALUE.link_id } {
	# Procedure called to validate link_id
	return true
}

proc update_PARAM_VALUE.slot_id { PARAM_VALUE.slot_id } {
	# Procedure called to update slot_id when any of the dependent parameters in the arguments change
}

proc validate_PARAM_VALUE.slot_id { PARAM_VALUE.slot_id } {
	# Procedure called to validate slot_id
	return true
}

proc update_PARAM_VALUE.crate_id { PARAM_VALUE.crate_id } {
	# Procedure called to update crate_id when any of the dependent parameters in the arguments change
}

proc validate_PARAM_VALUE.crate_id { PARAM_VALUE.crate_id } {
	# Procedure called to validate crate_id
	return true
}

proc update_PARAM_VALUE.detector_id { PARAM_VALUE.detector_id } {
	# Procedure called to update detector_id when any of the dependent parameters in the arguments change
}

proc validate_PARAM_VALUE.detector_id { PARAM_VALUE.detector_id } {
	# Procedure called to validate detector_id
	return true
}

proc update_PARAM_VALUE.threshold { PARAM_VALUE.threshold } {
	# Procedure called to update threshold when any of the dependent parameters in the arguments change
}

proc validate_PARAM_VALUE.threshold { PARAM_VALUE.threshold } {
	# Procedure called to validate threshold
	return true
}

proc update_PARAM_VALUE.version_id { PARAM_VALUE.version_id } {
	# Procedure called to update version_id when any of the dependent parameters in the arguments change
}

proc validate_PARAM_VALUE.version_id { PARAM_VALUE.version_id } {
	# Procedure called to validate version_id
	return true
}


proc update_MODELPARAM_VALUE.version { MODELPARAM_VALUE.version PARAM_VALUE.version } {
	# Procedure called to set VHDL generic/Verilog parameter value(s) based on TCL parameter value
	set_property value [get_property value ${PARAM_VALUE.version}] ${MODELPARAM_VALUE.version}
}

proc update_MODELPARAM_VALUE.link_id { MODELPARAM_VALUE.link_id PARAM_VALUE.link_id } {
	# Procedure called to set VHDL generic/Verilog parameter value(s) based on TCL parameter value
	set_property value [get_property value ${PARAM_VALUE.link_id}] ${MODELPARAM_VALUE.link_id}
}

proc update_MODELPARAM_VALUE.slot_id { MODELPARAM_VALUE.slot_id PARAM_VALUE.slot_id } {
	# Procedure called to set VHDL generic/Verilog parameter value(s) based on TCL parameter value
	set_property value [get_property value ${PARAM_VALUE.slot_id}] ${MODELPARAM_VALUE.slot_id}
}

proc update_MODELPARAM_VALUE.crate_id { MODELPARAM_VALUE.crate_id PARAM_VALUE.crate_id } {
	# Procedure called to set VHDL generic/Verilog parameter value(s) based on TCL parameter value
	set_property value [get_property value ${PARAM_VALUE.crate_id}] ${MODELPARAM_VALUE.crate_id}
}

proc update_MODELPARAM_VALUE.detector_id { MODELPARAM_VALUE.detector_id PARAM_VALUE.detector_id } {
	# Procedure called to set VHDL generic/Verilog parameter value(s) based on TCL parameter value
	set_property value [get_property value ${PARAM_VALUE.detector_id}] ${MODELPARAM_VALUE.detector_id}
}

proc update_MODELPARAM_VALUE.threshold { MODELPARAM_VALUE.threshold PARAM_VALUE.threshold } {
	# Procedure called to set VHDL generic/Verilog parameter value(s) based on TCL parameter value
	set_property value [get_property value ${PARAM_VALUE.threshold}] ${MODELPARAM_VALUE.threshold}
}

proc update_MODELPARAM_VALUE.version_id { MODELPARAM_VALUE.version_id PARAM_VALUE.version_id } {
	# Procedure called to set VHDL generic/Verilog parameter value(s) based on TCL parameter value
	set_property value [get_property value ${PARAM_VALUE.version_id}] ${MODELPARAM_VALUE.version_id}
}
}

# close the file
close $fileId