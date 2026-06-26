"""
Reproyecta un modelo.json existente a otro datum SIN re-escanear ni re-OCR.
Usa los vértices planos Gauss-Krüger ya guardados (`vertices_gk`), que son
independientes del datum, y regenera poligono_wgs84, centroide, modelo.json,
GeoJSON y XLSX.

Uso:
    python reproyectar.py ./out_2026 --datum posgar2007
"""

import argparse
import json
import os

from bsj import coords, outputs, eventos


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("salida", help="carpeta con modelo.json")
    ap.add_argument("--datum", default="posgar2007")
    a = ap.parse_args()

    ruta = os.path.join(a.salida, "modelo.json")
    doc = json.load(open(ruta, encoding="utf-8"))
    exps = doc["expedientes"]

    cambiados = 0
    for e in exps:
        e["datum"] = a.datum
        raw = e.get("vertices_gk") or []
        # limpia outliers de OCR + envolvente convexo + reproyecta al datum pedido
        ring, pol, cen = eventos.finalizar_geometria(raw, a.datum, coords)
        e["vertices_gk"] = [list(v) for v in ring]
        e["n_vertices"] = len(ring)
        e["poligono_wgs84"] = pol
        e["centroide"] = cen
        if pol:
            cambiados += 1

    doc.setdefault("meta", {})["datum"] = a.datum
    outputs.guardar_modelo_json(exps, ruta, doc.get("meta"))
    outputs.guardar_modelo_geojson(exps, os.path.join(a.salida, "pedimentos.geojson"))
    outputs.guardar_modelo_xlsx(exps, os.path.join(a.salida, "pedimentos.xlsx"))
    print(f"Reproyectados {cambiados}/{len(exps)} expedientes a {a.datum}.")


if __name__ == "__main__":
    main()
