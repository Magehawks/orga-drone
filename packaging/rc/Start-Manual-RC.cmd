@echo off
setlocal
rem Dedicated RC data; never fall back to the normal user library.
set "ORGA_DRONE_DATA_DIR=%~dp0manual-test-data"
set "ORGA_DRONE_HOST=127.0.0.1"
set "ORGA_DRONE_PORT=0"
set "ORGA_DRONE_LANG=de"
set "ORGA_DRONE_BROWSER="
set "ORGA_DRONE_E2E="
set "ORGA_DRONE_CDP_PORT="
set "ORGA_DRONE_GEOCODE_PROBE="
pushd "%~dp0"
start "" /wait "%~dp0orga-drone\orga-drone.exe"
popd
endlocal
