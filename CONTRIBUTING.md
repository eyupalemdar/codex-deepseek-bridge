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

Security-sensitive changes to path containment, environment handling, broker
execution, or exec-policy rules require focused tests and a clear threat-model
explanation.
