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


def _split(titular):
    """Separa co-titulares por ' - '. Devuelve nombres limpios."""
    partes = re.split(r"\s+-\s+", titular or "")
    return [p.strip(" .,-") for p in partes if p.strip(" .,-")]


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
    ent_props = defaultdict(list)     # nombre -> [propiedad]
    edges = Counter()                 # (a,b) -> nº de propiedades compartidas
    vistos = defaultdict(set)         # nombre -> set(expediente) para deduplicar

    for capa in CAPAS_TITULAR:
        fp = os.path.join(cat_dir, f"catastro_{capa}.geojson")
        if not os.path.exists(fp):
            continue
        gj = json.load(open(fp, encoding="utf-8"))
        for f in gj.get("features", []):
            p = f.get("properties", {})
            titular = p.get("titular")
            if not titular:
                continue
            ents = _split(titular)
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

    # actividad del boletín (edictos) por titular. Si el titular no está en el padrón
    # de minas/manifestaciones, igual se crea la entidad (así entran empresas que solo
    # aparecen en el boletín: cateos, servidumbres, etc.). Se guarda la geometría para
    # poder plotearla en el buscador de sociedades.
    edictos_por_ent = defaultdict(list)
    modelo = os.path.join(salida, "modelo.json")
    if os.path.exists(modelo):
        dm = json.load(open(modelo, encoding="utf-8"))
        nombres_norm = {_norm(n): n for n in ent_props}
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
            }
            for parte in _split(tit):
                ent = nombres_norm.get(_norm(parte), parte)  # matchea existente o crea
                edictos_por_ent[ent].append(item)

    # armar la lista de sociedades (unión de titulares del catastro + del boletín)
    socs = []
    for nombre in set(ent_props) | set(edictos_por_ent):
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
        # conteo de expedientes del boletín por TIPO de acto. Permite rankear por
        # "cuántos cateos / mensuras / manifestaciones" tiene cada titular: no es lo
        # mismo tener miles de ha en cateo (mera exploración) que ha mensuradas
        # (derecho consolidado). La superficie del boletín está corrupta por OCR, así
        # que acá van los CONTEOS (confiables); las hectáreas siguen siendo las del
        # catastro (total_ha, registradas).
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
            "total_ha": round(sum(p["ha"] or 0 for p in props), 2),
            "departamentos": deptos,
            "minerales": minset,
            "desde": min(fechas) if fechas else None,
            "hasta": max(fechas) if fechas else None,
            "co": dict(co.most_common()),
            "edictos": edx,
            "props": props,
        })
    socs.sort(key=lambda s: -(s["n"] + s["n_edictos"]))

    doc = {
        "meta": {
            "generado": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            "n_sociedades": len(socs),
            "n_propiedades": sum(len(p) for p in ent_props.values()),
        },
        "sociedades": socs,
        "edges": [{"a": a, "b": b, "w": w} for (a, b), w in edges.most_common()],
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
