"""
Escaneo del Boletín Oficial de San Juan con foco minero -> modelo
expediente -> eventos -> titulares (ver bsj/eventos.py).

Para cada edición del rango:
  1) baja el PDF (HTTP directo del mirror K2),
  2) detecta la sección "EDICTOS DE MINAS" (texto nativo, sin OCR),
  3) si la trae, OCR-ea SOLO esas páginas y corre el parser,
  4) clasifica el tipo de evento y agrega todo por expediente,
     colapsando las publicaciones repetidas de un mismo acto.

Salidas en --salida:
  modelo.json              -> visor (expedientes + eventos + titulares + calendario)
  pedimentos.geojson       -> un polígono por expediente (mapa / QGIS)
  pedimentos.xlsx          -> una fila por expediente
  calendario_minero.json   -> días con edictos de minas

Uso:
    python escanear.py 2026-01-01 2026-12-31 --salida ./out_2026 --datum posgar94
    python escanear.py 2026-06-01 2026-06-30 --sin-ocr      # solo calendario
"""

import argparse
import os
import json
from datetime import datetime, timezone

import fitz  # PyMuPDF (para contar páginas de PDFs cacheados)
from bsj import boletin, parser as P, outputs, eventos, coords


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("desde"); ap.add_argument("hasta")
    ap.add_argument("--salida", default="./out_mes")
    ap.add_argument("--datum", default="posgar2007")  # SJ 2026: GK Faja 2 POSGAR 2007
    ap.add_argument("--sin-ocr", action="store_true", help="solo detectar días con minas")
    ap.add_argument("--ocr-detect", action="store_true",
                    help="OCR-detecta ediciones escaneadas sin capa de texto (2021). Caro.")
    a = ap.parse_args()
    os.makedirs(a.salida, exist_ok=True)
    pdf_dir = os.path.join(a.salida, "pdf"); os.makedirs(pdf_dir, exist_ok=True)
    ocr_dir = os.path.join(a.salida, "ocr"); os.makedirs(ocr_dir, exist_ok=True)

    ediciones = boletin.listar_ediciones(desde=a.desde, hasta=a.hasta)
    print(f"Ediciones en el rango: {len(ediciones)}")

    calendario, todos = [], []
    for e in sorted(ediciones, key=lambda x: x["fecha"]):
        destino = os.path.join(pdf_dir, f"{e['fecha']}_{e['item_id']}.pdf")
        pags = None
        if not os.path.exists(destino):
            # solo consultamos el item (HTTP) si hay que bajar el PDF
            url, nombre, pags = boletin.link_descarga(e["item_url"])
            if not url:
                print(f"  {e['fecha']}: sin PDF"); continue
            try:
                boletin.bajar_pdf(url, destino)
            except Exception as ex:
                print(f"  {e['fecha']}: error al bajar ({ex})"); continue
        texto = boletin.extraer_texto(destino)
        if pags is None:  # PDF cacheado: las páginas salen del propio archivo
            try:
                _d = fitz.open(destino); pags = _d.page_count; _d.close()
            except Exception:
                pags = None
        hay = boletin.tiene_edictos_de_minas(texto)
        cache = os.path.join(ocr_dir, f"{e['fecha']}_{e['item_id']}.txt")

        # OCR-detección para años ESCANEADOS sin capa de texto (2021), solo con --ocr-detect.
        # Cachea el resultado (aunque sea vacío = marcador de 'sin minas') para no re-OCR-ear.
        # OJO: solo 2021 tiene la minería 100% en imágenes (sin señal en la capa de
        # texto). 2020 es texto nativo y 2022-2026 se detectan por texto, así que
        # OCR-detectar esos años sería OCR-ear de más miles de páginas no-mineras.
        txt_ocrdet = None
        if (not hay and a.ocr_detect and not a.sin_ocr and e["fecha"][:4] == "2021"
                and boletin.esta_escaneado(texto, pags or 1)):
            if os.path.exists(cache):
                txt_ocrdet = open(cache, encoding="utf-8").read()
            else:
                print(f"  {e['fecha']}  ({pags}p)  OCR-detección de escaneado…")
                txt_ocrdet = boletin.minas_por_ocr(destino)
                with open(cache, "w", encoding="utf-8") as fh:
                    fh.write(txt_ocrdet)
            hay = bool(txt_ocrdet.strip())

        fila = {"fecha": e["fecha"], "item_id": e["item_id"], "paginas": pags,
                "minas": hay, "eventos": 0}
        print(f"  {e['fecha']}  ({pags}p)  minas={'SÍ' if hay else 'no'}")

        if hay and not a.sin_ocr:
            # caché de OCR determinística (permite iterar el parser sin re-OCR-ear).
            if txt_ocrdet is not None:
                txt_minas = txt_ocrdet                    # ya OCR-eado por la detección
            elif os.path.exists(cache):
                txt_minas = open(cache, encoding="utf-8").read()
                print("      texto/OCR (caché)")
            else:
                pgs = boletin.paginas_de_minas(destino)
                print(f"      texto/OCR páginas de minas: {[x+1 for x in pgs]}")
                txt_minas = boletin.texto_de_paginas(destino, pgs)  # nativo (2020) u OCR (2024+)
                with open(cache, "w", encoding="utf-8") as fh:
                    fh.write(txt_minas)
            peds = P.parsear_boletin(txt_minas)
            fila["eventos"] = len(peds)
            for p in peds:
                p.crudo = f"[{e['fecha']}] " + p.crudo
                todos.append((e["fecha"], p))
                print(f"        - {eventos.ETIQUETAS.get(p.tipo_evento, p.tipo_evento)} | "
                      f"{p.expediente or '(s/expte)'} | {p.titular or '?'} | "
                      f"{p.mina or '-'} | {p.departamento or '?'} | {len(p.vertices)} vért.")
        calendario.append(fila)

    # agregación al modelo
    expedientes = eventos.agregar_expedientes(todos, a.datum, coords)

    meta = {
        "generado": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "desde": a.desde, "hasta": a.hasta, "datum": a.datum,
        "n_ediciones": len(ediciones),
        "n_ediciones_con_minas": sum(1 for c in calendario if c["minas"]),
        "n_expedientes": len(expedientes),
        "calendario": calendario,
        "tipos": {k: v for k, v in eventos.ETIQUETAS.items()},
    }

    # GUARDIÁN de datos: si esta corrida no encontró expedientes (típico cuando el
    # mirror del boletín falla y lista 0 ediciones) NO pisar un modelo.json que ya
    # tiene datos. Sin esto, un fallo de red en la corrida diaria borra toda la base.
    modelo_path = os.path.join(a.salida, "modelo.json")
    if not expedientes and os.path.exists(modelo_path):
        try:
            prev = json.load(open(modelo_path, encoding="utf-8"))
            n_prev = len(prev.get("expedientes", []))
        except Exception:
            n_prev = 0
        if n_prev:
            print(f"\n[GUARDIÁN] 0 expedientes en esta corrida y el modelo existente "
                  f"tiene {n_prev}. No se sobrescribe (probable fallo del listado/red).")
            return

    with open(os.path.join(a.salida, "calendario_minero.json"), "w", encoding="utf-8") as f:
        json.dump(calendario, f, ensure_ascii=False, indent=2)
    outputs.guardar_modelo_json(expedientes, modelo_path, meta)
    outputs.guardar_modelo_geojson(expedientes, os.path.join(a.salida, "pedimentos.geojson"))
    outputs.guardar_modelo_xlsx(expedientes, os.path.join(a.salida, "pedimentos.xlsx"))

    # resumen
    dias = [c["fecha"] for c in calendario if c["minas"]]
    print(f"\nResumen: {len(calendario)} ediciones, {len(dias)} con edictos de minas, "
          f"{len(expedientes)} expedientes.")
    porestado = {}
    for ex in expedientes:
        porestado[ex["estado_label"]] = porestado.get(ex["estado_label"], 0) + 1
    for k, v in sorted(porestado.items(), key=lambda x: -x[1]):
        print(f"  {v:3d}  {k}")


if __name__ == "__main__":
    main()
