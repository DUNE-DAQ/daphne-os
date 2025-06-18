-- daphne3_package.vhd
-- Jamieson Olsen <jamieson@fnal.gov>

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

package daphne3_package is

    type array_4x4_type is array (3 downto 0) of std_logic_vector(3 downto 0);
    type array_4x6_type is array (3 downto 0) of std_logic_vector(5 downto 0);
    type array_4x14_type is array (3 downto 0) of std_logic_vector(13 downto 0);
    type array_4x32_type is array (3 downto 0) of std_logic_vector(31 downto 0);
    type array_5x4_type is array (4 downto 0) of std_logic_vector(3 downto 0);
    type array_5x8_type is array (4 downto 0) of std_logic_vector(7 downto 0);
    type array_5x9_type is array (4 downto 0) of std_logic_vector(8 downto 0);
    type array_8x4_type is array (7 downto 0) of std_logic_vector(3 downto 0);
    type array_8x14_type is array (7 downto 0) of std_logic_vector(13 downto 0);
    type array_8x32_type is array (7 downto 0) of std_logic_vector(31 downto 0);
    type array_9x14_type is array (8 downto 0) of std_logic_vector(13 downto 0);
    type array_9x16_type is array (8 downto 0) of std_logic_vector(15 downto 0);
    type array_9x32_type is array (8 downto 0) of std_logic_vector(31 downto 0);
    type array_10x6_type is array (9 downto 0) of std_logic_vector(5 downto 0);
    type array_10x14_type is array (9 downto 0) of std_logic_vector(13 downto 0);
    type array_40x64_type is array(39 downto 0) of std_logic_vector(63 downto 0);

    type array_4x4x6_type is array (3 downto 0) of array_4x6_type;
    type array_4x4x14_type is array (3 downto 0) of array_4x14_type;
    type array_4x10x6_type is array (3 downto 0) of array_10x6_type;
    type array_4x10x14_type is array (3 downto 0) of array_10x14_type;
    type array_5x8x4_type is array (4 downto 0) of array_8x4_type;
    type array_5x8x14_type is array (4 downto 0) of array_8x14_type;
    type array_5x8x32_type is array (4 downto 0) of array_8x32_type;
    type array_5x9x14_type is array (4 downto 0) of array_9x14_type;
    type array_5x9x16_type is array (4 downto 0) of array_9x16_type;
    type array_5x9x32_type is array (4 downto 0) of array_9x32_type;

    -- default values for self trigger output record header fields

    constant DEFAULT_link_id:     std_logic_vector(5 downto 0) := "000000";
    constant DEFAULT_slot_id:     std_logic_vector(3 downto 0) := "0010";
    constant DEFAULT_crate_id:    std_logic_vector(9 downto 0) := "0000000011";
    constant DEFAULT_detector_id: std_logic_vector(5 downto 0) := "000010";
    constant DEFAULT_version_id:  std_logic_vector(5 downto 0) := "000011";

    -- default values for self trigger algo

    constant DEFAULT_threshold: std_logic_vector(13 downto 0) := "10000000000000";
    constant DEFAULT_runlength: integer := 256;
    constant DEFAULT_core_enable: std_logic_vector(39 downto 0) := X"0000000000";

    -- default values for 10G Ethernet sender

    constant DEFAULT_ext_mac_addr_0: std_logic_vector(47 downto 0)  := X"DEADBEEFCAFE"; -- Ethernet MAC address
    constant DEFAULT_ext_ip_addr_0: std_logic_vector(31 downto 0)   := X"C0A80064"; -- Ethernet IP address 192.168.0.100
    constant DEFAULT_ext_port_addr_0: std_logic_vector(15 downto 0) := X"1234"; -- Ethernet Port number

end package;


