"""
Cliente del Catastro Minero Digital de San Juan — GeoServer OGC (WFS / WMS).

Servicios:
  WFS: https://catastrominero.sanjuan.gob.ar/geoserver/wfs   (geometrías + atributos)
  WMS: https://catastrominero.sanjuan.gob.ar/geoserver/wms   (imágenes para overlay)

Todas las capas están en EPSG:5344 (POSGAR 2007 Faja 2), el mismo datum que usa el
pipeline para 2026. El catastro es la fuente AUTORITATIVA de la geometría y los
atributos limpios (titular, expediente, mineral, nombre de mina, superficie); el
boletín aporta la línea de tiempo de eventos. Se cruzan por nº de expediente /
titular / nombre de mina.

Capas (typeName -> qué es), totales aprox. observados:
  vw_minas_padron             Minas (1378)           — denominacion, titular, minerales,
                                                       tipoYacimiento, sup_reg_ha, expediente,
                                                       cantidadPertenencias, fechas de mensura
  vw_manifestaciones_padron   Manif. descubrimiento (1256) — idem minas
  vw_permisos_exploracion     Permisos de exploración / cateos (1116) — expte_siged, sup_reg_ha
  vw_canteras                 Canteras 3ra categoría (306) — denominacion, expte_siged
  vw_solicitudes_poligonos    Solicitudes (223)
  vw_servidumbres_poligonos   Servidumbres polígono (97) — tipo_de_servidumbre, expte_siged
  vw_servidumbres_lineas      Servidumbres línea
  vw_proyectosmineros         Proyectos mineros
  vw_limite_provincial_dgc    Límite provincial
"""

import os
import json
import requests

BASE = "https://catastrominero.sanjuan.gob.ar/geoserver"
WFS = BASE + "/wfs"
WMS = BASE + "/wms"
UA = {"User-Agent": "Mozilla/5.0 (boletin-minero; investigacion)"}
TIMEOUT = 120

# clave lógica -> (typeName, etiqueta)
CAPAS = {
    "minas":            ("mineria:vw_minas_padron",           "Minas"),
    "manifestaciones":  ("mineria:vw_manifestaciones_padron", "Manifestaciones de descubrimiento"),
    "permisos":         ("mineria:vw_permisos_exploracion",   "Permisos de exploración (cateos)"),
    "canteras":         ("mineria:vw_canteras",               "Canteras"),
    "solicitudes":      ("mineria:vw_solicitudes_poligonos",  "Solicitudes"),
    "servidumbres":     ("mineria:vw_servidumbres_poligonos", "Servidumbres (polígono)"),
    "servidumbres_lin": ("mineria:vw_servidumbres_lineas",    "Servidumbres (línea)"),
    "proyectos":        ("mineria:vw_proyectosmineros",       "Proyectos mineros"),
    "limite":           ("mineria:vw_limite_provincial_dgc",  "Límite provincial"),
}


def _get(url, **params):
    last = None
    for verify in (True, False):
        try:
            r = requests.get(url, params=params, headers=UA, timeout=TIMEOUT, verify=verify)
            r.raise_for_status()
            return r
        except requests.exceptions.SSLError as e:
            last = e
            continue
    raise last


def wfs_geojson(typeName, srs="EPSG:4326", count=None, bbox=None, cql=None):
    """Trae features de una capa como GeoJSON (por defecto reproyectado a EPSG:4326,
    listo para Leaflet). `cql`: filtro CQL (ej. "titular ILIKE '%PACHON%'")."""
    params = {
        "service": "WFS", "version": "2.0.0", "request": "GetFeature",
        "typeNames": typeName, "outputFormat": "application/json", "srsName": srs,
    }
    if count:
        params["count"] = count
    if bbox:
        params["bbox"] = bbox
    if cql:
        params["cql_filter"] = cql
    return _get(WFS, **params).json()


def buscar(clave_capa, cql, srs="EPSG:4326", count=50):
    """Busca en una capa por filtro CQL. Ej.: buscar('minas', "titular ILIKE '%GLENCORE%'")."""
    typeName = CAPAS[clave_capa][0]
    return wfs_geojson(typeName, srs=srs, count=count, cql=cql)


def descargar_padron(carpeta, claves=None, srs="EPSG:4326"):
    """Baja capas del catastro como GeoJSON a `carpeta` (para el visor / QGIS)."""
    os.makedirs(carpeta, exist_ok=True)
    claves = claves or list(CAPAS)
    res = {}
    for k in claves:
        typeName, label = CAPAS[k]
        try:
            gj = wfs_geojson(typeName, srs=srs)
            n = len(gj.get("features", []))
            with open(os.path.join(carpeta, f"catastro_{k}.geojson"), "w", encoding="utf-8") as f:
                json.dump(gj, f, ensure_ascii=False)
            res[k] = n
            print(f"  {k:18s} {n:5d} features  ({label})")
        except Exception as e:
            res[k] = f"ERROR {e}"
            print(f"  {k:18s} ERROR {e}")
    return res


def wms_layer_url():
    """URL base WMS para usar como L.tileLayer.wms en Leaflet."""
    return WMS


if __name__ == "__main__":
    print("Capas del catastro (WFS):")
    cap = _get(WFS, service="WFS", version="2.0.0", request="GetCapabilities")
    import re
    for b in re.findall(r"<FeatureType[ >].*?</FeatureType>", cap.text, re.S):
        nm = re.search(r"<Name>(.*?)</Name>", b)
        ti = re.search(r"<Title>(.*?)</Title>", b)
        print(f"  - {nm.group(1) if nm else '?':42s} {ti.group(1).strip() if ti else ''}")
