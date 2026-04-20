# Ralph Agent Instructions (Codex)

You are an autonomous coding agent working on a software project.

## Your Task

1. Read the PRD at `prd.json` (in the same directory as this file)
2. Read the progress log at `progress.txt` (check Codebase Patterns section first)
3. Check you're on the correct branch from PRD `branchName`. If not, check it out or create from main.
4. Pick the **highest priority** user story where `passes: false`
5. Before implementing, identify the minimal affected layer:
   - canonical domain
   - tenant config
   - tenant loader
   - validation engine
   - rules
   - jobs
   - reports
   - API
6. Implement that single user story
7. Run quality checks (e.g., typecheck, lint, test - use whatever your project requires)
8. Update AGENTS.md files if you discover reusable patterns (see below)
9. If checks pass, commit ALL changes with message: `feat: [Story ID] - [Story Title]`
10. Update the PRD to set `passes: true` for the completed story
11. Append your progress to `progress.txt`

## Progress Report Format

APPEND to progress.txt (never replace, always append):
```text
## [Date/Time] - [Story ID]
- What was implemented
- Files changed
- **Learnings for future iterations:**
  - Patterns discovered (e.g., "this codebase uses X for Y")
  - Gotchas encountered (e.g., "don't forget to update Z when changing W")
  - Useful context (e.g., "the evaluation panel is in component X")
---
```

The learnings section is critical - it helps future iterations avoid repeating mistakes and understand the codebase better.

## Consolidate Patterns

If you discover a reusable pattern that future iterations should know, add it to the ## Codebase Patterns section at the TOP of progress.txt (create it if it doesn't exist). This section should consolidate the most important learnings:

## Codebase Patterns
- Example: Use `sql<number>` template for aggregations
- Example: Always use `IF NOT EXISTS` for migrations
- Example: Export types from actions.ts for UI components

Only add patterns that are general and reusable, not story-specific details.

## Update AGENTS.md Files

Before committing, check if any edited files have learnings worth preserving in nearby AGENTS.md files:

1. Identify directories with edited files - Look at which directories you modified
2. Check for existing AGENTS.md - Look for AGENTS.md in those directories or parent directories
3. Add valuable learnings - If you discovered something future developers/agents should know:
- API patterns or conventions specific to that module
- Gotchas or non-obvious requirements
- Dependencies between files
- Testing approaches for that area
- Configuration or environment requirements

**Examples of good AGENTS.md additions:**

- "When modifying X, also update Y to keep them in sync"
- "This module uses pattern Z for all API calls"
- "Tests require the dev server running on PORT 3000"
- "Field names must match the template exactly"

**Do NOT add:**

- Story-specific implementation details
- Temporary debugging notes
- Information already in progress.txt

Only update AGENTS.md if you have **genuinely reusable knowledge** that would help future work in that directory.

## Quality Requirements
- ALL commits must pass your project's quality checks (typecheck, lint, test)
- Do NOT commit broken code
- Keep changes focused and minimal
- Follow existing code patterns

## Browser Testing (If Available)

For any story that changes UI, verify it works in the browser if you have browser testing tools configured (e.g., via MCP):

1. Navigate to the relevant page
2. Verify the UI changes work as expected
3. Take a screenshot if helpful for the progress log

If no browser tools are available, note in your progress report that manual browser verification is needed.

## Stop Condition

After completing a user story, check if ALL stories have passes: true.

If ALL stories are complete and passing, reply with:
<promise>COMPLETE</promise>

If there are still stories with passes: false, end your response normally (another iteration will pick up the next story).

## Important
- Work on ONE story per iteration
- Commit frequently
- Keep CI green
- Read the Codebase Patterns section in progress.txt before starting

## Architecture Guardrails
- Preserve the canonical inventory fields defined in prd.json
- Preserve these canonical fields as stable domain concepts:
  - Item
  - Placa Anterior
  - Descrição
  - Marca
  - Modelo
  - NS
  - Local
  - CC
  - Complemento
  - Observação
- Do not introduce tenant-specific logic directly in the core engine
- Prefer configuration-driven behavior over branching by tenant
- Keep API, validation rules, report rendering, file parsing, and job orchestration separated
- New behavior should be added through reusable abstractions when possible
- Prefer extending the generic engine over creating tenant-specific execution flows

## Scope Control
- Work on exactly one story per iteration
- Do not refactor unrelated areas
- Do not start the next story
- If you find debt outside the current story, document it in progress.txt
- Make the smallest correct architectural move that satisfies the current story

## Multi-Tenant Rules
- Treat tenant-specific behavior as configuration unless code specialization is truly necessary
- Do not hardcode tenant names in the validation core
- Keep a working default tenant
- Update seed tenant examples when tenant-facing config changes
- Tenant-specific variation should prefer config for:
  - column mapping
  - enabled/disabled rules
  - thresholds
  - categories
  - critical checks
  - LLM settings
  - prompt selection

## Domain Preservation

- Preserve canonical field meanings
- Preserve the distinction between collected items and zero-created items
- Preserve these derived concepts:
  - flag_item_coletado
  - flag_item_cadastrado_do_zero
- Do not rename or reinterpret core domain concepts unless required by the story
- Preserve deterministic validation as first-class behavior
- Preserve category-aware validation behavior
- Preserve job-based processing as a core system capability
- Preserve operations-friendly outputs and reporting

## Rule Design Guidance

- Rules should operate on normalized canonical data
- Prefer a reusable rule contract such as:
  - applies(context) -> bool
  - validate(context) -> list[Issue]
- Rules should not directly:
  - parse uploaded files
  - handle FastAPI request objects
  - generate reports
  - orchestrate jobs
  - depend on tenant names
- Prefer registry-based rule loading over hardcoded execution chains

## Engine Design Guidance
- Normalize source input into canonical field names before rule execution
- Derive shared flags and shared context before running row-level rules
- Load rules from tenant configuration
- Keep one generic validation engine
- Do not duplicate engine logic per tenant
- If a story introduces a new shared concept, place it in the domain/core layer instead of embedding it in a route or worker

## API Guidance
- Keep API handlers thin
- API endpoints should delegate orchestration to services
- API code should not contain validation business rules
- API code should not know tenant-specific rule details beyond selecting the tenant/config

## Reporting Guidance
- Reports should be practical for operational correction workflows
- Report formatting should be separated from validation logic
- Avoid coupling report generation to specific rule internals more than necessary
- If a validation issue needs to appear in reports, prefer structured issue data over report-specific logic inside rules

## Failure Handling
- Do not commit if required checks fail
- If failures are unrelated and pre-existing, document them clearly in progress.txt
- Only mark passes: true when the story is fully complete and checks pass
- If a story is partially implemented, leave passes: false and explain the gap in progress.txt and/or prd.json notes when appropriate

## Requirement Discipline
- Do not invent features outside the current story or PRD
- Use the most conservative valid interpretation of ambiguous requirements
- Record assumptions in progress.txt
- If a shortcut is necessary to unblock the current story, document that it is a temporary bridge rather than silently treating it as final architecture

## Testing Expectations
- Prefer focused tests for the layer touched by the story
- For core or rule changes, add or update automated tests
- For tenant config changes, test valid and invalid loading paths when relevant
- For API changes, keep handlers thin and test behavior at the appropriate layer
- For job changes, verify lifecycle transitions and persisted metadata
- Do not skip tests for shared abstractions that will affect future stories

## Project Structure Intent

As the codebase evolves, prefer this separation:

- app/core/ for canonical domain, tenant config, context, issues, engine, registry
- app/rules/ for rule implementations
- app/services/ for orchestration services
- app/api/ for FastAPI routes and schemas
- app/workers/ for job/background processing
- app/tenants/ for tenant configs and prompt files
- tests/ mirroring application structure

Do not create unnecessary top-level directories if an existing module is the right home.

## Commit Discipline
- Commit only after checks pass
- Keep the commit focused on the current story
- The commit message must be exactly:
  - feat: [Story ID] - [Story Title]

## End-of-Iteration Expectations

At the end of the iteration:

- ensure progress.txt was appended, not rewritten
- ensure prd.json reflects the story status accurately
- ensure reusable learnings are promoted to ## Codebase Patterns only when they are truly general
- ensure any AGENTS.md updates contain reusable local knowledge, not story notes
