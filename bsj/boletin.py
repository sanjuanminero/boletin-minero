"""
Acceso al Boletín Oficial de San Juan + diagnóstico del PDF.

DESCUBRIMIENTO (jun-2026): la web pública boletinoficial.sanjuan.gob.ar es una SPA,
pero el MISMO contenido se publica en el portal de transparencia Joomla/K2:

    https://contenido.sanjuan.gob.ar/  (categoría id=48 = "Boletín Oficial")

Ese portal SÍ entrega HTML plano y el PDF por HTTP directo. No hace falta Selenium.
Flujo: listar la categoría -> cada item -> link de descarga del PDF.

HALLAZGO IMPORTANTE sobre los PDF:
  La capa de texto del PDF trae SOLO el índice, los títulos de sección y las
  referencias de cobro (N° de aviso / Cta. Cte. / importe). El CUERPO de cada
  edicto está pegado como IMAGEN escaneada (el organismo pide "soporte informático
  y además el original"). => Para leer el contenido de los edictos de minas
  (titular, mineral, coordenadas) HACE FALTA OCR. Los títulos de sección, en cambio,
  son texto nativo, así que se puede detectar QUÉ DÍAS hubo "EDICTOS DE MINAS"
  sin OCR (triage), y reservar el OCR para esas páginas.
"""

import os
import re
import html as _html
import requests
import fitz  # PyMuPDF

BASE = "https://contenido.sanjuan.gob.ar"
CAT_ID = 48  # categoría "Boletín Oficial"
UA = {"User-Agent": "Mozilla/5.0 (investigacion-mineria; contacto@ejemplo.com)"}
TIMEOUT = 90

# El portal K2 entrega HTML (no Markdown). Se hace html.unescape() antes de matchear,
# así los enlaces quedan con '&' en vez de '&amp;'.
# Item: ...id=10705:boletin-oficial-de-24-06-2026&Itemid=148  (fecha dd-mm-yyyy en el slug;
# OJO: hay slugs con typo, p.ej. 'boletin-oficil-de-...', por eso el slug se matchea laxo).
_RX_ITEM = re.compile(
    r"option=com_k2&view=item&id=(\d+):[a-z0-9\-]*?(\d{2})-(\d{2})-(\d{4})",
    re.IGNORECASE)
# Descarga: href="/index.php?...task=download&id=10958_<hash>&Itemid=148"
_RX_PDF = re.compile(
    r'href="(/index\.php\?option=com_k2&view=item&task=download&id=[^"]+)"',
    re.IGNORECASE)
# Nombre de archivo (para contar páginas): (06)_(JUNIO)_24-06-2026__(P._80_Internet.pdf
_RX_NOMBRE = re.compile(r"([^\s\"'>]+\.pdf)", re.IGNORECASE)
_RX_PAGS = re.compile(r"\(P\.?_?(\d+)", re.IGNORECASE)


def _get(url):
    r = requests.get(url, headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    return r.text


def listar_ediciones(desde=None, hasta=None, max_paginas=200):
    """
    Lista ediciones del Boletín. desde/hasta: 'YYYY-MM-DD' (inclusive) para filtrar.
    Devuelve [{'fecha':'YYYY-MM-DD','item_url':..,'item_id':..}], más nuevas primero.
    Pagina la categoría K2 (12 por página) con limitstart.
    """
    out, seen = [], set()
    for p in range(max_paginas):
        url = (f"{BASE}/index.php?option=com_k2&view=itemlist&task=category"
               f"&id={CAT_ID}&Itemid=148&limitstart={p*12}")
        html = _html.unescape(_get(url))
        encontrados = _RX_ITEM.findall(html)
        if not encontrados:
            break
        seguir = True
        for iid, d, m, y in encontrados:
            fecha = f"{y}-{int(m):02d}-{int(d):02d}"
            if iid in seen:
                continue
            seen.add(iid)
            if desde and fecha < desde:
                seguir = False
                continue
            if hasta and fecha > hasta:
                continue
            item_url = (f"{BASE}/index.php?option=com_k2&view=item"
                        f"&id={iid}&Itemid=148")
            out.append({"fecha": fecha, "item_url": item_url, "item_id": iid})
        if desde and not seguir:
            break
    out.sort(key=lambda x: x["fecha"], reverse=True)
    return out


def link_descarga(item_url):
    """Dada la URL del item, devuelve (url_pdf, nombre_archivo, n_paginas|None)."""
    html = _html.unescape(_get(item_url))
    m = _RX_PDF.search(html)
    if not m:
        return None, None, None
    url = m.group(1)
    if url.startswith("/"):
        url = BASE + url
    nm = _RX_NOMBRE.search(html)
    nombre = nm.group(1) if nm else None
    pags = _RX_PAGS.search(nombre) if nombre else None
    return url, nombre, int(pags.group(1)) if pags else None


def bajar_pdf(url_pdf, destino):
    r = requests.get(url_pdf, headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    with open(destino, "wb") as f:
        f.write(r.content)
    return destino


# ---------- diagnóstico / extracción ----------
def diagnosticar_pdf(ruta):
    doc = fitz.open(ruta)
    n = doc.page_count
    total_chars = paginas_con_imagen = 0
    muestra = min(n, 12)
    for i in range(muestra):
        pg = doc[i]
        total_chars += len(pg.get_text("text").strip())
        if pg.get_images():
            paginas_con_imagen += 1
    doc.close()
    cpp = total_chars / max(muestra, 1)
    if cpp > 1500:
        veredicto = "TEXTO_NATIVO"
    elif paginas_con_imagen >= muestra * 0.6:
        veredicto = "ESCANEADO"      # cuerpo en imágenes -> OCR
    else:
        veredicto = "MIXTO"
    return {"paginas": n, "chars_por_pagina_prom": round(cpp, 1),
            "paginas_con_imagen": paginas_con_imagen, "veredicto": veredicto}


def extraer_texto(ruta):
    doc = fitz.open(ruta)
    txt = "\n".join(pg.get_text("text") for pg in doc)
    doc.close()
    return txt


def _tesseract_cmd():
    """Ubica tesseract.exe: PATH o instalaciones típicas en Windows."""
    import shutil
    cmd = shutil.which("tesseract")
    if cmd:
        return cmd
    for c in (r"C:\Program Files\Tesseract-OCR\tesseract.exe",
              r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"):
        if os.path.exists(c):
            return c
    return None


def _tessdata_dir():
    """Carpeta tessdata que contenga spa.traineddata. Prioriza la local del proyecto
    (raíz del repo / cwd) para no depender de permisos de Program Files."""
    candidatos = [
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "tessdata"),
        os.path.join(os.getcwd(), "tessdata"),
    ]
    for d in candidatos:
        if os.path.exists(os.path.join(d, "spa.traineddata")):
            return d
    return None


def extraer_texto_ocr(ruta, dpi=300, idioma="spa", solo_paginas=None):
    """
    OCR del cuerpo escaneado. Rasteriza con PyMuPDF (sin poppler) y OCR-ea con
    tesseract. Requiere: pip install pytesseract Pillow + binario tesseract
    + spa.traineddata (carpeta ./tessdata o en la instalación de tesseract).
    solo_paginas: lista de índices (0-based) para OCR-ear solo las páginas de minas.
    """
    import io
    import pytesseract
    from PIL import Image

    cmd = _tesseract_cmd()
    if cmd:
        pytesseract.pytesseract.tesseract_cmd = cmd
    # Vía TESSDATA_PREFIX (no por --tessdata-dir: pytesseract parte el config por
    # espacios y rompería rutas con espacios como 'Boletin Minero').
    td = _tessdata_dir()
    if td:
        os.environ["TESSDATA_PREFIX"] = td

    doc = fitz.open(ruta)
    indices = list(solo_paginas) if solo_paginas else list(range(doc.page_count))
    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)
    partes = []
    for i in indices:
        pix = doc[i].get_pixmap(matrix=mat)
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        partes.append(pytesseract.image_to_string(img, lang=idioma))
    doc.close()
    return "\n".join(partes)


# ---------- detección de la sección de minas ----------
def _norm(s):
    """Mayúsculas sin NINGÚN espacio: los títulos del boletín vienen con espaciado
    entre letras ('E D I C TO S  DE MINAS'), así que se colapsa todo para matchear."""
    return re.sub(r"\s+", "", s.upper())


# vocabulario minero fuerte para el formato VIEJO (2020-2023), que no usa el título
# de sección 'EDICTOS DE MINAS'. En 2020 los edictos son texto nativo.
_SENALES_MINERAS = ("JUZGADOADMINISTRATIVODEMINAS", "ESCRIBANIADEMINAS",
                    "DIRECTORDEMINERIA", "DIRECCIONDEMINERIA", "GAUSSKRUGER",
                    "MANIFESTACIONDEDESCUBRIMIENTO", "PERTENENCIA", "LABORLEGAL")


def tiene_edictos_de_minas(texto):
    """True si hay contenido minero. Primero por el título 'EDICTOS DE MINAS'
    (formato 2024+); si no, por vocabulario minero fuerte (formato viejo 2020-2023).
    OJO: 'Ministro de Minería' aparece SIEMPRE en el encabezado; no cuenta."""
    t = _norm(texto)
    if "EDICTOSDEMINAS" in t:
        return True
    if any(s in t for s in _SENALES_MINERAS):
        return True
    return ("MENSURA" in t or "CATEO" in t) and ("VERTICE" in t or "COORDENADAS" in t)


def paginas_de_minas(ruta):
    """Índices (0-based) de las páginas cuyo texto cae bajo 'EDICTOS DE MINAS'
    y hasta el próximo título de sección. Útil para OCR-ear solo esas páginas."""
    doc = fitz.open(ruta)
    secciones = ("NOTIFICACIONES", "RESOLUCIONES", "LICITACIONES", "ORDENANZAS",
                 "CONVOCATORIAS", "EDICTOSJUDICIALES", "REMATES", "RAZONSOCIAL",
                 "USUCAPION", "USUCAPIÓN", "SUCESORIOS", "LEYES",
                 "DECRETOS", "RECAUDACION")
    secciones = tuple(_norm(s) for s in secciones)
    en_minas, por_titulo = False, []
    for i in range(doc.page_count):
        t = _norm(doc[i].get_text("text"))
        if "EDICTOSDEMINAS" in t:
            en_minas = True
        elif en_minas and any(s in t for s in secciones):
            en_minas = False
        if en_minas:
            por_titulo.append(i)
    if por_titulo:                       # formato 2024+ (título de sección)
        doc.close()
        return por_titulo
    # formato viejo (2020-2023): páginas con vocabulario minero fuerte
    por_kw = [i for i in range(doc.page_count)
              if any(s in _norm(doc[i].get_text("text")) for s in _SENALES_MINERAS)]
    doc.close()
    return por_kw


def esta_escaneado(texto, n_paginas):
    """True si el PDF es (casi) todo imagen: capa de texto pobre. Los boletines
    de 2021 son así (sin capa de texto útil para detectar la sección de minas)."""
    return len((texto or "").strip()) < max(1, n_paginas) * 400


def minas_por_ocr(ruta, dpi=220, idioma="spa"):
    """Para boletines ESCANEADOS sin capa de texto (2021): OCR-ea todas las páginas
    y devuelve el texto de las que tienen vocabulario minero. Caro: usar solo cuando
    la detección por capa de texto falla. Devuelve '' si no hay minería."""
    import io
    import pytesseract
    from PIL import Image
    cmd = _tesseract_cmd()
    if cmd:
        pytesseract.pytesseract.tesseract_cmd = cmd
    td = _tessdata_dir()
    if td:
        os.environ["TESSDATA_PREFIX"] = td
    # MINERO-ESPECÍFICO: en 2021 abundan las mensuras CIVILES (usucapión), que NO son
    # mineras. Se exige vocabulario propio de minería para no meter falsos positivos.
    claves = ("gauss", "posgar", "pertenencia", "escribania de minas",
              "juzgado administrativo de minas", "director de mineria",
              "manifestacion de descubrimiento", "labor legal")
    doc = fitz.open(ruta)
    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)
    partes = []
    for i in range(doc.page_count):
        pix = doc[i].get_pixmap(matrix=mat)
        t = pytesseract.image_to_string(Image.open(io.BytesIO(pix.tobytes("png"))), lang=idioma)
        tl = t.lower()
        if any(k in tl for k in claves):
            partes.append(t)
    doc.close()
    return "\n".join(partes)


def texto_de_paginas(ruta, paginas, umbral=1200):
    """Texto de las páginas dadas: usa la CAPA DE TEXTO nativa si es sustancial
    (boletines viejos con edictos en texto), si no OCR-ea (escaneados). Así 2020
    se lee directo del texto y 2024+ por OCR."""
    if not paginas:
        return ""
    doc = fitz.open(ruta)
    nativo = sum(1 for i in paginas if len((doc[i].get_text("text") or "").strip()) > umbral)
    if nativo >= len(paginas) * 0.5:
        txt = "\n".join(doc[i].get_text("text") for i in paginas)
        doc.close()
        return txt
    doc.close()
    return extraer_texto_ocr(ruta, solo_paginas=paginas)


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1].endswith(".pdf"):
        info = diagnosticar_pdf(sys.argv[1])
        print("Diagnóstico:", info)
        print("¿Sección de minas?:", tiene_edictos_de_minas(extraer_texto(sys.argv[1])))
        print("Páginas de minas:", paginas_de_minas(sys.argv[1]))
    else:
        print("Listando ediciones de junio 2026...")
        for e in listar_ediciones(desde="2026-06-01", hasta="2026-06-30"):
            url, nombre, pags = link_descarga(e["item_url"])
            print(f"  {e['fecha']}  ({pags}p)  {url}")
