# Reconstructed from the repository RAM-boot sequence; no nonvolatile writes.
array set opt {-fsbl "" -pmufw "" -bl31 "" -bitstream "" -uboot "" -dtb "" -hw-server "tcp:localhost:3121"}
if {[llength $argv] % 2} { error "Expected option/value pairs" }
foreach {key value} $argv {
    if {![info exists opt($key)]} { error "Unknown option $key" }
    set opt($key) $value
}
foreach key {-fsbl -pmufw -bl31 -bitstream -uboot -dtb} {
    if {![file isfile $opt($key)]} { error "Missing $key: $opt($key)" }
}
connect -url $opt(-hw-server)
targets -set -nocase -filter {name =~ "*PSU*"}
# Clear peripheral state left by Linux, storage erase, and previous RAM boots.
# In JTAG boot mode, BootROM waits for this complete RAM-loading sequence.
rst -system
after 1000
targets -set -nocase -filter {name =~ "*PSU*"}
mwr 0xffca0038 0x1ff
targets -set -nocase -filter {name =~ "*MicroBlaze PMU*"}
dow $opt(-pmufw)
con
after 1000
targets -set -nocase -filter {name =~ "*Cortex-A53*#0*"}
rst -processor
after 500
dow $opt(-fsbl)
con
after 6000
stop
fpga -file $opt(-bitstream)
targets -set -nocase -filter {name =~ "*Cortex-A53*#0*"}
dow $opt(-bl31)
dow -data $opt(-uboot) 0x08000000
dow -data $opt(-dtb) 0x00100000
# Enter TF-A first. It installs the secure monitor/PSCI interface and hands
# off to the nonsecure U-Boot image. Direct U-Boot entry leaves Linux without
# a working SMC conduit.
rwr r0 0
con -addr 0xfffea000
puts "TF-A started in RAM; inspect serial console for U-Boot."
