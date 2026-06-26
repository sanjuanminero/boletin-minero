"""
Conversión de coordenadas para minería de San Juan.

San Juan está en la FAJA 2 de Gauss-Krüger (meridiano central -69°).
Los pedimentos mineros publican vértices en coordenadas planas X (Norte) / Y (Este),
donde el Este lleva el prefijo de faja: 2.5xx.xxx  ->  faja 2, false easting 2.500.000.

Datums posibles según la antigüedad del expediente:
  - Campo Inchauspe (Gauss-Krüger clásico)  -> mensuras viejas. EPSG:22182 (Faja 2)
  - POSGAR 94                               -> intermedio.       EPSG:22192 (Faja 2)
  - POSGAR 2007                             -> estándar actual,  EPSG:5344  (Faja 2)
    (OJO: 5345 es Faja 3. El Catastro Minero Digital de San Juan migró TODO a POSGAR 2007)

OJO con el datum: confundir Campo Inchauspe con POSGAR desplaza el punto ~100-200 m.
Si el edicto no aclara el datum, lo más seguro es asumir el que use el expediente
de esa época; ante la duda, POSGAR 2007 para lo nuevo, Campo Inchauspe para lo viejo.
"""

from pyproj import Transformer

# EPSG de cada datum en Faja 2 (Argentina faja 2 = meridiano central -69°)
EPSG_FAJA2 = {
    "campo_inchauspe": 22182,
    "posgar94": 22192,
    "posgar2007": 5344,
}

WGS84 = 4326

# Rangos plausibles para validar que un par (X,Y) es realmente GK Faja 2 en San Juan.
# Sirve para descartar números basura que el parser pesque por error.
RANGO_NORTE = (6_000_000, 7_200_000)   # X (Norte)
RANGO_ESTE = (2_300_000, 2_700_000)    # Y (Este), faja 2


def _transformer(datum: str) -> Transformer:
    epsg = EPSG_FAJA2.get(datum)
    if epsg is None:
        raise ValueError(f"Datum desconocido: {datum}. Use uno de {list(EPSG_FAJA2)}")
    # always_xy=True -> trabajamos en orden (Este, Norte) = (Y, X) de entrada proyectada
    return Transformer.from_crs(epsg, WGS84, always_xy=True)


def es_par_valido(norte: float, este: float) -> bool:
    """True si (Norte, Este) cae dentro de rangos plausibles de San Juan Faja 2."""
    return (RANGO_NORTE[0] <= norte <= RANGO_NORTE[1]
            and RANGO_ESTE[0] <= este <= RANGO_ESTE[1])


def gk_a_wgs84(norte: float, este: float, datum: str = "posgar2007"):
    """
    Convierte un vértice Gauss-Krüger Faja 2 (Norte=X, Este=Y) a (lat, lon) WGS84.
    Devuelve (lat, lon) en grados decimales.
    """
    tr = _transformer(datum)
    # proyectada usa (x=Este, y=Norte). always_xy => primero Este, después Norte.
    lon, lat = tr.transform(este, norte)
    return lat, lon


def wgs84_a_gk(lat: float, lon: float, datum: str = "posgar2007"):
    """Inverso: (lat, lon) WGS84 -> (Norte, Este) Gauss-Krüger Faja 2."""
    tr = Transformer.from_crs(WGS84, EPSG_FAJA2[datum], always_xy=True)
    este, norte = tr.transform(lon, lat)
    return norte, este


def poligono_a_wgs84(vertices, datum: str = "posgar2007"):
    """
    vertices: lista de (norte, este). Devuelve lista de (lon, lat) para GeoJSON
    (GeoJSON usa orden lon, lat) y además el centroide (lat, lon).
    """
    pts_lonlat = []
    for norte, este in vertices:
        lat, lon = gk_a_wgs84(norte, este, datum)
        pts_lonlat.append((lon, lat))
    n = len(pts_lonlat)
    cen_lon = sum(p[0] for p in pts_lonlat) / n
    cen_lat = sum(p[1] for p in pts_lonlat) / n
    return pts_lonlat, (cen_lat, cen_lon)


if __name__ == "__main__":
    # --- Punto de control: Ciudad de San Juan ~ (-31.5375, -68.5364) ---
    print("== Test ida y vuelta (Ciudad de San Juan) ==")
    lat0, lon0 = -31.5375, -68.5364
    for datum in EPSG_FAJA2:
        norte, este = wgs84_a_gk(lat0, lon0, datum)
        lat1, lon1 = gk_a_wgs84(norte, este, datum)
        print(f"{datum:16s} -> N={norte:12.2f}  E={este:12.2f}  "
              f"| vuelta lat={lat1:.6f} lon={lon1:.6f}  valido={es_par_valido(norte, este)}")

    # --- Diferencia de datum sobre un MISMO par de coordenadas planas ---
    # Si el mismo X,Y se interpreta con datums distintos, ¿cuánto se corre?
    print("\n== Mismo (N,E) interpretado con distintos datums ==")
    N, E = 6_510_000.0, 2_543_000.0
    ref = None
    for datum in EPSG_FAJA2:
        lat, lon = gk_a_wgs84(N, E, datum)
        print(f"{datum:16s} -> lat={lat:.6f} lon={lon:.6f}")
