@echo off
rem codebase-memory-mcp stdio wrapper for this project.
rem v0.10.8 rejects a session whose working directory contains non-ASCII characters
rem (this project folder is Korean), so start the server from an ASCII directory.
rem The project itself is reachable through the ASCII junction C:\Users\zxaswe\Desktop\fibmtf.
cd /d "%USERPROFILE%"
"%LOCALAPPDATA%\Programs\codebase-memory-mcp\codebase-memory-mcp.exe" %*
