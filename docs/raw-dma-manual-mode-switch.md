# DAPHNE10: DMA manual y retorno al modo por defecto

El comando instalado en `/home/petalinux/scripts/daphne-mode` usa los productos
cualificados de `/opt/daphne-dma-persistent-manual-20261012`. Su helper
privilegiado es `/usr/local/libexec/daphne-manual-mode.py`; no guarda contraseñas.

```sh
~/scripts/daphne-mode dma       # cargar DMA, configurar y medir alineación
~/scripts/daphne-mode status    # comprobar identidad, servicios y AFEs
~/scripts/daphne-mode default   # restaurar el perfil de arranque y su runtime
# "defecto" es un alias de "default"
```

Solicita sudo. Al entrar en DMA selecciona la imagen `630a9da`, servidor
experimental en `193.206.157.36:40001`, proveedor acotado y consumidor de sesión
persistente. Configura VGAIN 1700, offset 2275, trim/bias 0, LPF 10 MHz,
PGA 24 dB y clamp -2 dBFS, LNA 12 dB y clamp 1,15 Vpp, ADC14 unsigned y
bias-control 1300. Mide los cinco AFEs con rampa, aplica las ventanas comunes
de ocho lanes y verifica 32768 muestras. No reutiliza taps de otro arranque.
El scan se ejecuta por AFE, con 2 ms de asentamiento por cambio de timing;
conserva cada resultado y detiene la preparación si una verificación falla.

Repetir `dma` cuando ya está preparado sólo verifica el estado; conserva los
ajustes del experimento. Reiniciar manualmente el servidor invalida su cache de
alineación: se debe volver a configurar y medir antes de adquirir datos.

`default` lee el perfil actual de `/etc/daphne-gateware/default-profile` y su
configuración instalada. Restaura firmware, clockchip, endpoint, Hermes y
`daphne.service`. No modifica ese archivo ni la selección del próximo arranque.
La configuración analógica para otros experimentos queda a cargo del usuario.

La transición detiene los propietarios del driver, prueba reposo vivo y sólo
entonces permite retirar el overlay y descargar los módulos. La parada de
`firmware.service` también queda protegida mientras DMA está activo. Un driver
ocupado, una cuarentena o una prueba de reposo fallida aborta antes del unload;
no fuerza reset ni libera DDR insegura. Una transición fallida puede dejar el
runtime detenido: consultar el log y el estado antes de reintentar.

Las unidades experimentales y el guard se crean en `/run`: un reset vuelve a
la configuración de arranque por defecto. El cambio comparte el lock del
selector instalado. Usar este comando para las transiciones DMA; el selector
genérico no instala el proveedor ni configura el frontend DMA.

Registro: `/var/log/daphne-manual-mode.log`. Configuración solicitada,
alineación completa y verificación: `/var/lib/daphne-manual-mode/frontend-*`.
Fuentes: `scripts/deploy/daphne-mode`, `daphne_manual_mode.py` y
`daphne_dma_frontend.py`. El frontend usa seis clientes del mismo checkout y
los bindings instalados del build ARM cualificado. Los hashes de servidor,
módulos, bitstream y DTBO se verifican antes de entrar en DMA; un cambio de
kernel requiere recompilar el driver en daphne-dev contra PetaLinux.

Los clientes manuales de red deben usar los bindings de revisión 3 y seleccionar
explícitamente backend DMA. Las opciones de sesiones, ventanas y guardado están
en el [contrato server/clientes](raw-dma-persistent-server-client-contract.md).
Los límites físicos vigentes están en el [informe de cualificación](raw-dma-persistent-physical-results-2026-10-12.md).

## Validación del 2026-10-12 tras hard reset

Boot ID: `d029e578-9ef3-4921-93e9-9fb1f6c5f7f3`. Se confirmó el arranque
por defecto con imagen `e8faa9a`, servidor de `/usr/bin` y Hermes.

La primera transición se detuvo después de descargar el modo por defecto
porque `systemctl reset-failed` rechazó una unidad experimental no cargada.
Se corrigió el reset de las unidades pertinentes y la reanudación desde
un runtime vacío comprobado. No fue un fallo de carga hardware.

El primer scan combinado, con asentamiento de 10 us, falló su verificación
física final. Se retuvo el error en el log. La medición individual con 2 ms
pasó en los cinco AFEs, sin reducir muestras ni relajar las comprobaciones:
`frontend-20261012-095234`, máscaras `0xff`, VGAIN 1700 confirmado. Esto
documenta una medición posterior exitosa; no atribuye la causa del fallo.

El comando instalado `daphne-mode default` completó la descarga protegida
de DMA, retiró ambos módulos y restauró la imagen `e8faa9a`, el servidor de
`/usr/bin`, Hermes y las seis unidades de runtime comprobadas.

El regreso con `daphne-mode dma` también pasó, incluida nueva alineación en
`frontend-20261012-095514`: los cinco AFEs ALIGNED, máscaras `0xff`, generación
2 y VGAIN 1700. El comando `status` comprueba el mismo estado mediante RPC.
Una sesión real desde daphne-dev, N2/L32000/P4096 y canales 39/0/17, transfirió
384000 bytes: todos los contadores finales en 2, un START/STOP, guards válidos,
sin errores. Evidencia de cliente: `manual-mode-smoke-20261012.json` en
`/home/ecristal/daphne-tests/persistent-20261011`. DMA quedó activo para pruebas
manuales; el perfil del próximo arranque continuó en `self-trigger`.
La prueba final de reposo pasó con el servidor calibrado aún activo:
driver liberado y los tres motores HALTED. Archivo de evidencia copiado al PC:
`build/dma-persistent-transfer/manual-mode-evidence-20261012.tar.gz`, SHA256
`e42f9e61058b93cb9225a91af141bae6c49a89e3806cb13889dc3e70dbd4c66a`.

Las cuatro regresiones locales verifican: fallo de reposo impide parar
firmware/descargar módulos; el guard no descarga tras fallo; el guard del modo
por defecto no accede a registros DMA; repetir un DMA preparado conserva
la configuración actual.
