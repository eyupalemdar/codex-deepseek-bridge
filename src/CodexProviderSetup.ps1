[CmdletBinding(SupportsShouldProcess)]
param(
    [string]$Action,[string]$ProviderName,[string]$BaseUrl,
    [string]$ApiKeyEnvironmentVariable,[string[]]$Models,[string]$DefaultModel,[string[]]$ImageInputModels=@('deepseek-flash'),
    [string]$ReasoningEffort,[string]$PlanReasoningEffort,[int]$ContextWindow,
    [ValidateSet('','user','auto_review')][string]$ApprovalsReviewer,
    [string]$ProviderCodexHome,[string]$GptCodexHome,[string]$InstallBin,
    [string]$BrokerRoot,[string]$CommandName,[string]$ProjectRoot,
    [string]$ProjectId,[string]$DeliveryPolicy,[switch]$LiveTest,[switch]$SkipPathUpdate
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$utf8 = New-Object Text.UTF8Encoding($false)

function Write-Utf8([string]$Path,[string]$Content) {
    [IO.File]::WriteAllText($Path,$Content,$utf8)
}
function Assert-Token([string]$Value,[string]$Label) {
    if($Value -cnotmatch '^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$'){throw "Invalid ${Label}: $Value"}
}
function Assert-EnvName([string]$Value) {
    if($Value -cnotmatch '^[A-Za-z_][A-Za-z0-9_]*$'){throw "Invalid environment variable name: $Value"}
}
function Require-Codex {
    if(-not(Get-Command codex -ErrorAction SilentlyContinue)){throw 'Install OpenAI Codex CLI and place codex on PATH first.'}
}
function Get-ConfigText {
    $lines=@(
        "model = `"$DefaultModel`""
        "model_reasoning_effort = `"$ReasoningEffort`""
        "plan_mode_reasoning_effort = `"$PlanReasoningEffort`""
        "model_provider = `"$ProviderName`""
        "model_context_window = $ContextWindow"
        "model_auto_compact_token_limit = $([Math]::Floor($ContextWindow * 0.9))"
    )
    if(-not[string]::IsNullOrWhiteSpace($ApprovalsReviewer)){$lines+="approvals_reviewer = `"$ApprovalsReviewer`""}
    $lines+=@(
        'web_search = "disabled"'
        ''
        "[model_providers.$ProviderName]"
        "name = `"$ProviderName`""
        "base_url = `"$BaseUrl`""
        "env_key = `"$ApiKeyEnvironmentVariable`""
        "env_key_instructions = `"Set $ApiKeyEnvironmentVariable in the user environment. Never put the value in this file.`""
        'wire_api = "responses"'
        'request_max_retries = 3'
        'stream_max_retries = 3'
        'stream_idle_timeout_ms = 300000'
    )
    ($lines -join "`r`n") + "`r`n"
}
function New-Catalog {
    Require-Codex
    $catalog=(& codex debug models --bundled|ConvertFrom-Json)
    $template=$catalog.models|Where-Object slug -eq 'gpt-5.4'|Select-Object -First 1
    if($null-eq$template){throw 'Compatible bundled metadata template was not found.'}
    $levels=@('none','minimal','low','medium','high','xhigh','max')|ForEach-Object{[ordered]@{effort=$_;description="$_ reasoning"}}
    $instructions='You are a coding agent operating through Codex CLI. Follow the active system, developer, project, safety, permission, and user instructions. Use available tools carefully and work within the current workspace.'
    $items=@();$priority=0
    foreach($slug in $Models){
        Assert-Token $slug 'model';$priority++
        $vision=$ImageInputModels -contains $slug
        $m=($template|ConvertTo-Json -Depth 20|ConvertFrom-Json)
        $m.slug=$slug;$m.display_name=($slug -replace '-',' ');$m.description="$ProviderName model exposed through a custom Codex provider."
        $m.default_reasoning_level=$ReasoningEffort;$m.supported_reasoning_levels=$levels
        $m.visibility='list';$m.priority=$priority;$m.additional_speed_tiers=@();$m.service_tiers=@();$m.availability_nux=$null;$m.upgrade=$null
        $m.model_messages=$null;$m.base_instructions=$instructions;$m.supports_image_detail_original=$vision;$m.supports_search_tool=$false
        $m|Add-Member -NotePropertyName auto_review_model_override -NotePropertyValue $DefaultModel -Force
        # Only a vision-capable model may declare image input: Codex strips image
        # parts and rejects view_image when the modality is missing, and DeepSeek
        # V4 Pro receives an "Unsupported Image" placeholder instead.
        $modes=@('text');if($vision){$modes+='image'}
        $m.input_modalities=$modes;$m.context_window=$ContextWindow;$m.max_context_window=$ContextWindow;$items+=$m
    }
    [ordered]@{fetched_at=[DateTime]::UtcNow.ToString('o');etag="local-$ProviderName-catalog-v1";client_version=(& codex --version).Split(' ')[1];models=$items}
}
function Install-Launcher {
    New-Item -ItemType Directory -Path $InstallBin -Force|Out-Null
    $launcher=Join-Path $InstallBin "$CommandName.cmd"
    $keeper=Join-Path $InstallBin "$CommandName-cache-keeper.ps1"
    $keeperBody=@'
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$CachePath,
    [int]$IntervalSeconds=240,
    [int]$MaxHours=12,
    [int]$ParentPid=0,
    [int]$MaxIterations=0
)
$ErrorActionPreference='Stop'
if($ParentPid-le0){try{$ParentPid=[int](Get-CimInstance Win32_Process -Filter "ProcessId = $PID" -ErrorAction Stop).ParentProcessId}catch{$ParentPid=0}}
$utf8=New-Object Text.UTF8Encoding($false);$deadline=(Get-Date).AddHours($MaxHours);$touches=0
function Update-Cache {
    if(-not(Test-Path -LiteralPath $CachePath -PathType Leaf)){return $false}
    try{
        $cache=Get-Content -LiteralPath $CachePath -Raw|ConvertFrom-Json
        $cache.fetched_at=[DateTime]::UtcNow.ToString('o')
        $temp="$CachePath.keeper.tmp"
        [IO.File]::WriteAllText($temp,($cache|ConvertTo-Json -Depth 20),$utf8)
        try{[IO.File]::Replace($temp,$CachePath,$null)}catch{[IO.File]::Copy($temp,$CachePath,$true);Remove-Item -LiteralPath $temp -Force}
        return $true
    }catch{return $false}
}
while((Get-Date)-lt$deadline){
    if($MaxIterations-gt0-and$touches-ge$MaxIterations){break}
    if($ParentPid-gt0-and-not(Get-Process -Id $ParentPid -ErrorAction SilentlyContinue)){break}
    if(-not(Update-Cache)){break}
    $touches++
    Start-Sleep -Seconds $IntervalSeconds
}
'@
    Write-Utf8 $keeper $keeperBody
    $compactLimit=[Math]::Floor($ContextWindow * 0.9)
    $modelArgs=('-c model="{0}" -c model_context_window={1} -c model_auto_compact_token_limit={2} -c model_reasoning_effort="%EFFORT%" -c plan_mode_reasoning_effort="%PLANEFFORT%"' -f $DefaultModel,$ContextWindow,$compactLimit)
    $providerArgs=('-c model_provider="{0}" -c model_providers.{0}.name="{0}" -c model_providers.{0}.base_url="{1}" -c model_providers.{0}.env_key="{2}" -c model_providers.{0}.wire_api="responses"' -f $ProviderName,$BaseUrl,$ApiKeyEnvironmentVariable)
    $bodyLines=@(
        '@echo off'
        'setlocal'
        "set `"CODEX_HOME=$ProviderCodexHome`""
        'rem Optional first argument selects the reasoning level for this session:'
        'rem   --none --minimal --low --medium --high --xhigh --max'
        "set `"EFFORT=$ReasoningEffort`""
        "set `"PLANEFFORT=$PlanReasoningEffort`""
        'set "LEVELFLAG="'
        'set "PASSTHRU=%*"'
        'if /i "%~1"=="--none"    (set "EFFORT=none"    & set "PLANEFFORT=none"    & set "LEVELFLAG=1")'
        'if /i "%~1"=="--minimal" (set "EFFORT=minimal" & set "PLANEFFORT=minimal" & set "LEVELFLAG=1")'
        'if /i "%~1"=="--low"     (set "EFFORT=low"     & set "PLANEFFORT=low"     & set "LEVELFLAG=1")'
        'if /i "%~1"=="--medium"  (set "EFFORT=medium"  & set "PLANEFFORT=medium"  & set "LEVELFLAG=1")'
        'if /i "%~1"=="--high"    (set "EFFORT=high"    & set "PLANEFFORT=high"    & set "LEVELFLAG=1")'
        'if /i "%~1"=="--xhigh"   (set "EFFORT=xhigh"   & set "PLANEFFORT=xhigh"   & set "LEVELFLAG=1")'
        'if /i "%~1"=="--max"     (set "EFFORT=max"     & set "PLANEFFORT=max"     & set "LEVELFLAG=1")'
        'if defined LEVELFLAG call set "PASSTHRU=%%PASSTHRU:--%EFFORT%=%%"'
        "if not defined $ApiKeyEnvironmentVariable ("
        "  echo $ApiKeyEnvironmentVariable is not configured. 1>&2"
        '  exit /b 2'
        ')'
        "if not exist `"$ProviderCodexHome\models_cache.json`" ("
        '  echo Provider model catalog is missing; run setup.ps1 -Action Install first. 1>&2'
        '  exit /b 3'
        ')'
        "start `"$CommandName-cache-keeper`" /b powershell -NoLogo -NoProfile -ExecutionPolicy Bypass -File `"$keeper`" -CachePath `"$ProviderCodexHome\models_cache.json`" >nul 2>nul"
        "call codex $modelArgs $providerArgs %PASSTHRU%"
        'exit /b %ERRORLEVEL%'
    )
    $body=($bodyLines -join "`r`n")+"`r`n"
    Write-Utf8 $launcher $body
    if(-not$SkipPathUpdate){$userPath=[Environment]::GetEnvironmentVariable('Path','User');$entries=@($userPath-split';'|Where-Object{$_});if(-not($entries|Where-Object{$_.TrimEnd('\')-ieq$InstallBin.TrimEnd('\')})){[Environment]::SetEnvironmentVariable('Path',(@($entries)+$InstallBin)-join';','User')}}
    $launcher
}
function Install-All {
    Require-Codex;Assert-Token $ProviderName 'provider';Assert-EnvName $ApiKeyEnvironmentVariable
    if($Models -notcontains $DefaultModel){throw 'DefaultModel must be included in Models.'}
    foreach($imageModel in $ImageInputModels){if($Models -notcontains $imageModel){throw 'ImageInputModels must be a subset of Models.'}}
    if(-not[string]::IsNullOrWhiteSpace($ApprovalsReviewer)){Assert-Token $ApprovalsReviewer 'approvals reviewer'}
    New-Item -ItemType Directory -Path $ProviderCodexHome -Force|Out-Null
    Write-Utf8 (Join-Path $ProviderCodexHome 'config.toml') (Get-ConfigText)
    Write-Utf8 (Join-Path $ProviderCodexHome 'models_cache.json') ((New-Catalog)|ConvertTo-Json -Depth 20)
    $launcher=Install-Launcher
    [ordered]@{status='installed';launcher=$launcher;cache_keeper=(Join-Path $InstallBin "$CommandName-cache-keeper.ps1");provider_home=$ProviderCodexHome;models=$Models;approvals_reviewer=$ApprovalsReviewer;secret_written=$false;new_terminal_required=$true}|ConvertTo-Json -Depth 4
}
function Set-Key {
    Assert-EnvName $ApiKeyEnvironmentVariable
    $secure=Read-Host "Enter $ApiKeyEnvironmentVariable" -AsSecureString
    $ptr=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try{$plain=[Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr);if([string]::IsNullOrWhiteSpace($plain)){throw 'Empty key.'};[Environment]::SetEnvironmentVariable($ApiKeyEnvironmentVariable,$plain,'User');Set-Item -LiteralPath "Env:$ApiKeyEnvironmentVariable" -Value $plain}
    finally{if($ptr-ne[IntPtr]::Zero){[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)};$plain=$null}
    [ordered]@{status='configured';variable=$ApiKeyEnvironmentVariable;value_printed=$false;new_terminal_required=$true}|ConvertTo-Json
}
function Register-Project {
    Require-Codex
    if(-not(Test-Path -LiteralPath $ProjectRoot -PathType Container)){throw 'ProjectRoot must be an existing directory.'}
    $root=(Resolve-Path $ProjectRoot).Path;if([string]::IsNullOrWhiteSpace($ProjectId)){$ProjectId=Split-Path $root -Leaf};Assert-Token $ProjectId 'project ID'
    if(-not(Test-Path -LiteralPath $GptCodexHome -PathType Container)){throw 'Normal ChatGPT Codex home not found. Run codex login first.'}
    New-Item -ItemType Directory -Path $BrokerRoot -Force|Out-Null
    Copy-Item (Join-Path $PSScriptRoot 'broker\codex-image.ps1') (Join-Path $BrokerRoot 'codex-image.ps1') -Force
    New-Item -ItemType Directory -Path $InstallBin -Force|Out-Null
    $imageLauncher="@echo off`r`npowershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File `"$BrokerRoot\codex-image.ps1`" %*`r`n"
    Write-Utf8 (Join-Path $InstallBin 'codex-image.cmd') $imageLauncher
    $cfgPath=Join-Path $BrokerRoot 'broker.config.json';$projects=@()
    if(Test-Path $cfgPath){$old=Get-Content -Raw $cfgPath|ConvertFrom-Json;$projects=@($old.projects|Where-Object{$_.id-ne$ProjectId})}
    $projects+=[ordered]@{id=$ProjectId;root=$root;delivery_policy=$DeliveryPolicy}
    Write-Utf8 $cfgPath ([ordered]@{schema_version=1;gpt_codex_home=$GptCodexHome;projects=$projects}|ConvertTo-Json -Depth 6)
    New-Item -ItemType Directory -Path (Join-Path $ProviderCodexHome 'rules') -Force|Out-Null
    $escaped=(Join-Path $BrokerRoot 'codex-image.ps1').Replace('\','\\')
    $rule="prefix_rule(`n    pattern = [`"powershell.exe`", `"-NoLogo`", `"-NoProfile`", `"-ExecutionPolicy`", `"Bypass`", `"-File`", `"$escaped`", `"-RequestPath`"],`n    decision = `"allow`",`n    justification = `"Run the protected built-in image broker only.`",`n)`n"
    Write-Utf8 (Join-Path $ProviderCodexHome 'rules\image-broker.rules') $rule
    [ordered]@{status='registered';project_id=$ProjectId;root=$root;delivery_policy=$DeliveryPolicy;secret_written=$false}|ConvertTo-Json
}
function Test-All {
    $present=-not[string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($ApiKeyEnvironmentVariable,'User'))
    $result=[ordered]@{codex_present=[bool](Get-Command codex -ErrorAction SilentlyContinue);provider_home=(Test-Path $ProviderCodexHome);launcher=(Test-Path(Join-Path $InstallBin "$CommandName.cmd"));cache_keeper=(Test-Path(Join-Path $InstallBin "$CommandName-cache-keeper.ps1"));key_present=$present;key_value_printed=$false;live_test='not-requested'}
    if($LiveTest){if(-not$present){throw 'Provider key is missing.'};$launcher=Join-Path $InstallBin "$CommandName.cmd";$output=& $launcher exec --ephemeral --skip-git-repo-check 'Reply with exactly PROVIDER_SMOKE_OK' 2>&1;$result.live_test=if($LASTEXITCODE-eq0){'passed'}else{'failed'};if($LASTEXITCODE-ne0){throw ($output|Out-String)}}
    $result|ConvertTo-Json
}
function Uninstall-All {
    $targets=@((Join-Path $InstallBin "$CommandName.cmd"),(Join-Path $InstallBin "$CommandName-cache-keeper.ps1"),(Join-Path $InstallBin "$CommandName-refresh-model-catalog.ps1"),$ProviderCodexHome)
    foreach($target in $targets){if(Test-Path $target){if($PSCmdlet.ShouldProcess($target,'Remove tool-owned path')){Remove-Item -LiteralPath $target -Recurse -Force}}}
    [ordered]@{status='uninstalled';normal_codex_home_preserved=$GptCodexHome;projects_preserved=$true;broker_preserved=$true}|ConvertTo-Json
}

switch($Action){'Install'{Install-All};'SetKey'{Set-Key};'RegisterProject'{Register-Project};'Test'{Test-All};'Uninstall'{Uninstall-All};default{throw "Unknown action: $Action"}}
