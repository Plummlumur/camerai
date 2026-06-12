const occupancyEl = document.getElementById("occupancy");
const todayInEl = document.getElementById("today-in");
const todayOutEl = document.getElementById("today-out");
const connectionEl = document.getElementById("connection");
const correctionForm = document.getElementById("correction-form");
const correctionInput = document.getElementById("correction-value");

let chart = null;

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
}

function renderChart(stats) {
  const labels = stats.hours.map((h) => `${String(h.hour).padStart(2, "0")}`);
  const datasets = [
    {
      label: "Eintritte",
      data: stats.hours.map((h) => h.in),
      backgroundColor: "#4cc38a",
      borderRadius: 3,
    },
    {
      label: "Austritte",
      data: stats.hours.map((h) => h.out),
      backgroundColor: "#e5704c",
      borderRadius: 3,
    },
  ];
  if (chart) {
    chart.data = { labels, datasets };
    chart.update();
    return;
  }
  chart = new Chart(document.getElementById("hourly-chart"), {
    type: "bar",
    data: { labels, datasets },
    options: {
      responsive: true,
      animation: false,
      scales: {
        x: {
          grid: { display: false },
          ticks: { color: "#8b95a3", maxTicksLimit: 12 },
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
  if (message.type === "count") refresh();
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
connectWebSocket();
setInterval(refresh, 60000);
