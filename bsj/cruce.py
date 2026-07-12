"""
Cruce y enriquecimiento boletín <-> catastro.

El boletín aporta la LÍNEA DE TIEMPO de eventos (qué pasó, cuándo). El catastro aporta
la GEOMETRÍA y los ATRIBUTOS autoritativos (sin ruido de OCR). Se cruzan por el nº de
EXPEDIENTE, con respaldo por nombre de mina y por proximidad espacial.

Para cada expediente del modelo del boletín se busca el feature del catastro y, si hay
match, se agrega un bloque `catastro` con denominación, titular, minerales, superficie y
la geometría oficial (que el visor usa en lugar del polígono de OCR).

Match (de más fuerte a más débil):
  1) expediente   — clave canónica (dependencia, número, año). Alta.
  2) nombre_mina  — denominación exacta normalizada (+ mismo depto si hay varios). Media.
  3) espacial     — centroide del catastro a < 2 km del centroide del boletín y mismo
                    departamento. Baja (para los edictos sin nº de expediente).
"""

import os
import re
import json
import glob

# capa local (archivo) -> clave lógica
_CAPA_DE_ARCHIVO = lambda fp: os.path.basename(fp).replace("catastro_", "").replace(".geojson", "")


def _norm(s):
    s = (s or "").lower()
    for a, b in (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"), ("ñ", "n")):
        s = s.replace(a, b)
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", s)).strip()


def canon_exp(s):
    """Clave canónica (dep, numero:int, año:4dig) de un nº de expediente, tolerante a
    formatos: '1124-000108-2022-EXP-MANIF', '1124-343-S-14', '296.796-L-90'."""
    if not s:
        return None
    nums = re.findall(r"\d+", s)
    if len(nums) < 2:
        return None
    dep = nums[0]
    year = nums[-1]
    if len(year) == 2:
        year = ("19" if int(year) > 30 else "20") + year
    elif len(year) != 4:
        return None
    # caso pegado 'NNNN NNNNNN' sin separador (ej. 1124000474-2022): dep(4)+num
    if len(nums) == 2 and len(nums[0]) >= 8:
        dep, num = nums[0][:4], nums[0][4:]
    else:
        medio = nums[1:-1] or [nums[1]]
        num = max(medio, key=len)
    try:
        return (dep, int(num), year)
    except ValueError:
        return None


def _anillo(geom):
    """Anillo exterior [[lon,lat],...] del polígono mayor (Polygon o MultiPolygon)."""
    if not geom:
        return None
    t = geom.get("type"); c = geom.get("coordinates")
    if t == "Polygon":
        return c[0]
    if t == "MultiPolygon":
        return max((p[0] for p in c), key=len)
    return None


def _centroide(anillo):
    if not anillo:
        return None
    lon = sum(p[0] for p in anillo) / len(anillo)
    lat = sum(p[1] for p in anillo) / len(anillo)
    return [lat, lon]


def cargar_catastro(carpeta):
    """Lee los catastro_*.geojson y devuelve features normalizados."""
    feats = []
    for fp in glob.glob(os.path.join(carpeta, "catastro_*.geojson")):
        capa = _CAPA_DE_ARCHIVO(fp)
        if capa == "limite":
            continue
        d = json.load(open(fp, encoding="utf-8"))
        for f in d.get("features", []):
            p = f.get("properties", {})
            anillo = _anillo(f.get("geometry"))
            exp = p.get("expediente") or p.get("expte_siged") or ""
            feats.append({
                "capa": capa, "props": p,
                "exp": exp, "canon": canon_exp(exp),
                "den": _norm(p.get("denominacion") or p.get("nombre_mina")),
                "tit": _norm(p.get("titular")),
                "depto": _norm(p.get("departamento")),
                "anillo": anillo, "centroide": _centroide(anillo),
            })
    return feats


def _indexar(feats):
    by_canon, by_den = {}, {}
    for f in feats:
        if f["canon"]:
            by_canon.setdefault(f["canon"], []).append(f)
        if f["den"]:
            by_den.setdefault(f["den"], []).append(f)
    return by_canon, by_den


def _dist_km(a, b):
    import math
    dlat = (a[0] - b[0]) * 111.0
    dlon = (a[1] - b[1]) * 111.0 * math.cos(math.radians((a[0] + b[0]) / 2))
    return math.hypot(dlat, dlon)


def _punto_en_anillo(lon, lat, anillo):
    """Ray casting: ¿(lon,lat) está dentro del anillo [[lon,lat],...]?"""
    dentro = False
    n = len(anillo)
    j = n - 1
    for i in range(n):
        xi, yi = anillo[i][0], anillo[i][1]
        xj, yj = anillo[j][0], anillo[j][1]
        if ((yi > lat) != (yj > lat)) and (lon < (xj - xi) * (lat - yi) / ((yj - yi) or 1e-12) + xi):
            dentro = not dentro
        j = i
    return dentro


def _area_aprox(anillo):
    """Área (shoelace) en grados² — solo para comparar tamaños relativos."""
    a = 0.0
    n = len(anillo)
    for i in range(n):
        x1, y1 = anillo[i]
        x2, y2 = anillo[(i + 1) % n]
        a += x1 * y2 - x2 * y1
    return abs(a) / 2.0


def _bloque(f, metodo, confianza):
    p = f["props"]
    return {
        "match_metodo": metodo, "match_confianza": confianza,
        "capa": f["capa"], "expediente": f["exp"],
        "denominacion": p.get("denominacion") or p.get("nombre_mina"),
        "titular": p.get("titular"),
        "minerales": p.get("minerales"),
        "tipo_yacimiento": p.get("tipoYacimiento"),
        "sup_reg_ha": p.get("sup_reg_ha"),
        "cantidad_pertenencias": p.get("cantidadPertenencias"),
        "departamento": p.get("departamento"),
        # fecha de inscripción de la MENSURA: si está, la mensura es EFECTIVA (mina
        # registrada); si falta, está EN TRÁMITE. Lo usa el visor para distinguirlas.
        "fechaInscripcionMensura": p.get("fechaInscripcionMensura"),
        "numeroInscripcionMensura": p.get("numeroInscripcionMensura"),
        "poligono_wgs84": f["anillo"], "centroide": f["centroide"],
    }


def matchear(e, by_canon, by_den, feats):
    """Devuelve el bloque catastro para un expediente del boletín, o None."""
    # 1) por expediente canónico
    c = canon_exp(e.get("expediente"))
    if c and c in by_canon:
        cand = by_canon[c]
        # si hay varios, preferir mismo departamento
        dep = _norm(e.get("departamento"))
        best = next((f for f in cand if f["depto"] == dep), cand[0])
        return _bloque(best, "expediente", "alta")
    # 2) por nombre de mina (denominación) exacta
    mina = _norm(e.get("mina"))
    if mina and len(mina) > 2 and mina in by_den:
        cand = by_den[mina]
        dep = _norm(e.get("departamento"))
        mismo = [f for f in cand if f["depto"] == dep] or cand
        if len(mismo) == 1:
            return _bloque(mismo[0], "nombre_mina", "media")
    # 3) espacial: el centroide del boletín cae DENTRO de la parcela del catastro
    #    (punto-en-polígono). Mucho más preciso que "el más cercano".
    cen = e.get("centroide")
    if cen:
        dep = _norm(e.get("departamento"))
        candidatos = [f for f in feats if f["anillo"] and (not dep or not f["depto"] or f["depto"] == dep)]
        dentro = [f for f in candidatos if _punto_en_anillo(cen[1], cen[0], f["anillo"])]
        if len(dentro) == 1:
            return _bloque(dentro[0], "espacial", "media")
        if len(dentro) > 1:
            # varias parcelas contienen el punto: quedarse con la más chica (más específica)
            dentro.sort(key=lambda f: _area_aprox(f["anillo"]))
            return _bloque(dentro[0], "espacial", "baja")
    return None


def enriquecer(salida, catastro_dir=None):
    """Cruza modelo.json con el catastro y reescribe el modelo enriquecido."""
    catastro_dir = catastro_dir or os.path.join(salida, "catastro")
    ruta = os.path.join(salida, "modelo.json")
    doc = json.load(open(ruta, encoding="utf-8"))
    feats = cargar_catastro(catastro_dir)
    by_canon, by_den = _indexar(feats)

    stats = {"total": len(doc["expedientes"]), "expediente": 0, "nombre_mina": 0,
             "espacial": 0, "sin_match": 0}
    for e in doc["expedientes"]:
        m = matchear(e, by_canon, by_den, feats)
        e["catastro"] = m
        stats[m["match_metodo"] if m else "sin_match"] += 1

    doc.setdefault("meta", {})["catastro_features"] = len(feats)
    doc["meta"]["cruce"] = stats
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
    return stats


if __name__ == "__main__":
    import sys
    salida = sys.argv[1] if len(sys.argv) > 1 else "./out_2026"
    s = enriquecer(salida)
    tot = s["total"]
    match = s["expediente"] + s["nombre_mina"] + s["espacial"]
    print(f"Cruce sobre {tot} expedientes:")
    print(f"  por expediente : {s['expediente']}")
    print(f"  por nombre mina: {s['nombre_mina']}")
    print(f"  espacial       : {s['espacial']}")
    print(f"  sin match      : {s['sin_match']}")
    print(f"  TOTAL con match: {match}/{tot} ({100*match//tot}%)")
