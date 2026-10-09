"""Check experimental DT preparation without hardware or firmware edits."""
import importlib.util
from pathlib import Path
import subprocess
import shutil
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('raw_dma_dts', ROOT / 'scripts/petalinux/prepare_raw_dma_dts.py')
DMA = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DMA)


def fixture():
    body = ['pl2: pl2 { compatible = "fixed-clock"; #clock-cells = <0>; clock-frequency = <199998001>; };']
    for path in range(3):
        base = 0xb0020000 + path * 0x20000
        body.append(f'''
        raw_dma_{path}: dma@{base:x} {{
          compatible = "xlnx,axi-dma-7.1", "xlnx,axi-dma-1.00.a";
          reg = <0 0x{base:x} 0 0x10000>;
          #dma-cells = <1>; xlnx,addrwidth = <40>;
          xlnx,include-sg; xlnx,sg-length-width = <26>;
          interrupt-parent = <&gic>;
          clocks = <&pl2>, <&pl2>, <&pl2>;
          clock-names = "s_axi_lite_aclk", "m_axi_sg_aclk", "m_axi_s2mm_aclk";
          dma-channel@{base+48:x} {{
            compatible = "xlnx,axi-dma-s2mm-channel";
            xlnx,datawidth = <128>; interrupts = <0 {104+path} 4>;
          }};
        }};
        pattern_{path}: dma-diagnostic-source@{base+65536:x} {{
          compatible = "dune.pds,dma-diagnostic-source-1.0";
          reg = <0 0x{base+65536:x} 0 0x1000>;
        }};''')
    return '/dts-v1/; /plugin/; / { fragment@2 { target = <&amba>; __overlay__ { #address-cells = <2>; #size-cells = <2>;\n' + '\n'.join(body) + '\n}; }; };'


class RawDmaDtsTests(unittest.TestCase):
    def test_three_consumers_preserve_provider_registers_and_clocks(self):
        original = fixture()
        output = DMA.transform(original)
        self.assertEqual(output.count('"daphne,raw-dma-diagnostic-v1"'), 3)
        for path, controller, _ in DMA.validate(original):
            output_controller = next(n for n in DMA.parse(output) if n.name == controller.name)
            self.assertEqual(controller.direct(), output_controller.direct())
            self.assertIn(f'dmas = <&raw_dma_{path} 1>;', output)
        self.assertIn('0xb0060030', output)
        self.assertNotIn('dma-coherent', output)

    def test_missing_local_labels_are_added(self):
        output = DMA.transform(fixture().replace('raw_dma_1: ', ''))
        self.assertIn('daphne_raw_dma_1: dma@', output)
        self.assertIn('dmas = <&daphne_raw_dma_1 1>;', output)

    def test_legacy_and_wrong_contracts_rejected(self):
        with self.assertRaises(ValueError):
            DMA.transform('/dts-v1/; / { model = "spybuffer"; };')
        for before, after in [('<40>', '<32>'), ('<26>', '<23>'),
                              ('<128>', '<64>'), ('<0 104 4>', '<0 104 1>'),
                              ('199998001', '200000000'),
                              ('xlnx,include-sg;', 'dma-coherent;'),
                              ('xlnx,datawidth = <128>;', 'xlnx,datawidth = <128>; xlnx,include-dre;'),
                              ('<0 0xb0030000 0 0x1000>', '<0 0xb0031000 0 0x1000>')]:
            with self.subTest(before=before):
                with self.assertRaises(ValueError):
                    DMA.transform(fixture().replace(before, after, 1))

    def test_duplicate_producer_and_existing_consumer_rejected(self):
        text = fixture().replace('compatible = "dune.pds,dma-diagnostic-source-1.0";',
                                'dmas = <&raw_dma_0 1>; compatible = "dune.pds,dma-diagnostic-source-1.0";', 1)
        with self.assertRaises(ValueError):
            DMA.transform(text)

    def test_comments_preserve_edit_offsets(self):
        output = DMA.transform(fixture().replace('raw_dma_1:', '/* { a fake comment } */ raw_dma_1:'))
        self.assertIn('/* { a fake comment } */ raw_dma_1:', output)
        self.assertEqual(output.count('daphne,path-id'), 3)

    def test_commented_properties_are_not_edited(self):
        text = fixture().replace('compatible = "dune.pds,dma-diagnostic-source-1.0";',
                '/* compatible = "example"; reg = <0 0 0 0>; */\n'
                'compatible = "dune.pds,dma-diagnostic-source-1.0";', 1)
        output = DMA.transform(text)
        self.assertIn('/* compatible = "example"; reg = <0 0 0 0>; */', output)
        self.assertEqual(output.count('"daphne,raw-dma-diagnostic-v1"'), 3)

    def test_opt_in_does_not_change_default_images(self):
        shared = (ROOT / 'petalinux/config/kr260/local.conf.append').read_text()
        self.assertNotIn('DAPHNE_ENABLE_RAW_DMA_DIAG', shared)
        self.assertNotIn('kernel-module-daphne-dma-diag', shared)
        recipe = (ROOT / 'petalinux/meta-daphne/recipes-kernel/linux/linux-xlnx_%.bbappend').read_text()
        self.assertIn('DAPHNE_ENABLE_RAW_DMA_DIAG ?= "0"', recipe)
        self.assertIn("bb.utils.contains('DAPHNE_ENABLE_RAW_DMA_DIAG', '1'", recipe)

    @unittest.skipUnless(shutil.which('dtc'), 'requires dtc on a Linux build host')
    def test_transformed_overlay_compiles_with_local_dma_relocations(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'raw.dts'
            output = Path(directory) / 'raw.dtbo'
            source.write_text(DMA.transform(fixture()))
            result = subprocess.run(['dtc', '-@', '-I', 'dts', '-O', 'dtb',
                                     '-o', str(output), str(source)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertGreater(output.stat().st_size, 0)


if __name__ == '__main__':
    unittest.main()
