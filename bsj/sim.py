"""
Cliente del SIM Producción — Padrón Minero de San Juan (Dirección de Minería).

API pública (sin token): https://simback.sanjuan.gob.ar/api/v1
  - historicoMina  : padrón ACTUAL, paginado (perPage<=200). Cada registro trae el
    expediente, estado (Vigente / caduco / vacante...), fechas de caducidad y vacancia,
    cantidad de pertenencias, departamento, minerales, categoría y los CONCESIONARIOS
    (personas físicas con DNI/CUIT y jurídicas con CUIT) — el "quién" oficial y al día.
  - departamentos  : catálogo.

Complementa a las otras dos fuentes: el catastro (GeoServer, geometrías) y el boletín
(línea de tiempo de publicaciones). El cruce es por número de expediente canónico.
"""

import os
import re
import json
import time
import requests

BASE = "https://simback.sanjuan.gob.ar/api/v1"
UA = {"User-Agent": "Mozilla/5.0 (boletin-minero; investigacion)", "Accept": "application/json"}


def _get(url, **params):
    last = None
    for verify in (True, False):
        try:
            r = requests.get(url, params=params, headers=UA, timeout=60, verify=verify)
            r.raise_for_status()
            return r.json()
        except requests.exceptions.SSLError as e:
            last = e
            continue
    raise last


def descargar(salida, per_page=200, pausa=0.3):
    """Baja todo historicoMina paginando. Devuelve la lista de registros crudos y la
    guarda en salida/sim/padron_sim_raw.json."""
    out_dir = os.path.join(salida, "sim")
    os.makedirs(out_dir, exist_ok=True)
    recs, page = [], 1
    while True:
        d = _get(BASE + "/historicoMina", perPage=per_page, page=page)
        recs.extend(d.get("data", []))
        meta = d.get("meta", {})
        last = meta.get("last_page", page)
        print(f"  historicoMina página {page}/{last}  ({len(recs)}/{meta.get('total','?')})")
        if page >= last:
            break
        page += 1
        time.sleep(pausa)
    with open(os.path.join(out_dir, "padron_sim_raw.json"), "w", encoding="utf-8") as f:
        json.dump(recs, f, ensure_ascii=False)
    return recs


def _concesionarios(c):
    """Aplana concesionarios (físicas + jurídicas) a [{nombre, id_fiscal, tipo, pct}]."""
    out = []
    c = c or {}
    for pj in c.get("personasJuridicas", []) or []:
        p = pj.get("persona") or {}
        out.append({"nombre": p.get("razonSocial"), "id_fiscal": p.get("cuit"),
                    "tipo": "juridica", "pct": pj.get("porcentajeParticipacion")})
    for pf in c.get("personasFisicas", []) or []:
        p = pf.get("persona") or {}
        nom = " ".join(x for x in [p.get("nombre"), p.get("apellido")] if x).strip()
        out.append({"nombre": nom or None, "id_fiscal": p.get("cuit") or p.get("dni"),
                    "tipo": "fisica", "pct": pf.get("porcentajeParticipacion")})
    return out


def normalizar(recs):
    """Aplana cada registro del padrón SIM a un dict plano para análisis/visor."""
    out = []
    for r in recs:
        e = r.get("expediente") or {}
        out.append({
            "expediente": e.get("numero"),
            "nombre": e.get("nombre"),
            "estado": r.get("estado"),
            "activo": r.get("activo"),
            "departamento": (r.get("departamento") or {}).get("nombre"),
            "tipoYacimiento": (r.get("tipoYacimiento") or {}).get("nombre"),
            "categoria": (r.get("categoriaMineral") or {}).get("nombre"),
            "minerales": [m.get("nombre") for m in (r.get("minerales") or [])],
            "pertenencias": e.get("cantidadPertenencias"),
            "resolucion": e.get("resolucion"),
            "fechaInscripcion": (e.get("fechaInscripcion") or "")[:10] or None,
            "fechaInscripcionMensura": (e.get("fechaInscripcionMensura") or "")[:10] or None,
            "fechaResolucionMensura": (e.get("fechaResolucionMensura") or "")[:10] or None,
            "nroInscripcion": e.get("nroInscripcion"),
            "nroInscripcionMensura": e.get("nroInscripcionMensura"),
            "fechaInicio": (r.get("fechaInicio") or "")[:10] or None,
            "fechaFin": (r.get("fechaFin") or "")[:10] or None,
            "fecha_caducidad": (r.get("fecha_caducidad") or "")[:10] or None,
            "fechainscripcionvacante": (r.get("fechainscripcionvacante") or "")[:10] or None,
            "fecharesolucionvacante": (r.get("fecharesolucionvacante") or "")[:10] or None,
            "puede_iniciar_rescate": r.get("puede_iniciar_rescate"),
            "concesionarios": _concesionarios(r.get("concesionarios")),
        })
    return out


def _canon(x):
    return re.sub(r"\D", "", x or "")


def enriquecer_geometria(salida, minas):
    """Adjunta cen/pol a cada mina del SIM cruzando por nº de expediente con las capas
    del catastro (minas + manifestaciones + permisos). Devuelve cuántas quedaron con geom."""
    cat_dir = os.path.join(salida, "catastro")

    def anillo(g):
        if not g:
            return None
        t, c = g.get("type"), g.get("coordinates")
        if t == "Polygon":
            return c[0]
        if t == "MultiPolygon":
            return max((p[0] for p in c), key=len)
        return None

    idx = {}
    for capa in ("minas", "manifestaciones", "permisos"):
        fp = os.path.join(cat_dir, f"catastro_{capa}.geojson")
        if not os.path.exists(fp):
            continue
        for f in json.load(open(fp, encoding="utf-8")).get("features", []):
            p = f.get("properties", {})
            e = _canon(p.get("expediente") or p.get("expte_siged"))
            if e and e not in idx:
                r = anillo(f.get("geometry"))
                if r:
                    cen = [round(sum(x[1] for x in r) / len(r), 6),
                           round(sum(x[0] for x in r) / len(r), 6)]
                    idx[e] = {"cen": cen, "pol": r}
    # área en hectáreas del polígono (reproyecta a POSGAR 2007). Opcional: si no está
    # shapely/pyproj, deja ha=None y sigue.
    try:
        from shapely.geometry import Polygon
        from shapely.ops import transform
        from pyproj import Transformer
        _to_m = Transformer.from_crs("EPSG:4326", "EPSG:5344", always_xy=True).transform
        def _ha(pol):
            try:
                return round(transform(_to_m, Polygon([(x[0], x[1]) for x in pol])).area / 10000.0, 1)
            except Exception:
                return None
    except Exception:
        _ha = lambda pol: None
    n = 0
    for m in minas:
        g = idx.get(_canon(m.get("expediente")))
        m["cen"] = g["cen"] if g else None
        m["pol"] = g["pol"] if g else None
        m["ha"] = _ha(g["pol"]) if g else None
        if g:
            n += 1
    return n


if __name__ == "__main__":
    import sys
    salida = sys.argv[1] if len(sys.argv) > 1 else "./out_hist"
    recs = descargar(salida)
    norm = normalizar(recs)
    con_geo = enriquecer_geometria(salida, norm)
    with open(os.path.join(salida, "sim", "padron_sim.json"), "w", encoding="utf-8") as f:
        json.dump({"generado": time.strftime("%Y-%m-%dT%H:%M:%S"), "n": len(norm),
                   "con_geometria": con_geo, "minas": norm}, f, ensure_ascii=False)
    print(f"SIM padrón: {len(norm)} registros ({con_geo} con geometría) -> {salida}/sim/padron_sim.json")
