@echo off
REM Abre el visor del Boletin Minero en el navegador y levanta el servidor local.
REM Doble clic para usar. Cerrar esta ventana negra detiene el servidor.
cd /d "C:\Users\DAMS-04\OneDrive\Escritorio\Boletin Minero"
echo Iniciando servidor en http://localhost:8765/visor.html
echo (No cierres esta ventana mientras uses el visor)
start "" "http://localhost:8765/visor.html"
"C:\Users\DAMS-04\AppData\Local\Programs\Python\Python312\python.exe" -m http.server 8765
