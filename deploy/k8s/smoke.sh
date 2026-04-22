#!/usr/bin/env sh
set -eu

NAMESPACE="${NAMESPACE:-validador-final}"
API_URL="${API_URL:-}"
FRONTEND_URL="${FRONTEND_URL:-}"

kubectl -n "$NAMESPACE" rollout status deployment/validador-final
kubectl -n "$NAMESPACE" rollout status deployment/validador-final-worker
kubectl -n "$NAMESPACE" rollout status deployment/validador-final-frontend

if [ -n "$API_URL" ]; then
  curl -fsS "$API_URL/readyz" >/dev/null
fi

if [ -n "$FRONTEND_URL" ]; then
  curl -fsS "$FRONTEND_URL/" >/dev/null
fi
