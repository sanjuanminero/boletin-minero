# -*- coding: utf-8 -*-
"""Mapa de oportunidades: qué se puede pedir HOY y qué está en pipeline.

Cruza las tres fuentes y clasifica cada derecho por *exigibilidad legal*, que no
es lo mismo que su estado administrativo:

  DISPONIBLE   área libre en el catastro, o vacante con art. 220 CM operado
  PIPELINE     mina caduca sin vacancia declarada/publicada — NO pedible aún
  BLOQUEADO    vacante reciente (art. 90 Ley 688-M) o preferencia del IPEEM

TRAMPA CRÍTICA del SIM (no repetir el error):
    `historicoMina` devuelve TRAMOS de estado, no minas. 2.898 registros son
    1.848 expedientes; 820 tienen más de un tramo y hay tramos ya cerrados
    (minas que caducaron y volvieron a vigente al pagar). Contar registros da
    690 caducas; contar el tramo ABIERTO más reciente por expediente da 455.
    Usar siempre `estado_actual()`.
"""

from __future__ import annotations

import json
import os
import re
import datetime as dt
from collections import defaultdict, Counter

# Plazos del régimen de vacancia (días corridos salvo aclaración)
RESCATE_DIAS = 45        # art. 219 CM — desde la NOTIFICACIÓN, no desde la caducidad
DISPONIBLE_DIAS = 10     # art. 90 Ley 688-M — desde la publicación de la vacancia
IPEEM_HABILES = 180      # art. 29 in fine Ley 688-M
ART220_DIAS = 1095       # art. 220 CM — 3 años de empadronamiento como vacante


def _f(s):
    """Fecha ISO (con o sin hora) -> date."""
    if not s:
        return None
    try:
        return dt.date(*map(int, str(s)[:10].split("-")))
    except Exception:
        return None


def canon_expediente(e) -> str:
    """Sólo los dígitos: permite cruzar entre SIM, catastro y boletín."""
    return re.sub(r"\D", "", str(e or ""))


def estado_actual(registros: list[dict]) -> dict[str, dict]:
    """Estado vigente por expediente a partir del histórico crudo del SIM.

    Toma el tramo ABIERTO (fechaFin nulo) más reciente. Si todos están cerrados,
    toma el último cerrado. Devuelve {nro_expediente: registro}.
    """
    por = defaultdict(list)
    for r in registros:
        num = (r.get("expediente") or {}).get("numero")
        if num:
            por[num].append(r)

    out = {}
    for num, rs in por.items():
        abiertos = [r for r in rs if not r.get("fechaFin")] or rs
        abiertos.sort(key=lambda r: (str(r.get("fechaInicio") or ""), r.get("id") or 0))
        out[num] = abiertos[-1]
    return out


def clasificar(mina: dict, hoy: dt.date | None = None) -> dict:
    """Clasifica una mina del padrón procesado por exigibilidad legal."""
    hoy = hoy or dt.date.today()
    estado = str(mina.get("estado") or "")
    f_vac = _f(mina.get("fechainscripcionvacante"))
    f_cad = _f(mina.get("fecha_caducidad"))

    if estado == "Caduca":
        dias = (hoy - f_cad).days if f_cad else None
        return {
            "nivel": "PIPELINE",
            "pedible": False,
            "motivo": "Caduca sin vacancia declarada ni publicada. Requiere "
                      "inscripción, publicación y 10 días.",
            "norma": "art. 219 CM; arts. 88-90 Ley 688-M",
            "dias_desde_caducidad": dias,
            "solicitud_rescate": bool(mina.get("solicitud_rescate")),
        }

    if estado.startswith("Vacante"):
        dias = (hoy - f_vac).days if f_vac else None
        if dias is not None and dias > ART220_DIAS:
            return {
                "nivel": "DISPONIBLE",
                "pedible": True,
                "motivo": "Más de 3 años empadronada como vacante: el registro se "
                          "anula y el terreno queda franco, incorporándose de pleno "
                          "derecho y sin cargo a los permisos vigentes que lo cubran.",
                "norma": "art. 220 CM",
                "dias_vacante": dias,
            }
        return {
            "nivel": "BLOQUEADO",
            "pedible": False,
            "motivo": "Vacante reciente. Rige la preferencia del IPEEM (180 días "
                      "hábiles) y el plazo de disponibilidad del art. 90.",
            "norma": "art. 29 in fine y art. 90 Ley 688-M",
            "dias_vacante": dias,
        }

    return {"nivel": "VIGENTE", "pedible": False,
            "motivo": "Derecho vigente de un tercero.", "norma": "—"}


def analizar(salida: str = "./out_hist", hoy: dt.date | None = None) -> dict:
    """Construye el mapa de oportunidades desde los archivos ya descargados."""
    hoy = hoy or dt.date.today()
    sim_dir = os.path.join(salida, "sim")

    with open(os.path.join(sim_dir, "padron_sim_raw.json"), encoding="utf-8") as fh:
        crudo = json.load(fh)
    with open(os.path.join(sim_dir, "padron_sim.json"), encoding="utf-8") as fh:
        proc = json.load(fh)["minas"]

    actual = estado_actual(crudo)

    # quedarse con el registro procesado que coincide con el estado vigente
    minas = {}
    for m in proc:
        e = m.get("expediente")
        if e in actual and m.get("estado") == actual[e].get("estado"):
            if e not in minas or (m.get("ha") or 0) > (minas[e].get("ha") or 0):
                minas[e] = m

    niveles = defaultdict(list)
    for e, m in minas.items():
        c = clasificar(m, hoy)
        m = {**m, **c}
        niveles[c["nivel"]].append(m)

    resumen = {
        n: {"minas": len(v), "hectareas": round(sum(x.get("ha") or 0 for x in v), 1)}
        for n, v in niveles.items()
    }
    return {
        "generado": hoy.isoformat(),
        "expedientes_en_padron": len(actual),
        "resumen": resumen,
        "niveles": dict(niveles),
    }


def concesionarios_expuestos(niveles: dict, nivel: str = "PIPELINE", top: int = 15):
    """Quiénes están dejando caer más derechos."""
    n, ha = Counter(), Counter()
    for m in niveles.get(nivel, []):
        for c in (m.get("concesionarios") or []):
            n[c["nombre"]] += 1
            ha[c["nombre"]] += (m.get("ha") or 0)
    return [(k, v, round(ha[k], 1)) for k, v in n.most_common(top)]


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    r = analizar("./out_hist")
    print(f"Expedientes en el padrón del SIM: {r['expedientes_en_padron']}")
    print()
    for n in ("DISPONIBLE", "PIPELINE", "BLOQUEADO", "VIGENTE"):
        d = r["resumen"].get(n)
        if d:
            print(f"  {n:12s} {d['minas']:5d} minas   {d['hectareas']:12,.0f} ha")
    print()
    print("Concesionarios con más derechos en pipeline de caducidad:")
    for nom, cant, ha in concesionarios_expuestos(r["niveles"])[:10]:
        print(f"  {cant:4d} minas  {ha:10,.0f} ha   {nom}")
