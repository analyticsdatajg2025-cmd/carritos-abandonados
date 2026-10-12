@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo   Reporte diario Magento  -  JSON  -  FTP
echo ============================================
echo.
python reportes.py %*
echo.
if errorlevel 1 (
  echo *** Algo fallo. Lee el mensaje de arriba. ***
) else (
  echo *** Listo. Los JSON quedaron en la carpeta salida. ***
)
echo.
pause
