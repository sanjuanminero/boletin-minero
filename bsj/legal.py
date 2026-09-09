# -*- coding: utf-8 -*-
"""Motor de cómputo de plazos del derecho procesal minero de San Juan.

El bot abogado NO debe inventar fechas: las calcula acá. Toda función devuelve
además la norma que la funda, para que la respuesta sea citable.

Marco: Código de Minería de la Nación (Ley 1919, t.o. + Ley 27.701) y
Código de Procedimientos Mineros de San Juan (Ley Provincial 688-M).

Regla de cómputo (art. 26 Ley 688-M): los términos *procesales* de la 688-M se
cuentan en DÍAS HÁBILES; los fijados por el Código de Minería, en DÍAS CORRIDOS.
Esa distinción es la fuente más común de error y está codificada abajo en el
campo `habiles` de cada plazo.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Iterable

# --------------------------------------------------------------------------
# Feriados nacionales/provinciales. Ampliar por año; si falta el año se avisa.
# --------------------------------------------------------------------------
FERIADOS: dict[int, set[dt.date]] = {}


def _fijos(anio: int) -> set[dt.date]:
    """Feriados inamovibles nacionales + San Juan (Difunta Correa no es feriado)."""
    d = dt.date
    return {
        d(anio, 1, 1), d(anio, 3, 24), d(anio, 4, 2), d(anio, 5, 1),
        d(anio, 5, 25), d(anio, 6, 20), d(anio, 7, 9), d(anio, 12, 8),
        d(anio, 12, 25),
    }


def feriados(anio: int) -> set[dt.date]:
    if anio not in FERIADOS:
        FERIADOS[anio] = _fijos(anio)
    return FERIADOS[anio]


def es_habil(f: dt.date) -> bool:
    return f.weekday() < 5 and f not in feriados(f.year)


def sumar_habiles(desde: dt.date, dias: int) -> dt.date:
    """Suma días hábiles. El cómputo arranca el día siguiente (art. 26, 688-M)."""
    f, n = desde, 0
    while n < dias:
        f += dt.timedelta(days=1)
        if es_habil(f):
            n += 1
    return f


def sumar_corridos(desde: dt.date, dias: int) -> dt.date:
    """Suma días corridos. Si cae inhábil, vence el hábil siguiente (art. 26)."""
    f = desde + dt.timedelta(days=dias)
    while not es_habil(f):
        f += dt.timedelta(days=1)
    return f


# --------------------------------------------------------------------------
# Catálogo de plazos
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Plazo:
    codigo: str
    etapa: str
    descripcion: str
    dias: int
    habiles: bool
    desde: str            # hecho que dispara el cómputo
    norma: str
    consecuencia: str     # qué pasa si se vence
    fatal: bool = False   # True = pérdida del derecho

    def vence(self, hecho: dt.date) -> dt.date:
        return (sumar_habiles if self.habiles else sumar_corridos)(hecho, self.dias)


PLAZOS: list[Plazo] = [
    # ---------------- Permiso de exploración / cateo ----------------
    Plazo("CAT-PUB", "cateo", "Publicar edictos: 2 veces alternadas en 10 días",
          10, False, "orden de anotación en Registro de Exploraciones",
          "art. 41 Ley 688-M; art. 53 CM",
          "Sin publicación acreditada no avanza el trámite."),
    Plazo("CAT-ACR", "cateo", "Acreditar la publicación ante la Autoridad Minera",
          20, True, "notificación de la anotación del pedimento",
          "art. 41, párr. 2 Ley 688-M",
          "Debe exhibirse al menos copia del recibo de pago."),
    Plazo("CAT-OPO", "cateo", "Plazo de terceros para deducir oposición",
          20, False, "última publicación de edictos en el Boletín Oficial",
          "art. 42 Ley 688-M; art. 27 CM",
          "Vencido sin oposición, el expediente queda en estado de resolver."),
    Plazo("CAT-INST", "cateo", "Instalar los trabajos del programa mínimo",
          30, False, "notificación del otorgamiento del permiso",
          "art. 45 Ley 688-M; art. 30, párr. 3 CM",
          "Revocación del permiso (art. 41 inc. a CM).", fatal=True),
    Plazo("CAT-SUP", "cateo", "Expedirse sobre el área libre en superposición parcial",
          5, True, "vista del informe del Registro Catastral",
          "art. 40 Ley 688-M",
          "Se tiene por aceptado el informe y sigue por la parte libre."),
    Plazo("CAT-INFO", "cateo", "Presentar información y documentación técnica",
          90, False, "vencimiento del permiso",
          "art. 45 in fine Ley 688-M; art. 30 in fine CM",
          "Multa igual al DOBLE del canon abonado."),
    Plazo("CAT-REPED", "cateo", "Veda para pedir de nuevo la misma zona (mismo titular o socio)",
          365, False, "publicación de la caducidad",
          "art. 47 Ley 688-M; art. 30, párr. 5 CM",
          "Rechazo del nuevo pedimento.", fatal=True),
    Plazo("CAT-TERC", "cateo", "Veda para que un TERCERO pida la zona liberada",
          10, False, "publicación de la liberación (art. 29, párr. 2)",
          "art. 46 Ley 688-M; art. 29 párr. 2 Ley 688-M",
          "Antes del día 11 el pedimento se rechaza in limine."),

    # ---------------- Manifestación de descubrimiento ----------------
    Plazo("MD-AREA", "manifestacion", "Rectificar el área si excede el máximo legal",
          5, True, "emplazamiento de la Autoridad Minera",
          "art. 56 Ley 688-M",
          "Pérdida automática de la prioridad.", fatal=True),
    Plazo("MD-FRANCO", "manifestacion", "Pronunciarse sobre el área libre (terreno no franco)",
          15, True, "notificación del informe de Catastro",
          "art. 55 Ley 688-M",
          "Se archiva la petición sin más trámite.", fatal=True),
    Plazo("MD-PUB", "manifestacion", "Publicar edictos: 3 veces en 15 días",
          15, False, "orden de registro de la manifestación",
          "art. 57 Ley 688-M; art. 53 CM",
          "Caducidad del pedido y archivo.", fatal=True),
    Plazo("MD-OPO", "manifestacion", "Plazo de oposición de terceros",
          60, False, "última publicación de edictos",
          "art. 57 Ley 688-M; art. 66 CM",
          "Precluye el derecho a oponerse."),
    Plazo("MD-LABOR", "manifestacion", "Ejecutar y comunicar la LABOR LEGAL (10 m sobre el criadero)",
          100, False, "notificación del registro de la manifestación",
          "art. 58 Ley 688-M; arts. 19, 68 CM",
          "Caducidad del derecho; manifestación como no presentada.", fatal=True),
    Plazo("MD-MENS", "manifestacion", "Solicitar mensura y demarcación de pertenencias",
          30, False, "vencimiento del plazo de labor legal (o sus prórrogas)",
          "art. 59 Ley 688-M; arts. 71, 81 CM",
          "Se tienen por desistidos los derechos; la mina se inscribe VACANTE.", fatal=True),

    # ---------------- Mensura ----------------
    Plazo("MEN-PUB", "mensura", "Publicar la petición de mensura: 3 veces en 15 días",
          15, False, "proveído de la petición de mensura",
          "art. 59 Ley 688-M; art. 53 CM",
          "Sin publicación no se aprueba la mensura.", fatal=True),
    Plazo("MEN-OPO", "mensura", "Oposición de terceros a la petición de mensura",
          15, True, "última publicación de edictos",
          "art. 62 Ley 688-M; art. 84 CM",
          "Precluye la oposición."),
    Plazo("MEN-NOTIF", "mensura", "Notificación anticipada a minas colindantes",
          5, True, "fecha fijada para la diligencia (hacia atrás)",
          "art. 103 Ley 688-M; art. 85 CM",
          "Vicio de procedimiento oponible."),
    Plazo("MEN-DEP", "mensura", "Depositar el costo de la mensura (perito oficial)",
          10, True, "fecha de iniciación fijada (hacia atrás)",
          "art. 100 Ley 688-M",
          "Se tiene por desistido el derecho; mina VACANTE.", fatal=True),
    Plazo("MEN-EJEC", "mensura", "Ejecutar la mensura",
          60, False, "fecha de inicio fijada por la Autoridad Minera",
          "art. 99 Ley 688-M",
          "Si es perito particular: desistimiento y vacancia (art. 101).", fatal=True),
    Plazo("MEN-PRES", "mensura", "Presentar la diligencia de mensura por triplicado + plano",
          10, True, "terminación de las operaciones de campo",
          "art. 106 Ley 688-M",
          "Demora sancionable; retrasa la aprobación."),

    # ---------------- Amparo (vida de la mina) ----------------
    Plazo("AMP-CANON1", "amparo", "Canon minero: 1er semestre",
          0, False, "vence el 30 de junio de cada año",
          "art. 216 CM",
          "Mora."),
    Plazo("AMP-CANON2", "amparo", "Canon minero: 2do semestre",
          0, False, "vence el 31 de diciembre de cada año",
          "art. 216 CM",
          "Mora."),
    Plazo("AMP-CADUC", "amparo", "Caducidad ipso facto por falta de pago del canon",
          60, False, "vencimiento del semestre impago",
          "art. 216 in fine CM",
          "Caducidad automática de la concesión.", fatal=True),
    Plazo("AMP-RESC", "amparo", "Derecho de RESCATE de la mina caduca por canon",
          45, False, "notificación de la caducidad",
          "art. 219 CM (t.o. Ley 27.701)",
          "Paga canon actualizado + 100% de recargo. Vencido: vacancia automática.",
          fatal=True),
    Plazo("AMP-INV", "amparo", "Presentar estimación del plan y monto de inversiones",
          365, False, "fecha de la petición de mensura",
          "art. 217 CM",
          "Caducidad de la concesión (art. 218 inc. c).", fatal=True),
    Plazo("AMP-INVEJ", "amparo", "Ejecutar íntegramente las inversiones estimadas",
          1826, False, "presentación de la estimación de inversiones",
          "art. 217, párr. 2 CM",
          "Mínimo 300 cánones anuales; caducidad si baja de 500 (art. 218 inc. b).",
          fatal=True),
    Plazo("AMP-SUBS", "amparo", "Subsanar error u omisión intimado (inc. a-d art. 218)",
          30, False, "intimación previa de la Autoridad Minera",
          "art. 218, párr. 2 CM",
          "Se declara la caducidad.", fatal=True),
    Plazo("AMP-DEF", "amparo", "Vista para defensa (incs. e-h art. 218)",
          15, False, "vista de lo actuado",
          "art. 218, párr. 3 CM",
          "Se declara la caducidad.", fatal=True),
    Plazo("AMP-REACT", "amparo", "Presentar proyecto de reactivación de mina inactiva",
          180, False, "intimación por inactividad mayor a 4 años",
          "art. 225 CM",
          "Caducidad de la concesión.", fatal=True),

    # ---------------- Vacancia y abandono ----------------
    Plazo("VAC-INSC", "vacancia", "Inscribir la mina en el Registro de Minas Vacantes",
          5, True, "resolución firme de vacancia",
          "art. 89 Ley 688-M",
          "Deber de oficio de la Autoridad Minera."),
    Plazo("VAC-PUB", "vacancia", "Publicar la vacancia en el Boletín Oficial (1 día)",
          30, False, "inscripción en el Registro de Minas Vacantes",
          "art. 90 Ley 688-M",
          "Deber de oficio."),
    Plazo("VAC-DISP", "vacancia", "La mina vacante queda DISPONIBLE para terceros",
          10, False, "publicación de la vacancia",
          "art. 90 Ley 688-M",
          "Antes del día 11 el pedido se rechaza."),
    Plazo("VAC-IPEEM", "vacancia", "Derecho de preferencia del IPEEM sobre el área liberada",
          180, True, "notificación al IPEEM de las actuaciones",
          "art. 29 in fine Ley 688-M; Ley 387-A; Tít. XXI CM",
          "Si el IPEEM no se expide, el área queda disponible para privados.",
          fatal=True),
    Plazo("VAC-EXTIT", "vacancia", "Veda al ANTERIOR concesionario para repedir la mina",
          365, False, "inscripción de la vacancia",
          "art. 90 Ley 688-M; art. 219 in fine CM",
          "Rechazo del pedimento.", fatal=True),
    Plazo("VAC-ANUL", "vacancia", "Anulación automática del registro de mina vacante",
          1095, False, "empadronamiento como vacante",
          "art. 220 CM",
          "El terreno queda FRANCO e incorporado de pleno derecho a los cateos vigentes."),
    Plazo("ABA-ANT", "abandono", "Anticipación para declarar el abandono",
          20, False, "fecha prevista de cese (hacia atrás)",
          "art. 226 CM",
          "Subsisten derechos y obligaciones hasta que se admita el abandono."),
    Plazo("ABA-PUB", "abandono", "Publicar la manifestación de abandono: 3 veces en 15 días",
          15, False, "proveído del escrito de abandono",
          "art. 91 Ley 688-M; art. 228 CM",
          "Recién después corre el plazo del art. 29 párr. 2."),

    # ---------------- Servidumbres ----------------
    Plazo("SER-VISTA", "servidumbre", "Vista del informe del Registro Catastral",
          5, True, "notificación del informe",
          "art. 108 Ley 688-M",
          "Se tiene por consentido."),
    Plazo("SER-PUB", "servidumbre", "Publicar edictos: 2 veces en 10 días",
          10, False, "resolución que ordena la publicación",
          "art. 108 Ley 688-M",
          "Sin publicación no se concede."),
    Plazo("SER-OPO", "servidumbre", "Oposición de propietarios y titulares afectados",
          10, True, "notificación personal",
          "art. 108 in fine Ley 688-M",
          "Precluye la oposición."),

    # ---------------- Procesal general ----------------
    Plazo("GEN-CADUC", "procesal", "Emplazamiento por paralización del trámite",
          5, True, "notificación del emplazamiento (tras 60 días de inacción)",
          "art. 4 Ley 688-M",
          "Abandono del trámite, pérdida de derechos y archivo.", fatal=True),
    Plazo("GEN-PARAL", "procesal", "Inacción que habilita el emplazamiento de oficio",
          60, True, "último acto de impulso del interesado",
          "art. 4 Ley 688-M",
          "Habilita el emplazamiento del art. 4."),
    Plazo("GEN-SUBSAN", "procesal", "Subsanar requisitos omitidos en la petición inicial",
          5, True, "notificación de la observación",
          "art. 12 Ley 688-M",
          "Se tiene por no presentada la solicitud.", fatal=True),
    Plazo("GEN-VISTA", "procesal", "Vistas y traslados sin término especial",
          5, True, "notificación",
          "art. 27 Ley 688-M",
          "Se tiene por evacuada."),
    Plazo("GEN-REPO", "procesal", "Recurso de reposición",
          5, True, "notificación de la resolución",
          "art. 128 Ley 688-M",
          "Queda firme la resolución.", fatal=True),
    Plazo("GEN-APEL", "procesal", "Recurso de apelación ante la Cámara",
          10, True, "notificación de la resolución definitiva",
          "art. 129 Ley 688-M",
          "Queda firme la resolución.", fatal=True),
    Plazo("GEN-TRASL", "procesal", "Traslado de demanda u oposición (contencioso minero)",
          10, True, "notificación", "art. 125 Ley 688-M", "Rebeldía."),
    Plazo("GEN-PRUEBA", "procesal", "Período de prueba en el contencioso minero",
          20, True, "auto de apertura a prueba", "art. 126 Ley 688-M",
          "Precluye la producción."),
    Plazo("GEN-ALEG", "procesal", "Alegato sobre el mérito de la prueba",
          5, True, "certificación del vencimiento probatorio",
          "art. 127 Ley 688-M", "Precluye."),
]

POR_CODIGO = {p.codigo: p for p in PLAZOS}


# --------------------------------------------------------------------------
# Parámetros cuantitativos del Código de Minería
# --------------------------------------------------------------------------
UNIDAD_CATEO_HA = 500                 # art. 29 CM
MAX_UNIDADES_POR_PERMISO = 20         # art. 29 CM
MAX_PERMISOS_POR_PROVINCIA = 20       # art. 29 CM
MAX_UNIDADES_POR_PROVINCIA = 400      # art. 29 CM

CANON_1RA = 1900        # $ por pertenencia/año - art. 215 inc. 1 CM (Ley 27.701)
CANON_2DA = 960         # $ por pertenencia/año - art. 215 inc. 2 CM
CANON_CATEO_UNIDAD = 9680   # $ por unidad de medida - art. 215 inc. 3 CM

# Pertenencias (Título V CM). Superficie en ha y multiplicador de canon.
PERTENENCIAS = {
    "comun":      dict(ha=6.0,   desc="300 m x 200 m (ampliable a 300 m)", mult=1, norma="art. 73 CM"),
    "hierro":     dict(ha=24.0,  desc="600 m x 400 m (ampliable a 600 m)", mult=3, norma="art. 76 CM"),
    "carbon":     dict(ha=54.0,  desc="900 m x 600 m (ampliable a 900 m)", mult=6, norma="art. 76 CM"),
    "diseminado": dict(ha=100.0, desc="100 ha (explotación a gran escala no selectiva)", mult=10, norma="art. 76 CM"),
    "borato_litio": dict(ha=100.0, desc="100 ha", mult=10, norma="art. 76 CM"),
}


def duracion_cateo(unidades: int) -> int:
    """Días corridos de duración del permiso de exploración (art. 30 CM)."""
    if unidades < 1:
        raise ValueError("El permiso debe constar de al menos 1 unidad de medida.")
    if unidades > MAX_UNIDADES_POR_PERMISO:
        raise ValueError(
            f"Máximo {MAX_UNIDADES_POR_PERMISO} unidades por permiso (art. 29 CM); "
            f"se pidieron {unidades}."
        )
    return 150 + 50 * (unidades - 1)


def unidades_de(hectareas: float) -> int:
    """Unidades de medida que consume una superficie (fracción = unidad completa)."""
    import math
    return max(1, math.ceil(hectareas / UNIDAD_CATEO_HA))


def canon_cateo(unidades: int) -> int:
    return unidades * CANON_CATEO_UNIDAD


def canon_mina(pertenencias: int, tipo: str = "comun", categoria: int = 1) -> int:
    base = CANON_1RA if categoria == 1 else CANON_2DA
    mult = PERTENENCIAS.get(tipo, PERTENENCIAS["comun"])["mult"]
    return pertenencias * base * mult


def inversion_minima(pertenencias: int, tipo: str = "comun", categoria: int = 1) -> dict:
    """Piso de inversión del art. 217/218 CM."""
    c = canon_mina(pertenencias, tipo, categoria)
    return {
        "canon_anual": c,
        "inversion_comprometida_min": c * 300,   # art. 217, párr. 2
        "piso_caducidad": c * 500,               # art. 218 inc. b
        "primeros_dos_anios_c_u": None,          # 20% del total estimado - art. 217
        "norma": "arts. 217 y 218 CM",
    }


# --------------------------------------------------------------------------
# Cronogramas
# --------------------------------------------------------------------------
@dataclass
class Hito:
    fecha: dt.date
    codigo: str
    descripcion: str
    norma: str
    consecuencia: str
    fatal: bool

    def __str__(self) -> str:
        marca = "[FATAL]" if self.fatal else "       "
        return f"{self.fecha}  {marca} {self.codigo:11s} {self.descripcion}  ({self.norma})"


def cronograma_cateo(fecha_solicitud: dt.date, hectareas: float,
                     dias_resolucion: int = 60) -> list[Hito]:
    """Cronograma completo de un permiso de exploración.

    `dias_resolucion` es el tiempo estimado entre el fin del plazo de oposición
    y el otorgamiento: NO es un plazo legal (el art. 29 inc. c da 30 días desde
    que quedan firmes los autos), sino una estimación operativa.
    """
    u = unidades_de(hectareas)
    dur = duracion_cateo(u)
    hitos: list[Hito] = []

    def add(f: dt.date, cod: str, extra: str = ""):
        p = POR_CODIGO[cod]
        hitos.append(Hito(f, cod, p.descripcion + extra, p.norma, p.consecuencia, p.fatal))

    # La anotación y orden de publicación es prácticamente inmediata al informe
    # de Catastro; se estima 15 días hábiles desde la presentación.
    orden_pub = sumar_habiles(fecha_solicitud, 15)
    add(orden_pub, "CAT-PUB")
    ult_pub = sumar_corridos(orden_pub, 10)
    hitos.append(Hito(ult_pub, "CAT-PUB2", "Última publicación de edictos (fin del plazo de 10 días)",
                      "art. 41 Ley 688-M", "Desde acá corre la oposición.", False))
    add(sumar_habiles(orden_pub, 20), "CAT-ACR")
    fin_opo = sumar_corridos(ult_pub, 20)
    add(fin_opo, "CAT-OPO")
    otorg = sumar_habiles(fin_opo, dias_resolucion)
    hitos.append(Hito(otorg, "CAT-OTOR", f"Otorgamiento estimado del permiso ({u} unidades, {dur} días de duración)",
                      "art. 29 inc. c Ley 688-M", "Estimación operativa, no plazo legal.", False))
    add(sumar_corridos(otorg, 30), "CAT-INST")
    inicio = otorg + dt.timedelta(days=30)
    venc = sumar_corridos(inicio, dur)
    hitos.append(Hito(venc, "CAT-VENC", f"VENCIMIENTO del permiso ({dur} días corridos)",
                      "art. 30 CM", "Caducidad de pleno derecho (art. 48 Ley 688-M).", True))

    # Liberaciones parciales del art. 30 CM
    if u > 4:
        for dia, etiqueta in ((300, "1ra"), (700, "2da")):
            if dur >= dia:
                f = sumar_corridos(inicio, dia)
                hitos.append(Hito(
                    f, f"CAT-LIB{dia}",
                    f"{etiqueta} liberación obligatoria: desafectar la mitad del excedente sobre 4 unidades",
                    "art. 30, párr. 2 CM",
                    "Si no se pide en término, libera Catastro a su criterio + multa igual al canon.",
                    True))
    add(sumar_corridos(venc, 90), "CAT-INFO")
    hitos.sort(key=lambda h: h.fecha)
    return hitos


def cronograma_manifestacion(fecha_registro: dt.date,
                             prorroga_labor_dias: int = 0) -> list[Hito]:
    """Cronograma desde el registro de la manifestación hasta la mensura.

    `prorroga_labor_dias`: prórrogas de labor legal de los arts. 69/70 CM.
    """
    hitos: list[Hito] = []

    def add(f: dt.date, cod: str):
        p = POR_CODIGO[cod]
        hitos.append(Hito(f, cod, p.descripcion, p.norma, p.consecuencia, p.fatal))

    add(sumar_corridos(fecha_registro, 15), "MD-PUB")
    ult_pub = fecha_registro + dt.timedelta(days=15)
    add(sumar_corridos(ult_pub, 60), "MD-OPO")
    fin_labor = fecha_registro + dt.timedelta(days=100 + prorroga_labor_dias)
    hitos.append(Hito(sumar_corridos(fecha_registro, 100 + prorroga_labor_dias),
                      "MD-LABOR", POR_CODIGO["MD-LABOR"].descripcion +
                      (f" (+{prorroga_labor_dias}d de prórroga)" if prorroga_labor_dias else ""),
                      POR_CODIGO["MD-LABOR"].norma, POR_CODIGO["MD-LABOR"].consecuencia, True))
    f_mens = sumar_corridos(fin_labor, 30)
    add(f_mens, "MD-MENS")
    hitos.append(Hito(sumar_corridos(f_mens, 365), "AMP-INV",
                      POR_CODIGO["AMP-INV"].descripcion, POR_CODIGO["AMP-INV"].norma,
                      POR_CODIGO["AMP-INV"].consecuencia, True))
    hitos.sort(key=lambda h: h.fecha)
    return hitos


def cronograma_vacancia(fecha_caducidad: dt.date, por_canon: bool = True) -> list[Hito]:
    """Desde la caducidad hasta que la mina es adquirible por un tercero."""
    hitos: list[Hito] = []

    def add(f: dt.date, cod: str):
        p = POR_CODIGO[cod]
        hitos.append(Hito(f, cod, p.descripcion, p.norma, p.consecuencia, p.fatal))

    if por_canon:
        add(sumar_corridos(fecha_caducidad, 45), "AMP-RESC")
        base = fecha_caducidad + dt.timedelta(days=45)
    else:
        base = fecha_caducidad
    insc = sumar_habiles(base, 5)
    add(insc, "VAC-INSC")
    add(sumar_habiles(insc, 180), "VAC-IPEEM")
    pub = sumar_corridos(insc, 30)
    add(pub, "VAC-PUB")
    add(sumar_corridos(pub, 10), "VAC-DISP")
    add(sumar_corridos(insc, 365), "VAC-EXTIT")
    add(sumar_corridos(insc, 1095), "VAC-ANUL")
    hitos.sort(key=lambda h: h.fecha)
    return hitos


def buscar(texto: str) -> list[Plazo]:
    """Busca plazos por palabra clave en descripción, etapa o norma."""
    t = texto.lower()
    return [p for p in PLAZOS
            if t in p.descripcion.lower() or t in p.etapa.lower()
            or t in p.norma.lower() or t in p.codigo.lower()]


def imprimir(hitos: Iterable[Hito]) -> str:
    return "\n".join(str(h) for h in hitos)


if __name__ == "__main__":
    import sys
    hoy = dt.date.today()
    print("=" * 78)
    print("CRONOGRAMA — Permiso de exploración de 5.000 ha solicitado hoy")
    print("=" * 78)
    print(imprimir(cronograma_cateo(hoy, 5000)))
    print()
    print("=" * 78)
    print("CRONOGRAMA — Manifestación de descubrimiento registrada hoy")
    print("=" * 78)
    print(imprimir(cronograma_manifestacion(hoy)))
    print()
    print("=" * 78)
    print("CRONOGRAMA — Mina caduca por falta de canon (hoy) hasta ser adquirible")
    print("=" * 78)
    print(imprimir(cronograma_vacancia(hoy)))
    print()
    print("Canon cateo 10 unidades:", f"${canon_cateo(10):,}")
    print("Canon mina 20 pertenencias diseminado:", f"${canon_mina(20, 'diseminado'):,}")
    print("Inversión art. 217:", inversion_minima(20, "diseminado"))
