@echo off
rem Build __RK_PROJECT__ with MSVC (run from a Developer Command Prompt).
setlocal
cd /d "%~dp0"
if not exist build mkdir build
rc /nologo /I include /fo build\app.res src\app.rc || exit /b 1
cl /nologo /O2 /utf-8 /W4 /I include /Fo:build\ /Fe:build\__RK_PROJECT__.exe src\__RK_SNAKE__.c build\app.res || exit /b 1
