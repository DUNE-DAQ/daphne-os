# Boot a ZynqMP/Kria U-Boot image into RAM over JTAG using xsdb.
#
# Usage:
#   /tools/2026.1/Vivado/bin/xsdb scripts/remote/xsdb_boot_uboot.tcl \
#     -fsbl zynqmp_fsbl.elf -pmufw pmufw.elf -bl31 bl31.elf -uboot u-boot-dtb.elf
#
# This script does not program QSPI/eMMC. It only starts a RAM-resident
# bootloader so station automation can flash eMMC from U-Boot.

proc usage {} {
    puts stderr "Usage: xsdb_boot_uboot.tcl -fsbl FILE -pmufw FILE -bl31 FILE -uboot FILE ?-hw-server URL? ?-a53-target PATTERN? ?-pmu-target PATTERN?"
    exit 2
}

array set opt {
    -fsbl ""
    -pmufw ""
    -bl31 ""
    -uboot ""
    -hw-server ""
    -a53-target "*Cortex-A53*#0*"
    -pmu-target "*MicroBlaze PMU*"
    -fsbl-wait-ms 6000
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

foreach key {-fsbl -pmufw -bl31 -uboot} {
    if {$opt($key) eq ""} {
        puts stderr "Missing required option: $key"
        usage
    }
    if {![file exists $opt($key)]} {
        puts stderr "Missing file for $key: $opt($key)"
        exit 2
    }
}

if {$opt(-hw-server) ne ""} {
    connect -url $opt(-hw-server)
} else {
    connect
}

puts "INFO: connected to JTAG target"

targets -set -nocase -filter "name =~ \"$opt(-pmu-target)\""
puts "INFO: downloading PMU firmware: $opt(-pmufw)"
dow $opt(-pmufw)
con
after 1000

targets -set -nocase -filter "name =~ \"$opt(-a53-target)\""
puts "INFO: resetting A53 target"
rst -processor
after 500

puts "INFO: downloading FSBL: $opt(-fsbl)"
dow $opt(-fsbl)
con
after $opt(-fsbl-wait-ms)
stop

puts "INFO: downloading ATF/BL31: $opt(-bl31)"
dow $opt(-bl31)

puts "INFO: downloading U-Boot: $opt(-uboot)"
dow $opt(-uboot)

puts "INFO: starting U-Boot"
con
puts "INFO: hand over to serial console and catch the U-Boot prompt"
