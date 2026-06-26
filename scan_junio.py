"""
Escaneo de un mes completo del Boletín Oficial de San Juan, foco minero.

Para cada edición del rango:
  1) baja el PDF (HTTP directo desde el mirror K2),
  2) detecta si trae sección "EDICTOS DE MINAS" (texto nativo, sin OCR),
  3) si trae, OCR-ea SOLO esas páginas y corre el parser de pedimentos,
  4) acumula todo en GeoJSON + XLSX + un calendario minero del mes.

Requiere OCR para el contenido: pip install pytesseract pdf2image
  + sistema: tesseract-ocr tesseract-ocr-spa poppler-utils

Uso:
    python scan_junio.py 2026-06-01 2026-06-30 --salida ./out_junio
    python scan_junio.py 2026-06-01 2026-06-30 --sin-ocr   # solo calendario (rápido)
"""

import argparse
import os
import json
from bsj import boletin, parser as P, outputs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("desde"); ap.add_argument("hasta")
    ap.add_argument("--salida", default="./out_mes")
    ap.add_argument("--datum", default="posgar2007")
    ap.add_argument("--sin-ocr", action="store_true", help="solo detectar días con minas")
    a = ap.parse_args()
    os.makedirs(a.salida, exist_ok=True)
    pdf_dir = os.path.join(a.salida, "pdf"); os.makedirs(pdf_dir, exist_ok=True)

    ediciones = boletin.listar_ediciones(desde=a.desde, hasta=a.hasta)
    print(f"Ediciones en el rango: {len(ediciones)}")

    calendario, todos = [], []
    for e in ediciones:
        url, nombre, pags = boletin.link_descarga(e["item_url"])
        if not url:
            print(f"  {e['fecha']}: sin PDF"); continue
        destino = os.path.join(pdf_dir, f"{e['fecha']}.pdf")
        if not os.path.exists(destino):
            boletin.bajar_pdf(url, destino)
        texto = boletin.extraer_texto(destino)
        hay = boletin.tiene_edictos_de_minas(texto)
        fila = {"fecha": e["fecha"], "paginas": pags, "minas": hay, "pedimentos": 0}
        print(f"  {e['fecha']}  ({pags}p)  minas={'SÍ' if hay else 'no'}")

        if hay and not a.sin_ocr:
            pgs = boletin.paginas_de_minas(destino)
            print(f"      OCR de páginas de minas: {[x+1 for x in pgs]}")
            txt_minas = boletin.extraer_texto_ocr(destino, solo_paginas=pgs)
            peds = P.parsear_boletin(txt_minas)
            fila["pedimentos"] = len(peds)
            for p in peds:
                p.crudo = f"[{e['fecha']}] " + p.crudo
            todos.extend((e["fecha"], p) for p in peds)
            for p in peds:
                print(f"        - {p.expediente or '(s/expte)'} | {p.titular or '?'} "
                      f"| {p.departamento or '?'} | {len(p.vertices)} vért.")
        calendario.append(fila)

    # salidas
    with open(os.path.join(a.salida, "calendario_minero.json"), "w", encoding="utf-8") as f:
        json.dump(calendario, f, ensure_ascii=False, indent=2)
    if todos:
        peds = [p for _, p in todos]
        outputs.guardar_geojson(peds, os.path.join(a.salida, "pedimentos_mes.geojson"), a.datum)
        outputs.guardar_xlsx(peds, os.path.join(a.salida, "pedimentos_mes.xlsx"), a.datum)

    dias_minas = [c["fecha"] for c in calendario if c["minas"]]
    print(f"\nResumen: {len(calendario)} ediciones, {len(dias_minas)} con edictos de minas.")
    print("Días con minas:", ", ".join(dias_minas) or "ninguno")
    if todos:
        print(f"Pedimentos parseados (con OCR): {len(todos)}")


if __name__ == "__main__":
    main()
