Multi-Tenant Inventory Validator

Multi-tenant inventory validation platform with a shared canonical domain model, tenant-specific configuration, optional LLM audit, asynchronous jobs, and operational reports.

Purpose

This project validates patrimonial and inventory spreadsheets while preserving a stable canonical domain across all tenants.

The system is designed to support:

canonical inventory fields shared across all tenants
tenant-specific configuration instead of tenant-specific engine branching
deterministic validation rules
category-aware critical checks
optional LLM-assisted review
asynchronous file validation jobs
operational reports for correction workflows
Canonical Domain

All tenants must map back to the same canonical fields:

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
Derived Flags

The system also preserves these derived concepts:

flag_item_coletado
flag_item_cadastrado_do_zero

Semantics:

flag_item_coletado = 1 means the item originated from prior collection context
flag_item_cadastrado_do_zero = 1 means the item was created from scratch
the distinction between collected items and zero-created items is a core business rule
Architectural Principles

This project should evolve with the following direction:

one generic validation engine
configuration-driven tenant variation
registry-based rule execution
thin API layer
separated job orchestration
separated report generation

Important rules:

do not hardcode tenant names in the validation core
do not duplicate the engine per company
do not mix API, rules, jobs, and reports in one large abstraction
do not reinterpret canonical field meanings across tenants
prefer reusable abstractions over special-case execution paths
Planned Project Structure

Essential markdown files only:

CLAUDE.md
README.md
progress.txt

Main code structure:

app/api
app/core
app/rules
app/services
app/tenants
app/workers
tests

Core Concepts
Canonical field normalization

Tenants may use different source column names, but validation must execute against one normalized canonical model.

Tenant configuration

Tenant variation should primarily live in configuration, such as:

column mappings
enabled and disabled rules
thresholds
categories
critical checks
LLM settings
prompt selection

The `columns` mapping is applied during normalization. This means a tenant can point canonical
fields to different source headers, such as mapping canonical `descricao` to a source column like
`Espécie`.
Validation engine

The engine should:

normalize input into canonical fields
derive shared flags and shared context
load enabled rules from tenant configuration
execute rules against normalized data
aggregate structured issues
generate output artifacts
Rule-based validation

Validation logic should be implemented as reusable rules rather than hardcoded chains.

Preferred shape:

applies(context) -> bool
validate(context) -> list[Issue]
Async job pipeline

Validation should support asynchronous processing for uploaded files, with persisted job metadata and output artifact tracking.

Operational reporting

Outputs should be readable and useful for non-technical teams correcting inventory issues.

Initial Scope

The foundation phase is expected to build:

canonical inventory domain model
tenant configuration model
tenant loader
validation context
generic validation engine
deterministic integrity rules
zero-item quality rules
category classification and critical checks
optional LLM inventory audit
async validation jobs
output reports
API endpoints for validation and job status
Development Workflow

This project is intended to be developed iteratively with story-driven execution.

Primary project documents:

prd.json as the source of truth for story order and acceptance criteria
progress.txt as the execution history and reusable patterns log
CLAUDE.md as architectural instructions for autonomous work
Story Execution Expectations

Each iteration should:

read prd.json
read progress.txt
pick the highest priority unfinished story
implement only that story
run required checks
update progress.txt
update prd.json
commit only when the story is complete and checks pass
Multi-Tenant Design Expectations

When adding tenant support:

keep a working default tenant
do not scatter tenant-specific if statements through the core engine
prefer config-driven rule activation
preserve canonical field semantics
preserve collected vs zero-created item semantics
keep tenant configuration easy to extend
Testing Expectations

Tests should be focused by layer:

core tests for canonical domain, engine, config, and context
rule tests for validation behavior
service tests for orchestration
API tests for request and response behavior
worker and job tests for lifecycle and persistence
Current Status

This repository is in foundation mode and should grow from a clean architecture baseline.

Essential Files

Use only these markdown and text files at the beginning:

CLAUDE.md
README.md
progress.txt

Other important files:

prd.json
TASKS.md
Notes

This project should optimize for maintainability, configurability, and safe iteration over ad-hoc speed.

Running the API

One local way to run the API is:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
uvicorn app.main:app --reload
```

The app will then be available at `http://127.0.0.1:8000`.

Operational Frontend

The main operational UI now lives in the Next.js app under `frontend/`.

Suggested local setup:

```bash
source .venv/bin/activate
uvicorn app.main:app --reload
```

In another terminal:

```bash
cd frontend
cp .env.example .env.local
npm install
npm run dev
```

By default, the frontend expects the API at `http://127.0.0.1:8000` via
`NEXT_PUBLIC_API_BASE_URL`.

The backend enables CORS for `http://127.0.0.1:3000` and `http://localhost:3000` by default.
To point the UI to other origins, set `VALIDATOR_FRONTEND_ORIGINS` before starting FastAPI:

```bash
export VALIDATOR_FRONTEND_ORIGINS="http://127.0.0.1:3000,http://localhost:3000"
uvicorn app.main:app --reload
```

Operational Persistence

Low-volume operational metadata can now share one optional SQLite database through
`VALIDATOR_SQLITE_PATH`, for example:

```bash
export VALIDATOR_SQLITE_PATH="results/operational.sqlite3"
uvicorn app.main:app --reload
```

When `VALIDATOR_SQLITE_PATH` is set, these service stores use the shared SQLite file:

- job metadata
- audit log events
- issued API keys

Dedicated Worker Mode

The API still defaults to inline/background execution for local development and tests.
To move job execution out of the FastAPI process, set:

```bash
export VALIDATOR_SQLITE_PATH="results/operational.sqlite3"
export VALIDATOR_JOB_EXECUTION_MODE="worker"
```

Then run the API and the dedicated worker separately:

```bash
uvicorn app.main:app --reload
```

In another terminal:

```bash
python -m app.workers.validation_worker
```

In worker mode:

- `POST /validate` and `POST /jobs/{job_id}/reprocess` only enqueue persisted jobs
- the worker claims jobs atomically from the shared SQLite store
- stale running jobs can be reclaimed after the execution lease expires
- Kubernetes should run the API and worker as separate deployments over the same
  shared uploads/results volumes
- managed operator records

If `VALIDATOR_SQLITE_PATH` is not set, the legacy JSON-backed env vars remain supported:

- `VALIDATOR_JOB_STORE_PATH`
- `VALIDATOR_AUDIT_STORE_PATH`
- `VALIDATOR_API_KEY_STORE_PATH`
- `VALIDATOR_OPERATOR_STORE_PATH`

Production Auth Hardening

Set `VALIDATOR_ENV=production` in published environments. In production mode:

- legacy static `api_keys` from tenant YAML are not accepted by default
- seed operators declared in tenant YAML are not valid login credentials unless they have a
  persisted managed-operator overlay
- managed operators and issued API keys continue to use the operational store

Emergency compatibility exceptions are available but should not be used as a normal operating
mode:

```bash
export VALIDATOR_ALLOW_LEGACY_API_KEYS_IN_PRODUCTION=true
export VALIDATOR_ALLOW_SEED_OPERATORS_IN_PRODUCTION=true
```

When these exceptions are active and matching YAML credentials exist, `/health` reports a failing
`auth_policy` check so the insecure state is visible to operators.

The frontend keeps issued `X-API-Key` values in memory by default. To preserve the previous
sessionStorage behavior for a controlled local environment, set
`NEXT_PUBLIC_PERSIST_RAW_API_SESSION=true` before building or running the frontend.

Bootstrap do primeiro operador administrativo

To create the first administrative operator for the official tenant during API startup, set:

```bash
export VALIDATOR_SQLITE_PATH="results/operational.sqlite3"
export VALIDATOR_OFFICIAL_TENANT_ID="redesim"
export VALIDATOR_BOOTSTRAP_ADMIN_USERNAME="admin.operacional"
export VALIDATOR_BOOTSTRAP_ADMIN_PASSWORD="troque-esta-senha"
uvicorn app.main:app --reload
```

The bootstrap flow uses the persisted operator store, saves only the password hash plus operator
metadata, and is safe to rerun:

- if the configured username does not exist and the official tenant has no operators yet, the
  startup creates the first operator
- if the same username already exists, the startup leaves it unchanged by default
- set `VALIDATOR_BOOTSTRAP_ADMIN_FORCE_RESET=true` only when you intentionally want startup to
  replace that operator's password hash

Bootstrap is intentionally disabled when no persistent operator store is configured, because the
initial admin must survive process restarts.

First-run setup through the application

The API also exposes a public first-run setup flow for environments that should create the initial
administrator through the application instead of startup env credentials:

- `GET /setup` returns `available=true` only when persistent operator storage is configured and no
  operator has been persisted yet.
- `POST /setup` creates the initial administrator once, stores only the password hash and minimal
  operator metadata, records an audit event, and closes the public setup flow.
- Set `VALIDATOR_SETUP_TOKEN` to require a one-time setup token in the request body for published
  environments. The token itself is never stored in operator metadata or audit payloads.

Generated artifacts remain file-based on purpose:

- uploaded CSV files
- result JSON/PDF/CSV outputs under `results/`
- per-job `review_flags.json` sidecars
- LLM cache files from `VALIDATOR_LLM_CACHE_PATH`

The new frontend is intended for patrimonial and inventory staff who need a friendlier view than
the raw PDF:

- upload a CSV without calling the API manually
- follow job progress on screen
- read grouped problems in plain Portuguese
- edit CSV rows directly in the current job
- resolve duplicates while preserving the same `job_id`
- download JSON, PDF, CSV corrigido, and operational CSV exports

The UI converts the internal zero-based `row_index` into a human-friendly spreadsheet line number
that already accounts for the header row.

Legacy Inline Frontend

The inline HTML page served by FastAPI at `http://127.0.0.1:8000/` remains available as a
temporary compatibility path while the React/Next.js frontend becomes the recommended operational
entry point.

Notebook Frontend

A Jupyter notebook client is available at `notebooks/api_frontend.ipynb`.

Suggested setup:

```bash
source .venv/bin/activate
pip install notebook
jupyter notebook
```

Notebook workflow:

1. Start the FastAPI app locally.
2. Open `notebooks/api_frontend.ipynb`.
3. Update `BASE_URL`, `TENANT_ID`, and `CSV_PATH`.
4. Run the cells in order.

What the notebook does:

- checks `/health`
- previews the selected CSV
- uploads the file to `POST /validate`
- polls `GET /jobs/{job_id}` until completion or failure
- fetches `GET /jobs/{job_id}/result`
- renders summary, row results, duplicates, and grouped problems as tables
- downloads `GET /jobs/{job_id}/report` and saves both JSON and PDF locally

Success and failure behavior:

- if the job completes, the notebook renders the structured report and stores the JSON/PDF under `notebook_downloads/`
- if the job fails, the polling cell raises an error with the API `error_message`

Report Outputs

The structured report returned by `GET /jobs/{job_id}/result` now includes:

- `row_results[*].item`
- `row_results[*].descricao`
- `duplicates[*].descricao`
- `grouped_problems[code][*].item`
- `grouped_problems[code][*].descricao`

The PDF report also shows `item` and `descricao` in the duplicates and grouped problems tables.

Tenant Example: RedeSim

The repository now includes a tenant example at `app/tenants/redesim/tenant.yaml` that demonstrates:

- canonical `descricao` sourced from the tenant column `descricao`
- semicolon-separated CSV input with `iso-8859-1` encoding
- species-specific required fields such as `marca`, `modelo`, `complemento`, and `ns`
- species-specific critical pattern checks such as polegadas, BTUs, portas, canais, and litros

This tenant is intentionally conservative in ambiguous cases from the source matrix: the initial
configuration encodes the clearest field expectations first and can be expanded safely as the
organization confirms additional cases.
