# simple TCL code to generate Device Tree Overlay for Petalinux
# this code must run inside the XSCT Vitis environment
# call for this specific process to run first
 
# check if XSCT is callable
if {[catch {exec xsct -h} result]} {
    puts "ERROR: XSCT not found in PATH."
    puts "Please make sure Vitis is installed and XSCT is in your PATH."
    exit 1
} else {
    puts "INFO: XSCT found and available."
}
 
# define the hardware description files
set hw      [lindex $argv 0]
 
# define output directory
set out_dir [lindex $argv 1]
 
# receive the git commit number
set git_sha [lindex $argv 2]
 
# generate the device tree using the generated XSA
createdts -hw $hw -out $out_dir -platform-name daphne3_$git_sha -overlay
 
# exit the process once done
exit