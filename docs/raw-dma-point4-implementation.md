# Punto 4: cliente mínimo para captura AFE finita

Implementación experimental sobre `293ec79`. Spybuffer continúa como default;
no se cambia daphneServer, el perfil por defecto ni los servicios. No hay ring,
N total, créditos ni descarga Ethernet concurrente (puntos 5–7).

Requiere el firmware nuevo con capabilities `0x530`, ABI 2.0 y variante 3,
controlador AFEC ABI/formato 1 en `0xB0080000`, y provider Xilinx con la
terminación acotada cualificada en punto 3. El driver comprueba identidad antes
de acceder al nuevo MMIO, incluso al consultar estado o cerrar una sesión
sin configuración válida. Firmware viejo se rechaza.

Una máscara no vacía de canales 0–39, L y C produce S=L*C ticks consecutivos
con un START común. Una ruta vacía no produce payload. Rutas: 0–15, 16–31,
32–39. Layout raw16 little-endian, tick y canal creciente; 16-bit ADC original.
Bytes válidos 2*K*S, DMA redondeado a 16; read elimina el padding final.
Un chunk es un paquete por ruta; cadena SG completa de bloques hasta 4 MiB,
preparada antes de START. Máximo 256 MiB por ruta y 448 MiB de asignaciones
por defecto (guards/páginas incluidos; CMA 512 MiB no garantiza disponibilidad).

`/dev/daphne-afe-dma` exclusivo/0600. Se reclaman los tres motores para evitar
mezclar diagnóstico y captura. MODE 0 diagnóstico al reset/cierre, MODE 1
captura explícita. El diagnóstico anterior conserva su ABI y acepta el bit
adicional, comprobando MODE=0. Las configuraciones de imágenes por defecto
no incluyen este módulo; solo el ejemplo raw-dma opt-in lo añade.

Preparación del DTS desde el nuevo XSA normalizado:

```bash
python3 scripts/petalinux/prepare_afe_dma_dts.py pl.normalized.dts pl.linux-afe.dts
```

No cargar un DTBO preparado para el firmware viejo. Rechaza falta/duplicación
del capturador, direcciones incorrectas, coherencia/provider incompatibles y
entrada ya transformada. Las referencias DMA S2MM usan argumento 1.

Después de síntesis, revisión de timing/CDC/XSA, DTBO y carga mediante el
procedimiento de diagnóstico aprobado:

```bash
sudo python3 daphne-server/dma/daphne-afe-capture.py --acquisition dma-afe \
  --channels 1,5,9,15 --length 100000 --count 100 --pattern \
  --expected-build-id 0xBUILDID --output /tmp/afe-pattern-run
```

`--pattern` prueba el productor pre-CDC `(canal<<10)|(tick&1023)`, no los AFEs.
Captura física utiliza `--frontend-aligned` después de configurar/alinear los
AFEs con el procedimiento existente. Readiness eléctrico no comprueba cada
lane. Se registra timestamp del primer tick y su validez, sin calibración aún
del desfase respecto al ADC.

Solo se lee un chunk COMPLETE íntegro, con sizes/beats/ticks/guards correctos.
Overflow, salud perdida, reset DMA o timeout invalidan el conjunto. ABORT y
cierre prueban HALTED/RUN/RESET antes de liberar; si falla se conservan buffers
y canales en cuarentena y no se debe retirar el overlay. Herramienta escribe
routeN.raw16/metadata.json, comprueba patrón completo cuando se solicita, halt,
liberación y reapertura. No reintenta ni cambia gateware/servicios.

Evidencia sin placa: 6 tests nuevos Python PASS, 7 tests DTS anteriores PASS
(1 de dtc omitido por falta en PATH), diagnóstico C++ compilado con g++ y tests
unitarios/default spybuffer PASS; ambos módulos compilados contra el kernel
6.18.10-xilinx-g4f7afe14f724 de daphne-dev sin warnings. FW: simulación XPM real
2026.1 PASS con máscaras parciales/40 canales, stalls, salud/reset, overflow y
rearme; todavía no hay síntesis ni calificación física del capturador nuevo.

Secuencia de placa pendiente: admisión/identidad y control; patrones canales
0,39,1/5/9/15 y 40; caso >4 MiB por ruta para cruzar SG; cancelación/rearme y
CMA restaurado; finalmente patrón AFE por canal, orden de lanes y captura
física. El cierre de punto 3 no sustituye esas pruebas. Puntos 5/7 aguardan
la validación de esta fuente AFE.
