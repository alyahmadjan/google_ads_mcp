@echo off
cd /d "E:\Sample Projects\google-ads-mcp"
call ".venv\Scripts\activate.bat"
REM stdout MUST stay clean for the MCP JSON-RPC stream to Claude Desktop.
REM Only stderr (logs/errors) is redirected to the log file for debugging.
python -u server.py 2>> mcp.log