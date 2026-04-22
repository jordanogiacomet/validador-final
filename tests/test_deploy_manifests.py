from pathlib import Path
from typing import Any

import yaml

K8S_DIR = Path(__file__).resolve().parents[1] / "deploy" / "k8s"


def _load_k8s_documents() -> list[dict[str, Any]]:
    documents: list[dict[str, Any]] = []
    for path in sorted(K8S_DIR.glob("*.yaml")):
        with path.open(encoding="utf-8") as manifest_file:
            for document in yaml.safe_load_all(manifest_file):
                if isinstance(document, dict) and document.get("kind"):
                    documents.append(document)
    return documents


def _documents_by_kind(kind: str) -> list[dict[str, Any]]:
    return [document for document in _load_k8s_documents() if document.get("kind") == kind]


def _container_by_name(deployment: dict[str, Any], name: str) -> dict[str, Any]:
    containers = deployment["spec"]["template"]["spec"]["containers"]
    return next(container for container in containers if container["name"] == name)


def test_k8s_manifests_do_not_depend_on_fixed_ips_nodeports_or_storage_class() -> None:
    combined_manifest = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(K8S_DIR.glob("*.yaml"))
    )

    assert "192.168." not in combined_manifest
    assert "30091" not in combined_manifest
    assert "30092" not in combined_manifest
    assert "NodePort" not in combined_manifest
    assert "nodePort" not in combined_manifest
    assert "nfs-client" not in combined_manifest


def test_services_are_internal_and_ingress_provides_tls_exposure() -> None:
    services = _documents_by_kind("Service")

    assert services
    assert {service["spec"].get("type", "ClusterIP") for service in services} == {
        "ClusterIP"
    }

    ingresses = _documents_by_kind("Ingress")
    assert len(ingresses) == 1
    ingress = ingresses[0]
    assert ingress["spec"]["tls"][0]["secretName"] == "validador-final-tls"

    backend_services = {
        path["backend"]["service"]["name"]
        for rule in ingress["spec"]["rules"]
        for path in rule["http"]["paths"]
    }
    assert backend_services == {"validador-final", "validador-final-frontend"}


def test_deployments_are_scaled_and_use_deployment_safe_probes() -> None:
    deployments = {
        deployment["metadata"]["name"]: deployment
        for deployment in _documents_by_kind("Deployment")
    }

    assert deployments["validador-final"]["spec"]["replicas"] >= 2
    assert deployments["validador-final-worker"]["spec"]["replicas"] >= 2
    assert deployments["validador-final-frontend"]["spec"]["replicas"] >= 2

    api_container = _container_by_name(deployments["validador-final"], "api")
    assert api_container["readinessProbe"]["httpGet"]["path"] == "/readyz"
    assert api_container["livenessProbe"]["httpGet"]["path"] == "/livez"

    worker_container = _container_by_name(deployments["validador-final-worker"], "worker")
    assert "exec" in worker_container["readinessProbe"]
    assert "exec" in worker_container["livenessProbe"]
