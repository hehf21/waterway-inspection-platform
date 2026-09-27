@echo off
chcp 65001 >nul
cd /d %~dp0
echo ============================================
echo  Waterway Transport Inspection Platform
echo  (ShuiLu YunShu JianCha PingTai)
echo ============================================
echo  URL    : http://127.0.0.1:8098
echo  Note   : first login forces password change.
echo           Keep data\secret.key with data\ backups.
echo  Deploy : set SLYS_HOST=0.0.0.0 for LAN access.
echo  Stop   : press Ctrl+C
echo ============================================
python app.py
pause
