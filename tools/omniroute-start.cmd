@echo off
rem OmniRoute local AI gateway (npm -g omniroute) — start as a background daemon on http://localhost:20128
rem   dashboard : http://localhost:20128            API : http://localhost:20128/v1
rem   stop      : omniroute stop                    logs: omniroute serve --log
where omniroute >nul 2>nul
if errorlevel 1 (
  echo omniroute CLI not found. Run: npm install -g omniroute
  exit /b 1
)
call omniroute serve --daemon --no-open %*
