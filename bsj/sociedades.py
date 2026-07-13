"""
Base de SOCIEDADES / TITULARES mineros a partir del catastro (minas + manifestaciones,
que traen `titular`, `fechaInscripcion`, `minerales` y geometría) + la actividad del
boletín. Produce sociedades.json para:
  - el buscador por sociedad (todas sus propiedades + edictos en un mapa),
  - el entramado / mapa conceptual de terratenientes (co-titularidad).

La co-titularidad viene en el campo `titular` separada por ' - ' (ej.
"Hugo Enrique Bastias - Jorge Alfredo Bastias"). Se separa en entidades individuales y
cada propiedad compartida genera una arista entre ellas (para la red).
"""

import os
import re
import json
import glob
from collections import Counter, defaultdict
from datetime import datetime, timezone

CAPAS_TITULAR = ("minas", "manifestaciones")
_RX_SOC = re.compile(r"\bS\.?\s?A\.?\b|\bS\.?R\.?L\.?|\bS\.?A\.?S\.?|\bS\.?A\.?C\.?I|"
                     r"\bLTDA|\bLIMITADA|\bCOMPA[ÑN]", re.IGNORECASE)


def _norm(s):
    s = (s or "").lower()
    for a, b in (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"), ("ñ", "n")):
        s = s.replace(a, b)
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", s)).strip()


def _es_sociedad(nombre):
    return bool(_RX_SOC.search(nombre or ""))


# ---------- limpieza + resolución de entidades (unificar nombres) ----------
# El catastro trae "APELLIDO NOMBRE" en MAYÚSCULA y limpio; el boletín (OCR) trae
# variantes: minúscula, "Nombre Apellido", truncados, símbolos mal leídos ($=S, |=I).
# Acá se limpian y se colapsan las variantes de una misma entidad en un nombre canónico
# (MAYÚSCULA, formato del catastro). Ver prototipo validado en el commit.

def _clean(s):
    s = (s or "").replace("$", "S").replace("|", "I").replace("ﬁ", "fi").replace("�", "")
    s = re.sub(r"\bS\s*[:;]\s*A\b", "S.A", s)      # 'S:A' / 'S;A' (OCR) -> 'S.A'
    return re.sub(r"\s+", " ", s).strip(" .,-")


def _deburr(s):
    import unicodedata
    return unicodedata.normalize("NFD", s or "").encode("ascii", "ignore").decode()


def _ntok(s):
    return len([t for t in _deburr(_clean(s)).split() if len(t) > 1])


def _split(titular):
    """Separa co-titulares. Además de ' - ', separa personas por ' Y ' y por ', '
    cuando ambos lados son nombres completos (>=3 tokens: distingue dos personas de
    'Apellido, Nombre'). Las empresas NO se cortan por ' Y ' (ej. 'Gold Y Energy S.R.L')."""
    out = []
    for p in re.split(r"\s+-\s+", titular or ""):
        p = _clean(p)
        if not p:
            continue
        if _es_sociedad(p):
            out.append(p)
            continue
        for q in re.split(r"\s+[Yy]\s+", p):
            q = _clean(q)
            cs = re.split(r"\s*,\s*", q)
            if len(cs) == 2 and all(_ntok(x) >= 3 for x in cs):
                out.extend(_clean(x) for x in cs)
            elif q:
                out.append(q)
    return [x for x in out if x]


def _legal(s):
    d = _deburr(s).upper()
    for pat, tag in ((r"S\.?R\.?L", "SRL"), (r"S\.?A\.?S", "SAS"),
                     (r"LTDA|LIMITADA|\bLTD", "LTD"), (r"S\.?A\b", "SA")):
        if re.search(pat, d):
            return tag
    return ""


def _tokset(s):
    return frozenset(t for t in re.sub(r"[^a-z0-9 ]", " ", _deburr(_clean(s)).lower()).split()
                     if len(t) > 1)


def _key(s):
    # empresa: tokens + forma legal (para NO mezclar S.A con S.R.L); persona: set de tokens
    return ("C", _tokset(s), _legal(s)) if _es_sociedad(s) else ("P", _tokset(s), "")


def _is_combo(s):
    return ("," in s) or bool(re.search(r"\s[Yy]\s", s)) or _ntok(s) >= 5


def _canonizar(nombres, cat_names):
    """nombres: set de nombres individuales ya limpios. Devuelve dict nombre->canónico.
    Colapsa variantes (mismo set de tokens) y truncados (subconjunto de un único
    superset de UNA sola persona). El canónico es la variante más completa, en MAYÚSCULA."""
    groups = defaultdict(list)
    for n in nombres:
        groups[_key(n)].append(n)
    rep = {}
    # merge cruzado persona->empresa: si un nombre sin sufijo legal ('ANDES CORPORACION
    # MINERA', 'PACHON') tiene el mismo set de tokens que una empresa ('...S.A'), es la
    # misma entidad (el boletín a veces omite el S.A/S.R.L).
    comp_by_toks = {}
    for k in groups:
        if k[0] == "C" and k[1]:
            comp_by_toks.setdefault(k[1], k)
    for k in list(groups):
        if k[0] == "P" and k[1] in comp_by_toks:
            rep[k] = comp_by_toks[k[1]]
    pk = [k for k in groups if k[0] == "P" and k[1] and k not in rep]
    singles = {k for k in pk if len(k[1]) <= 4 and all(not _is_combo(v) for v in groups[k])}
    for k in pk:
        if len(k[1]) < 2:
            continue
        sup = [o for o in singles if o != k and k[1] < o[1]]
        if len(sup) == 1:
            rep[k] = sup[0]

    def root(k):
        seen = set()
        while k in rep and k not in seen:
            seen.add(k)
            k = rep[k]
        return k

    clusters = defaultdict(list)
    for n in nombres:
        clusters[root(_key(n))].append(n)
    canon = {}
    for variants in clusters.values():
        best = max(variants, key=lambda v: (_ntok(v), v in cat_names, len(v)))
        disp = _clean(best).upper()
        for v in variants:
            canon[v] = disp
    return canon


def _apellido(nombre):
    """Heurística de apellido para agrupar familias (personas). Toma la 1a palabra
    'tipo apellido' del nombre; los edictos suelen escribir Apellido(s) Nombre(s)."""
    if _es_sociedad(nombre):
        return None
    toks = [t for t in re.split(r"\s+", nombre) if len(t) > 2]
    return toks[0].title() if toks else None


def _anillo(geom):
    if not geom:
        return None
    t, c = geom.get("type"), geom.get("coordinates")
    if t == "Polygon":
        return c[0]
    if t == "MultiPolygon":
        return max((p[0] for p in c), key=len)
    return None


def _centroide(anillo):
    if not anillo:
        return None
    return [round(sum(p[1] for p in anillo) / len(anillo), 6),
            round(sum(p[0] for p in anillo) / len(anillo), 6)]


def _fecha(s):
    return (s or "")[:10] or None


def construir(salida):
    cat_dir = os.path.join(salida, "catastro")
    modelo = os.path.join(salida, "modelo.json")

    # ---- Pass 0: universo de nombres crudos (catastro + boletín) -> mapa canónico ----
    # Se resuelven las entidades ANTES de agregar, para que catastro y boletín usen el
    # MISMO nombre canónico (unifica mayúscula/minúscula, orden y truncados del OCR).
    cat_geo = {}
    raw, cat_names = set(), set()
    for capa in CAPAS_TITULAR:
        fp = os.path.join(cat_dir, f"catastro_{capa}.geojson")
        cat_geo[capa] = json.load(open(fp, encoding="utf-8")) if os.path.exists(fp) else {"features": []}
        for f in cat_geo[capa]["features"]:
            t = (f.get("properties") or {}).get("titular")
            for p in _split(t):
                raw.add(p); cat_names.add(p)
    dm = json.load(open(modelo, encoding="utf-8")) if os.path.exists(modelo) else {"expedientes": []}
    for e in dm.get("expedientes", []):
        c = e.get("catastro") or {}
        tit = c.get("titular") or e.get("titular_actual")
        for p in _split(tit):
            raw.add(p)
    canon = _canonizar(raw, cat_names)

    def C(name):
        return canon.get(name, _clean(name).upper())

    ent_props = defaultdict(list)     # nombre canónico -> [propiedad]
    edges = Counter()                 # (a,b) -> nº de propiedades compartidas
    vistos = defaultdict(set)         # nombre -> set(expediente) para deduplicar

    for capa in CAPAS_TITULAR:
        for f in cat_geo[capa]["features"]:
            p = f.get("properties", {})
            titular = p.get("titular")
            if not titular:
                continue
            ents = list(dict.fromkeys(C(x) for x in _split(titular)))   # canónicos, sin dup
            anillo = _anillo(f.get("geometry"))
            prop = {
                "tipo": "mina" if capa == "minas" else "manifestacion",
                "denom": p.get("denominacion") or p.get("nombre_mina") or p.get("denom"),
                "expte": p.get("expediente"),
                "depto": p.get("departamento"),
                "ha": p.get("sup_reg_ha"),
                "min": p.get("minerales"),
                "yac": p.get("tipoYacimiento"),
                "fecha": _fecha(p.get("fechaInscripcion")),
                # fecha de inscripción de la MENSURA: si está, esta manifestación/mina
                # tiene la mensura EFECTIVAMENTE registrada en el padrón (WFS).
                "finMensura": _fecha(p.get("fechaInscripcionMensura")),
                "cen": _centroide(anillo),
                "pol": anillo,
                "cotit": ents if len(ents) > 1 else None,
            }
            for e in ents:
                key = prop["expte"] or prop["denom"] or id(prop)
                if key in vistos[e]:
                    continue
                vistos[e].add(key)
                ent_props[e].append(prop)
            for i in range(len(ents)):
                for j in range(i + 1, len(ents)):
                    a, b = sorted([ents[i], ents[j]])
                    edges[(a, b)] += 1

    # actividad del boletín (edictos) por titular canónico. Acá está el VALOR del
    # scraper: le pone nombre a cateos/servidumbres que el WFS deja sin titular. Se
    # guarda la geometría y la superficie oficial del catastro (cruce) para el buscador.
    edictos_por_ent = defaultdict(list)
    for e in dm.get("expedientes", []):
        c = e.get("catastro") or {}
        tit = c.get("titular") or e.get("titular_actual")
        if not tit:
            continue
        fechas = sorted({f for ev in e.get("eventos", []) for f in ev["fechas"]})
        item = {
            "expte": e.get("expediente"),
            "estado": e.get("estado_label"),
            "estado_k": e.get("estado"),
            "fechas": fechas,
            "depto": c.get("departamento") or e.get("departamento"),
            "cen": c.get("centroide") or e.get("centroide"),
            "pol": c.get("poligono_wgs84") or e.get("poligono_wgs84"),
            # superficie del POLÍGONO del catastro (WFS) que matcheó el cruce. Confiable
            # (a diferencia de la superficie del boletín, corrupta por OCR). Es la que
            # usamos para las hectáreas de cateo por titular.
            "sup_ha": c.get("sup_reg_ha"),
        }
        for ent in dict.fromkeys(C(x) for x in _split(tit)):
            edictos_por_ent[ent].append(item)

    # armar la lista de sociedades (unión de titulares del catastro + del boletín)
    socs = []
    validos = set()
    for nombre in set(ent_props) | set(edictos_por_ent):
        # descartar fragmentos: un nombre de PERSONA válido tiene >=2 palabras (los
        # truncados de OCR tipo 'JULIAN', 'MAIDANA', 'IL' son basura, no una entidad).
        # Y descartar referencias legales mal capturadas como titular ('LEY 27...').
        if not _es_sociedad(nombre) and _ntok(nombre) < 2:
            continue
        if re.match(r"^(LEY|EXPTE|EXPEDIENTE|ART|ARTICULO|FS|BOLETIN|DECRETO)\b", nombre):
            continue
        validos.add(nombre)
        props = ent_props.get(nombre, [])
        edx = edictos_por_ent.get(nombre, [])
        fechas = [p["fecha"] for p in props if p["fecha"]] + [f for e in edx for f in e["fechas"]]
        deptos = sorted({p["depto"] for p in props if p["depto"]}
                        | {e["depto"] for e in edx if e["depto"]})
        minset = sorted({m for p in props if p["min"] for m in re.split(r"\s*-\s*", p["min"])})
        co = Counter()
        for p in props:
            for other in (p["cotit"] or []):
                if other != nombre:
                    co[other] += 1
        # HECTÁREAS POR TIPO — hectáreas del catastro (WFS), confiables:
        #  - manif    = superficie de las MANIFESTACIONES de descubrimiento (capa del
        #               catastro, con titular+ha; historia completa).
        #  - cateo    = superficie del POLÍGONO de cateo que el cruce asoció al titular
        #               (el nombre lo aporta el boletín; la ha, el catastro).
        #  - mensura  = superficie MENSURADA según los EDICTOS DE MENSURA del boletín,
        #               cruzada al polígono del catastro. OJO: la capa 'minas' del
        #               catastro son las minas ya registradas en pertenencias (chicas,
        #               ~12 ha); una mensura MIDE una manifestación (área grande), por
        #               eso se toma el área del acto de mensura (lo que se ve en el edicto).
        # De-duplico por expediente para no sumar dos veces la misma superficie.
        ha_manif = round(sum(p["ha"] or 0 for p in props if p["tipo"] == "manifestacion"), 2)

        def _ha_por_tipo(estado_k):
            vistos_e, tot = set(), 0.0
            for x in edx:
                if x.get("estado_k") != estado_k or not x.get("sup_ha"):
                    continue
                k = x.get("expte") or id(x)
                if k in vistos_e:
                    continue
                vistos_e.add(k)
                tot += x["sup_ha"]
            return round(tot, 2)

        ha_cateo = _ha_por_tipo("cateo_exploracion")
        # mensura EN TRÁMITE: área de los edictos de mensura del boletín (el derecho se
        # está midiendo; aún no consta inscripción de mensura en el padrón).
        ha_mensura = _ha_por_tipo("edicto_mensura")
        # mensura EFECTIVA (registrada): manifestaciones/minas del catastro que YA tienen
        # fechaInscripcionMensura en el WFS. Esta es la verdad oficial de qué mensuras se
        # inscribieron (ej. Andes Corp. Minera: 14 registros, ~19.664 ha en 2024-2025),
        # independiente de si el edicto quedó capturado en el boletín.
        ha_mensurada = round(sum(p["ha"] or 0 for p in props if p.get("finMensura")), 2)
        # minas registradas en pertenencias (capa 'minas', chicas) — dato de referencia.
        ha_minas = round(sum(p["ha"] or 0 for p in props if p["tipo"] == "mina"), 2)
        tpc = Counter(x.get("estado_k") for x in edx if x.get("estado_k"))
        socs.append({
            "nombre": nombre,
            "tipo": "sociedad" if _es_sociedad(nombre) else "persona",
            "apellido": _apellido(nombre),
            "n": len(props),
            "n_edictos": len(edx),
            "n_cateo": tpc.get("cateo_exploracion", 0),
            "n_mensura": tpc.get("edicto_mensura", 0),
            "n_manifestacion": tpc.get("manifestacion_descubrimiento", 0),
            "ha_cateo": round(ha_cateo, 2),
            "ha_manif": ha_manif,
            "ha_mensura": ha_mensura,
            "ha_mensurada": ha_mensurada,
            "ha_minas": ha_minas,
            "total_ha": round(sum(p["ha"] or 0 for p in props), 2),
            "departamentos": deptos,
            "minerales": minset,
            "desde": min(fechas) if fechas else None,
            "hasta": max(fechas) if fechas else None,
            "co": dict(co.most_common()),
            "edictos": edx,
            "props": props,
        })
    socs.sort(key=lambda s: -(s["ha_cateo"] + s["ha_manif"] + s["ha_mensura"]))

    doc = {
        "meta": {
            "generado": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            "n_sociedades": len(socs),
            "n_propiedades": sum(len(p) for p in ent_props.values()),
        },
        "sociedades": socs,
        # aristas de co-titularidad solo entre entidades válidas (sin fragmentos descartados)
        "edges": [{"a": a, "b": b, "w": w} for (a, b), w in edges.most_common()
                  if a in validos and b in validos],
    }
    ruta = os.path.join(salida, "sociedades.json")
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False)
    return doc["meta"], len(doc["edges"])


if __name__ == "__main__":
    import sys
    salida = sys.argv[1] if len(sys.argv) > 1 else "./out_hist"
    meta, nedges = construir(salida)
    print("sociedades.json:", meta, "| aristas de co-titularidad:", nedges)
