@echo off
echo ========================================
echo   Configurando JARVIS 24h
echo ========================================
echo.

:: Desabilitar suspensão e hibernação
echo [1/4] Desabilitando suspensão...
powercfg /change standby-timeout-ac 0
powercfg /change hibernate-timeout-ac 0
powercfg /change monitor-timeout-ac 0
echo OK!

:: Criar tarefa agendada
echo [2/4] Criando tarefa agendada...
schtasks /create /tn "JARVIS 24h" /xml "jarvis_task.xml" /f
echo OK!

:: Criar atalho no startup
echo [3/4] Criando atalho no startup...
powershell -Command "$startupPath = [Environment]::GetFolderPath('Startup'); $WshShell = New-Object -ComObject WScript.Shell; $shortcut = $WshShell.CreateShortcut(\"$startupPath\JARVIS 24h.lnk\"); $shortcut.TargetPath = \"C:\Users\edson\Mark-XLVIII\autostart.bat\"; $shortcut.WorkingDirectory = \"C:\Users\edson\Mark-XLVIII\"; $shortcut.WindowStyle = 7; $shortcut.Save()"
echo OK!

:: Iniciar serviço agora
echo [4/4] Iniciando JARVIS...
echo.
echo ========================================
echo   JARVIS configurado para rodar 24/7!
echo   - Auto-start no login
echo   - Auto-restart se crashar
echo   - Suspensão desabilitada
echo ========================================
echo.
echo Iniciando JARVIS agora...
start /min python jarvis_service.py
echo JARVIS iniciado!
pause
