$envFile = ".env.s3"
if (-not (Test-Path $envFile)) {
    throw "Missing $envFile"
}

Get-Content $envFile | ForEach-Object {
    if (-not ($_ -match '^\s*#' -or $_ -match '^\s*$')) {
        $name, $value = $_ -split '=', 2
        if (-not [string]::IsNullOrWhiteSpace($name)) {
            Set-Item -Path "Env:$name" -Value $value
        }
    }
}

# Token-free integration for long-lived key/secret credentials.
Remove-Item Env:AWS_SESSION_TOKEN -ErrorAction SilentlyContinue

if (-not $env:PYTHONPATH) {
    $env:PYTHONPATH = "src"
}

Write-Output "Loaded .env.s3 (token-free mode)."
