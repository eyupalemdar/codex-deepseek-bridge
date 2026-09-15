# Security

Report vulnerabilities privately through GitHub Security Advisories. Do not
open a public issue containing credentials, tokens, `auth.json`, request logs,
or generated private assets.

The installer never reads or copies OpenAI authentication material. Provider
keys are accepted through hidden input and stored only as a Windows user
environment variable. The optional image broker returns manifests and image
files, never credentials.

Review every project registration and generated image before production use.
Do not weaken the broker path checks or replace its fixed exec-policy prefix
with a general PowerShell allow rule.

