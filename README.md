# Boletín Minero San Juan (v0)

Lee el Boletín Oficial de San Juan desde la óptica minera: detecta los edictos del
Juzgado Administrativo de Minas, extrae **coordenadas, titular, mineral, departamento
y superficie**, convierte las coordenadas **Gauss-Krüger Faja 2 → WGS84** y genera un
**GeoJSON** (para mapa/QGIS) y una **planilla Excel**. Pensado para correrse todos los días.

## Estado de esta v0
Ya funciona y está probado en este repo:
- ✅ `bsj/coords.py` — conversión GK/POSGAR Faja 2 ↔ WGS84 (Campo Inchauspe, POSGAR 94, POSGAR 2007). Verificado con punto de control de la Ciudad de San Juan.
- ✅ `bsj/parser.py` — detección de avisos mineros + extracción de campos y vértices (maneja el formato de número argentino `6.511.304,01`).
- ✅ `bsj/outputs.py` — GeoJSON + XLSX.
- ✅ `bsj/pipeline.py` — orquesta todo a partir de un PDF.
- ✅ `bsj/boletin.py` — descarga + **diagnóstico texto vs escaneado** (clave).
- ✅ `bsj/catastro.py` — cliente ArcGIS REST del Catastro Minero Digital.

Falta confirmar **en tu red** (este sandbox no llega a los servidores de San Juan):
1. El **endpoint real del Boletín** (la web es una SPA; ver instrucciones en `boletin.py`).
2. Si los PDF del boletín son **texto o escaneados** → corré `python -m bsj.boletin <pdf>`.
3. La **URL de la capa** del catastro ArcGIS (ver `catastro.py`).

## Instalación
```bash
pip install -r requirements.txt
```

## Uso rápido
```bash
# 1) Diagnóstico de un boletín bajado a mano (define si hace falta OCR)
python -m bsj.boletin /ruta/boletin_2026-06-23.pdf

# 2) Pipeline completo sobre ese PDF
python -m bsj.pipeline /ruta/boletin_2026-06-23.pdf --datum posgar2007 --salida ./out

# 3) Catastro: descubrir capas y luego consultar por titular
python -m bsj.catastro
```

## Las dos fuentes (y por qué se usan juntas)
- **Boletín Oficial** = feed diario de novedades: dónde aparecen los pedimentos nuevos.
- **Catastro Minero Digital (ArcGIS)** = geometría y atributos autoritativos, ya en
  POSGAR 2007. Se cruza con el boletín por nº de expediente o titular.

## Nota sobre el datum (importante)
San Juan = **Faja 2** (meridiano central −69°). Mensuras viejas suelen estar en
**Campo Inchauspe**; lo nuevo en **POSGAR 2007**. Elegir mal el datum corre el punto
~100–200 m. Si el edicto no lo aclara, usar el criterio por época y verificar contra
el catastro.

## Próximos pasos sugeridos
- Conectar el endpoint del boletín y automatizar (cron / Tarea programada / GitHub Actions diario).
- Cruce automático boletín ↔ catastro por expediente.
- Lista de "titulares vigilados" con alerta por mail cuando aparezca uno.
- Acumular en una sola planilla histórica + capa única para QGIS.
