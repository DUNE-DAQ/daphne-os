# DAPHNE V3/MEZZ Firmware Repository

## Documentation

The documentation related to the DAPHNE V3/MEZZ board is still under development and whenever there is a wiki that explains everything you will find the link pointing to it here.

The memory map can be found inside the `src/` directory. Since this design contains PS-PL features, it is actually very large and is still under constant modification.

## Discussion

The #daphne channel on the DUNE workspace on Slack is the proper place to discuss this firmware.

## How can I build it?

The most important thing to note is, that most of the commands that lie inside each TCL script were written using **Vivado 2024.1** Version, backwards compatibility is not supported, so any older version than the one specified will yield errors when trying to build it. Forwards compatibility is supported for newer versions (such as Vivado 2025.1) however creating the Device Tree Overlays is not supported, as the Kria k26c SOM full support is not available on this Vivado version (as of September 2025).

This design workflow follows Vivado Non-Project mode strategy. The repository contains a bunch of TCL scripts that generate the DAPHNE PL IP, a Block Design that connects both Zynq UltraScale+ PS and Firmware's PL, and a batch file that produces bitstream, XSA files, device tree overlays and everything needed to program the board.

On Windows:

1. Go to search bar and look for Vivado 202X.*  Tcl Shell.
2. Navigate to the location of the xilinx directory of the folder where the repo was cloned.
3. Run the source command for the TCL batch file.

```bash
$ cd *:/path/to/repo/daphne-os/xilinx
$ source vivado_batch.tcl
```

On Linux:

1. Navigate to the location of the xilinx directory of the folder where the repo was cloned.
2. Run the source command for the TCL batch file in TCL mode.

```bash
$ cd src/xilinx
$ vivado -mode tcl -source vivado_batch.tcl
```

After Vivado completes the process, the output reports, bit/bin and XSA files and overlay files can be found in the `src/xilinx/output` directory.

## How do I know the building process is working?

Once you clone the repository for the first time, you will see a repository structure like this:

    📂 daphne-os/
    ├── 📂 ip_repo/
    │   ├── 📂 daphne3_ip/
    │   │   ├── 📂 constraints/
    │   │   ├── 📂 rtl/
    │   │   ├── 📂 sim/
    │   │   └── 📂 src/
    │   └── ...
    ├── 📂 xilinx/
    │   ├── 📄 daphne3_bd_gen.tcl
    │   ├── 📄 daphne3_ip_gen.tcl
    │   ├── 📄 DAPHNE_V3_PIN_MAP.xdc
    │   ├── 📄 vivado_batch.tcl
    │   └── ...
    ├── 📄 .gitignore
    ├── 📄 Memory_Map.md
    └── 📄 README.md

The IP repository folder, located in `src/ip_repo/` might include more custom IP cores in the future, but the general idea follows the same structure as the main `src/ip_repo/daphne3_ip` directory.

After you run the `src/xilinx/vivado_batch.tcl` script, there will be a few new folders generated, these contain stuff like IP information, Block Design structure, IP-XACT files, binaries and more. These folders are automatically generated on your local machine. They are excluded from version control to keep the repository clean, lightweight, and efficient when shared on GitHub. The final repo structure after the script finished executing should be:

    📂 daphne-os/
    ├── 📂 bd/
    ├── 📂 ip_repo/
    │   ├── 📂 daphne3_ip/
    │   │   ├── 📂 constraints/
    │   │   ├── 📂 rtl/
    │   │   ├── 📂 sim/
    │   │   ├── 📂 src/
    │   │   ├── 📂 xgui/
    │   │   └── 📄 component.xml
    │   └── ...
    ├── 📂 xilinx/
    │   ├── 📂 output/
    │   │   ├── 📄 daphne3.bin
    │   │   ├── 📄 daphne3.bit
    │   │   ├── 📦 daphne3.xsa
    │   │   └── ...
    │   ├── 📄 daphne3_bd_gen.tcl
    │   ├── 📄 daphne3_ip_gen.tcl
    │   ├── 📄 DAPHNE_V3_PIN_MAP.xdc
    │   ├── 📄 vivado_batch.tcl
    │   └── ...
    ├── 📄 .gitignore
    ├── 📄 Memory_Map.md
    └── 📄 README.md

However, keep in mind that this is just an overview of what you should notice at first glance, because many other things appear inside these folders, as there are a lot of generated files, many of them, inside the `bd/` directory. You will have a better explanation of what you can find on each folder/file by opening these, make sure you do it, and have fun!

### Better description of each folder

Click on every arrow and a general description of the folder/file will appear.

<details>
<summary>📂 <code>bd/</code></summary>
Folder that stores all of the files related to the IP cores used in the block design, as well as their wrappers, constraints, synthesis files, IP cores xci description files, and so on. It is created once you run the 📄 <code>daphne3_bd_gen.tcl</code> script, and this folder also contains the 📄 <code>DAPHNE_V3_F4_3.bd</code> and 📄 <code>DAPHNE_V3_F4_3.bda</code> files, so this is the path that can be used to read the full design. This folder is automatically generated and it is not committed to Github.
</details>

<details>
<summary>📂 <code>ip_repo/</code></summary>
Directory for all of the custom IPs that the user can create to import/use in the design. Currently there is one main IP, DAPHNE3 PL. With the introduction of newer spybuffers, there is a smaller IP, an AXI Lite RAM. Every custom IP folder must contain a description file, normally named as 📄 <code>component.xml</code> and an 📂 <code>xgui/</code> folder where the tcl that allows the user to modify the IP's parameters in the GUI is stored.
</details>

<details>
<summary>📂 <code>ip_repo/daphne3_ip/</code></summary>
This is the folder where you can find everything related to the PL side of DAPHNE V3/MEZZ, it includes the description and GUI files for the IP, as mentioned before, as well as all the RTL files that both describe the design and allow to execute simulations. The folder contains the following elements:

- 📂 <code>constraints/</code>: (Deprecated) Contains the constraints of the design.
- 📂 <code>rtl/</code>: Contains all of the VHDL/Verilog files that build the design, there are many subfolders that specify to what function/submodule the HDL file belongs. But the top level can be found almost immediately by opening the folder.
- 📂 <code>sim/</code>: Contains all of the HDL files that allow the user to perform simulations. These includes mainly test bench files.
- 📂 <code>src/</code>: Contains all of the files related to the Hermes 10G Sender sub IP core. Inside you can also find more tcl files, as well as another 📄 <code>component.xml</code> file related to the Hermes module. 📄 <code>daphne3_ip_gen.tcl</code> imports the IP into the main DAPHNE3 IP by flattening the Hermes module and declaring each VHDL/Verilog files, instead of using the <code>.xci</code> files.
- 📂 <code>xgui/</code>: Contains the TCL script that allows the user to edit the IP's parameters in the GUI.  
- 📄 <code>component.xml</code>: Xilinx IP packaging file that contains all of the IP's metadata, automatically generated.

</details>

<details>
<summary>📂 <code>xilinx/</code></summary>
Here are stored all of the tcl files that the project uses in order to generate the outputs (e.g., binaries, hardware description files). As well as the output folder of the design. The main files are:

- 📄 <code>daphne3_ip_gen.tcl</code>: Creates a custom IP for the DAPHNE3 PL Side.  
- 📄 <code>daphne3_bd_gen.tcl</code>: Creates a Block Design that connects DAPHNE3's PL and PS.  
- 📄 <code>daphne3_xgui_gen.tcl</code>: Creates a GUI file for the custom DAPHNE3 PL IP core.  
- 📄 <code>DAPHNE_V3_PIN_MAP.xdc</code>: Main constraints file.  
- 📄 <code>vivado_batch.tcl</code>: Main script, generates EVERYTHING.  

You might also find other IP generation files related to more custom IPs here, however, it is strongly recommended to generate all the custom HDL inside the DAPHNE3 PL, to keep the repository clean and easier to maintain. Here you can also find the main constraints file.
</details>

<details>
<summary>📂 <code>xilinx/output/</code></summary>
This folder contains all of the output files, including reports, binaries, Xilinx Support Archive (<code>.xsa</code>) or hardware handoff files, all of the Device Tree Overlay files needed to generate the <code>.dtbo</code> files and so on. This folder should be ZIPPED UP and commented on each commit of the repository, as it is also ignored to keep the repository clean.
</details>

<details>
<summary>📄 <code>.gitignore</code></summary>
Defines which files and directories Git should ignore (e.g., xilinx IP files, text files, logs).
</details>

<details>
<summary>📄 <code>Memory_Map.md</code></summary>
Map of registers in the device's memory that are used by the design, since there is a bunch of AXI interfaces and AXI Address spaces, this file actually contains a lot of registers, so whenever you're gonna make modifications to the device behaviour, make sure to check for help on this file.
</details>

<details>
<summary>📄 <code>README.md</code></summary>
Main documentation file. Provides an overview of the repository, how you can build stuff with it, what every folder contains, where you should make modifications, and more.
</details>

## How can I add modules to the design?

The design was created so that the process of building it is almost automatic. In order to add new modules, you just have to update the TOP levels where the modules are supposed to be located, and add the new files to the respective directory where they should be, this means that VHDL/Verilog files should be created/placed inside the `rtl` folder.

    src/ip_repo/daphne3_ip/rtl

And simulation/testbench files should go into the sim folder.

    src/ip_repo/daphne3_ip/sim

Any modifications to the constraints should be done in the constraints file inside the `src/xilinx` directory. 

    src/xilinx/DAPHNE_V3_PIN_MAP.xdc

Any other constraints in the repository are currently ignored by the design flow (as they are deprecated).

The `src/xilinx/daphne3_ip_gen.tcl` script will automatically read for all of the files inside the `rtl` directory and add them to the IP, so you don't have to worry about adding them later. If you want to specifically ignore a file, but don't want to delete it from the repository, you should open the `src/xilinx/daphne3_ip_gen.tcl` script and look for the proc `ignore_files`. This procedure receives the name of the file you want to ignore and avoids including it in the IP, an example is the variable/list `vhdlFiles`, a list where the name of the files for the IP is created. Locate it inside the `src/xilinx/daphne3_ip_gen.tcl` script and you will be able to add the files you want to "delete". See the following piece of code:

```tcl
set vhdlFiles_start [get_files_recursive $rtlDir "*.vhd"]   # Add all of the files that match the condition: ends in .vhd
set vhdlFiles [ignore_files $vhdlFiles_start {"daphne3.vhd" "auto_afe.vhd" "auto_fsm.vhd" "i2cm.vhd" "spim_cm.vhd" "DAQ_CLOCKS.vhd" "trig.vhd" "baseline.vhd"}] # Do not include the files daphne3.vhd, auto_afe.vhd and so on...
```

## How do I make sure the design is indeed what I thought?

It is strongly recommended to NOT use the Vivado GUI (Project Mode) to build this design; some settings in the TCL script will likely not be applied properly if that design flow is attempted, however, it is possible to monitor how the design was built by checking every step using Vivado's GUI to verify. The flow used by the repository to build the design is as follows (This is what the batch file does):

1. Create the DAPHNE3 PL IP. This is done by running the script `src/xilinx/daphne3_ip_gen.tcl`.
    
    This script generates the IP using all of the RTL sources inside the src/ip_repo/daphne3_ip directory. The file generates sub IP cores used by the Hermes 10G Sender module, adds ports (inputs and outputs), generic parameters, associates top level file, includes all opf the submodules, and calls for the `src/xilinx/daphne3_xgui_gen.tcl` script to generate the XGUI file needed to change each parameter of the IP using the Vivado GUI.

    You can see if the IP contains the files/sources that you want by:

    1. If you already run the `src/xilinx/vivado_batch.tcl`:

        1. Run Vivado in TCL mode.
        2. Navigate to the location of the xilinx directory of the folder where the repo was cloned.
        3. Create a dummy project, so that later an IP editing project can be created.
        4. Load the IP repository and update it.
        5. Start the GUI and magic will happen.

        ```tcl
        $ cd src/xilinx
        $ set_part xck26-sfvc784-2LV-c
        $ set_property BOARD_PART xilinx.com:k26c:part0:1.4 [current_project]
        $ set_property TARGET_LANGUAGE VHDL [current_project]
        $ set_property DEFAULT_LIB work [current_project]
        $ set_property IP_REPO_PATHS ../ip_repo [current_project]
        $ update_ip_catalog 
        $ ipx::edit_ip_in_project ../ip_repo/daphne3_ip/component.xml
        $ start_gui
        ```

    2. If you have not run the `src/xilinx/vivado_batch.tcl`:

        1. Run Vivado in TCL mode.
        2. Navigate to the location of the xilinx directory of the folder where the repo was cloned.
        3. Source the DAPHNE3 generation TCL script.
        4. Create a dummy project, so that later an IP editing project can be created.
        5. Start the GUI and magic will happen.

        ```tcl
        $ cd src/xilinx
        $ source daphne3_ip_gen.tcl
        $ ipx::edit_ip_in_project ../ip_repo/daphne3_ip/component.xml
        $ start_gui
        ```

        **IMPORTANT NOTE**: For both cases, running the `ipx::edit_ip_in_project` will create the folders that the dummy project will use, since these should not be part of the design, you can safely delete them **AFTER** closing the Vivado GUI.

        *Folders to delete:* `src/ip_repo/daphne3_ip/edit_ip.cache src/ip_repo/daphne3_ip/edit_ip.gen src/ip_repo/daphne3_ip/edit_ip.hw src/ip_repo/daphne3_ip/edit_ip.ip_user_files src/ip_repo/daphne3_ip/edit_ip.sim src/ip_repo/daphne3_ip/edit_ip.xpr`.

2. Create the DAPHNE3 Block Design. This is done by running the script `src/xilinx/daphne3_bd_gen.tcl`.

    This script generates the Block Design that connects both PS side and PL side, the last one being the DAPHNE3 IP core generated earlier. This script creates cells that include the Zynq UltraScale+ MPSoC, AXI Interconnect module, AXI Quad SPI module, Interrupts and more. It also creates the address segments used by each module, assigns their sizes, and more.

    You can check the created Block Design by following these steps:

    1. If you already run the `src/xilinx/vivado_batch.tcl`:

        1. Run Vivado in TCL mode.
        2. Navigate to the location of the xilinx directory of the folder where the repo was cloned.
        3. Source the IP generation files (Normally only the script is needed, but with more IPs... More scripts to run first)
        4. Load the IP repository and update it.
        5. Open the Block Design.
        6. Start the GUI and magic will happen.

        ```tcl
        $ cd src/xilinx
        $ source daphne3_ip_gen.tcl
        $ source axilite_ram_ip_gen.tcl                               <---- This one can be skipped if this IP is not in the design
        $ set_property IP_REPO_PATHS ../ip_repo [current_project]
        $ update_ip_catalog 
        $ read_bd ../bd/DAPHNE_V3_F4_3/DAPHNE_V3_F4_3.bd
        $ open_bd_design ../bd/DAPHNE_V3_F4_3/DAPHNE_V3_F4_3.bd
        $ upgrade_ip [get_ips]
        $ start_gui
        ```

    2. If you have not run the `src/xilinx/vivado_batch.tcl`:

        1. Run Vivado in TCL mode.
        2. Navigate to the location of the xilinx directory of the folder where the repo was cloned.
        3. Make sure you get the git commit number first in the TCL environment.
        4. Source the Block Design generation file.
        5. Start the GUI and magic will happen.

        ```tcl
        $ cd src/xilinx
        $ set git_sha [exec git rev-parse --short=7 HEAD]
        $ set v_git_sha "28'h$git_sha"
        $ source daphne3_bd_gen.tcl
        $ start_gui
        ```

3. Once both the DAPHNE3 IP and the Block Design have been created, the batch file creates a wrapper for the TOP level fo the Block Design, generates all the necessary outputs of each IP (wrappers, constraints, and so on) and then starts the design building process, by running the synthesis, then implementation, and then the bitstream (In a super summarized way of saying it).        

## Does it meet timing?

The timing constraints for this design were written after finishing the process, look for the file:

    src/xilinx/output/post_route_timing_summary.rpt

Make sure to check for the "All user specified timing constraints are met" line inside this file. This would mean that the design met timing, and all of the constraints were successfully applied. If the design does not meet timing there will be negative slack in the worst timing paths, therefore in this case it is suggested to review and change the code to address and solve this critical warnings.

## Where can I found all the outputs?

Output files are usually ZIPPED up and attached to each commit in the comments section. The ZIPPED folder contains reports, binaries, platform files and device tree overlay files.

## What are we missing?

The design was pretty much written for a Windows version, so we still need to add lines of code that allow for a full automatic generation of device tree overlay in Linux. Windows does not allow the process to run fully automatic, as the `vivado_batch.tcl` script generates up to the `pl.dts - pl.dtsi` files, the user must run the `dtc` command by either using a Windows Subsystem for Linux installation (safer way), or a Machine that runs Linux as its OS, in order to generate both `pl.dtbo` and `shell.json` files.

- [x] Create Bitstream and Platform Files (`.bit .bin .xsa .dts .dtsi`).
- [x] Manually generate Device Tree Overlay Files (`.dtbo`) using WSL.
- [ ] Automatically generate Device Tree Overlay Files (`.dtbo`) using Linux.
- [ ] Automatically wrap everything up in a single folder so that DAPHNE's Petalinux xmultapp can load it.
- [ ] Automatically detect and add new sub IP cores (Current strategy is to reverse engineer `.xci` files).

<daniel.avila@eia.edu.co - daniel.avila.gomez@cern.ch>