$ErrorActionPreference='Stop'
$root=(Resolve-Path(Join-Path $PSScriptRoot '..')).Path
$testRoot=Join-Path ([IO.Path]::GetTempPath()) ('codex-provider-bridge-test-'+[Guid]::NewGuid().ToString('N'))
try {
    $providerHome=Join-Path $testRoot 'provider-home'
    $gptHome=Join-Path $testRoot 'gpt-home'
    $bin=Join-Path $testRoot 'bin'
    $broker=Join-Path $testRoot 'broker'
    $project=Join-Path $testRoot 'sample-project'
    New-Item -ItemType Directory -Path $gptHome,$project -Force|Out-Null

    & (Join-Path $root 'setup.ps1') -Action Install -ProviderCodexHome $providerHome -GptCodexHome $gptHome -InstallBin $bin -BrokerRoot $broker -CommandName test-codex-provider -SkipPathUpdate | Out-Null
    $refreshHelper=Join-Path $bin 'test-codex-provider-refresh-model-catalog.ps1'
    foreach($path in @((Join-Path $providerHome 'config.toml'),(Join-Path $providerHome 'models_cache.json'),(Join-Path $bin 'test-codex-provider.cmd'),$refreshHelper)){if(-not(Test-Path $path -PathType Leaf)){throw "Install output missing: $path"}}
    $launcherText=Get-Content -Raw (Join-Path $bin 'test-codex-provider.cmd')
    if($launcherText -notmatch '(?m)^call codex'){throw 'Launcher must preserve the isolated provider home with CALL.'}
    if($launcherText -match 'approve-for-me|ask-for-approval'){throw 'Launcher must leave approval behavior to the active Codex permissions profile.'}
    if($launcherText -notmatch 'model_context_window=1000000' -or $launcherText -notmatch 'model_auto_compact_token_limit=900000'){throw 'Launcher context overrides are missing.'}
    $configText=Get-Content -Raw (Join-Path $providerHome 'config.toml')
    if($configText -match 'approvals_reviewer|approval_policy'){throw 'Config must not override Codex approval behavior.'}
    if($configText -notmatch 'model_context_window = 1000000' -or $configText -notmatch 'model_auto_compact_token_limit = 900000'){throw 'Config context settings are missing.'}
    $catalogPath=Join-Path $providerHome 'models_cache.json'
    $catalog=Get-Content -Raw $catalogPath|ConvertFrom-Json
    if(@($catalog.models|Where-Object{$_.auto_review_model_override -eq 'deepseek-flash'}).Count-ne2){throw 'Catalog reviewer override is missing.'}
    $catalog.fetched_at='2000-01-01T00:00:00.0000000Z'
    [IO.File]::WriteAllText($catalogPath,($catalog|ConvertTo-Json -Depth 20),(New-Object Text.UTF8Encoding($false)))
    & $refreshHelper -CachePath $catalogPath
    $refreshed=Get-Content -Raw $catalogPath|ConvertFrom-Json
    if(([DateTime]::UtcNow-[DateTime]::Parse($refreshed.fetched_at)).TotalMinutes-ge1){throw 'Catalog TTL refresh helper failed.'}

    $testResult=& (Join-Path $root 'setup.ps1') -Action Test -ProviderCodexHome $providerHome -InstallBin $bin -CommandName test-codex-provider|ConvertFrom-Json
    if(-not$testResult.codex_present-or-not$testResult.provider_home-or-not$testResult.launcher){throw 'Installation validation failed.'}

    & (Join-Path $root 'setup.ps1') -Action RegisterProject -ProviderCodexHome $providerHome -GptCodexHome $gptHome -InstallBin $bin -BrokerRoot $broker -ProjectRoot $project -ProjectId sample-project -DeliveryPolicy staging|Out-Null
    $request=[ordered]@{project_id='sample-project';task_id='validation-only';operation='generate';prompt='Create a safe original diagnostic background.';reference_images=@();output_directory='Saved/AI_Temp/DelegatedImages/validation-only';max_images=1}
    $requestPath=Join-Path $project 'image-request.json';[IO.File]::WriteAllText($requestPath,($request|ConvertTo-Json),(New-Object Text.UTF8Encoding($false)))
    $validation=& (Join-Path $broker 'codex-image.ps1') -RequestPath $requestPath -ValidateOnly|ConvertFrom-Json
    if($validation.status-ne'validated'-or$validation.project_id-ne'sample-project'){throw 'Broker validation failed.'}

    [ordered]@{status='passed';install=$true;catalog=$true;catalog_ttl_refresh=$true;reviewer_model_override=$true;permissions_preserved=$true;context_pinned=$true;project_registration=$true;broker_validation=$true}|ConvertTo-Json
}
finally {
    if(Test-Path -LiteralPath $testRoot){Remove-Item -LiteralPath $testRoot -Recurse -Force}
}
