# Kubernetes Deploy

These manifests are environment-neutral. They avoid fixed NodePorts, private IPs, and
storage-class names so each environment can publish the same application through its own ingress,
TLS secret, image registry, and storage class.

Apply with Kustomize after setting environment-specific patches:

```bash
kubectl kustomize deploy/k8s | kubectl apply -f -
```

Patch these values per environment before rollout:

- `validador-final-env` ConfigMap:
  - `VALIDATOR_FRONTEND_URL`
  - `VALIDATOR_FRONTEND_ORIGINS`
  - `VALIDATOR_FRONTEND_ORIGIN_REGEX`
  - `VALIDATOR_FRONTEND_API_BASE_URL`
  - `VALIDATOR_OFFICIAL_TENANT_ID`
- `ingress.yaml` hosts and `secretName`
- deployment images `validador-final-api` and `validador-final-frontend`
- PVC `storageClassName` only when the cluster has no suitable default RWX storage class

The frontend container writes `/app/public/runtime-config.js` at startup from
`VALIDATOR_FRONTEND_API_BASE_URL`, so the same built image can move between environments without
rebuilding for a different API URL.

The API and frontend default to two replicas. Workers also default to two replicas and rely on the
SQLite-backed `JobService` claim/lease path introduced for dedicated worker mode; keep
`VALIDATOR_SQLITE_PATH` on the shared results volume.

Readiness and liveness are intentionally separate:

- API readiness uses `/readyz`, which runs storage and policy checks.
- API liveness uses `/livez`, which only confirms the process can answer.
- Worker probes validate that the dedicated worker can build against SQLite-backed storage.

After applying an overlay, run:

```bash
NAMESPACE=validador-final \
API_URL=https://api.example.com \
FRONTEND_URL=https://validador.example.com \
deploy/k8s/smoke.sh
```
