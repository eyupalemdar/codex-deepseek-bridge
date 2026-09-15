[CmdletBinding(SupportsShouldProcess)]
param(
    [ValidateSet('Install','SetKey','RegisterProject','Test','Uninstall')]
    [string]$Action = 'Install',
    [string]$ProviderName = 'deepseek',
    [string]$BaseUrl = 'https://api.deepseek.com',
    [string]$ApiKeyEnvironmentVariable = 'DEEPSEEK_API_KEY',
    [string[]]$Models = @('deepseek-flash','deepseek-v4-pro'),
    [string]$DefaultModel = 'deepseek-flash',
    [ValidateSet('none','minimal','low','medium','high','xhigh','max')]
    [string]$ReasoningEffort = 'max',
    [ValidateSet('none','minimal','low','medium','high','xhigh','max')]
    [string]$PlanReasoningEffort = 'max',
    [ValidateRange(16000,1000000)][int]$ContextWindow = 1000000,
    [string]$ProviderCodexHome = (Join-Path $env:USERPROFILE '.codex-deepseek'),
    [string]$GptCodexHome = (Join-Path $env:USERPROFILE '.codex'),
    [string]$InstallBin = (Join-Path $env:USERPROFILE '.local\bin'),
    [string]$BrokerRoot = (Join-Path $env:USERPROFILE '.codex-image-broker'),
    [string]$CommandName = 'codex-deepseek',
    [string]$ProjectRoot,
    [string]$ProjectId,
    [ValidateSet('staging','approval-before-copy')]
    [string]$DeliveryPolicy = 'staging',
    [switch]$LiveTest,
    [switch]$SkipPathUpdate
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$src = Join-Path $PSScriptRoot 'src'

$forward = @{
    Action = $Action
    ProviderName = $ProviderName
    BaseUrl = $BaseUrl
    ApiKeyEnvironmentVariable = $ApiKeyEnvironmentVariable
    Models = $Models
    DefaultModel = $DefaultModel
    ReasoningEffort = $ReasoningEffort
    PlanReasoningEffort = $PlanReasoningEffort
    ContextWindow = $ContextWindow
    ProviderCodexHome = $ProviderCodexHome
    GptCodexHome = $GptCodexHome
    InstallBin = $InstallBin
    BrokerRoot = $BrokerRoot
    CommandName = $CommandName
    ProjectRoot = $ProjectRoot
    ProjectId = $ProjectId
    DeliveryPolicy = $DeliveryPolicy
    LiveTest = $LiveTest
    SkipPathUpdate = $SkipPathUpdate
}
if ($WhatIfPreference) { $forward.WhatIf = $true }
& (Join-Path $src 'CodexProviderSetup.ps1') @forward
