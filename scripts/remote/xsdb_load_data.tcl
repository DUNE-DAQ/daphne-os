# Load one binary chunk into DDR while U-Boot is stopped at its serial prompt.
#
# Usage:
#   xsdb xsdb_load_data.tcl -file CHUNK -address 0x10000000 \
#     ?-hw-server URL? ?-a53-target PATTERN?

proc usage {} {
    puts stderr "Usage: xsdb_load_data.tcl -file FILE -address ADDRESS ?-hw-server URL? ?-a53-target PATTERN?"
    exit 2
}

array set opt {
    -file ""
    -address ""
    -hw-server ""
    -a53-target "*Cortex-A53*#0*"
}

if {[llength $argv] % 2 != 0} {
    usage
}

foreach {key value} $argv {
    if {![info exists opt($key)]} {
        puts stderr "Unknown option: $key"
        usage
    }
    set opt($key) $value
}

foreach key {-file -address} {
    if {$opt($key) eq ""} {
        puts stderr "Missing required option: $key"
        usage
    }
}

if {![file isfile $opt(-file)]} {
    puts stderr "Missing data file: $opt(-file)"
    exit 2
}

if {[catch {expr {$opt(-address) + 0}}]} {
    puts stderr "Invalid address: $opt(-address)"
    exit 2
}

if {$opt(-hw-server) ne ""} {
    connect -url $opt(-hw-server)
} else {
    connect
}

targets -set -nocase -filter "name =~ \"$opt(-a53-target)\""
puts "INFO: stopping A53 U-Boot target"
if {[catch {stop} stop_error]} {
    puts stderr "ERROR: unable to stop A53 target: $stop_error"
    exit 3
}

after 100
puts "INFO: downloading [file size $opt(-file)] bytes from $opt(-file) to $opt(-address)"
if {[catch {dow -data $opt(-file) $opt(-address)} download_error]} {
    catch {con}
    puts stderr "ERROR: XSDB data download failed: $download_error"
    exit 3
}

puts "INFO: resuming U-Boot"
if {[catch {con} resume_error]} {
    puts stderr "ERROR: unable to resume A53 target: $resume_error"
    exit 3
}

puts "INFO: XSDB data load completed"
exit 0
