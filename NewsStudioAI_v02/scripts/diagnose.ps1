$ErrorActionPreference = "Continue"
Write-Host "`n=== NEWS STUDIO AI / SYSTEM DIAGNOSTICS ===" -ForegroundColor Cyan
Write-Host "`n--- Operating System ---" -ForegroundColor Yellow
Get-CimInstance Win32_OperatingSystem | Select-Object Caption,Version,BuildNumber,OSArchitecture | Format-List
Write-Host "`n--- CPU ---" -ForegroundColor Yellow
Get-CimInstance Win32_Processor | Select-Object Name,NumberOfCores,NumberOfLogicalProcessors,MaxClockSpeed | Format-List
Write-Host "`n--- RAM ---" -ForegroundColor Yellow
Get-CimInstance Win32_ComputerSystem | Select-Object @{N="RAM_GB";E={[math]::Round($_.TotalPhysicalMemory/1GB,2)}} | Format-List
Write-Host "`n--- GPU ---" -ForegroundColor Yellow
Get-CimInstance Win32_VideoController | Select-Object Name,DriverVersion,@{N="VRAM_GB";E={if($_.AdapterRAM){[math]::Round($_.AdapterRAM/1GB,2)}else{"Unknown"}}} | Format-Table -AutoSize
Write-Host "`n--- Disks ---" -ForegroundColor Yellow
Get-PhysicalDisk -ErrorAction SilentlyContinue | Select-Object FriendlyName,MediaType,HealthStatus,Size | Format-Table -AutoSize
Write-Host "`n--- Free C: space ---" -ForegroundColor Yellow
Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='C:'" | Select-Object DeviceID,@{N="Free_GB";E={[math]::Round($_.FreeSpace/1GB,2)}} | Format-List
Write-Host "`n--- Developer tools ---" -ForegroundColor Yellow
foreach($n in @("python","git","node","npm","ffmpeg","ffprobe","iscc")){$c=Get-Command $n -ErrorAction SilentlyContinue;if($c){Write-Host "$n : $($c.Source)"}else{Write-Host "$n : NOT FOUND" -ForegroundColor DarkYellow}}
Write-Host "`n=== END DIAGNOSTICS ===" -ForegroundColor Cyan
