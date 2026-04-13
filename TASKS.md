TASKS
Foundation

[ ] Create canonical inventory domain model
[ ] Create TenantConfig
[ ] Create tenant loader
[ ] Create validation context
[ ] Create issue model
[ ] Create generic validation engine
[ ] Create rule registry

Deterministic Rules

[ ] Implement duplicate Item rule
[ ] Implement flag consistency rule
[ ] Implement zero-item empty Complemento rule
[ ] Implement zero-item short Complemento rule
[ ] Implement zero-item missing Marca rule
[ ] Implement zero-item missing Modelo rule
[ ] Implement relative complement quality comparison by item type

Category Rules

[ ] Implement category classification from tenant config
[ ] Implement category critical checks
[ ] Implement BTU-like validation for air conditioner category
[ ] Implement inches-like validation for TV category

LLM Audit

[ ] Create tenant-configurable LLM settings
[ ] Create tenant prompt loading
[ ] Implement optional LLM audit for zero-created items
[ ] Normalize LLM findings into structured issues
[ ] Handle LLM timeout and failure safely

Async Jobs

[ ] Create job model
[ ] Create job persistence
[ ] Support queued status
[ ] Support running status
[ ] Support completed status
[ ] Support failed status
[ ] Persist tenant_id in job metadata
[ ] Persist file path, result path, and report path
[ ] Persist row counters and error details

Reports

[ ] Create structured row validation output
[ ] Create duplicate items section
[ ] Create grouped operational problems section
[ ] Create PDF report generation
[ ] Create CSV or JSON output artifact

API

[ ] Create file upload endpoint
[ ] Accept tenant identifier in request
[ ] Start async validation job
[ ] Create job status endpoint
[ ] Create result download endpoints

Tests

[ ] Test tenant loading
[ ] Test flag derivation
[ ] Test duplicate Item validation
[ ] Test zero-item rules
[ ] Test category critical checks
[ ] Test job lifecycle