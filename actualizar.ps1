# Actualización diaria del Boletín Minero San Juan.
# Encadena: escanear -> reproyectar (limpieza geom) -> padrón catastro -> cruce.
# Pensado para correr desde el Programador de tareas de Windows.
# Las cachés de PDF y OCR (out_<año>/pdf, /ocr) hacen que el re-escaneo diario sea
# incremental: solo OCR-ea las ediciones nuevas.

$ErrorActionPreference = 'Continue'
$proj = 'C:\Users\DAMS-04\OneDrive\Escritorio\Boletin Minero'
$py   = 'C:\Users\DAMS-04\AppData\Local\Programs\Python\Python312\python.exe'
Set-Location $proj

$desde = '2024-01-01'        # base histórica unificada (2024 -> hoy)
$hoy   = (Get-Date -Format 'yyyy-MM-dd')
$out   = './out_hist'

$logdir = Join-Path $proj 'logs'
New-Item -ItemType Directory -Force $logdir | Out-Null
$log = Join-Path $logdir ("actualizar_{0}.log" -f (Get-Date -Format 'yyyy-MM-dd_HHmmss'))

function Log($m) {
  $line = "{0}  {1}" -f (Get-Date -Format 'HH:mm:ss'), $m
  Write-Output $line
  Add-Content -Path $log -Value $line -Encoding utf8
}

Log "=== Actualización Boletín Minero ($desde -> $hoy) ==="

Log "1/4 escanear (descarga + OCR incremental + modelo)..."
& $py escanear.py $desde $hoy --salida $out --datum posgar2007 *>> $log

Log "2/4 reproyectar + limpieza de geometría (POSGAR 2007)..."
& $py reproyectar.py $out --datum posgar2007 *>> $log

Log "3/4 padrón del catastro (best-effort; si falla, se conserva el anterior)..."
& $py -c "from bsj import catastro; catastro.descargar_padron('$out/catastro')" *>> $log

Log "4/4 cruce boletín <-> catastro..."
& $py -m bsj.cruce $out *>> $log

Log "=== Fin. Modelo: $out/modelo.json ==="
