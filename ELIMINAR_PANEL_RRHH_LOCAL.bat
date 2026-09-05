@echo off
cd /d "%~dp0"
if exist "static\cumpleanos-rrhh.html" del /q "static\cumpleanos-rrhh.html"
if exist "static\cumpleanos-rrhh.js" del /q "static\cumpleanos-rrhh.js"
echo Panel RR.HH. local eliminado. El acceso ahora apunta al portal externo.
pause
