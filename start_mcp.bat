@echo off
cd /d "E:\Sample Projects\google-ads-mcp"
call ".venv\Scripts\activate.bat"
python -u server.py >> mcp.log 2>&1