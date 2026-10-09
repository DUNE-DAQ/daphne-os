# DAPHNE raw DMA diagnostic kernel client

Experimental DMAengine client for three S2MM diagnostic producers, not physical
AFE waveforms. See the [build/usage and qualification runbook](../../../docs/raw-dma-diagnostics.md)
and [hardware contract](../../../docs/raw-dma-hardware-contract.md).

Build against a matching configured kernel:

```sh
make KDIR=/path/to/kernel/build
```

The optional PetaLinux recipe owns module packaging. Building does not load the
module, activate an overlay, start a producer or change runtime services.
The read-only UAPI reports actual DMA addresses; the client never writes DMA
hardware registers or constructs hardware descriptors. Closing a session
terminates and reclaims resources only after hardware cessation is proven.
