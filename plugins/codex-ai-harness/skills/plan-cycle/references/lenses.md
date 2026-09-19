# Specialist lens roster

Each lens owns one concern and must not invent findings from adjacent areas.

## security (`AC-SEC`)

Always runs. Threat-model the new attack surface, authentication and
authorization on every path, injection (including prompt injection), secrets,
supply chain, tenant isolation, and privacy. For personal data, cover
minimisation, retention, deletion, export, exposure, and third parties.

## qa (`AC-QA`)

Always runs. Own happy and unhappy paths, boundaries, state transitions,
concurrency, failure injection, regression risk, and the executable proof for
each behavior. Prefer tests that can fail for the intended reason.

## simplicity (`AC-SIMP`)

Planning only. Argue for less scope, fewer states, fewer dependencies, and the
smallest mechanism that meets the need. Identify accidental frameworks and
speculative extensibility. A veto needs a concrete cost, not taste.

## product (`AC-PROD`)

Run for specs and user-visible behavior. Identify the user, problem, benefit,
success signal, confusing defaults, failure messaging, and whether the change
solves the stated problem rather than a proxy.

## design (`AC-DESIGN`)

Run for UI, templates, styles, and copy. Own hierarchy, flows, states,
responsive behavior, consistency with the existing design system, and removal
of superseded interface elements.

## accessibility (`AC-A11Y`)

Run for UI and copy. Own WCAG 2.2 AA, semantics, keyboard operation, focus,
contrast, motion, announcements, touch targets, and assistive-technology
behavior.

## architecture (`AC-ARCH`)

Run for new modules, boundaries, dependencies, and UI changes during review.
Own coupling, cohesion, extension points backed by a real requirement, scale,
and old code or interfaces made dead by the change.

## data (`AC-DATA`)

Run for schemas, migrations, persistence, destructive operations, personal
data, caching, and concurrency. Own atomicity, idempotency, races, recovery,
lookup correctness, and whether deletion/export mechanisms really work.

## operability (`AC-OPS`)

Run for production behavior. Own observability, rollout, rollback, degraded
modes, timeouts, retries, resource limits, alerting, and operator recovery.

## verification (`AC-VERIFY`)

Review only, after the domain lenses. Use fresh eyes and no planning rationale
to challenge whether evidence proves the claims, reproduce suspicious paths,
and find important behavior that no criterion anticipated.
