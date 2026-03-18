param(
    [string]$InputDir = "docs/diagrams",
    [string]$JarPath = ""
)

$ErrorActionPreference = "Stop"

function Resolve-PlantUmlJar {
    param([string]$Preferred)

    if ($Preferred -and (Test-Path $Preferred)) {
        return (Resolve-Path $Preferred).Path
    }

    if ($env:PLANTUML_JAR -and (Test-Path $env:PLANTUML_JAR)) {
        return (Resolve-Path $env:PLANTUML_JAR).Path
    }

    $candidates = @(
        "$env:USERPROFILE\.vscode\extensions\jebbs.plantuml-2.18.1\plantuml.jar",
        "$env:USERPROFILE\.vscode\extensions\jebbs.plantuml-2.18.0\plantuml.jar"
    )
    foreach ($item in $candidates) {
        if (Test-Path $item) {
            return (Resolve-Path $item).Path
        }
    }

    $search = Get-ChildItem "$env:USERPROFILE\.vscode\extensions" -Recurse -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -eq "plantuml.jar" } |
        Select-Object -First 1
    if ($search) {
        return $search.FullName
    }

    throw "plantuml.jar not found. Install VSCode extension jebbs.plantuml or pass -JarPath."
}

$jar = Resolve-PlantUmlJar -Preferred $JarPath
$absInputDir = (Resolve-Path $InputDir).Path

$files = Get-ChildItem $absInputDir -Filter *.puml
if (-not $files) {
    throw "No .puml files found in: $absInputDir"
}

Write-Host "PlantUML JAR: $jar"
Write-Host "Input dir: $absInputDir"

& java -jar $jar -charset UTF-8 -tpng -Sdpi=300 "$absInputDir\*.puml"

Write-Host "Done."
