# Contributing

Keep changes provider-neutral, parameterized, and free of credentials or local
absolute paths. Never add captured authentication files, API responses that
contain headers, private prompts, generated user assets, or production project
content.

Run both test scripts before opening a pull request:

```powershell
.\tests\Static.Tests.ps1
.\tests\Functional.Tests.ps1
```

For macOS changes, also run:

```sh
sh -n setup.sh
python3 -m unittest discover -s tests -p 'test_macos.py' -v
```

macOS tests use a simulated Codex executable and temporary homes. They cover
argument preservation, cache renewal and shutdown, key file permissions,
process termination, image delivery policies, symlink escapes and uninstall
ownership. CI additionally generates a prompt through the installed launcher
using the actual Codex CLI, without making provider requests. Keep the Windows
PowerShell entry point working; its tests run in a separate Windows CI job.

Security-sensitive changes to path containment, environment handling, broker
execution, or exec-policy rules require focused tests and a clear threat-model
explanation.
