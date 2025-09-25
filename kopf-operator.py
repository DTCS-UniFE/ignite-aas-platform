import kopf
from kubernetes import client, config


# Load kube-config only once at startup
def _init_kube():
    # First try in-cluster config (Pod). If it fails, use local kubeconfig.
    try:
        config.load_incluster_config()
    except Exception:
        config.load_kube_config()
    return client.AppsV1Api(), client.CoreV1Api()


k8s_apps_api, k8s_core_api = _init_kube()


@kopf.on.create("igni.te", "v1", "aass")
def create_app(body, spec, **kwargs):
    name = body["metadata"]["name"]
    namespace = body["metadata"]["namespace"]
    image = spec["image"]
    target_node = spec.get("targetNode")
    valkey_name = spec.get("valkeyName", f"{name}-valkey")
    labels = {"app": name}

    app_deployment = {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {"name": name},
        "spec": {
            "replicas": 1,
            "selector": {"matchLabels": labels},
            "template": {
                "metadata": {"labels": labels},
                "spec": {
                    "containers": [
                        {
                            "name": name,
                            "image": image,
                            "ports": [{"containerPort": 8000}],
                            "env": [
                                {"name": "VALKEY_HOST", "value": valkey_name},
                                {"name": "VALKEY_PORT", "value": "6379"},
                            ],
                        }
                    ],
                    "imagePullSecrets": [{"name": "ghcr-secret"}],
                    "nodeSelector": (
                        {"kubernetes.io/hostname": target_node} if target_node else {}
                    ),
                },
            },
        },
    }

    valkey_labels = {"app": valkey_name}
    valkey_deployment = {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {"name": valkey_name},
        "spec": {
            "replicas": 1,
            "selector": {"matchLabels": valkey_labels},
            "template": {
                "metadata": {"labels": valkey_labels},
                "spec": {
                    "containers": [
                        {
                            "name": "valkey",
                            "image": "valkey/valkey:8.1-alpine",
                            "ports": [{"containerPort": 6379}],
                            "volumeMounts": [{"mountPath": "/data", "name": "data"}],
                            "command": [
                                "valkey-server",
                                "--appendonly",
                                "yes",  # Use AOF mode (more reliable than RDB)
                                "--appendfsync",
                                "always",  # Dump to file on every write oation
                                "--dir",
                                "/data",  # PVC volume path
                            ],
                        }
                    ],
                    "volumes": [
                        {
                            "name": "data",
                            "persistentVolumeClaim": {
                                "claimName": f"{valkey_name}-pvc"
                            },
                        }
                    ],
                    "nodeSelector": (
                        {"kubernetes.io/hostname": target_node} if target_node else {}
                    ),
                },
            },
        },
    }

    pvc = {
        "apiVersion": "v1",
        "kind": "PersistentVolumeClaim",
        "metadata": {"name": f"{valkey_name}-pvc"},
        "spec": {
            "accessModes": ["ReadWriteMany"],
            "resources": {"requests": {"storage": "1Gi"}},
            "volumeName": "valkey-nfs-pv",
            "storageClassName": "",  # <-- disable implicit storage class, we use our existing NFS
        },
    }

    valkey_service = {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {"name": valkey_name},
        "spec": {
            "selector": valkey_labels,
            "ports": [{"protocol": "TCP", "port": 6379, "targetPort": 6379}],
        },
    }

    service = {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {"name": name},
        "spec": {
            "selector": labels,
            "ports": [{"protocol": "TCP", "port": 80, "targetPort": 8000}],
        },
    }

    k8s_apps_api.create_namespaced_deployment(namespace=namespace, body=app_deployment)
    k8s_core_api.create_namespaced_service(namespace=namespace, body=service)
    k8s_core_api.create_namespaced_persistent_volume_claim(
        namespace=namespace, body=pvc
    )
    k8s_apps_api.create_namespaced_deployment(
        namespace=namespace, body=valkey_deployment
    )
    k8s_core_api.create_namespaced_service(namespace=namespace, body=valkey_service)

    kopf.info(
        body, reason="Created", message=f"Created {name} with Valkey {valkey_name}"
    )


@kopf.on.update("igni.te", "v1", "aass")
def update_app(body, spec, **kwargs):
    name = body["metadata"]["name"]
    namespace = body["metadata"]["namespace"]
    target_node = spec.get("targetNode")
    valkey_name = spec.get("valkeyName", f"{name}-valkey")

    patch = {
        "spec": {
            "template": {
                "spec": {"nodeSelector": {"kubernetes.io/hostname": target_node}}
            }
        }
    }

    k8s_apps_api.patch_namespaced_deployment(name, namespace, patch)
    k8s_apps_api.patch_namespaced_deployment(valkey_name, namespace, patch)

    kopf.info(
        body,
        reason="Updated",
        message=f"Moved app {name} and Valkey {valkey_name} to node {target_node}",
    )
