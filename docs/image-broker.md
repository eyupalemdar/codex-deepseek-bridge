# Protected image broker

The provider-backed Codex process operates from a separate `CODEX_HOME`.
Credential access depends on the active Codex sandbox and permissions; a
separate home is not itself a security boundary. A fixed command prefix permits
the registered broker command. See [SECURITY.md](../SECURITY.md) for the trust
model and limitations.

The broker:

1. Loads a bounded JSON request located inside a registered project.
2. Rejects unknown fields, path traversal, invalid project IDs, excess images,
   missing edit references, and output paths outside the selected policy.
3. Starts an ephemeral normal Codex session using built-in image generation.
4. Detects newly generated PNG files.
5. Copies permitted outputs and writes dimensions, SHA-256 hashes, provider
   identity, and `production_approved=false` to `result.json`.
6. Never reads or returns ChatGPT OAuth files or provider API-key values.

On macOS use `codex-image --request-path /path/to/request.json --validate-only`
to validate and omit `--validate-only` to generate. The implementation uses
Python's standard library for process handling, POSIX file locking, SHA-256 and
PNG dimensions; PowerShell and `System.Drawing` are not required. Both platforms
use the same request and manifest fields and delivery policies. The macOS
broker accepts requests up to 64 KiB and resolves symlinks in paths before
checking containment.

Output discovery currently compares PNG paths in the normal Codex home's
`generated_images` directory before and after execution. Avoid generating
images in another normal Codex session at the same time: the broker lock
serializes broker requests only, and cannot distinguish unrelated new PNGs.
If your Codex version does not save built-in image output there, generation
will report an unexpected image count. No automatic transcript extraction is
implemented. Provider/image service compatibility requires a live test with
your own account; offline tests use a simulated Codex process.

Image generation can consume ChatGPT plan allowance. A successful bridge result
is diagnostic/staging output and does not authorize publication or application
import.

For `approval-before-copy`, the manifest remains below the protected broker
root. Copying an approved candidate is intentionally outside this tool.
