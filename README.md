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
- Explicit context and compaction limits for custom-provider models
- A local model catalog so `/model` recognizes configured provider models
- A session-lifetime cache keeper that renews the five-minute catalog TTL
- Launch-time reasoning-level selection (`--low` … `--xhigh`, see below)
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

## Reasoning levels at launch

The launcher accepts an optional first argument that sets both the Default and
the Plan reasoning effort for that session:

```powershell
codex-deepseek --xhigh
codex-deepseek --low exec "summarize the failing test"
```

Supported switches: `--none`, `--minimal`, `--low`, `--medium`, `--high`,
`--xhigh`, `--max`. Without a switch the install defaults apply (`max` for both
in the DeepSeek default profile). The switch is matched case-insensitively, is
consumed by the launcher and never forwarded to `codex`; every remaining
argument is passed through unchanged.

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

By default the generated provider config does not override Codex approval
behavior: the permissions and reviewer selection made inside Codex remain
authoritative. Pass `-ApprovalsReviewer auto_review` if the provider profile
should default to Approve for me (or `-ApprovalsReviewer user` to pin manual
review). The in-session `/permissions` selection still wins for the running
session.

Codex 0.154.0 accepts a cached custom-model catalog for five minutes and loads
it with `refresh_strategy=offline` when it spawns guardian/auto-review sessions.
A stale entry drops the reviewer override and fails closed to a manual approval
prompt, so the launcher starts a hidden keeper that renews the cache timestamp
every four minutes for the life of the session; the keeper exits when the
launcher exits and only rewrites `fetched_at` (atomic temp-file replace), never
the model metadata. The launcher stops with a clear error if the catalog file
is missing. Re-run `setup.ps1 -Action Install` after a Codex CLI update to
regenerate the catalog for the new client version. Codex exposes 95% of the
declared model window as usable context, so the 1M DeepSeek default reports
950,000 tokens.

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
The launcher does not pass `--approve-for-me`, `--ask-for-approval`, or an
approval-policy override; only the optional `-ApprovalsReviewer` install
parameter writes a config-level reviewer default. Each model's generated
metadata sets `auto_review_model_override` to the configured default provider
model. When Approve for me is active, Codex therefore uses a model that the
custom provider can serve instead of sending the internal `codex-auto-review`
slug. On Windows the launcher uses `CALL` so the isolated provider home and its
fresh catalog remain active for the complete Codex process.

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
local model catalog, the cache keeper, and the broker request boundary, and
remove that directory.
