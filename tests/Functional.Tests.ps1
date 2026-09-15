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
    foreach($path in @((Join-Path $providerHome 'config.toml'),(Join-Path $providerHome 'models_cache.json'),(Join-Path $bin 'test-codex-provider.cmd'))){if(-not(Test-Path $path -PathType Leaf)){throw "Install output missing: $path"}}
    $launcherText=Get-Content -Raw (Join-Path $bin 'test-codex-provider.cmd')
    if($launcherText -notmatch 'call codex'){throw 'Launcher does not preserve batch environment with CALL.'}
    if($launcherText -match 'approve-for-me|ask-for-approval'){throw 'Launcher must leave approval behavior to the active Codex permissions profile.'}
    if($launcherText -notmatch 'model_context_window=1000000' -or $launcherText -notmatch 'model_auto_compact_token_limit=900000'){throw 'Launcher context overrides are missing.'}
    $configText=Get-Content -Raw (Join-Path $providerHome 'config.toml')
    if($configText -match 'approvals_reviewer|approval_policy'){throw 'Config must not override Codex approval behavior.'}
    if($configText -notmatch 'model_context_window = 1000000' -or $configText -notmatch 'model_auto_compact_token_limit = 900000'){throw 'Config context settings are missing.'}

    $testResult=& (Join-Path $root 'setup.ps1') -Action Test -ProviderCodexHome $providerHome -InstallBin $bin -CommandName test-codex-provider|ConvertFrom-Json
    if(-not$testResult.codex_present-or-not$testResult.provider_home-or-not$testResult.launcher){throw 'Installation validation failed.'}

    & (Join-Path $root 'setup.ps1') -Action RegisterProject -ProviderCodexHome $providerHome -GptCodexHome $gptHome -InstallBin $bin -BrokerRoot $broker -ProjectRoot $project -ProjectId sample-project -DeliveryPolicy staging|Out-Null
    $request=[ordered]@{project_id='sample-project';task_id='validation-only';operation='generate';prompt='Create a safe original diagnostic background.';reference_images=@();output_directory='Saved/AI_Temp/DelegatedImages/validation-only';max_images=1}
    $requestPath=Join-Path $project 'image-request.json';[IO.File]::WriteAllText($requestPath,($request|ConvertTo-Json),(New-Object Text.UTF8Encoding($false)))
    $validation=& (Join-Path $broker 'codex-image.ps1') -RequestPath $requestPath -ValidateOnly|ConvertFrom-Json
    if($validation.status-ne'validated'-or$validation.project_id-ne'sample-project'){throw 'Broker validation failed.'}

    [ordered]@{status='passed';install=$true;catalog=$true;launcher_call_fix=$true;permissions_preserved=$true;context_pinned=$true;project_registration=$true;broker_validation=$true}|ConvertTo-Json
}
finally {
    if(Test-Path -LiteralPath $testRoot){Remove-Item -LiteralPath $testRoot -Recurse -Force}
}
