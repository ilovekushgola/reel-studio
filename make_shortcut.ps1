$ErrorActionPreference = "Stop"
$root  = Join-Path $env:USERPROFILE "ig-reels-studio"
$lnk   = Join-Path ([Environment]::GetFolderPath("Desktop")) "Reel Studio.lnk"
$ws    = New-Object -ComObject WScript.Shell
$s     = $ws.CreateShortcut($lnk)
$s.TargetPath       = Join-Path $env:SystemRoot "System32\wscript.exe"
$s.Arguments        = '"' + (Join-Path $root "ReelStudio.vbs") + '"'
$s.WorkingDirectory = $root
$s.IconLocation     = (Join-Path $root "icon.ico")
$s.Description      = "Reel Studio - Instagram reel & profile scraper"
$s.WindowStyle      = 1
$s.Save()

# also drop one in the Start Menu so it shows up in search
$startDir = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
$s2 = $ws.CreateShortcut((Join-Path $startDir "Reel Studio.lnk"))
$s2.TargetPath       = $s.TargetPath
$s2.Arguments        = $s.Arguments
$s2.WorkingDirectory = $root
$s2.IconLocation     = $s.IconLocation
$s2.Description      = $s.Description
$s2.Save()

Write-Output ("desktop  : " + $lnk + "  exists=" + (Test-Path $lnk))
Write-Output ("startmenu: " + (Join-Path $startDir "Reel Studio.lnk") + "  exists=" + (Test-Path (Join-Path $startDir "Reel Studio.lnk")))
