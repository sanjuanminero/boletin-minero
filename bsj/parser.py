"""
Parser de edictos mineros del Boletín Oficial de San Juan.

Estrategia:
  1) Trocear el texto del boletín en "avisos" (bloques).
  2) Quedarse con los que son mineros (Juzgado Administrativo de Minas,
     manifestación de descubrimiento, cateo, exploración, mensura, servidumbre...).
  3) De cada aviso minero extraer: expediente, titular, mineral, departamento,
     superficie (ha) y los vértices de coordenadas Gauss-Krüger.

Es heurístico a propósito: los edictos tienen plantilla repetitiva pero no idéntica,
así que conviene revisar manualmente lo que el parser marque con baja confianza.
"""

import re
from dataclasses import dataclass, field
from .coords import es_par_valido

# ---------- Detección de avisos mineros ----------
KW_MINERO = [
    "juzgado administrativo de minas", "manifestación de descubrimiento",
    "manifestacion de descubrimiento", "solicita cateo", "permiso de cateo",
    "permiso de exploración", "permiso de exploracion", "mensura minera",
    "servidumbre minera", "registro de mina", "pedimento", "dirección de minería",
    "direccion de mineria", "labor legal", "concesión minera", "concesion minera",
    # vocabulario real de los edictos de SJ (visto por OCR):
    "edicto de mensura", "director de minería", "director de mineria",
    "mensura de la mina", "pertenencia", "código de minería", "codigo de mineria",
    "manifestación", "manifestacion", "gauss kruger", "gauss krüger",
]

DEPARTAMENTOS = [
    "Albardón", "Angaco", "Calingasta", "Capital", "Caucete", "Chimbas",
    "Iglesia", "Jáchal", "9 de Julio", "Pocito", "Rawson", "Rivadavia",
    "San Martín", "Santa Lucía", "Sarmiento", "Ullum", "Valle Fértil",
    "25 de Mayo", "Zonda",
]

MINERALES = [
    "oro", "plata", "cobre", "litio", "uranio", "hierro", "plomo", "zinc",
    "molibdeno", "manganeso", "bentonita", "caliza", "calcáreo", "mármol",
    "yeso", "diatomita", "cuarzo", "feldespato", "talco", "baritina",
]


def _num(s: str) -> float:
    """Normaliza un número en formato argentino o el que sale del OCR.
    Casos:
      6.511.304,01  -> 6511304.01   (coma decimal clásica)
      3.500         -> 3500         (solo miles)
      6.621.897.70  -> 6621897.70   (OCR convierte la coma decimal en punto;
                                      último grupo de 1-2 dígitos = decimales)
      6.5           -> 6.5
    """
    s = s.strip().replace(" ", "")
    if "," in s:
        # la coma es el decimal; los puntos son miles
        return float(s.replace(".", "").replace(",", "."))
    if s.count(".") == 0:
        return float(s)
    grupos = s.split(".")
    ultimo = grupos[-1]
    if len(ultimo) == 3:
        # todos los grupos son miles -> entero
        return float("".join(grupos))
    # el último grupo (1-2 díg.) son decimales; el resto, miles
    return float("".join(grupos[:-1]) + "." + ultimo)


# X/Norte ~ 6-7 millones, Y/Este ~ 2.3-2.7 millones. Miles con '.'/espacio y decimal
# con ',' o '.' (el OCR suele convertir la coma decimal en punto: 6.621.897.70).
_NUMERO = r"\d{1,3}(?:[.\s]\d{3})+(?:[.,]\d{1,3})?|\d{6,}(?:[.,]\d+)?"

# Captura pares etiquetados: X=... Y=...  /  Norte:... Este:...  /  Y=... X=...
_PAR_XY = re.compile(
    r"(?:x|norte|n)\s*[:=]?\s*(" + _NUMERO + r")"
    r"[\s;,]*"
    r"(?:y|este|e)\s*[:=]?\s*(" + _NUMERO + r")",
    re.IGNORECASE,
)
_PAR_YX = re.compile(
    r"(?:y|este|e)\s*[:=]?\s*(" + _NUMERO + r")"
    r"[\s;,]*"
    r"(?:x|norte|n)\s*[:=]?\s*(" + _NUMERO + r")",
    re.IGNORECASE,
)
# Fallback: dos números grandes seguidos, separados por espacio/coma/pipe (tablas OCR).
_PAR_SUELTO = re.compile(r"(" + _NUMERO + r")[\s;,|]+(" + _NUMERO + r")")

# Expediente: tras 'Expte.'/'Expediente' viene 'N°' (que el OCR lee como N°/Nº/N*/NS/N9/N"),
# o palabras como 'es'. Saltamos cualquier no-dígito (hasta 7 chars) y capturamos DESDE el
# primer dígito, así no nos comemos basura tipo 'S'. Captura: 1124-661-B-2022, 296.796-L-90.
_EXPTE = re.compile(r"(?:expte\.?|expediente)\s*[^\d\n]{0,7}(\d[\w\-./]*\d|\d)", re.IGNORECASE)
_SUP = re.compile(r"(" + _NUMERO + r")\s*(?:has?\.?|hect[áa]reas?)", re.IGNORECASE)


@dataclass
class Pedimento:
    expediente: str = ""
    titular: str = ""
    mineral: str = ""
    mina: str = ""                                  # nombre de la mina (ej. "AGU 5")
    agrimensor: str = ""                            # profesional actuante (si el edicto lo nombra)
    tipo_evento: str = ""                           # clave de taxonomía (ver bsj.eventos)
    departamento: str = ""
    superficie_ha: float | None = None
    vertices: list = field(default_factory=list)   # [(norte, este), ...]
    confianza: str = "alta"
    crudo: str = ""


def _ordenar_par(a: float, b: float):
    """Devuelve (norte, este) sin importar el orden de entrada, usando los rangos."""
    if es_par_valido(a, b):
        return a, b
    if es_par_valido(b, a):
        return b, a
    return None


def extraer_vertices(texto: str):
    vistos = set()
    out = []
    for rx in (_PAR_XY, _PAR_YX, _PAR_SUELTO):
        for m in rx.finditer(texto):
            try:
                a, b = _num(m.group(1)), _num(m.group(2))
            except ValueError:
                continue
            par = _ordenar_par(a, b)
            if par is None:
                continue
            clave = (round(par[0], 1), round(par[1], 1))
            if clave in vistos:
                continue
            vistos.add(clave)
            out.append(par)
        if out:  # si una estrategia ya pescó vértices válidos, no mezclamos con el fallback
            break
    return out


def es_minero(bloque: str) -> bool:
    b = bloque.lower()
    return any(k in b for k in KW_MINERO)


def trocear_avisos(texto: str):
    """Divide el texto en edictos. Corta en los encabezados fuertes 'EDICTO DE ...'
    (MENSURA / MANIFESTACIÓN / CATEO / EXPLORACIÓN / SERVIDUMBRE), conservando el
    encabezado con su bloque (split por lookahead). NO se fragmenta por párrafos:
    eso dispersaba los vértices de un mismo edicto en bloques distintos."""
    # OJO: el OCR espacia las letras del encabezado ("EDICTO D E CATEO"), por eso
    # se tolera 'D\s*E' — si no, varios edictos quedan pegados en un solo bloque.
    partes = [p for p in re.split(r"(?im)(?=^\s*EDICTO\s+D\s*E\b)", texto) if p.strip()]
    if len(partes) >= 2:
        return partes
    # un solo edicto (o sin encabezados claros): tratar todo como un bloque
    return [texto] if texto.strip() else []


def _limpiar_titular(s: str) -> str:
    """Recorta el nombre del titular: corta en marcadores que indican fin del nombre
    (s/, /, '—', 'en el', 'expte', 'solicita'...) y ante la primera corrida de dígitos
    (coordenadas). Evita que el titular se lleve media frase u OCR de tablas."""
    s = re.sub(r"\s+", " ", s).strip()
    s = re.split(r"\s*(?:—|–|\bs/|/|\ben el\b|\bexpte|\bexpediente|\bsolicit|"
                 r"\bmanifiesta|\bregistr|\bpor resoluc|\bcomunica\b)", s, flags=re.IGNORECASE)[0]
    # cortar la boilerplate de cola del edicto que se cuela tras el nombre
    # ("<NOMBRE>. Publíquese Edicto 2 veces", "... Cítese", "... de conformidad...").
    s = re.split(r"\s*(?:\bpubl[ií]?quese\b|\bpublicar\b|\bpubl[ií]c\w*|\bedicto\b|"
                 r"\bc[ií]tese\b|\bnotif\w*|\bde conformidad\b|\bconf\.|\bdispon\w*|"
                 r"\bresuel\w*|\bh[áa]gase\b|\bhace saber\b|\bp[oó]r\s+\d)",
                 s, flags=re.IGNORECASE)[0]
    s = re.split(r"\d{3,}", s)[0]
    return s.strip(" ,.;:-")[:80]


def _buscar(lista, texto):
    tl = texto.lower()
    for item in lista:
        if item.lower() in tl:
            return item
    return ""


def parsear_pedimento(bloque: str) -> Pedimento:
    p = Pedimento(crudo=bloque.strip()[:1200])
    m = _EXPTE.search(bloque)
    if m:
        p.expediente = m.group(1).strip(" .")
    p.departamento = _buscar(DEPARTAMENTOS, bloque)
    p.mineral = _buscar(MINERALES, bloque)
    ms = _SUP.search(bloque)
    if ms:
        try:
            p.superficie_ha = _num(ms.group(1))
        except ValueError:
            pass
    p.vertices = extraer_vertices(bloque)

    # titular / solicitante. Plantillas vistas en SJ (mensura, cateo, servidumbre):
    #   "...Inscríbase el presente pedido a nombre de <NOMBRE>, Publicar..."  (la más limpia)
    #   "...se ha presentado <NOMBRE> s/Exploración | solicitando la Mensura | .-"
    #   "...hace saber que, <NOMBRE> solicita/registra/manifiesta..."
    #   índice: "<NOMBRE> s/ <acto>"
    # 1) el PETICIONANTE: "...se ha presentado <NOMBRE> [s/ | solicitando | .-]"
    mt = re.search(r"(?:se ha presentado|presentad[oa])\s+(.{3,90}?)\s*"
                   r"(?:s\s*/|/|,?\s*solicit|manifiesta|,?\s*en el\b|\.\s*-)",
                   bloque, re.IGNORECASE | re.DOTALL)
    # 2) "hace saber que, <NOMBRE> ..."
    if not mt:
        mt = re.search(r"hace saber que,?\s*(.{3,90}?)\s+(?:solicit|registr|en expte|manifiesta)",
                       bloque, re.IGNORECASE | re.DOTALL)
    # 3) registro EXPLÍCITO: "Inscríbase el presente pedido a nombre de <NOMBRE>" o
    #    "denominándola X a nombre de <NOMBRE>". NUNCA 'figura a nombre de', que en los
    #    cateos cita a los DUEÑOS de las parcelas colindantes (no al peticionante).
    if not mt:
        mt = re.search(r"(?:inscr[ií]base[^\n]{0,40}?|presente pedido\s+|denomin[áa]ndola[^\n]{0,30}?)"
                       r"a nombre de\s+(.{3,80}?)[.,]?\s*(?:public|inscr|c[ií]tese|\n|$)",
                       bloque, re.IGNORECASE | re.DOTALL)
    # 4) índice "<NOMBRE> s/ <acto>"
    if not mt:
        mt = re.search(r"(?:^|\n)\s*([A-ZÁÉÍÓÚÑ][^\n]{2,80}?)\s+s\s*/\s", bloque)
    if mt:
        p.titular = _limpiar_titular(mt.group(1))

    # nombre de la mina: "Mensura de la Mina AGU 5," -> "AGU 5"
    mm = re.search(r"\bmina\s+([A-ZÁÉÍÓÚÑ0-9][\w áéíóúñ.\-]{1,40}?)\s*,",
                   bloque, re.IGNORECASE)
    if mm:
        p.mina = re.sub(r"\s+", " ", mm.group(1)).strip(" ,.")

    # agrimensor / profesional actuante. RARO en SJ: el edicto de mensura es la
    # petición y no suele nombrar al profesional; se captura si aparece (p.ej. en
    # 'EDICTO DE DESIGNACIÓN' o 'practicará la mensura el Ing./Agrim. <nombre>').
    ma = re.search(
        r"(?:agrimensor|ing(?:\.|eniero)?\s*agrim\w*|profesional\s+actuante|"
        r"perito\s+agrimensor|practicar[áa]?\s+la\s+mensura\s+el\s+(?:ing\.?|agrim\.?)?|"
        r"design[ao]se?\s+(?:al\s+)?(?:agrimensor|ing\.?|perito))\s+(?:don\s+|d\.\s+)?"
        r"([A-ZÁÉÍÓÚÑ][A-Za-zÁÉÍÓÚÑáéíóúñ.\- ]{4,45}?)(?:[,.;]|\s+(?:aprob|para|Mat|CT|N[°º]))",
        bloque)
    if ma:
        p.agrimensor = _limpiar_titular(ma.group(1))

    # tipo de evento del derecho procesal minero (taxonomía)
    from . import eventos
    p.tipo_evento = eventos.clasificar(bloque)

    # confianza
    faltan = [not p.expediente, not p.vertices, not p.departamento]
    if sum(faltan) >= 2:
        p.confianza = "baja"
    elif any(faltan):
        p.confianza = "media"
    return p


def parsear_boletin(texto: str):
    """Devuelve la lista de Pedimentos mineros encontrados en el texto de un boletín."""
    resultados = []
    for bloque in trocear_avisos(texto):
        if es_minero(bloque):
            resultados.append(parsear_pedimento(bloque))
    return resultados


if __name__ == "__main__":
    # Edicto sintético con el formato típico para probar el parser de punta a punta.
    demo = """
    EDICTO
    El Juzgado Administrativo de Minas de la Provincia de San Juan hace saber que,
    MINERA ANDINA DEL SOL S.A., en Expte. N° 414-0123-2026, solicita permiso de
    exploración (cateo) para mineral de oro y plata de primera categoría, en el
    departamento de Iglesia, con una superficie de 3.500 hectáreas, según las
    siguientes coordenadas Gauss-Krüger POSGAR 2007:
    Vértice 1: X=6.650.000,00  Y=2.420.000,00
    Vértice 2: X=6.650.000,00  Y=2.430.000,00
    Vértice 3: X=6.640.000,00  Y=2.430.000,00
    Vértice 4: X=6.640.000,00  Y=2.420.000,00
    Publíquese. Fdo. El Juez Administrativo de Minas.

    EDICTO
    Se comunica licitación de obra pública vial sin relación con minería.

    EDICTO
    El Juzgado Administrativo de Minas hace saber que, JUAN PEREZ, en Expte.
    N° 414-0456-2026, manifiesta descubrimiento de mineral de cobre en el
    departamento de Calingasta, superficie 100 has. Coordenadas:
    Norte: 6.480.000,00 Este: 2.510.000,00
    """
    peds = parsear_boletin(demo)
    print(f"Pedimentos mineros detectados: {len(peds)}\n")
    for i, p in enumerate(peds, 1):
        print(f"--- Pedimento {i} (confianza: {p.confianza}) ---")
        print(f"  Expediente : {p.expediente}")
        print(f"  Titular    : {p.titular}")
        print(f"  Mineral    : {p.mineral}")
        print(f"  Depto      : {p.departamento}")
        print(f"  Superficie : {p.superficie_ha} ha")
        print(f"  Vértices   : {p.vertices}")
        print()
