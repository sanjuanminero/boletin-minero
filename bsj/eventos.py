"""
Taxonomía de eventos del procedimiento minero de San Juan y agregación al modelo
expediente -> eventos -> titulares.

Fundamento legal (verificado, jun-2026): el trámite se rige por el Código de
Procedimientos Mineros de San Juan (Ley 7199 / texto ordenado 688-M) aplicando el
Código de Minería de la Nación (Ley 1919) como fondo. La unidad NO es el edicto
suelto sino el EXPEDIENTE: un mismo expediente atraviesa etapas (cateo ->
manifestación de descubrimiento -> mensura -> registro/concesión -> servidumbres /
transferencias -> caducidad / vacancia / abandono) y, además, cada acto se publica
varias veces dentro de un plazo legal (manifestación y mensura 3 veces en 15 días,
art. 53 CM; cateo 2x/10 días; abandono 3x/15 días; vacancia 1 día; caducidad 1 vez).
Por eso hay que (a) clasificar el TIPO de evento y (b) colapsar las publicaciones
repetidas de un mismo acto en un único evento con N apariciones.
"""

import re

# Orden = prioridad de clasificación (de señal más fuerte/avanzada a más débil).
# (clave, etiqueta, etapa, patrones_regex_sobre_texto_normalizado)
TIPOS = [
    ("edicto_mensura", "Edicto de mensura", "constitucion",
     [r"edicto de mensura", r"\bmensura\b", r"peticion de mensura",
      r"operaciones de mensura", r"area de pedido de mensura",
      r"pertenencia", r"planilla de coordenadas"]),
    ("manifestacion_descubrimiento", "Manifestación de descubrimiento", "constitucion",
     [r"manifestacion de descubrimiento", r"manifiesta descubrimiento",
      r"registro de (la )?manifestacion", r"nuevo criadero"]),
    ("cateo_exploracion", "Permiso de cateo / exploración", "constitucion",
     [r"permiso de exploracion", r"\bcateo\b", r"permiso de cateo",
      r"solicita.{0,20}exploracion"]),
    ("registro_mina", "Registro / concesión de mina", "constitucion",
     [r"registro de mina", r"concesion de mina", r"\bconcesion\b", r"labor legal"]),
    ("servidumbre", "Servidumbre minera", "vida",
     [r"servidumbre"]),
    ("transferencia", "Transferencia / cesión", "vida",
     [r"cede y transfiere", r"\bcesion\b", r"transferencia", r"\btransfiere\b"]),
    ("vacancia", "Mina vacante / vacancia", "extincion",
     [r"mina vacante", r"\bvacante\b", r"vacancia"]),
    ("abandono", "Abandono / subasta", "extincion",
     [r"abandono", r"subasta", r"\bremate\b"]),
    ("caducidad", "Caducidad", "extincion",
     [r"caducidad", r"\bcaduc"]),
]

ETIQUETAS = {k: lbl for k, lbl, _, _ in TIPOS}
ETAPAS = {k: et for k, _, et, _ in TIPOS}
ETIQUETAS["otro"] = "Otro / sin clasificar"
ETAPAS["otro"] = "otro"

_RX_ENCABEZADO = re.compile(r"edicto\s+d\s*e\s+([a-zñáéíóú]+)", re.IGNORECASE)
# encabezado textual -> clave de tipo
_ENCABEZADOS = {
    "mensura": "edicto_mensura",
    "manifestacion": "manifestacion_descubrimiento",
    "cateo": "cateo_exploracion",
    "exploracion": "cateo_exploracion",
    "servidumbre": "servidumbre",
    "abandono": "abandono",
}


def _norm(s: str) -> str:
    s = s.lower()
    for a, b in (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"), ("ñ", "n")):
        s = s.replace(a, b)
    return re.sub(r"\s+", " ", s)


def clasificar(texto: str) -> str:
    """Devuelve la clave del tipo de evento. Prioriza el encabezado 'EDICTO DE X';
    si no, puntúa por vocabulario (cada patrón suma; gana el de mayor puntaje y, a
    igualdad, el de mayor prioridad en TIPOS)."""
    t = _norm(texto)
    m = _RX_ENCABEZADO.search(t)
    if m:
        cab = m.group(1)
        for k, clave in _ENCABEZADOS.items():
            if cab.startswith(k[:6]):
                return clave
    mejor, mejor_pts = "otro", 0
    for idx, (clave, _, _, patrones) in enumerate(TIPOS):
        pts = sum(len(re.findall(p, t)) for p in patrones)
        # leve desempate por prioridad (orden en TIPOS)
        if pts > mejor_pts:
            mejor, mejor_pts = clave, pts
    return mejor


# ---------- limpieza de geometría (errores de OCR) ----------
def _filtrar_outliers(verts):
    """Descarta vértices outlier (un dígito mal OCR-eado en el Norte/Este deja un
    punto a cientos de km y estira el polígono). Criterio ROBUSTO por MAD: en cada
    eje se descarta lo que se aleja > max(8*MAD, 5 km) de la mediana. Así no recorta
    geometrías que son legítimamente largas (p. ej. servidumbres de línea), donde el
    MAD es grande, pero sí mata el outlier aislado de una mensura."""
    import statistics
    verts = [tuple(v) for v in verts]
    if len(verts) < 4:
        return verts
    for axis in (0, 1):
        vals = [v[axis] for v in verts]
        med = statistics.median(vals)
        mad = statistics.median(sorted(abs(x - med) for x in vals)) or 1.0
        thr = max(8 * mad, 5000)
        filt = [v for v in verts if abs(v[axis] - med) <= thr]
        if len(filt) >= 3:
            verts = filt
    return verts


def _convex_hull(pts):
    """Envolvente convexo (monotone chain). pts: [(norte,este),...] -> anillo
    [(norte,este),...] en orden. Da un footprint limpio en vez del polígono cruzado
    que sale de leer las tablas de pertenencias en orden de OCR."""
    P = sorted(set((round(p[1], 2), round(p[0], 2)) for p in pts))  # (x=este, y=norte)
    if len(P) < 3:
        return [(y, x) for x, y in P]

    def cross(o, a, b):
        return (a[0]-o[0])*(b[1]-o[1]) - (a[1]-o[1])*(b[0]-o[0])

    lower = []
    for p in P:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper = []
    for p in reversed(P):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    hull = lower[:-1] + upper[:-1]
    return [(y, x) for x, y in hull]   # de vuelta a (norte, este)


def finalizar_geometria(raw, datum, geo):
    """Limpia outliers de OCR y devuelve (anillo_gk, poligono_wgs84, centroide[lat,lon])."""
    verts = _filtrar_outliers(raw or [])
    ring = _convex_hull(verts) if len(verts) >= 3 else verts
    if not ring:
        return [], None, None
    try:
        pts_lonlat, (clat, clon) = geo.poligono_a_wgs84(ring, datum)
        return ring, pts_lonlat, [clat, clon]
    except Exception:
        return ring, None, None


# ---------- agregación al modelo expediente -> eventos -> titulares ----------
def _clave_expediente(ped, fecha, idx):
    """Clave estable de agrupamiento. El nº de expediente es el identificador real.
    Sin expediente: se agrupa por titular+mina (si hay) para juntar publicaciones
    repetidas del mismo derecho; si tampoco hay titular/mina identificables, NO se
    agrupa (clave única) para no mezclar derechos distintos del mismo departamento."""
    exp = (ped.expediente or "").strip(" .-")
    if exp and len(exp) >= 4 and any(c.isdigit() for c in exp):
        return exp, True
    ident = _norm((ped.titular or "") + "|" + (ped.mina or ""))
    if ident.strip("| "):
        return f"?{_norm(ped.departamento or '')}|{ident}", False
    # sin ningún identificador estable -> entrada propia (no fusionar)
    return f"?sinid|{fecha}|{idx}", False


def agregar_expedientes(items, datum, geo):
    """
    items: lista de (fecha 'YYYY-MM-DD', Pedimento).
    datum: clave de datum para convertir coordenadas.
    geo:   módulo coords (se inyecta para no crear dependencia circular).
    Devuelve lista de expedientes (dicts) con eventos agrupados y titulares historizados.
    """
    porexp = {}
    for idx, (fecha, ped) in enumerate(items):
        clave, exp_real = _clave_expediente(ped, fecha, idx)
        e = porexp.get(clave)
        if e is None:
            e = porexp[clave] = {
                "clave": clave,
                "expediente": ped.expediente.strip(" .-") if exp_real else None,
                "departamento": ped.departamento or None,
                "datum": datum,
                "_eventos": {},      # (tipo) -> set de fechas
                "_titulares": [],    # [(fecha, nombre)]
                "_minerales": set(),
                "_minas": set(),
                "_agrimensores": set(),
                "_mejor_vert": [],   # vértices del evento con más vértices
                "_sup": None,
            }
        # departamento / expediente: completar si faltaba
        if not e["departamento"] and ped.departamento:
            e["departamento"] = ped.departamento
        if not e["expediente"] and exp_real:
            e["expediente"] = ped.expediente.strip(" .-")
        # evento (tipo) -> fechas (colapsa publicaciones repetidas)
        tipo = ped.tipo_evento or clasificar(ped.crudo)
        e["_eventos"].setdefault(tipo, set()).add(fecha)
        # titular / mineral / mina
        if ped.titular:
            e["_titulares"].append((fecha, ped.titular))
        if ped.mineral:
            e["_minerales"].add(ped.mineral)
        if ped.mina:
            e["_minas"].add(ped.mina)
        if getattr(ped, "agrimensor", ""):
            e["_agrimensores"].add(ped.agrimensor)
        # geometría: nos quedamos con el evento de más vértices
        if len(ped.vertices) > len(e["_mejor_vert"]):
            e["_mejor_vert"] = ped.vertices
        if ped.superficie_ha and not e["_sup"]:
            e["_sup"] = ped.superficie_ha

    salida = []
    for e in porexp.values():
        # eventos -> lista ordenada con apariciones
        eventos = []
        for tipo, fechas in e["_eventos"].items():
            fs = sorted(fechas)
            eventos.append({
                "tipo": tipo,
                "tipo_label": ETIQUETAS.get(tipo, tipo),
                "etapa": ETAPAS.get(tipo, "otro"),
                "fechas": fs,
                "apariciones": len(fs),
                "anios": sorted({f[:4] for f in fs}),
                "meses": sorted({f[:7] for f in fs}),
            })
        eventos.sort(key=lambda x: x["fechas"][0])
        # estado = tipo del evento más reciente
        ult = max(eventos, key=lambda x: x["fechas"][-1]) if eventos else None
        estado = ult["tipo"] if ult else "otro"
        # titulares historizados (orden por fecha; hasta = desde del siguiente)
        vistos, hist = [], []
        for fecha, nombre in sorted(e["_titulares"]):
            if not hist or hist[-1]["nombre"] != nombre:
                hist.append({"nombre": nombre, "desde": fecha, "hasta": None})
        for i in range(len(hist) - 1):
            hist[i]["hasta"] = hist[i + 1]["desde"]
        # geometría WGS84: limpia outliers de OCR + envolvente convexo
        bruto = e["_mejor_vert"]
        ring, poligono, centro = finalizar_geometria(bruto, e["datum"], geo)
        salida.append({
            "clave": e["clave"],
            "expediente": e["expediente"],
            "departamento": e["departamento"],
            "datum": e["datum"],
            "titulares": hist,
            "titular_actual": hist[-1]["nombre"] if hist else None,
            "minerales": sorted(e["_minerales"]),
            "minas": sorted(e["_minas"]),
            "mina": sorted(e["_minas"])[0] if e["_minas"] else None,
            "agrimensores": sorted(e["_agrimensores"]),
            "superficie_ha": e["_sup"],
            "n_vertices": len(ring),
            "n_vertices_ocr": len(bruto),
            "vertices_gk": [list(v) for v in ring],
            "poligono_wgs84": poligono,
            "centroide": centro,
            "estado": estado,
            "estado_label": ETIQUETAS.get(estado, estado),
            "eventos": eventos,
            "anios": sorted({a for ev in eventos for a in ev["anios"]}),
            "meses": sorted({m for ev in eventos for m in ev["meses"]}),
        })
    # orden: por primer mes y luego expediente
    salida.sort(key=lambda x: (x["meses"][0] if x["meses"] else "9999", x["expediente"] or "zzz"))
    return salida
