const occupancyEl = document.getElementById("occupancy");
const todayInEl = document.getElementById("today-in");
const todayOutEl = document.getElementById("today-out");
const connectionEl = document.getElementById("connection");
const correctionForm = document.getElementById("correction-form");
const correctionInput = document.getElementById("correction-value");
const cameraSection = document.getElementById("camera-section");
const cameraWrap = document.getElementById("camera-wrap");
const cameraImg = document.getElementById("camera-stream");
const cameraLine = document.getElementById("camera-line");
const cameraToggle = document.getElementById("camera-toggle");
const historyButtons = document.getElementById("history-buttons");
const historySummary = document.getElementById("history-summary");

let chart = null;
let historyChart = null;
let cameraStreaming = false;
let activePeriod = "current_week";
// Periods that include today and therefore change as new counts arrive.
const LIVE_PERIODS = new Set(["current_week", "current_month"]);

function setConnection(live) {
  connectionEl.classList.toggle("status--live", live);
  connectionEl.textContent = live ? "Live" : "Getrennt";
}

async function fetchJson(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${url}: ${response.status}`);
  return response.json();
}

function renderStatus(status) {
  occupancyEl.textContent = status.occupancy;
  todayInEl.textContent = status.today_in;
  todayOutEl.textContent = status.today_out;
  cameraSection.hidden = !status.preview_enabled;
  if (status.preview_enabled) {
    positionCameraLine(status.line_axis, status.line_position);
  }
}

function positionCameraLine(axis, position) {
  const pct = `${(position * 100).toFixed(1)}%`;
  if (axis === "y") {
    cameraLine.className = "camera-line camera-line--horizontal";
    cameraLine.style.top = pct;
    cameraLine.style.left = "0";
  } else {
    cameraLine.className = "camera-line camera-line--vertical";
    cameraLine.style.left = pct;
    cameraLine.style.top = "0";
  }
}

function setCameraStreaming(on) {
  cameraStreaming = on;
  cameraWrap.hidden = !on;
  cameraToggle.textContent = on ? "Kamerabild ausblenden" : "Kamerabild anzeigen";
  if (on) {
    // cache-bust so a re-open reconnects instead of reusing a closed stream
    cameraImg.src = `/api/camera/stream?t=${Date.now()}`;
  } else {
    cameraImg.removeAttribute("src");
  }
}

function barChart(canvasId, existing, labels, inData, outData, maxTicks) {
  if (existing) {
    // Replace only the data, not the datasets, so a visibility toggled via the
    // legend survives live refreshes.
    existing.data.labels = labels;
    existing.data.datasets[0].data = inData;
    existing.data.datasets[1].data = outData;
    existing.update();
    return existing;
  }
  const datasets = [
    { label: "Eintritte", data: inData, backgroundColor: "#4cc38a", borderRadius: 3 },
    // Exits hidden by default: the relevant trend is visitors entering. The
    // legend stays clickable to reveal exits when needed.
    { label: "Austritte", data: outData, backgroundColor: "#e5704c", borderRadius: 3, hidden: true },
  ];
  return new Chart(document.getElementById(canvasId), {
    type: "bar",
    data: { labels, datasets },
    options: {
      responsive: true,
      animation: false,
      scales: {
        x: {
          grid: { display: false },
          ticks: { color: "#8b95a3", maxTicksLimit: maxTicks },
        },
        y: {
          beginAtZero: true,
          grid: { color: "#232a33" },
          ticks: { color: "#8b95a3", precision: 0 },
        },
      },
      plugins: { legend: { labels: { color: "#e6e9ee", boxWidth: 12 } } },
    },
  });
}

function renderChart(stats) {
  const labels = stats.hours.map((h) => String(h.hour).padStart(2, "0"));
  chart = barChart(
    "hourly-chart",
    chart,
    labels,
    stats.hours.map((h) => h.in),
    stats.hours.map((h) => h.out),
    12,
  );
}

function formatDay(iso) {
  const [, month, day] = iso.split("-");
  return `${day}.${month}.`;
}

function renderHistory(data) {
  const labels = data.days.map((d) => formatDay(d.date));
  historyChart = barChart(
    "history-chart",
    historyChart,
    labels,
    data.days.map((d) => d.in),
    data.days.map((d) => d.out),
    16,
  );
  const totalIn = data.days.reduce((sum, d) => sum + d.in, 0);
  const totalOut = data.days.reduce((sum, d) => sum + d.out, 0);
  const range =
    data.start === data.end
      ? formatDay(data.start)
      : `${formatDay(data.start)}–${formatDay(data.end)}`;
  historySummary.textContent = `${range} · ${totalIn} Eintritte · ${totalOut} Austritte`;
}

async function loadHistory(period) {
  activePeriod = period;
  for (const button of historyButtons.querySelectorAll("button")) {
    button.classList.toggle("active", button.dataset.period === period);
  }
  try {
    renderHistory(await fetchJson(`/api/stats/history?period=${period}`));
  } catch (error) {
    console.error("history failed", error);
  }
}

async function refresh() {
  try {
    const [status, stats] = await Promise.all([
      fetchJson("/api/status"),
      fetchJson("/api/stats/today"),
    ]);
    renderStatus(status);
    renderChart(stats);
  } catch (error) {
    console.error("refresh failed", error);
  }
}

function handleMessage(message) {
  if (typeof message.occupancy === "number") {
    occupancyEl.textContent = message.occupancy;
  }
  if (message.type === "count") {
    refresh();
    if (LIVE_PERIODS.has(activePeriod)) loadHistory(activePeriod);
  }
}

function connectWebSocket() {
  const protocol = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${protocol}://${location.host}/ws`);
  ws.onopen = () => setConnection(true);
  ws.onclose = () => {
    setConnection(false);
    setTimeout(connectWebSocket, 3000);
  };
  ws.onmessage = (event) => handleMessage(JSON.parse(event.data));
}

cameraToggle.addEventListener("click", () => setCameraStreaming(!cameraStreaming));

historyButtons.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-period]");
  if (button) loadHistory(button.dataset.period);
});

correctionForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const value = Number(correctionInput.value);
  if (!Number.isInteger(value) || value < 0) return;
  await fetch("/api/occupancy", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ value }),
  });
  correctionInput.value = "";
});

refresh();
loadHistory(activePeriod);
connectWebSocket();
setInterval(refresh, 60000);
