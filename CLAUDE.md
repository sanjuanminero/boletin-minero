# CLAUDE.md — Boletín Minero San Juan

Contexto para trabajar este proyecto en Claude Code. Leer antes de tocar código.

## Qué es
Pipeline que lee el Boletín Oficial de San Juan desde la óptica minera: detecta
edictos del Juzgado Administrativo de Minas, extrae coordenadas + titular + mineral +
departamento + superficie, convierte Gauss-Krüger Faja 2 → WGS84 y genera GeoJSON y
planilla Excel. Incluye una app de mapa (`mapa_catastro_minero.html`, Leaflet + proj4).

## Estructura
- `bsj/coords.py`    — conversión GK/POSGAR Faja 2 ↔ WGS84 (probado con punto control SJ).
- `bsj/boletin.py`   — descarga + diagnóstico texto/escaneado + OCR (PyMuPDF rasteriza, tesseract OCR-ea; sin poppler).
- `bsj/parser.py`    — detección de avisos mineros + extracción de campos, titular, mina y vértices.
- `bsj/eventos.py`   — **taxonomía de eventos** del derecho procesal minero + agregación al modelo expediente→eventos→titulares.
- `bsj/outputs.py`   — GeoJSON, XLSX y **modelo.json** (modelo rico para el visor).
- `bsj/catastro.py`  — cliente **GeoServer WFS/WMS** del Catastro Minero Digital (fuente autoritativa, POSGAR 2007). `descargar_padron()` baja las capas a `out_2026/catastro/*.geojson`; `buscar()` filtra por CQL. (Antes era ArcGIS, se reescribió.)
- `bsj/cruce.py`     — **cruce boletín↔catastro**: matchea cada expediente (por nº de expediente canónico, nombre de mina, o punto-en-polígono) y agrega el bloque `catastro` (geometría + atributos oficiales). `enriquecer(salida)` reescribe modelo.json. ~77/82 con match en 2026.
- `bsj/sociedades.py` — **base de sociedades/titulares** desde el catastro (minas+manifestaciones tienen `titular`+`fechaInscripcion`+geom). Separa co-titularidad (' - ') en entidades y genera aristas para el entramado. Produce `sociedades.json`.
- `sociedades.html`  — **buscador por sociedad**: escribís una sociedad/persona y ves todas sus propiedades en el mapa + fechas de registro + co-titulares + edictos.
- `red.html`         — **entramado**: grafo de co-titularidad (personas/sociedades), clústers familiares (ej. Bastias), fuerza propia en canvas. Nota: los edictos NO nombran agrimensores (0 menciones en el OCR).
- `bsj/pipeline.py`  — orquesta un PDF suelto (legado).
- `escanear.py`      — **orquestador principal**: escanea un rango de fechas → modelo.json + geojson + xlsx + calendario.
- `actualizar.ps1`   — **corrida diaria** (Programador de tareas, tarea `BoletinMinero-Diario` 07:00): encadena escanear→reproyectar→descargar_padron→cruce sobre `out_<año>`. Logs en `logs/`. Incremental por caché de PDF/OCR.
- `visor.html`       — **visor nuevo**: mapa + panel de expedientes + filtros año/mes/tipo/búsqueda + resumen anual (carga modelo.json). Tiene control de capas con el **padrón del catastro** (GeoJSON local de `out_2026/catastro/`, lazy + clickeable). OJO: el navegador no puede pegarle al GeoServer por CORS → el padrón se baja server-side.
- `scan_junio.py`, `mapa_catastro_minero.html` — versiones viejas (formato "pedimento" suelto), superadas por `escanear.py`/`visor.html`.

## Modelo de datos (clave conceptual)
La unidad NO es el edicto suelto: es el **EXPEDIENTE** (identificador estable). Un mismo
expediente atraviesa etapas (cateo → manifestación → mensura → registro → servidumbre/
transferencia → caducidad/vacancia) y cada acto se publica varias veces dentro de un plazo
legal (mensura/manifestación 3× en 15 días; cateo 2×/10 días). Por eso el pipeline (a)
clasifica el `tipo_evento` y (b) colapsa las publicaciones repetidas en un evento con N
apariciones. Atributos estables: expediente, departamento, coordenadas. Mutables (historizados):
titular, mineral/categoría, nombre de mina. La geometría de OCR se limpia en
`eventos.finalizar_geometria`: descarta vértices outlier (un dígito mal leído deja un
punto a cientos de km y estiraba el polígono) con criterio robusto por MAD, y dibuja el
envolvente convexo para un footprint limpio. Fundamento legal completo: ver memoria
`derecho-procesal-minero-sj`. Marco: Cód. Minería Nación (Ley 1919) + Cód. Proc. Mineros SJ (688-M).

## Invariantes técnicos (NO romper)
- San Juan está en **Faja 2** de Gauss-Krüger, meridiano central **−69°**.
- EPSG por datum en Faja 2:
  - Campo Inchauspe → **22182**
  - POSGAR 94       → **22192**
  - POSGAR 2007     → **5344**  ⚠ (5345 es Faja 3, error fácil de cometer)
- Formato de número argentino: `3.500` = 3500 ; `6.511.304,01` = 6511304.01.
  El punto puede ser separador de miles. Ya está contemplado en `parser._num`.
- Datum equivocado corre el punto ~100–200 m. Lo nuevo es POSGAR 2007; mensuras
  viejas suelen ser Campo Inchauspe. Si el edicto no aclara, decidir por época.
- Rangos de validación de coordenadas SJ: Norte 6.0–7.2 M ; Este 2.3–2.7 M.

## Dos fuentes (se usan juntas)
- **Boletín Oficial** — acceso RESUELTO por el mirror K2 `contenido.sanjuan.gob.ar`
  (HTTP plano, PDF directo). Ver `bsj/boletin.py` (`listar_ediciones`/`link_descarga`).
  OJO: el cuerpo de los edictos está como IMAGEN → requiere OCR; los títulos de
  sección son texto. `scan_junio.py` OCR-ea solo las páginas de 'EDICTOS DE MINAS'.
- **Catastro Minero Digital** — ArcGIS Online, org `arcmineria`,
  visor `webappviewer id=27bfda03ce4342b3834a27010da857e5`. Debajo hay un
  FeatureServer REST con datos vectoriales en POSGAR 2007. Falta cargar la URL de
  la capa en `catastro.CAPA_PEDIMENTOS`.

## Cómo correr
En esta máquina Python NO está en PATH: usar `C:\Users\DAMS-04\AppData\Local\Programs\Python\Python312\python.exe`
(ver memoria `entorno-boletin-minero`). Tesseract en `C:\Program Files\Tesseract-OCR`; el español
(`spa.traineddata`) está en `./tessdata` y se levanta vía `TESSDATA_PREFIX` desde `bsj.boletin`.
```bash
pip install -r requirements.txt          # núcleo
pip install pytesseract Pillow           # OCR (+ binario tesseract con spa)
python escanear.py 2026-01-01 2026-12-31 --salida ./out_2026 --datum posgar94
python escanear.py 2026-06-01 2026-06-30 --salida ./out --sin-ocr   # solo calendario (rápido)
python reproyectar.py ./out_2026 --datum posgar2007                 # recalcular WGS84 sin re-OCR
python -c "from bsj import catastro; catastro.descargar_padron('./out_2026/catastro')"  # padrón oficial
python -m bsj.cruce ./out_2026                                      # cruce boletín↔catastro
```
Flujo completo de regeneración: `escanear.py` → `reproyectar.py` (opcional) → `descargar_padron` → `bsj.cruce`.
Abrir el visor: servir la carpeta por HTTP (`python -m http.server 8765`) y entrar a
`http://localhost:8765/visor.html` (autocarga `out_2026/modelo.json`). Bajo `file://` algunos
navegadores bloquean el fetch: usar el botón "Cargar modelo.json".

## Pendientes (orden sugerido)
- [x] 1. Confirmar texto vs escaneado (es escaneado → OCR selectivo de páginas de minas).
- [x] 2. Cablear el endpoint del boletín (mirror K2, HTML real con `&amp;` y fecha en el slug).
- [x] 4. Ajustar el parser al formato real (expediente `N*`, tablas de coords con `|` y decimal en punto, titular).
- [x] +. Modelo expediente→evento→titular, taxonomía de eventos y visor nuevo con filtro mes/año.
- [x] 3/8. Catastro cableado (GeoServer WFS/WMS) y superpuesto en el visor como capas GeoJSON.
- [x] 4b. **Extracción de nº de expediente mejorada**: el regex salta basura no-numérica tras
    'Expte.' y captura desde el primer dígito (tolera N°/NS/N*/'es' y pegados '1124000474-2022').
    Resultado: 49/52 con número y los derechos se de-fragmentaron (82→52 expedientes), con 100%
    de match al catastro (38 firmes por expediente). El OCR se cachea en `out_2026/ocr/` para iterar.
- [x] 5. **Cruce boletín ↔ catastro** hecho (`bsj/cruce.py`): match por expediente canónico (alta),
    nombre de mina (media) y punto-en-polígono (media/baja); ~77/82. El visor dibuja la geometría
    oficial y muestra atributos limpios + badge ✓ catastro. Pendiente fino: los matches espaciales
    (confianza media/baja) son inferencias — revisar manualmente los críticos.
- [x] 6. Corrida diaria automatizada (tarea `BoletinMinero-Diario`, 07:00, `actualizar.ps1`). Acumula
    el año en `out_<año>`. Falta histórico multi-año unificado.
7. Lista de "titulares vigilados" + alerta por mail (PRÓXIMO).
- [x] 8. Visor: capas del catastro + selector de mapa base (Calles OSM / Satélite Esri / Terreno OpenTopoMap).
9. Datum: todo 2026 es POSGAR 2007 Faja 2 (EPSG 5344) — default ya seteado.
10. (sigue) Automatizar corrida diaria + histórico; alertas de titulares vigilados.

## Estilo de trabajo
Español rioplatense, ejecución directa (probar y mostrar, no planificar de más).
Verificar siempre las conversiones contra un punto de control conocido.
