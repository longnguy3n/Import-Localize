$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
py -m pip install -r requirements.txt
py .\src\main.py
