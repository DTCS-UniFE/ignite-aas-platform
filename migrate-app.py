from fastapi import FastAPI, HTTPException
from kubernetes import client, config
from kubernetes.client.exceptions import ApiException
from pydantic import BaseModel, Field

app = FastAPI(
    title="AAS Migration API",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


# Load kube-config only once at startup
def _init_kube():
    # First try in-cluster config (Pod). If it fails, use local kubeconfig.
    try:
        config.load_incluster_config()
    except Exception:
        config.load_kube_config()
    return client.CustomObjectsApi(), client.CoreV1Api()


k8s_custom_api, k8s_core_api = _init_kube()


class MigrateRequest(BaseModel):
    appName: str = Field(..., description="Name of the CR object")
    targetNode: str = Field(..., description="Destination node")
    namespace: str = Field("default", description="Kubernetes namespace")


class MigrateResponse(BaseModel):
    status: str


def _assert_node_exists(node_name: str) -> None:
    try:
        # If the node does not exist, the server responds with 404
        k8s_core_api.read_node(name=node_name)
    except ApiException as e:
        if e.status == 404:
            raise HTTPException(
                status_code=400,
                detail=f"targetNode '{node_name}' does not exist in the cluster",
            )
        if e.status == 403:
            # RBAC issue: the ServiceAccount cannot read nodes
            raise HTTPException(
                status_code=502,
                detail="Insufficient permissions to read nodes (403). Check ServiceAccount RBAC.",
            )
        # Other API errors (timeout, 5xx, etc.)
        raise HTTPException(
            status_code=502, detail=f"Kubernetes error (Nodes): {e.reason or e.status}"
        )


@app.post("/migrate", response_model=MigrateResponse)
def migrate_app(req: MigrateRequest):
    # Check that the target node exists in the cluster
    _assert_node_exists(req.targetNode)

    try:
        cr = k8s_custom_api.get_namespaced_custom_object(
            group="igni.te",
            version="v1",
            namespace=req.namespace,
            plural="aass",
            name=req.appName,
        )

        # Update the scheduling field
        cr.setdefault("spec", {})
        cr["spec"]["targetNode"] = req.targetNode

        k8s_custom_api.patch_namespaced_custom_object(
            group="igni.te",
            version="v1",
            namespace=req.namespace,
            plural="aass",
            name=req.appName,
            body=cr,
        )

        return MigrateResponse(
            status=f"{req.appName} (and Valkey) rescheduled to {req.targetNode}"
        )

    except ApiException as e:
        # Propagate HTTP code and error reason from the K8s API server
        detail = e.reason or "Kubernetes API error"
        status_code = e.status or 500
        raise HTTPException(status_code=status_code, detail=detail)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app=app, host="0.0.0.0", port=5000)
