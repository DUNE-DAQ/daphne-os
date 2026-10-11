"""Python client against the actual C++ service/protobuf over ZeroMQ, offline."""
import subprocess
import sys
import time
import unittest
import numpy as np
from test_dma_client import DmaClient, pb
from v2_client import V2Client

BINARY=sys.argv.pop() if len(sys.argv)>1 else None

@unittest.skipUnless(BINARY,'C++ fixture binary required')
class TransportTests(unittest.TestCase):
    def test_cpp_service_incremental_queue_wrap_pressure_and_cancel(self):
        proc=subprocess.Popen([BINARY,'--offline-fixture'],stdout=subprocess.PIPE,text=True)
        try:
            address=proc.stdout.readline().strip()
            self.assertTrue(address.startswith('tcp://127.0.0.1:'))
            with V2Client(pb,'127.0.0.1',int(address.rsplit(':',1)[1]),timeout_ms=5000) as transport:
                client=DmaClient(pb,transport.rpc)
                client.start_session([39,0,17],32769,37,pretrigger=1000,job_timeout_ms=20000)
                time.sleep(.05)
                before=client.session_status()
                self.assertEqual(len(before.available_events),16)
                self.assertEqual(before.state,pb.DMA_JOB_RUNNING)
                done=0
                while done<37:
                    data,meta=client.read_batch(min(7,37-done))
                    for w in range(data.shape[0]):
                        for i,ch in enumerate([39,0,17]):
                            np.testing.assert_array_equal(data[w,i],(np.arange(32769)+ch*100+(done+w)*10)&0x3fff)
                        self.assertEqual(meta['waveforms'][w]['trigger']['event_id']['sequence'],done+w+1)
                    client.ack_batch();done+=data.shape[0]
                final=client.finish_session()
                self.assertEqual(final.session_progress.starts,1)
                self.assertEqual(final.session_progress.stops,1)
                self.assertEqual(final.session_progress.acknowledged,37)
                client.start_session([0],2048,(1<<32)+1)
                client.cancel()
                self.assertIsNone(client.job_id)
        finally:
            proc.terminate();proc.wait(timeout=5);proc.stdout.close()

if __name__=='__main__':unittest.main()
