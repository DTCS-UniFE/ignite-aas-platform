# dashboard_api.py
from fastapi import FastAPI, HTTPException, Body
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import json, requests, yaml, os, base64

# URL base per i servizi AAS e di migrazione (da adattare in base all'ambiente)
# Per test locale: AAS_BASE_URL = "http://localhost:8080"

# BASE_URL = "http://192.168.0.109"
BASE_URL = os.getenv("BASE_URL", "http://localhost")
# ricordarsi di lanciare:
# export BASE_URL=http://<IP_DEL_NODO_MASTER>
# prima di avviare il dashboard_api.py in cluster (altrimenti rimane hardcoded su localhost)
# 
# uvicorn dashboard_api:app --reload --host 0.0.0.0 --port 5050

app = FastAPI(title="K3d Cluster Dashboard")

# --- CORS - Permette al browser di fare richieste ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # in produzione restringere
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Funzione per interrogare API server usando kubeconfig ---
def kube_http_json(resource, all_namespaces=False):
    kubeconfig_path = os.path.expanduser("~/.kube/config")
    with open(kubeconfig_path) as f:
        config = yaml.safe_load(f)

    ctx_name = config["current-context"]
    ctx = next(c for c in config["contexts"] if c["name"] == ctx_name)
    cluster_name = ctx["context"]["cluster"]
    user_name = ctx["context"]["user"]

    cluster = next(c for c in config["clusters"] if c["name"] == cluster_name)["cluster"]
    user = next(u for u in config["users"] if u["name"] == user_name)["user"]

    server = cluster["server"]

    ca_cert = None
    client_cert = None
    client_key = None

    if "certificate-authority-data" in cluster:
        ca_cert_data = base64.b64decode(cluster["certificate-authority-data"])
        with open("/tmp/ca.crt", "wb") as f:
            f.write(ca_cert_data)
        ca_cert = "/tmp/ca.crt"

    if "client-certificate-data" in user and "client-key-data" in user:
        client_cert_data = base64.b64decode(user["client-certificate-data"])
        client_key_data = base64.b64decode(user["client-key-data"])
        with open("/tmp/client.crt", "wb") as f:
            f.write(client_cert_data)
        with open("/tmp/client.key", "wb") as f:
            f.write(client_key_data)
        client_cert = "/tmp/client.crt"
        client_key = "/tmp/client.key"

    cert_tuple = (client_cert, client_key) if client_cert and client_key else None

    headers = {}
    if "token" in user:
        headers["Authorization"] = f"Bearer {user['token']}"

    url = f"{server}/api/v1/{resource}"
    if resource == "pods" and all_namespaces:
        url += "?limit=500"

    try:
        resp = requests.get(url, headers=headers, verify=ca_cert, cert=cert_tuple, timeout=5)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        raise RuntimeError(f"Errore richiesta API Kubernetes: {e}")

# --- Sostituzione kubectl_json ---
def kubectl_json(args):
    if "nodes" in args:
        return kube_http_json("nodes")
    elif "pods" in args:
        return kube_http_json("pods", all_namespaces="--all-namespaces" in args)
    else:
        raise ValueError(f"Resource non supportata: {args}")

# --- ENDPOINT API ---
@app.get("/api/cluster")
def cluster_state():
    try:
        nodes_data = kubectl_json(["get", "nodes"])
        pods_data = kubectl_json(["get", "pods", "--all-namespaces"])
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    pods_by_node = {}
    for p in pods_data.get("items", []):
        node_name = p.get("spec", {}).get("nodeName") or "<unscheduled>"
        pods_by_node.setdefault(node_name, []).append({
            "name": p.get("metadata", {}).get("name"),
            "namespace": p.get("metadata", {}).get("namespace"),
            "status": p.get("status", {}).get("phase"),
            "labels": p.get("metadata", {}).get("labels", {}),
        })

    servers = []
    workers = []

    for item in nodes_data.get("items", []):
        name = item["metadata"]["name"]

        ########################################################################### Modifica per test su cluster k3d
        # role = "master" if "server" in name else "worker" # <-- Logica originale basata su nome nodo
        labels = item.get("metadata", {}).get("labels", {})

        is_control_plane = (
            labels.get("node-role.kubernetes.io/control-plane") is not None
            or labels.get("node-role.kubernetes.io/master") is not None
        )

        role = "master" if is_control_plane else "worker"
        ########################################################################### Fine modifica per test su cluster k3d
        conditions = item.get("status", {}).get("conditions", [])
        status = "Unknown"
        for c in conditions:
            if c.get("type") == "Ready":
                status = "Ready" if c.get("status") == "True" else "NotReady"
                break

        node_obj = {
            "name": name,
            "role": role,
            "status": status,
            "labels": item.get("metadata", {}).get("labels", {}),
            "capacity": item.get("status", {}).get("capacity", {}),
            "allocatable": item.get("status", {}).get("allocatable", {}),
            "pods": pods_by_node.get(name, []),
        }

        # rileva AAS
        aas_running = any(
            ("test-aas" in p["name"]) or ("aas" in (p.get("labels") or {}))
            for p in node_obj["pods"]
        )
        node_obj["aas_running"] = aas_running

        # se AAS è attivo, recupera info braccio
        aas_info = None
        if aas_running:
            try:
                # res_state = requests.get("http://localhost:8080/aas/state", timeout=1)        # <-- URL hardcoded per test locale
                res_state = requests.get(f"{BASE_URL}/aas/state", timeout=1)                    # URL dinamico per test in cluster
                state = res_state.json() if res_state.ok else {}

                # res_static = requests.get("http://localhost:8080/aas/static", timeout=1)      # <-- URL hardcoded per test locale
                res_static = requests.get(f"{BASE_URL}/aas/static", timeout=1)                  # URL dinamico per test in cluster
                static_info = res_static.json() if res_static.ok else {}

                aas_info = {"static": static_info, "state": state}
            except Exception:
                aas_info = {"error": "Impossibile ottenere info AAS"}

        node_obj["aas_info"] = aas_info

        if role == "master":
            servers.append(node_obj)
        else:
            workers.append(node_obj)

    mapping = {}
    if servers:
        for i, w in enumerate(workers):
            mapping[w["name"]] = servers[i % len(servers)]["name"]
    else:
        for w in workers:
            mapping[w["name"]] = None

    return {
        "cluster": nodes_data.get("kind", "k3d-cluster"),
        "servers": servers,
        "workers": workers,
        "mapping": mapping
    }

#######################################################################################################

# --- ENDPOINT per la migrazione AAS ---
@app.post("/api/migrate-aas")
def migrate_aas(data: dict = Body(...)):
    """
    Riceve un JSON del tipo {"target": "nome_nodo_worker"}
    e inoltra la richiesta al servizio migrate-app.py in ascolto su :5000
    """
    target_node = data.get("target")
    if not target_node:
        raise HTTPException(status_code=400, detail="Target node mancante")

    try:
        # Nome dell'app AAS da migrare 
        app_name = "test-aas"

        # Inoltra la richiesta al servizio di migrazione
        res = requests.post(
            f"{BASE_URL}:5000/migrate",
            headers={"Content-Type": "application/json"},
            json={"appName": app_name, "targetNode": target_node},
            timeout=10
        )
        res.raise_for_status()

        # Restituisce la risposta 
        return {"message": f"Migrazione avviata: {res.text}"}

    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=500, detail=f"Errore durante la migrazione: {e}")


#####################################################################################################

# --- FILE STATICI ---
app.mount("/", StaticFiles(directory="dashboard", html=True), name="dashboard")

