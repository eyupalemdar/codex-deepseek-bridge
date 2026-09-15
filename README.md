# Codex DeepSeek Bridge

Run OpenAI Codex CLI with a separate DeepSeek-compatible provider profile while
keeping your normal ChatGPT Codex login isolated. Optionally install a protected
bridge that lets the provider-driven Codex session request built-in image
generation through your existing ChatGPT Codex login without exposing OAuth
credentials or requiring `OPENAI_API_KEY`.

Windows 10/11 and PowerShell 5.1+ are supported. The scripts are parameterized;
the repository contains no machine-specific paths, API keys, account data, or
generated assets.

## What it installs

- An isolated provider home, default: `%USERPROFILE%\.codex-deepseek`
- A global command, default: `codex-deepseek`
- Explicit provider/model CLI overrides to prevent profile fallback
- A local model catalog so `/model` recognizes configured provider models
- Independent Default and Plan reasoning levels
- Optional protected image broker and per-project delivery policy
- Validation, live smoke-test, and scoped uninstall actions

Your existing `%USERPROFILE%\.codex` login and configuration are not replaced.

## Quick start

Install Codex CLI and sign in with ChatGPT first if you want the optional image
bridge. Then clone this repository and run:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\setup.ps1 -Action Install
.\setup.ps1 -Action SetKey
```

Open a new terminal:

```powershell
codex-deepseek
```

Validate without printing secret values:

```powershell
.\setup.ps1 -Action Test
.\setup.ps1 -Action Test -LiveTest
```

The live test makes a small billed request to the configured provider.

## Provider customization

All defaults can be overridden:

```powershell
.\setup.ps1 -Action Install `
  -ProviderName deepseek `
  -BaseUrl https://api.deepseek.com `
  -ApiKeyEnvironmentVariable DEEPSEEK_API_KEY `
  -Models deepseek-flash,deepseek-v4-pro `
  -DefaultModel deepseek-flash `
  -ReasoningEffort max `
  -PlanReasoningEffort max `
  -ContextWindow 1000000
```

The `responses` wire API is required. A provider can expose standard OpenAI-like
model listing while still failing Codex's richer model-catalog schema; the local
catalog handles that mismatch. Its capability declaration is deliberately
conservative: text-only, no native search, and a configurable context window.
The DeepSeek V4.1 Flash/V4 Pro default is 1M, matching the provider's published
limit; lower it explicitly for other providers or models. See DeepSeek's
[current model table](https://api-docs.deepseek.com/quick_start/pricing).

## Optional image bridge

Register a project and install the protected broker:

```powershell
.\setup.ps1 -Action RegisterProject `
  -ProjectRoot C:\src\my-app `
  -ProjectId my-app `
  -DeliveryPolicy staging
```

Policies:

- `staging`: outputs remain under `<project>\Saved\AI_Temp\DelegatedImages`.
- `approval-before-copy`: outputs remain inside the protected broker directory
  until a person approves copying the exact candidate.

Validate a request without generating an image:

```powershell
codex-image -RequestPath C:\src\my-app\image-request.json -ValidateOnly
```

See [docs/image-broker.md](docs/image-broker.md) and
[examples/image-request.example.json](examples/image-request.example.json).

## Session controls

Inside either provider-backed or normal Codex sessions, `/mode`, `/plan`,
`Shift+Tab`, and `/permissions` remain Codex-local controls. Provider/model and
reasoning defaults are isolated by the launcher. `/model` may still include the
bundled OpenAI catalog; use only models registered for your active provider.

## Uninstall

Preview the scoped removal first:

```powershell
.\setup.ps1 -Action Uninstall -WhatIf
.\setup.ps1 -Action Uninstall
```

Uninstall removes only paths installed by this tool. It never deletes the normal
ChatGPT Codex home or registered projects.

## Trust boundary

This project automates configuration, not provider endorsement or production
asset approval. Review generated files and hashes. The scripts cannot guarantee
compatibility with future Codex CLI or third-party API changes.

## Development

```powershell
.\tests\Static.Tests.ps1
.\tests\Functional.Tests.ps1
```

Functional tests install only into a unique temporary directory, validate the
local model catalog and broker request boundary, and remove that directory.
