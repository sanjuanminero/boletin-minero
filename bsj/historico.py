"""
Análisis histórico y de VACANCIA del catastro minero.

Produce out_hist/analisis_historico.json para la pestaña "Análisis Histórico":

  1. antiguos  — registros ACTIVOS más viejos (minas/manifestaciones por fechaInscripcion).
                 Siguen en el padrón => siguen vigentes; los más viejos son los que más
                 tiempo llevan sin caducar.
  2. zonas     — grilla de "movimiento": celdas con más registros (cateos+manif+minas),
                 para detectar dónde hay más actividad.
  3. libres    — ÁREAS VACANTES donde se podría pedir un cateo. Clave conceptual: no
                 sirve el vacío del desierto del este (sin mineralización); lo útil son
                 los HUECOS dentro del cinturón minero (rodeados de manifestaciones/minas).
                 Por eso: libre = (límite provincial − TODO lo ocupado) ∩ cinturón, donde
                 cinturón = buffer alrededor de las minas+manifestaciones (la señal de
                 prospectividad real). Cada polígono libre trae su superficie en hectáreas.

Todo en WGS84 para el visor; las áreas se calculan reproyectando a POSGAR 2007 (EPSG:5344).
"""

import os
import json
from collections import defaultdict

from shapely.geometry import shape, mapping
from shapely.validation import make_valid
from shapely.ops import unary_union, transform
from pyproj import Transformer

# capas que "ocupan" terreno (no se puede pedir cateo encima)
OCUPADAS = ["permisos", "manifestaciones", "minas", "solicitudes", "canteras"]
# señal de prospectividad: dónde hay mineral descubierto/registrado
PROSPECTIVAS = ["manifestaciones", "minas"]

_TO_M = Transformer.from_crs("EPSG:4326", "EPSG:5344", always_xy=True).transform


def _ha(geom_wgs):
    """Superficie en hectáreas de una geometría WGS84 (reproyecta a metros POSGAR 2007)."""
    try:
        return round(transform(_TO_M, geom_wgs).area / 10000.0, 1)
    except Exception:
        return 0.0


def _valida(g):
    try:
        sh = shape(g)
        if not sh.is_valid:
            sh = make_valid(sh)
        return sh if (sh and not sh.is_empty) else None
    except Exception:
        return None


def _load(cat_dir, capa):
    fp = os.path.join(cat_dir, f"catastro_{capa}.geojson")
    if not os.path.exists(fp):
        return {"features": []}
    return json.load(open(fp, encoding="utf-8"))


def _poligonos(geom):
    """Explota (Multi)Polygon en lista de Polygon."""
    if geom.geom_type == "Polygon":
        return [geom]
    if geom.geom_type in ("MultiPolygon", "GeometryCollection"):
        return [g for g in geom.geoms if g.geom_type == "Polygon"]
    return []


def analizar(salida, buffer_grados=0.06, min_ha=80, max_ha=60000, top_libres=90):
    cat_dir = os.path.join(salida, "catastro")

    # ---- 1) manifestaciones DORMIDAS: reclamos antiguos que NUNCA se mensuraron ----
    # Manifestación con fechaInscripcion pero SIN fechaInscripcionMensura: un derecho
    # viejo que nunca avanzó a mina registrada. Son los interesantes (posible caducidad /
    # oportunidad), a diferencia de las minas (que arrastran registros de 1889 sin valor
    # para esto) y de las manifestaciones ya mensuradas (activas y al día).
    dormidas = []
    for f in _load(cat_dir, "manifestaciones")["features"]:
        p = f.get("properties", {})
        fecha = (p.get("fechaInscripcion") or "")[:10]
        if not fecha or p.get("fechaInscripcionMensura"):
            continue
        sh = _valida(f.get("geometry"))
        cen = None
        if sh:
            c = sh.representative_point()
            cen = [round(c.y, 6), round(c.x, 6)]
        dormidas.append({
            "tipo": "manifestacion",
            "titular": p.get("titular"),
            "denom": p.get("denominacion") or p.get("nombre_mina"),
            "fecha": fecha,
            "ha": p.get("sup_reg_ha"),
            "depto": p.get("departamento"),
            "min": p.get("minerales"),
            "cen": cen,
        })
    dormidas.sort(key=lambda x: x["fecha"])
    dormidas = dormidas[:60]

    # ---- 2) zonas de movimiento (grilla de centroides) ----
    CELL = 0.08  # ~8 km
    grid = defaultdict(lambda: {"cateo": 0, "manif": 0, "mina": 0})
    tipomap = {"permisos": "cateo", "manifestaciones": "manif", "minas": "mina"}
    for capa, tk in tipomap.items():
        for f in _load(cat_dir, capa)["features"]:
            sh = _valida(f.get("geometry"))
            if not sh:
                continue
            c = sh.representative_point()
            key = (round(c.x / CELL), round(c.y / CELL))
            grid[key][tk] += 1
    zonas = []
    for (gx, gy), cnt in grid.items():
        tot = cnt["cateo"] + cnt["manif"] + cnt["mina"]
        if tot < 4:
            continue
        zonas.append({"cen": [round(gy * CELL, 5), round(gx * CELL, 5)],
                      "n": tot, **cnt})
    zonas.sort(key=lambda z: -z["n"])
    zonas = zonas[:40]

    # ---- 3) áreas vacantes dentro del cinturón minero ----
    limite = _valida(_load(cat_dir, "limite")["features"][0]["geometry"])
    ocup = []
    for capa in OCUPADAS:
        for f in _load(cat_dir, capa)["features"]:
            sh = _valida(f.get("geometry"))
            if sh:
                ocup.append(sh)
    ocupado = unary_union(ocup) if ocup else None

    prosp = []
    for capa in PROSPECTIVAS:
        for f in _load(cat_dir, capa)["features"]:
            sh = _valida(f.get("geometry"))
            if sh:
                prosp.append(sh)
    cinturon = unary_union(prosp).buffer(buffer_grados) if prosp else limite

    libre = limite.difference(ocupado) if ocupado else limite
    libre = libre.intersection(cinturon)      # solo huecos en el cinturón prospectivo

    feats = []
    for poly in _poligonos(libre):
        ha = _ha(poly)
        if ha < min_ha or ha > max_ha:
            continue
        c = poly.representative_point()
        simp = poly.simplify(0.0015, preserve_topology=True)
        feats.append((ha, {
            "type": "Feature",
            "properties": {"ha": ha, "cen": [round(c.y, 6), round(c.x, 6)]},
            "geometry": mapping(simp),
        }))
    feats.sort(key=lambda t: -t[0])
    libres = [f for _, f in feats[:top_libres]]
    libres_ha = round(sum(h for h, _ in feats), 1)

    doc = {
        "meta": {
            "n_dormidas": len(dormidas),
            "n_zonas": len(zonas),
            "n_libres": len(libres),
            "libres_ha_total": libres_ha,
            "cinturon_buffer_grados": buffer_grados,
        },
        "dormidas": dormidas,
        "zonas": zonas,
        "libres": {"type": "FeatureCollection", "features": libres},
    }
    ruta = os.path.join(salida, "analisis_historico.json")
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False)

    # capa MENSURAS EFECTIVAS para el visor (registros con fechaInscripcionMensura).
    generar_mensuras_efectivas(salida)
    return doc["meta"]


def generar_mensuras_efectivas(salida):
    """GeoJSON de las manifestaciones/minas con la mensura EFECTIVAMENTE inscripta
    (fechaInscripcionMensura). Lo usa el visor como capa naranja diferenciada."""
    cat_dir = os.path.join(salida, "catastro")
    feats = []
    for capa in ("manifestaciones", "minas"):
        for f in _load(cat_dir, capa)["features"]:
            p = f.get("properties", {})
            if not p.get("fechaInscripcionMensura"):
                continue
            feats.append({
                "type": "Feature",
                "geometry": f.get("geometry"),
                "properties": {
                    "denominacion": p.get("denominacion") or p.get("nombre_mina"),
                    "titular": p.get("titular"),
                    "expediente": p.get("expediente"),
                    "sup_reg_ha": p.get("sup_reg_ha"),
                    "minerales": p.get("minerales"),
                    "departamento": p.get("departamento"),
                    "fechaInscripcionMensura": (p.get("fechaInscripcionMensura") or "")[:10],
                    "capa": capa,
                },
            })
    ruta = os.path.join(cat_dir, "catastro_mensuras_efectivas.geojson")
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": feats}, f, ensure_ascii=False)
    return len(feats)


if __name__ == "__main__":
    import sys
    salida = sys.argv[1] if len(sys.argv) > 1 else "./out_hist"
    print("analisis_historico.json:", analizar(salida))
