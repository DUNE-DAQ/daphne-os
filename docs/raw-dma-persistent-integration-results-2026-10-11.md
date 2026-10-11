# Integración de sesión DMA persistente: resultados al 2026-10-11

Estado: implementación y builds verificados; **despliegue y campaña persistente física pendientes de acceso sudo**. La placa conserva la sesión anterior. No declarar `630a9da` cualificado físicamente a partir de estos resultados.

## Fuentes y contrato

Implementación local en `C:/Users/e_cri/Documents/DAPHNE/daphne-os`:

- `f644d40`: protobuf revisión 3, IDs y progreso persistentes.
- `6ebb9f9`: engine UAPI, staging acotado, servidor y pruebas C++/ZeroMQ.
- `bab54c6`: adaptador compartido, CLI de archivos y osc.py.
- `a66ec78`: compatibilidad de anotaciones de osc.py con Python 3.9.

Contrato: [raw-dma-persistent-server-client-contract.md](raw-dma-persistent-server-client-contract.md). El consumidor kernel y sus headers proceden de los cambios del hilo de firmware/driver, incluidos explícitamente en el snapshot; no se atribuyen a los commits del servidor/cliente.

El usuario corrigió expresamente el procedimiento de compilación: **driver en daphne-dev contra el proyecto PetaLinux que generó la imagen**, servidor nativo en daphne-10. Esta instrucción sustituye el requisito de build nativo del módulo en el handoff. No se compiló ningún módulo en daphne-10 ni se instaló el árbol de kernel en `/lib/modules`.

## Builds y pruebas offline

| Entorno | Resultado | Límite |
|---|---|---|
| PC, WSL Ubuntu 24.04 | Servidor y 28/28 casos de CTest PASS | Host x86 con wrapper SIMDe; Qt opcional omitido |
| PC, Python Conda/Qt offscreen | 23 pruebas de clientes y 6 de osc PASS | Sin placa |
| daphne-dev, Python 3.9.18/Qt offscreen | 23 pruebas de clientes y 6 de osc PASS | Sin placa, mocks |
| daphne-10, GCC 13.4.0 aarch64 | Servidor y 28/28 casos de CTest PASS | Un caso Qt dentro de persistent-client y seis de osc omitidos por dependencias; ejecutados en daphne-dev |
| daphne-dev y daphne-10 | Helpers de contrato y service del driver PASS | Codecs, ownership, layouts y MMIO simulado; no coherencia DDR |
| daphne-dev/PetaLinux | Consumidor kernel `W=1` PASS, sin advertencias | Compilación cruzada, no instalación |

La primera pasada ARM tuvo 27/28 por omitir `scripts/validation/diagnose_dma_patterns.py` en el bundle. Se incluyó el script y se repitió CTest completo: 28/28. El log inicial queda conservado y no representa un fallo de adquisición física.

Servidor ARM, directorio aislado:

```bash
cd /home/petalinux/dma-persistent-20261011-bab54c6
bash scripts/deploy/raw_dma_session_build.sh
```

El nombre del directorio conserva la etiqueta inicial; su `SOURCE_MANIFEST.json` actualizado identifica los fuentes `a66ec78` y los scripts de despliegue incluidos. CMake regenera conjuntamente C++ y Python con protoc 3.21.12.

Driver, ejecutado realmente en daphne-dev:

```bash
cd /home/ecristal/daphne-tests/persistent-20261011/server-client-petalinux-a66ec78
bash scripts/deploy/raw_dma_session_driver_build.sh
```

Proyecto: `/home/ecristal/daphne/daphne-dual-rc1-work/petalinux-dev`.
KDIR: `build/tmp/work-shared/xilinx-k26-kr/kernel-build-artifacts` dentro de ese proyecto.
Compilador de la receta original: `build/tmp/work/xilinx_k26_kr-amd-linux/linux-xlnx/6.18.10+git+v2026.1/recipe-sysroot-native/usr/bin/aarch64-amd-linux/aarch64-amd-linux-gcc`, GCC 13.4.0.
Vermagic: `6.18.10-xilinx-g4f7afe14f724 SMP mod_unload aarch64`, coincidente con `uname -r` de daphne-10.
No se modificó la configuración de ese proyecto.

## Huellas de artefactos

| Artefacto | SHA256 |
|---|---|
| Servidor ARM | `dfb0a74f9dbc81a5d2e24200f237ea3461aeb01bd75e17f4ce8366f9b25ccd09` |
| Consumidor kernel ARM | `d25ab970bb5288e1d419974f63ab92e9427163a34ec68a9d2a3c0f0f5f9a4255` |
| Sonda de sesión ARM | `bfb5195e55079c93986d43dece118ea0832d8ccc2a4cbc2dd19bae05fce7a91c` |
| UAPI sesión | `bccb38d3fc5d3bd864ab4ccae6bb0b322de1fc7d95531a935d0f4bb0a2e1cef5` |
| Proto high-level | `62b93753c43e7d15008f9315cc4988667205c51a61edb3c287c3d9ea9a1cb14e` |
| Binding Python high-level ARM | `0f1220af22abfc5655a9276d46c656f5fd317181d290e0676b40004dc9d4572d` |
| Binding Python low-level ARM | `da1fbafe0a60208ad80c7f4801c2f18199f21909564d236161922ad0cae1867a` |
| `.config` PetaLinux | `2ca71743d87937026933a6c743dba422e51fe2e7a01dff11a989a57c60d136e1` |
| `Module.symvers` PetaLinux | `ce047058ae59d23925cb4cc35654a209183882fd43eb15b26fd987650385309a` |

Firmware: se verificó íntegro el manifiesto del directorio `output-630a9da-session` y luego la copia recuperable `firmware-630a9da` en daphne-dev. Su paquete de transferencia `firmware-630a9da.tar.gz` tiene SHA256 `0f200fa168068665bca56daab77da6ccaf50a4ed1b74869095bc3130e394a165`. `630a9da` es fingerprint de fuentes, no commit Git; identidad esperada al cargar: `0x0630a9da`.

## Estado vivo y preparación

- daphne-10: `193.206.157.36:40001`, servicio `daphne-dma-manual.service` activo con el servidor anterior en `/opt/daphne-dma-trigger-manual-20261011`.
- Imagen actual `0x01d17a11`, protocolo 2, cinco AFEs `FRONTEND_ALIGNED`, máscaras `0xff`, generación 4 en el readback inicial.
- Perfil de arranque `/etc/daphne-gateware/default-profile`: `self-trigger`, sin cambios.
- Conjunto nuevo verificado, sin instalar, en `/home/petalinux/dma-persistent-stage-20261011`: `server-arm-artifacts`, `driver-arm-artifacts` y `firmware`.
- UART registra las tres interfaces FTDI desde daphne-JTAG-server. La actividad de consola aparece en `usb-Xilinx_DAPHNEMezz_FNALDMezz10-if01-port0`, 115200 8N1.
- Registro: `/home/ecristal/daphne-tests/persistent-20261011/uart` en daphne-JTAG-server; proceso en `uart-recorder.pid`. El recorder sólo lee, sin transmitir caracteres.
- JTAG conectado a hw_server `tcp:127.0.0.1:3122`; XSDB enumeró los cuatro A53 en ejecución sin halt/reset. Log `jtag-targets.log` en el mismo directorio.

Sudo rechazó la credencial facilitada en dos intentos. Se solicitó confirmar la contraseña o habilitar los comandos de instalación. No se detuvieron servicios ni retiraron módulos/overlay. La revisión automática rechazó una shell root interactiva por alcance excesivo; se sustituyó por un comando específico, que no llegó a ejecutarse por el fallo de autenticación.

Readback analógico guardado en `frontend-before-deploy.json`: VGAIN **1600** en los cinco AFEs, offsets 2275, trim/bias 0 y bias_control 1300. El handoff anterior citaba VGAIN 1700; registrar esta diferencia antes de reconfigurar. No se sobrescribieron parámetros ni se ejecutó scan/alineación durante esta etapa.

## Clientes y baseline físico

Todas las llamadas físicas de cliente de esta etapa se originaron en **daphne-dev** (`daphne-dev-alma94`). Entorno `/home/ecristal/daphne-tests/persistent-20261011/venv`, numpy/protobuf/pyzmq/tqdm/PyQt6/pyqtgraph. Ruta hacia la placa: `193.206.157.36 via 192.168.122.1 dev enp1s0 src 192.168.122.253`. Disco home: 97 GiB disponibles en la comprobación; no se midió aún caudal del enlace ni del sink.

Bindings copiados del build ARM y verificados por SHA256:

```bash
cd /home/ecristal/daphne-tests/persistent-20261011/server-client-petalinux-a66ec78
export DAPHNE_PROTO_PYTHON_DIR="$PWD/../server-arm-artifacts/protobuf"
../venv/bin/python scripts/validation/probe_dma_session_caps.py
```

Baseline **sobre la imagen anterior**, ejecutado con éxito:

```bash
timeout 60s ../venv/bin/python daphne-server/client/protobuf_acquire_list_channels.py \
  -ip 193.206.157.36 -port 40001 --dma --capture-mode finite \
  -trigger_source software -L 2048 -N 2 -chunk 1 -channel_list 39,0,17 \
  -foldername ../baseline-finite-old-1d17a11 --timeout_ms 10000
```

Cada archivo contiene 8192 bytes (2×2048 muestras u16). Rango observado: canal 39=8087..8111, canal 0=8188..8203, canal 17=8143..8158. Orden de canales solicitado conservado; decoder ADC14 y guardado terminados sin errores. Esto no prueba continuidad por rampa ni firmware nuevo.

El cliente persistente rechazó explícitamente la imagen anterior con `PERSISTENT_UNAVAILABLE`, sin crear trabajo ni fallback. Capabilities volvió a responder tras el baseline.

## Ensayos aún pendientes

1. Backup de la sesión viva y prueba privilegiada de quiescencia antes de unload; conservar reservas ante cuarentena.
2. Carga experimental de imagen/DTBO 630a9da, proveedor requerido y consumidor nuevo; preservar arranque por defecto.
3. Identidad real, CAPS ABI 1/features 31/slots 8, límites/CMA/permisos y nuevo servidor operativo.
4. Frontend configurado con parámetros acordados y alineación medida de los cinco AFEs.
5. Sonda patrón N=1/2/8/37, rutas/máscaras, P=0/P>0, L corto/largo, ventanas y generaciones; consumidor pausado y recuperación por créditos.
6. CLI persistente, última tanda parcial, append, IDs/READ/ACK inválidos, cancelación/lease/desconexión y DMA finito posterior.
7. osc.py real desde daphne-dev, Qt offscreen/render/guardado y cierre; regresión física spybuffer con su imagen correspondiente.
8. Benchmarks separados driver local, red/sink memoria y guardado; CPU/memoria/ocupación/pausas/ignored, sin atribuir coste de parada a copia.
9. N=100000/L=32000 sólo después de los casos acotados y del baseline real de red/sink. External/timing requieren estímulo controlado y siguen pendientes.

IRQ/CDC y latencia de parada del proveedor conservan las limitaciones del handoff. Las pruebas offline no las cierran.

## Evidencia conservada en el PC

`build/dma-persistent-transfer/` contiene el bundle reproducible con manifiesto, `server-arm-artifacts.tar.gz`, `driver-arm-artifacts.tar.gz`, `firmware-630a9da.tar.gz` y `evidence-client-20261011.tar.gz`. Los archivos de datos y logs no se incorporan a Git. Los scripts de build no instalan ni cambian servicios.
