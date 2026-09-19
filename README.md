# codex-ai-harness

A multi-lens planning, TDD and review harness for [Codex](https://developers.openai.com/codex),
packaged as a Codex plugin. It is the Codex counterpart of
[claude-ai-harness](https://github.com/bassings/claude-ai-harness): the same
acceptance-criteria contract between planning and review, adapted to Codex
skills, subagents and hooks.

The plugin itself, its skills and how to install it are documented in
[`plugins/codex-ai-harness/README.md`](plugins/codex-ai-harness/README.md).

## Layout

| Path | What it is |
|---|---|
| `.agents/plugins/marketplace.json` | Local marketplace entry, so this checkout can be installed directly |
| `plugins/codex-ai-harness/` | The plugin: skills, hooks, scripts and tests |
| `bin/verify` | The one command that says whether the repo passes; CI runs the same |

## Development

```bash
bin/setup-hooks.sh   # once per clone: turns on the pre-push gate
bin/verify           # the full suite
```

Licence: MIT.
