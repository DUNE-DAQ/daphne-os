import ctypes,importlib.util,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts/petalinux'))
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
AFE=load('afe',ROOT/'scripts/petalinux/prepare_afe_dma_dts.py')
OLD=load('fixture',ROOT/'tests/petalinux/test_raw_dma_dts.py')
CLI=load('cli',ROOT/'daphne-server/dma/daphne-afe-capture.py')
def fixture():
    text=OLD.fixture()
    return text.replace('pattern_0:', 'capture: afe-dma-capture@b0080000 { compatible="dune.pds,afe-dma-capture-1.0"; reg=<0 0xb0080000 0 0x1000>; }; pattern_0:')
class Tests(unittest.TestCase):
    def test_uapi_and_sizes(self):
        self.assertEqual(ctypes.sizeof(CLI.Config),32);self.assertEqual(ctypes.sizeof(CLI.Status),208)
        cfg,sizes=CLI.configuration([1,5,9,15],100000,100,2,10000,0x1234567)
        self.assertEqual(cfg.channel_mask,0x8222);self.assertEqual(sizes,[80000000,0,0])
        _,sizes=CLI.configuration(list(range(40)),100000,10,1,10000,1)
        self.assertEqual(sizes,[32000000,32000000,16000000])
    def test_invalid_admission(self):
        for channels,l,c,flags in [([],1,1,1),([40],1,1,1),([1,1],1,1,1),([0],0,1,1),([0],0xffffffff,2,1),([0],1,1,0),([0],1,1,4),([0],200000000,1,1)]:
            with self.assertRaises(ValueError):CLI.configuration(channels,l,c,flags,10000,1)
    def test_pattern_detects_corruption_and_channel_swap(self):
        data=b''.join(((ch<<10)|tick).to_bytes(2,'little') for tick in range(5) for ch in [1,5,9,15])
        CLI.verify_pattern(data[:14],[1,5,9,15],0);CLI.verify_pattern(data[14:],[1,5,9,15],7)
        with self.assertRaises(ValueError):CLI.verify_pattern(data,[5,1,9,15],0)
        corrupt=bytearray(data);corrupt[-1]^=1
        with self.assertRaises(ValueError):CLI.verify_pattern(corrupt,[1,5,9,15],0)
    def test_three_shared_consumers_and_safe_resource_map(self):
        out=AFE.transform(fixture())
        self.assertEqual(out.count('daphne,capture-controller = <&capture>;'),3)
        self.assertIn('dmas = <&raw_dma_0 1>, <&raw_dma_1 1>, <&raw_dma_2 1>;',out)
        self.assertIn('<0 0x940000e0 0 0x20>',out)
        for r in range(3):self.assertIn(f'<0 0x{0xb0020030+r*0x20000:x} 0 8>',out)
        self.assertEqual(out.count('daphne,raw-dma-diagnostic-v1'),3)
    def test_missing_wrong_duplicate_controller_and_coherency_rejected(self):
        text=fixture()
        for bad in [OLD.fixture(),text.replace('0xb0080000','0xdead0000'),text.replace('0x1000>; }; pattern_0','0x2000>; }; pattern_0'),
                    text.replace('#dma-cells = <1>','#dma-cells = <1>; dma-coherent'),
                    text.replace('pattern_0:', 'duplicate: afe-dma-capture@b0081000 { compatible="dune.pds,afe-dma-capture-1.0"; reg=<0 0xb0081000 0 0x1000>; }; pattern_0:')]:
            with self.assertRaises(ValueError):AFE.transform(bad)
    def test_transformed_input_rejected(self):
        with self.assertRaises(ValueError):AFE.transform(AFE.transform(fixture()))
if __name__=='__main__':unittest.main()
