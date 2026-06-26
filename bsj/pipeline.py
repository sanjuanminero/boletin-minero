"""
Pipeline de punta a punta para un boletín ya descargado (PDF local).

Uso:
    python -m bsj.pipeline ruta/al/boletin.pdf [--datum posgar2007] [--salida ./out]

Hace:
    1) Diagnostica si el PDF es texto o escaneado.
    2) Extrae texto (o avisa que hace falta OCR).
    3) Detecta avisos mineros y parsea expediente/titular/mineral/depto/sup/vértices.
    4) Convierte coordenadas GK Faja 2 -> WGS84 y escribe GeoJSON + XLSX.
"""

import argparse
import os
from datetime import date

from .boletin import diagnosticar_pdf, extraer_texto, extraer_texto_ocr
from .parser import parsear_boletin
from .outputs import guardar_geojson, guardar_xlsx


def procesar_pdf(ruta_pdf, datum="posgar2007", salida_dir=".", fecha_boletin=None, usar_ocr_si_hace_falta=False):
    fecha_boletin = fecha_boletin or date.today()
    diag = diagnosticar_pdf(ruta_pdf)
    print(f"[diagnóstico] {diag}")

    if diag["veredicto"] == "ESCANEADO":
        if usar_ocr_si_hace_falta:
            print("[ocr] PDF escaneado: corriendo OCR (puede tardar)...")
            texto = extraer_texto_ocr(ruta_pdf)
        else:
            raise SystemExit("PDF escaneado. Reintentá con --ocr (requiere tesseract instalado).")
    else:
        texto = extraer_texto(ruta_pdf)

    peds = parsear_boletin(texto)
    print(f"[parseo] {len(peds)} pedimento(s) minero(s) detectado(s)")
    for p in peds:
        flag = "  ⚠ REVISAR" if p.confianza != "alta" else ""
        print(f"   - {p.expediente or '(sin expte)'} | {p.titular or '(sin titular)'} "
              f"| {p.departamento or '?'} | {len(p.vertices)} vért.{flag}")

    os.makedirs(salida_dir, exist_ok=True)
    base = os.path.join(salida_dir, f"pedimentos_{fecha_boletin}")
    n_gj = guardar_geojson(peds, base + ".geojson", datum, fecha_boletin)
    n_xl = guardar_xlsx(peds, base + ".xlsx", datum, fecha_boletin)
    print(f"[salida] {base}.geojson ({n_gj} geometrías) | {base}.xlsx ({n_xl} filas)")
    return peds


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--datum", default="posgar2007",
                    choices=["campo_inchauspe", "posgar94", "posgar2007"])
    ap.add_argument("--salida", default="./out")
    ap.add_argument("--ocr", action="store_true")
    a = ap.parse_args()
    procesar_pdf(a.pdf, a.datum, a.salida, usar_ocr_si_hace_falta=a.ocr)
