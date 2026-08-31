// Hydroponics Dashboard frontend.
//
// Polls /api/devices and /api/devices/<id>/history on an interval, rendering
// one card per device with current readings and small per-metric line charts.
// Chart.js instances and card DOM nodes are created once and reused/updated
// on every refresh to avoid flicker and memory leaks.

const REFRESH_MS = (parseInt(document.body.dataset.refreshSeconds, 10) || 60) * 1000;

const cardElements = {}; // deviceId -> card root element
const chartInstances = {}; // "deviceId::metricKey" -> Chart instance

async function fetchJSON(url) {
  const res = await fetch(url);
  if (!res.ok) {
    throw new Error(`${url} -> HTTP ${res.status}`);
  }
  return res.json();
}

function formatTimestamp(iso) {
  if (!iso) return '';
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleString();
}

function formatValue(value) {
  if (value === null || value === undefined) return '\u2013';
  if (typeof value === 'number') {
    return Number.isInteger(value) ? String(value) : value.toFixed(1);
  }
  return String(value);
}

function statusClass(status, stale) {
  if (stale) return 'stale';
  if (!status) return '';
  if (status.startsWith('error')) return 'error';
  if (status === 'success') return 'success';
  return '';
}

function getOrCreateCard(device) {
  let card = cardElements[device.id];
  if (card) return card;

  const container = document.getElementById('devices');
  const loading = container.querySelector('.loading');
  if (loading) loading.remove();

  card = document.createElement('div');
  card.className = 'device-card';
  card.id = `device-card-${device.id}`;
  card.innerHTML = `
    <div class="device-card-header">
      <h2 class="device-name"></h2>
      <span class="status-badge"></span>
    </div>
    <div class="device-timestamp"></div>
    <div class="readings-grid"></div>
    <div class="charts-grid"></div>
    <div class="error-note" hidden></div>
  `;
  container.appendChild(card);
  cardElements[device.id] = card;
  return card;
}

function renderDeviceCard(device) {
  const card = getOrCreateCard(device);

  card.querySelector('.device-name').textContent = device.name || device.id;

  const badge = card.querySelector('.status-badge');
  badge.textContent = device.stale ? 'stale' : device.status || 'unknown';
  badge.className = `status-badge ${statusClass(device.status, device.stale)}`;

  card.querySelector('.device-timestamp').textContent = device.timestamp
    ? `Last update: ${formatTimestamp(device.timestamp)}`
    : 'No data yet';

  const readingsGrid = card.querySelector('.readings-grid');
  readingsGrid.innerHTML = '';
  const readingKeys = Object.keys(device.readings || {});
  if (readingKeys.length === 0) {
    readingsGrid.innerHTML = '<span class="reading-item">No readings</span>';
  } else {
    readingKeys.forEach((key) => {
      const reading = device.readings[key];
      const item = document.createElement('div');
      item.className = 'reading-item';
      item.innerHTML = `
        <span class="reading-label">${reading.label}</span>
        <span class="reading-value">${formatValue(reading.value)}${reading.unit ? ' ' + reading.unit : ''}</span>
      `;
      readingsGrid.appendChild(item);
    });
  }

  const errorNote = card.querySelector('.error-note');
  if (device.error) {
    errorNote.hidden = false;
    errorNote.textContent = device.stale
      ? `Showing last known data (${device.error})`
      : device.error;
  } else {
    errorNote.hidden = true;
  }

  return card;
}

function getOrCreateChart(card, deviceId, metricKey, metric) {
  const key = `${deviceId}::${metricKey}`;
  let chart = chartInstances[key];

  if (!chart) {
    const chartsGrid = card.querySelector('.charts-grid');
    const block = document.createElement('div');
    block.className = 'chart-block';
    block.id = `chart-block-${deviceId}-${metricKey}`;
    block.innerHTML = '<p class="chart-title"></p><canvas></canvas>';
    chartsGrid.appendChild(block);

    const canvas = block.querySelector('canvas');
    chart = new Chart(canvas, {
      type: 'line',
      data: {
        labels: [],
        datasets: [
          {
            data: [],
            borderColor: '#4cc38a',
            backgroundColor: 'rgba(76, 195, 138, 0.15)',
            pointRadius: 0,
            borderWidth: 2,
            tension: 0.25,
            spanGaps: true,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        plugins: { legend: { display: false } },
        scales: {
          x: { ticks: { display: false }, grid: { display: false } },
          y: { grid: { color: '#2a2e37' }, ticks: { color: '#9aa1ac', maxTicksLimit: 4 } },
        },
      },
    });
    chartInstances[key] = chart;
  }

  const block = document.getElementById(`chart-block-${deviceId}-${metricKey}`);
  block.querySelector('.chart-title').textContent = `${metric.label}${metric.unit ? ' (' + metric.unit + ')' : ''}`;

  return chart;
}

function renderDeviceCharts(deviceId, history) {
  const card = cardElements[deviceId];
  if (!card) return;

  const labels = (history.timestamps || []).map(formatTimestamp);
  Object.entries(history.metrics || {}).forEach(([metricKey, metric]) => {
    const chart = getOrCreateChart(card, deviceId, metricKey, metric);
    chart.data.labels = labels;
    chart.data.datasets[0].data = metric.values;
    chart.update();
  });
}

async function refreshAll() {
  try {
    const { devices } = await fetchJSON('/api/devices');

    devices.forEach((device) => renderDeviceCard(device));

    await Promise.all(
      devices.map(async (device) => {
        try {
          const history = await fetchJSON(`/api/devices/${encodeURIComponent(device.id)}/history`);
          renderDeviceCharts(device.id, history);
        } catch (err) {
          console.error(`Failed to load history for ${device.id}`, err);
        }
      })
    );

    document.getElementById('last-refreshed').textContent = `Updated ${new Date().toLocaleTimeString()}`;
  } catch (err) {
    console.error('Failed to load devices', err);
    document.getElementById('last-refreshed').textContent = `Refresh failed: ${err.message}`;
  }
}

refreshAll();
setInterval(refreshAll, REFRESH_MS);
