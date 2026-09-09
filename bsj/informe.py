"""
Informe avanzado de inteligencia minera: fusiona las 3 fuentes (boletín, catastro, padrón
SIM) con el MOTOR LEGAL (bsj.legal) y el clasificador de exigibilidad (bsj.oportunidades)
para producir out_hist/sim/informe_avanzado.json.

Aporta la capa jurídica sobre los datos, SIN inflar el conteo:
  - deduplica los tramos del SIM por expediente (bsj.oportunidades.estado_actual) →
    1.360 vigentes / 455 caducas / 33 vacantes (no 2.131/690/77);
  - clasifica cada derecho por EXIGIBILIDAD legal (DISPONIBLE / PIPELINE / BLOQUEADO /
    VIGENTE), que no es lo mismo que el estado administrativo del padrón;
  - canon minero estimado por mina (canon_mina, art. 215 CM t.o. Ley 27.701);
  - para cada mina CADUCA, el cronograma teórico de vacancia (cronograma_vacancia) —
    entendido como plantilla, porque el plazo real corre desde la NOTIFICACIÓN, dato que
    la API no expone;
  - el marco legal (etapas + artículos) y los caminos de adquisición.
"""

import os
import json
import datetime as dt
from collections import defaultdict, Counter

from . import legal as L
from . import oportunidades as OP

HOY = dt.date.today()


def _tipo_canon(m):
    ty = (m.get("tipoYacimiento") or "").lower()
    mins = " ".join(m.get("minerales") or []).lower()
    if "disemin" in ty:
        return "diseminado"
    if "litio" in mins or "borato" in mins:
        return "borato_litio"
    return "comun"


def _cat_num(m):
    c = (m.get("categoria") or "").lower()
    return 2 if "segunda" in c else 1


def _hito(cod, hitos):
    h = next((x for x in hitos if x.codigo == cod), None)
    return h.fecha if h else None


def construir(salida):
    """Construye informe_avanzado.json a partir de los padrones ya descargados.

    Deduplica los tramos del SIM y trabaja SOLO con el estado vigente por expediente.
    """
    sim_fp = os.path.join(salida, "sim", "padron_sim.json")
    raw_fp = os.path.join(salida, "sim", "padron_sim_raw.json")
    d = json.load(open(sim_fp, encoding="utf-8"))
    crudo = json.load(open(raw_fp, encoding="utf-8"))

    # ---- DEDUP: estado vigente por expediente (tramo abierto más reciente) ----
    actual = OP.estado_actual(crudo)                       # {expediente: tramo}
    proc = d["minas"]
    dedup = {}
    for m in proc:
        e = m.get("expediente")
        if e in actual and m.get("estado") == actual[e].get("estado"):
            # ante duplicados del mismo expediente, quedarse con el de más superficie
            if e not in dedup or (m.get("ha") or 0) > (dedup[e].get("ha") or 0):
                dedup[e] = m
    minas = list(dedup.values())

    # ---- canon por mina + cronograma de vacancia por mina (plantilla) ----
    canon_por_estado = defaultdict(float)
    for m in minas:
        p = m.get("pertenencias") or 0
        m["canon"] = L.canon_mina(p, _tipo_canon(m), _cat_num(m)) if p else 0
        canon_por_estado[m["estado"]] += m["canon"]
        m["fecha_disponible"] = None
        if m["estado"] == "Caduca" and m.get("fecha_caducidad"):
            try:
                fc = dt.date.fromisoformat(m["fecha_caducidad"][:10])
                h = L.cronograma_vacancia(fc, por_canon=True)
                vd = _hito("VAC-DISP", h)
                veda = _hito("VAC-EXTIT", h)
                ipeem = _hito("VAC-IPEEM", h)
                m["fecha_disponible"] = vd.isoformat() if vd else None
                m["fecha_fin_veda_extitular"] = veda.isoformat() if veda else None
                m["fecha_fin_pref_ipeem"] = ipeem.isoformat() if ipeem else None
            except Exception:
                pass

    cad = [m for m in minas if m["estado"] == "Caduca"]

    # ---- EXIGIBILIDAD LEGAL (no estado administrativo) ----
    niveles = defaultdict(list)
    for m in minas:
        c = OP.clasificar(m, HOY)
        niveles[c["nivel"]].append({**m, **c})
    exigibilidad = {
        n: {"minas": len(v), "ha": round(sum(x.get("ha") or 0 for x in v))}
        for n, v in niveles.items()
    }
    pedibles_hoy = niveles.get("DISPONIBLE", [])

    def _grp(items, keyfn):
        g = defaultdict(lambda: {"n": 0, "ha": 0.0, "canon": 0})
        for m in items:
            for k in keyfn(m):
                g[k]["n"] += 1
                g[k]["ha"] += (m.get("ha") or 0)
                g[k]["canon"] += (m.get("canon") or 0)
        return g

    por_anio = _grp(cad, lambda m: [(m.get("fecha_caducidad") or "?")[:4]])
    por_depto = _grp(cad, lambda m: [m.get("departamento") or "?"])
    por_min = Counter()
    for m in cad:
        for x in (m.get("minerales") or ["?"]):
            por_min[x] += 1

    # ---- concesionarios (por CUIT) con canon y riesgo ----
    holders = {}
    for m in minas:
        for c in m.get("concesionarios") or []:
            k = c.get("id_fiscal")
            if not k:
                continue
            g = holders.setdefault(k, {"cuit": k, "nombres": Counter(), "minas": 0,
                                       "ha": 0.0, "canon": 0, "caduca": 0, "tipo": c.get("tipo")})
            g["nombres"][c.get("nombre") or "?"] += 1
            g["minas"] += 1
            g["ha"] += (m.get("ha") or 0)
            g["canon"] += (m.get("canon") or 0)
            if m["estado"] == "Caduca":
                g["caduca"] += 1
    hl = []
    for g in holders.values():
        g["nombre"] = g["nombres"].most_common(1)[0][0]
        del g["nombres"]
        g["ha"] = round(g["ha"])
        g["canon"] = round(g["canon"])
        hl.append(g)

    # ---- concentración de la CADUCIDAD: quién deja caer más ----
    exp_pipeline = OP.concesionarios_expuestos(niveles, "PIPELINE", top=15)

    # ---- marco legal: etapas de la vacancia (plantilla, días relativos) ----
    ref = dt.date(2025, 1, 1)
    marco_vac = [{"cod": h.codigo, "dia": (h.fecha - ref).days, "desc": h.descripcion,
                  "norma": h.norma, "consecuencia": h.consecuencia, "fatal": h.fatal}
                 for h in L.cronograma_vacancia(ref, por_canon=True)]

    caminos = [
        {"n": "Mina vacante", "desc": "Pedir una mina caduca/vacante una vez declarada la "
         "vacancia y transcurrido el plazo del art. 90. Es la vía que abre el pipeline de "
         "455 caducidades — pero HOY ninguna es pedible: falta que la Dirección inscriba y "
         "publique la vacancia.",
         "norma": "arts. 89-90 Ley 688-M; arts. 219-220 CM", "clave": "vacancia"},
        {"n": "Permiso de cateo", "desc": "Solicitar exploración sobre área libre; si hay "
         "hallazgo se manifiesta. Vía para las áreas francas del Análisis.",
         "norma": "arts. 40-48 Ley 688-M; arts. 25-48 CM", "clave": "cateo"},
        {"n": "Manifestación de descubrimiento", "desc": "Denunciar un descubrimiento (con o "
         "sin cateo previo), labor legal y mensura.", "norma": "arts. 57-59 Ley 688-M; arts. 111 ss. CM",
         "clave": "manifestacion"},
        {"n": "Transferencia / cesión", "desc": "Comprar el derecho a un titular ANTES de que "
         "caduque (evita el proceso de vacancia y la veda al ex-titular). Ideal para carteras "
         "en riesgo detectadas en el pipeline.", "norma": "art. 25 CM (transmisibilidad)",
         "clave": "transferencia"},
        {"n": "Preferencia estatal (IPEEM)", "desc": "El IPEEM tiene preferencia sobre el área "
         "liberada durante 180 días hábiles; los privados operan después de esa ventana.",
         "norma": "art. 29 in fine Ley 688-M; Ley 387-A", "clave": "ipeem"},
    ]

    doc = {
        "generado": HOY.isoformat(),
        "totales": {"expedientes": len(minas),
                    "registros_crudos": len(crudo),
                    "por_estado": dict(Counter(m["estado"] for m in minas)),
                    "canon_anual_vigente": round(canon_por_estado.get("Vigente", 0)),
                    "canon_anual_caduca": round(canon_por_estado.get("Caduca", 0)),
                    "ha_caduca": round(sum(m.get("ha") or 0 for m in cad))},
        "exigibilidad": exigibilidad,
        "disponibilidad": {
            "pedibles_hoy": len(pedibles_hoy),
            "ha_pedibles_hoy": round(sum(m.get("ha") or 0 for m in pedibles_hoy)),
            "en_pipeline": exigibilidad.get("PIPELINE", {}).get("minas", 0),
            "ha_pipeline": exigibilidad.get("PIPELINE", {}).get("ha", 0),
            "nota": "El pipeline NO es pedible: son minas caducas cuyo circuito de vacancia "
                    "(inscripción + publicación + plazo del art. 90) la Dirección no activó. "
                    "Quien monitorea el SIM ve el pipeline 12-18 meses antes que el boletín.",
        },
        "caducidad": {
            "por_anio": {k: {"n": v["n"], "ha": round(v["ha"]), "canon": round(v["canon"])}
                         for k, v in sorted(por_anio.items())},
            "por_depto": {k: {"n": v["n"], "ha": round(v["ha"]), "canon": round(v["canon"])}
                          for k, v in sorted(por_depto.items(), key=lambda x: -x[1]["ha"])[:8]},
            "por_mineral": dict(por_min.most_common(8)),
            "concentracion": [{"nombre": nom, "minas": cant, "ha": ha}
                              for nom, cant, ha in exp_pipeline],
        },
        "concesionarios": {
            "n": len(hl),
            "top_ha": sorted(hl, key=lambda g: -g["ha"])[:12],
            "top_caduca": sorted(hl, key=lambda g: -g["caduca"])[:8],
        },
        "marco_legal": {"vacancia": marco_vac, "caminos": caminos,
                        "canon_ref": {"1ra_por_pertenencia": L.CANON_1RA, "2da": L.CANON_2DA,
                                      "cateo_unidad": getattr(L, "CANON_CATEO_UNIDAD", None)}},
        # compacto para el mapa de vencimiento (solo caducas georreferenciadas)
        "caducas_geo": [
            {"expediente": m.get("expediente"), "nombre": m.get("nombre"),
             "departamento": m.get("departamento"), "cen": m.get("cen"),
             "ha": round(m.get("ha") or 0, 1), "canon": m.get("canon") or 0,
             "pertenencias": m.get("pertenencias") or 0,
             "minerales": m.get("minerales") or [],
             "fecha_caducidad": (m.get("fecha_caducidad") or "")[:10],
             "titular": (m.get("concesionarios") or [{}])[0].get("nombre"),
             "cuit": (m.get("concesionarios") or [{}])[0].get("id_fiscal")}
            for m in cad if m.get("cen")
        ],
    }
    fp = os.path.join(salida, "sim", "informe_avanzado.json")
    json.dump(doc, open(fp, "w", encoding="utf-8"), ensure_ascii=False)
    return doc


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    salida = sys.argv[1] if len(sys.argv) > 1 else "./out_hist"
    doc = construir(salida)
    t = doc["totales"]
    print("informe_avanzado.json")
    print("  expedientes:", t["expedientes"], "(de", t["registros_crudos"], "tramos crudos)")
    print("  por_estado:", t["por_estado"])
    print("  canon vigente/año: $", f"{t['canon_anual_vigente']:,}")
    print("  canon caduca/año:  $", f"{t['canon_anual_caduca']:,}")
    print("  ha caduca:", f"{t['ha_caduca']:,}")
    print("  exigibilidad:", doc["exigibilidad"])
    print("  disponibilidad:", {k: v for k, v in doc["disponibilidad"].items() if k != "nota"})
