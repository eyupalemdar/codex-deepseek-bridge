# Protected image broker

The provider-backed Codex process operates from an isolated `CODEX_HOME`. It
cannot read the normal ChatGPT Codex credential store through the project
sandbox. A fixed command prefix permits only the protected broker script.

The broker:

1. Loads a bounded JSON request located inside a registered project.
2. Rejects unknown fields, path traversal, invalid project IDs, excess images,
   missing edit references, and output paths outside the selected policy.
3. Starts an ephemeral normal Codex session using built-in image generation.
4. Detects newly generated PNG files.
5. Copies permitted outputs and writes dimensions, SHA-256 hashes, provider
   identity, and `production_approved=false` to `result.json`.
6. Never reads or returns ChatGPT OAuth files or provider API-key values.

Image generation can consume ChatGPT plan allowance. A successful bridge result
is diagnostic/staging output and does not authorize publication or application
import.

For `approval-before-copy`, the manifest remains below the protected broker
root. Copying an approved candidate is intentionally outside this tool.

