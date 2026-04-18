Codex Agent Instructions

You are a coding agent working interactively in this repository.

Your job is to help improve the codebase efficiently, safely, and with minimal unnecessary changes.

This repository is a multi-tenant inventory validator.

How to Work in This Repository

Before making meaningful changes:

Read README.md
Read progress.txt, especially the Codebase Patterns section
Read the relevant files for the task
For medium or large tasks, propose a short plan before editing
Make the smallest correct change that satisfies the request
Explain how to validate the change

Do not behave like an autonomous backlog runner unless explicitly asked.
Do not pick the next story by yourself unless the user asks.
Do not make broad refactors unless clearly requested.

Default Interaction Style

For most requests, respond in this order:

Brief understanding of the request
Files that should change
Short plan
Code changes
Validation steps
Risks or follow-ups, only if relevant

For very small tasks, you may skip the formal plan and go straight to the edit.

Project Goal

This project validates patrimonial and inventory spreadsheets using:

a shared canonical domain
tenant-specific configuration
deterministic validation rules
category-based checks
optional LLM audit
asynchronous jobs
operational reports
Canonical Domain

Preserve these canonical fields as stable domain concepts:

Item
Placa Anterior
Descrição
Marca
Modelo
NS
Local
CC
Complemento
Observação

Preserve these derived concepts:

flag_item_coletado
flag_item_cadastrado_do_zero

Do not rename or reinterpret these concepts unless the user explicitly asks for it.

Architecture Guardrails
Keep one generic validation engine
Do not hardcode tenant names in the core engine
Prefer configuration-driven behavior over branching by tenant
Keep API, validation rules, report rendering, file parsing, and job orchestration separated
Prefer reusable abstractions over special-case logic
Do not duplicate engine logic per tenant
Keep tenant-specific behavior in config whenever possible
Multi-Tenant Rules

Tenant-specific variation should prefer configuration for:

column mapping
enabled and disabled rules
thresholds
categories
critical checks
LLM settings
prompt selection

Keep a working default tenant at all times.

When changing tenant-facing behavior:

preserve canonical field semantics
avoid tenant-specific conditionals in core modules
update the default tenant example if the configuration contract changes
derive upload/result/report filesystem paths through shared tenant-scoped helpers and keep legacy read fallbacks during path-layout migrations
Scope Control
Change only the files needed for the task
Do not refactor unrelated areas
Do not silently expand the task into adjacent features
If you notice architectural debt outside the request, mention it briefly instead of fixing it automatically
Prefer the smallest correct architectural move
Rule Design Guidance

Rules should operate on normalized canonical data.

Prefer a reusable rule contract such as:

applies(context) -> bool
validate(context) -> list[Issue]

Rules should not directly:

parse uploaded files
handle FastAPI request objects
generate reports
orchestrate jobs
depend on tenant names

Prefer registry-based rule loading over hardcoded execution chains.

Engine Design Guidance
Normalize source input into canonical field names before rule execution
Derive shared flags and shared context before running row-level rules
Load rules from tenant configuration
Keep one generic validation engine
If a new shared concept is introduced, place it in the domain or core layer instead of embedding it in a route or worker
API Guidance
Keep API handlers thin
API endpoints should delegate orchestration to services
API code should not contain validation business rules
API code should not know tenant-specific rule details beyond selecting the tenant or config
Tenant-scoped API auth should derive tenant context from the API key; request `tenant_id` values are hints and must be rejected on mismatch
When persisting auth-related operational metadata, store the configured `api_key_id` and never the raw `X-API-Key` secret
Middleware that enforces custom auth headers must allow unauthenticated `OPTIONS` preflight requests and keep operational probes like `/health` public
Observability Guidance
Keep Prometheus wiring centralized in `app/core/metrics.py`
Metrics must stay opt-in via `VALIDATOR_METRICS_ENABLED`
Never use `job_id`, `request_id`, or other per-request values as Prometheus labels
Expose `/metrics` from the API layer only; services and rules should call helper functions instead of importing `prometheus_client` directly
Keep `/health` thin by delegating probes to `app/core/health.py`
Treat uploads/results/job_store as critical health checks; keep LLM reachability probes opt-in per tenant via `llm.healthcheck_enabled` and conservative enough to avoid full audit completions
Reporting Guidance
Reports should be practical for operational correction workflows
Report formatting should be separated from validation logic
Prefer structured issue data over report-specific logic inside rules
Avoid coupling report generation tightly to rule internals
Improvement Workflow

When the user asks for an improvement:

First understand whether it belongs to:
core
rules
services
API
tenants
workers
tests
Then choose one of these modes:

Understanding mode
Use when the user wants explanation, diagnosis, or architecture guidance.
Explain the current flow before proposing changes.

Edit mode
Use when the user wants a direct implementation.
Change only the necessary files and preserve current behavior unless asked otherwise.

Review mode
Use when the user wants feedback on existing code.
Point out risks, inconsistencies, missing tests, and architectural issues before suggesting edits.

Planning Rule

If a task touches more than 2 files, changes architecture, or introduces a new abstraction:
provide a short plan before editing.

A good plan should include:

what will change
why those files are the right place
how behavior will be preserved
how the change will be validated
Testing Expectations
Prefer focused tests for the layer being changed
Core changes should have core tests
Rule changes should have rule tests
Tenant config changes should have loader or config tests
API changes should keep handlers thin and test behavior at the right layer
Job changes should verify lifecycle transitions and persisted metadata
Do not skip tests for shared abstractions that affect future work
Validation Expectations

Before considering a change complete, suggest the most relevant checks, such as:

typecheck
lint
unit tests
API tests
focused manual verification steps

If you cannot run something, say so clearly and still provide the correct command.

Progress and Memory

Use progress.txt as lightweight project memory.

Read it before larger tasks.
When the user asks for substantial changes, align suggestions with existing Codebase Patterns.

Do not rewrite progress.txt unless explicitly asked.
Do not invent history.

Requirement Discipline
Do not invent features outside the user’s request
Use the most conservative valid interpretation when requirements are ambiguous
State assumptions explicitly
If a shortcut is used, label it clearly as a temporary bridge rather than final architecture
Commit Discipline

Do not commit unless the user explicitly asks you to commit.

If the user asks for a commit:

make sure the requested checks have passed
keep the commit focused
use a clear commit message
Project Structure Intent

Prefer this separation as the codebase evolves:

app/core for canonical domain, tenant config, context, issues, engine, registry
app/rules for rule implementations
app/services for orchestration services
app/api for FastAPI routes and schemas
app/tenants for tenant configs and prompt files
app/workers for jobs and background processing
tests mirroring application structure

Do not create unnecessary top-level directories when an existing module is the correct home.

What Good Help Looks Like Here

Good help in this repository means:

understanding the existing architecture before editing
preserving domain semantics
keeping multi-tenant behavior configuration-driven
making targeted improvements
avoiding unnecessary rewrites
improving clarity, safety, and testability
When in Doubt

When in doubt:

ask whether the user wants explanation, plan, implementation, or review
prefer smaller changes
preserve existing behavior
avoid architectural shortcuts that hardcode tenant behavior into the core
