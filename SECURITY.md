# Security

Report vulnerabilities privately through GitHub Security Advisories. Do not
open a public issue containing credentials, tokens, `auth.json`, request logs,
or generated private assets.

The installer never reads or copies OpenAI authentication material. Provider
keys are accepted through hidden input. Windows stores them as a user
environment variable. macOS stores them as an owner-only (`600`) plaintext file
under the isolated provider home; an exported environment variable can be used
instead. This file is not encrypted or stored in Keychain. The optional image
broker returns manifests and image files, not credential files.

Separate `CODEX_HOME` directories isolate configuration, not operating-system
identities. Access to credentials and project files still depends on Codex's
active sandbox and permissions. Registered projects, broker code and config
must be trusted. The macOS broker resolves symlinks when validating paths,
rejects overlapping project/installation roots, and bounds request JSON to
64 KiB. These checks do not defend against a same-user process changing files
or symlinks between validation and use. Its Codex child uses `workspace-write`;
the prompt's instruction not to modify project files is not a read-only sandbox.
macOS removes provider and OpenAI API-key environment variables from the image
child; configure the normal Codex home with ChatGPT login before use.

Review every project registration and generated image before production use.
Do not weaken the broker path checks or replace its fixed exec-policy prefix
with a general PowerShell, Python or shell allow rule.
