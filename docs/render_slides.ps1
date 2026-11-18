# Render each slide of the deck to PNG using the installed PowerPoint (for visual QA).
param([string]$Deck, [string]$OutDir)
$ppt = New-Object -ComObject PowerPoint.Application
$pres = $ppt.Presentations.Open($Deck, $true, $false, $false)
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$i = 1
foreach ($s in $pres.Slides) {
    $s.Export((Join-Path $OutDir ("slide-$i.png")), "PNG", 1600, 900)
    $i++
}
$pres.Close()
$ppt.Quit()
