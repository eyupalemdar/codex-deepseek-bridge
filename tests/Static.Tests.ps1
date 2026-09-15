$ErrorActionPreference='Stop'
$root=(Resolve-Path(Join-Path $PSScriptRoot '..')).Path
$required=@('README.md','LICENSE','SECURITY.md','setup.ps1','src/CodexProviderSetup.ps1','src/broker/codex-image.ps1','examples/image-request.example.json')
foreach($file in $required){if(-not(Test-Path (Join-Path $root $file) -PathType Leaf)){throw "Missing: $file"}}
$all=Get-ChildItem $root -File -Recurse|Where-Object{$_.Extension -in @('.ps1','.md','.json','.gitignore')}
$workspaceRoot=(Resolve-Path (Join-Path $root '..\..\..\..')).Path
$forbidden=@($env:USERNAME,$workspaceRoot,('OPENAI_API_KEY'+'='),('DEEPSEEK_API_KEY'+'='))
foreach($file in $all){[string]$text=Get-Content -Raw $file.FullName;foreach($needle in $forbidden){if($text.IndexOf($needle,[StringComparison]::OrdinalIgnoreCase) -ge 0){throw "Forbidden machine-specific or secret-like content in $($file.FullName): $needle"}}}
foreach($script in @('setup.ps1','src/CodexProviderSetup.ps1','src/broker/codex-image.ps1')){$tokens=$null;$errors=$null;[Management.Automation.Language.Parser]::ParseFile((Join-Path $root $script),[ref]$tokens,[ref]$errors)|Out-Null;if($errors){throw($errors|Out-String)}}
[ordered]@{status='passed';files_checked=$all.Count;forbidden_markers=0}|ConvertTo-Json
