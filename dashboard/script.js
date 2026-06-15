const API = "/api/cluster";
const REFRESH_MS = 10000; // 10 secondi

async function fetchCluster() {
  const res = await fetch(API);
  if (!res.ok) throw new Error("API error: " + res.status);
  return await res.json();
}

function createNodeCard(node) {
  const div = document.createElement("div");
  div.className = "node " + (node.role === "master" ? "master" : "worker");
  div.id = `node-${CSS.escape(node.name)}`;

  const h = document.createElement("h3");
  h.textContent = node.name;
  div.appendChild(h);

  const rolep = document.createElement("p");
  rolep.innerHTML = `<strong>Ruolo:</strong> ${node.role}`;
  div.appendChild(rolep);

  const statusp = document.createElement("p");
  statusp.innerHTML = `<strong>Status:</strong> ${node.status}`;
  div.appendChild(statusp);

  const pods = document.createElement("p");
  pods.innerHTML = `<strong>Pods:</strong> ${node.pods.length}`;
  div.appendChild(pods);

  if (node.aas_running) {
    const aas = document.createElement("div");
    aas.className = "aas";
    // aas.textContent = "AAS: ✅ in esecuzione qui";
    aas.innerHTML = `AAS: <img src="img/robotic-arm.png" style="width:20px; height:20px; vertical-align:middle; margin-right:4px;"> in esecuzione qui`;
    div.appendChild(aas);

    // crea popup nascosto
    const popup = document.createElement("div");
    popup.className = "aas-popup";
    let popupHTML = "";

    if (node.aas_info && node.aas_info.static) {
      const s = node.aas_info.static;
      popupHTML += `<p><strong>Braccio robotico:</strong><br>
        ${s.asset_id} - ${s.type}<br>${s.manufacturer}, ${s.model}</p>`;
    }

    if (node.aas_info && node.aas_info.state && node.aas_info.state.position) {
      const pos = node.aas_info.state.position;
      popupHTML += `<p><strong>Posizione:</strong><br>x=${pos[0]}, y=${pos[1]}, z=${pos[2]}</p>`;
    }

    popup.innerHTML = popupHTML || "<p>Nessuna informazione AAS disponibile</p>";
    div.appendChild(popup);

    // mostra/nasconde popup al passaggio del mouse
    div.addEventListener("mouseenter", () => {
      popup.style.display = "block";
    });
    div.addEventListener("mouseleave", () => {
      popup.style.display = "none";
    });
  }

  return div;
}

function layoutAndDraw(cluster) {
  const container = document.getElementById("nodes-area");
  container.innerHTML = "";

  const masters = cluster.servers;
  const workers = cluster.workers;

  // master row
  const masterRow = document.createElement("div");
  masterRow.style.display = "flex";
  masterRow.style.gap = "24px";
  masterRow.style.width = "100%";
  masterRow.style.marginBottom = "30px";
  masters.forEach(m => masterRow.appendChild(createNodeCard(m)));
  container.appendChild(masterRow);

  // worker row
  const workerRow = document.createElement("div");
  workerRow.style.display = "flex";
  workerRow.style.flexWrap = "wrap";
  workerRow.style.gap = "24px";
  workerRow.style.width = "100%";
  workers.forEach(w => workerRow.appendChild(createNodeCard(w)));
  container.appendChild(workerRow);
}

// --- Tendina nodi worker ---
function updateWorkerDropdown(workers) {
  const select = document.getElementById("worker-select");
  select.innerHTML = `<option value="">-- scegli nodo --</option>`;
  workers.forEach(w => {
    const opt = document.createElement("option");
    opt.value = w.name;
    opt.textContent = w.name;
    select.appendChild(opt);
  });
}

// --- Aggiorna e recupera (fetch) il cluster ---
async function refresh() {
  try {
    document.getElementById("info").textContent = "Aggiornamento...";
    const cluster = await fetchCluster();
    document.getElementById("info").textContent = `Cluster: ${cluster.cluster} — servers: ${cluster.servers.length}, workers: ${cluster.workers.length}`;
    layoutAndDraw(cluster);
    updateWorkerDropdown(cluster.workers);
  } catch (err) {
    document.getElementById("info").textContent = "Errore: " + err.message;
    console.error(err);
    document.getElementById("nodes-area").innerHTML = "";
  }
}

// --- Pulsante Migrazione ---
document.getElementById("migrate-btn").addEventListener("click", async () => {
  const targetNode = document.getElementById("worker-select").value;
  const status = document.getElementById("migration-status");
  if (!targetNode) {
    status.textContent = "Seleziona un nodo worker!";
    return;
  }
  status.textContent = "Migrazione in corso...";
  try {
    const res = await fetch(`/api/migrate-aas`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ target: targetNode })
    });
    if (!res.ok) throw new Error("Errore API: " + res.status);
    const data = await res.json();
    status.textContent = data.message;
  } catch (err) {
    status.textContent = "Errore: " + err.message;
  }
});

refresh();
setInterval(refresh, REFRESH_MS);
