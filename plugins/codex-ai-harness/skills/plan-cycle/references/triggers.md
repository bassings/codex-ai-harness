# Trigger overrides

Lens selection is behavior-first. Paths are a deterministic hint, not a reason
to skip an obviously relevant lens.

The optional `.codex/harness-triggers.json` object may replace path globs for
these keys:

```json
{
  "ui": ["web/**", "**/*.css"],
  "data": ["db/**", "migrations/**"],
  "architecture": ["src/adapters/**"],
  "production": ["src/**", "deploy/**"]
}
```

Values must be arrays of non-empty relative glob strings. Reject absolute
paths, `..` segments, control characters, and unknown keys. A key replaces its
default list; omitted keys retain defaults. If parsing or validation fails,
report the error and use all defaults.

Defaults:

- `ui`: `**/*.html`, `**/*.css`, `**/*.scss`, `**/*.tsx`, `**/*.jsx`,
  `templates/**`, `frontend/**`, `web/**`, `app/**`
- `data`: `**/migrations/**`, `**/schema/**`, `**/*.sql`, `db/**`, `data/**`
- `architecture`: dependency manifests, lockfiles, `src/**`, `lib/**`, `app/**`
- `production`: application code, deployment configuration, infrastructure,
  jobs, observability, and CI workflows that alter shipped behavior

Mappings: `ui` triggers product, design, accessibility, and review-side
architecture; `data` triggers data and security; `architecture` triggers
architecture; `production` triggers operability.
