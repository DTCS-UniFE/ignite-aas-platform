# FlaskApp Operator & Dynamic Rescheduler on K3d

This project demonstrates how to dynamically orchestrate a Flask application using Valkey (Redis-compatible) for state persistence, in a local Kubernetes cluster based on **k3d**.

## Technologies Used

- [k3d](https://k3d.io/) – Local Kubernetes (K3s) cluster in Docker
- [Kopf](https://kopf.readthedocs.io/en/stable/) – Python operator framework
- **CRD** (Custom Resource Definition) – Custom resource to model an AAS
- [Valkey](https://valkey.io/) – In-memory database (Redis-compatible)
- **NFS** – For shared persistence between nodes
- [FastAPI](https://fastapi.tiangolo.com/) – API for workload migration

## Prerequisites

- A Linux system
- k3d
- kubectl
- Docker

## 1. Setup NFS Server
For this demo, an NFS server on Docker was used. Linux is required.

> [!NOTE]  
> The NFS container **needs** to run as **privileged**. \
> The NFS' [docker-compose.yml](nfs/docker-compose.yml) already has this option set.

### Startup
Navigate to the folder containing the project files:
```bash
cd /path/to/this-repo
```
Then:
```bash
cd nfs
docker compose up
```

## 2. Create the k3d cluster
Navigate to the folder containing the project files:
```bash
cd /path/to/this-repo
```

Use the k3d-cluster.yaml file to create a cluster with 3 servers and 3 agents:
```bash
k3d cluster create --config k3d-cluster.yaml
```
> [!NOTE]
> In our configuration we also tell k3d to map the load balancer's port 80 to out host's port 8080. \
> This is needed for our Ingress.

Check that the nodes are active:
```bash
kubectl get nodes -o wide
```

## 3. Create a venv for running the operator and REST API for AAS migration
```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## 4. k3d operations for app deployment
Navigate to the folder containing the project files:
```bash
cd /path/to/this-repo
```

### Deploy the Persistent Volume resource for Valkey
```bash
kubectl apply -f manifest/nfs-pv.yaml
```

### Apply the Custom Resource Definition (CRD)
```bash
kubectl apply -f manifest/crd.yaml
```

### Start the Kopf Operator (outside the cluster)
Start the operator and leave it running in a terminal:
```bash
kopf run kopf-operator.py
```
> [!WARNING]
> The operator file cannot be named "operator.py" because it conflicts with Python's stdlib "operator".

### Create an application with the Custom Resource
```bash
kubectl apply -f manifest/aas.yaml
```

### Create the Ingress to expose the AAS
```bash
kubectl apply -f manifest/ingress.yaml
```

### Test to verify the AAS robotic arm functionality
> [!IMPORTANT]
> 8080 is our chosen port for forwarding, see [cluster creation](#2-create-the-k3d-cluster).

- For static information:
  ```bash
  curl http://localhost:8080/aas/static
  ```
- For state information:
  ```bash
  curl http://localhost:8080/aas/state
  ```

- To command the arm movement:
  ```bash
  curl -X POST http://localhost:8080/aas/move \
      -H "Content-Type: application/json" \
      -d '{"x": 1.0, "y": 2.0, "z": 3.0}'
  ```

## 5. Move the robotic arm app between nodes
Start the REST service for migration management:
```bash
python migrate-app.py
```

Send a request to move the app to another node:
```bash
curl -X POST http://localhost:5000/migrate \
  -H "Content-Type: application/json" \
  -d '{"appName": "test-aas", "targetNode": "k3d-mycluster-agent-1"}'
```

## 6. Check if migration was successful
> [!TIP]
> To check if (when) the node is migrated successfully you can either use a GUI application like [Lens](https://k8slens.dev/) or by running `kubectl get pods -o wide -w`.

Run:
```bash
curl http://localhost:8080/aas/state
```
You should see:
```json
{"position":[1.0,2.0,3.0],"status":"idle"}
```
Confirming the application was migrated and state was successfully restored.

## 7. Stop everything
If you want to stop everything, you should:
- Stop kopf-operator and migrate-app with a CTRL-C
- Run `k3d cluster delete mycluster`
- And **only** after that, you can stop the NFS docker compose with a CTRL-C.
  - If you also want to delete all Valkey data:
  ```bash
  cd nfs
  rm -rf data/
  ```
