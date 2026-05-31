$ErrorActionPreference = "Stop"

$project = "paga-smoke"
$apiKey = "smoke-api-key-at-least-24"
$profileSalt = "smoke-profile-salt-at-least-24"
$encryptionKey = "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA="
$port = "8899"

$env:COMPOSE_PROJECT_NAME = $project
$env:PAGA_API_KEY = $apiKey
$env:PAGA_PROFILE_SALT = $profileSalt
$env:PAGA_ENCRYPTION_KEY = $encryptionKey
$env:PAGA_PORT = $port

try {
    docker compose up --detach --build
    if ($LASTEXITCODE -ne 0) { throw "docker compose up failed" }

    $container = "$project-paga-eval-1"
    $healthy = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        $status = docker inspect --format "{{.State.Health.Status}}" $container 2>$null
        if ($status -eq "healthy") {
            $healthy = $true
            break
        }
        Start-Sleep -Seconds 2
    }
    if (-not $healthy) {
        docker logs $container
        throw "container did not become healthy"
    }

    $health = Invoke-RestMethod -Uri "http://127.0.0.1:$port/healthz"
    $ready = Invoke-RestMethod -Uri "http://127.0.0.1:$port/readyz"
    if ($health.status -ne "ok" -or $health.version -ne "0.4.0") {
        throw "unexpected health payload"
    }
    if ($ready.status -ne "ready") {
        throw "unexpected readiness payload"
    }

    Invoke-RestMethod `
        -Method Post `
        -Uri "http://127.0.0.1:$port/v1/evaluations" `
        -Headers @{"X-API-Key" = $apiKey; "X-Request-ID" = "trace-docker-smoke"} `
        -ContentType "application/json" `
        -Body '{"target":"rabbit","attempt":"wabbit","action":"accept","evaluation_id":"docker-smoke-eval"}' |
        Out-Null
    Start-Sleep -Seconds 1
    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $logs = (& docker logs $container 2>&1 | Out-String)
    $ErrorActionPreference = $previousErrorActionPreference
    if ($logs -notmatch '"request_id":"trace-docker-smoke"') {
        throw "correlated structured request log missing"
    }
    if ($logs -match "rabbit|wabbit|$apiKey") {
        throw "sensitive request data leaked into logs"
    }

    $uid = docker exec $container id -u
    if ($uid -ne "10001") {
        throw "container must run as uid 10001"
    }

    $maintenance = docker exec $container python -m paga.maintenance check | ConvertFrom-Json
    if ($maintenance.status -ne "ok") {
        throw "unexpected maintenance check payload"
    }
    Write-Output "docker smoke passed: health=$($health.status) ready=$($ready.status) uid=$uid maintenance=$($maintenance.status)"
}
finally {
    docker compose down --volumes
}
