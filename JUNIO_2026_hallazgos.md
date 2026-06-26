# Escaneo Boletín Oficial San Juan — Junio 2026 (foco minero)

## Cómo se accede (resuelto)
La web oficial es una SPA, pero el portal de transparencia Joomla/K2 publica lo mismo
en HTML plano con el **PDF por descarga directa**, sin Selenium:
`https://contenido.sanjuan.gob.ar/` → categoría id=48. Ya quedó cableado en `bsj/boletin.py`.

## Hallazgo que define el trabajo de extracción
La capa de **texto** del PDF trae solo el **índice, los títulos de sección y las
referencias de cobro** (N° de aviso / Cta. Cte. / importe). El **cuerpo de cada edicto
está pegado como imagen escaneada**. Consecuencia:
- Detectar **qué días hubo edictos de minas** → se puede sin OCR (el título de sección
  "EDICTOS DE MINAS" es texto nativo). Hecho abajo.
- Extraer **titular, mineral y coordenadas** → **requiere OCR** sobre esas páginas.
  Por eso `scan_junio.py` OCR-ea selectivamente solo las páginas de la sección de minas.

Nota: "Ministro de Minería" figura en el encabezado de TODOS los boletines; no indica
edictos. El detector busca el título de sección "EDICTOS DE MINAS".

## Ediciones de junio (listado completo del portal)
05, 08, 09, 10, 11, 12, 16, 17, 18, 19, 22, 23 de junio 2026.
(13–14 y 20–21 fines de semana; 15 sin edición.)

## Estado del escaneo (lo verificado en vivo, capa de texto)
| Fecha  | Págs | ¿Edictos de minas? | Referencia del aviso minero |
|--------|------|--------------------|-----------------------------|
| 11/06  | 40   | **SÍ**             | N° 17.152 (corre Jun 10/12, $99.180) |
| 18/06  | 52   | **SÍ**             | Cta. Cte. 26.313 (corre Jun 18/22, $46.800) |
| 19/06  | 36   | **SÍ**             | Cta. Cte. 26.313 (corre Jun 18/22) |
| 23/06  | 40   | no                 | — |
| 05, 08, 09, 10, 12, 16, 17, 22 | — | pendiente | correr `scan_junio.py` |

## Lo que ya se puede afirmar de junio
Hubo **al menos dos** publicaciones de edictos de minas distintas:
1. **N° 17.152** — aparece el 11/06, con vigencia "Junio 10/12" (probable también 10 y 12).
   Importe alto ($99.180), lo que suele indicar un edicto largo (muchos vértices o varios avisos).
2. **Cta. Cte. 26.313** — vigencia "Junio 18/22"; visto el 18 y 19 (probable también el 22).

El contenido (empresa, mineral, coordenadas) está en las imágenes de esas páginas:
se extrae corriendo el OCR selectivo de `scan_junio.py`.

## Para completar el mes (en tu máquina o en Claude Code)
```bash
pip install -r requirements.txt
pip install pytesseract pdf2image           # + sistema: tesseract-ocr tesseract-ocr-spa poppler-utils
python scan_junio.py 2026-06-01 2026-06-30 --salida ./out_junio
# rápido, solo calendario de días con minas (sin OCR):
python scan_junio.py 2026-06-01 2026-06-30 --sin-ocr
```
Salidas: `calendario_minero.json`, `pedimentos_mes.geojson`, `pedimentos_mes.xlsx`.
El GeoJSON se abre directo en `mapa_catastro_minero.html`.
