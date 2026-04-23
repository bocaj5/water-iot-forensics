/* Water Treatment IoT Forensic Monitor - Dashboard JS */

const POLL_INTERVAL = 8000;
const MAX_POINTS    = 60;         // points per sensor visible on chart
const HISTORY_MIN   = 10;         // only show readings from last N minutes

// ── Score Gauge (canvas arc) ──────────────────────────────────────────────────

function drawGauge(canvasId, score) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const w = canvas.width, h = canvas.height;
    ctx.clearRect(0, 0, w, h);

    const cx = w / 2, cy = h * 0.9, r = Math.min(w, h * 1.8) * 0.42;
    const startAngle = Math.PI, endAngle = 2 * Math.PI;

    // Background arc
    ctx.beginPath();
    ctx.arc(cx, cy, r, startAngle, endAngle);
    ctx.lineWidth = 12;
    ctx.strokeStyle = '#2c3e50';
    ctx.stroke();

    // Score arc (colour by severity — threshold now 0.65)
    const scoreAngle = startAngle + (score * Math.PI);
    const color = score < 0.45 ? '#27ae60' : score < 0.65 ? '#f39c12' : '#e74c3c';
    ctx.beginPath();
    ctx.arc(cx, cy, r, startAngle, scoreAngle);
    ctx.lineWidth = 12;
    ctx.strokeStyle = color;
    ctx.lineCap = 'round';
    ctx.stroke();

    // Threshold marker at 0.65
    const threshAngle = startAngle + (0.65 * Math.PI);
    const mx = cx + r * Math.cos(threshAngle), my = cy + r * Math.sin(threshAngle);
    ctx.beginPath();
    ctx.arc(mx, my, 4, 0, 2 * Math.PI);
    ctx.fillStyle = '#e74c3c';
    ctx.fill();
}


// ── Chart Setup ──────────────────────────────────────────────────────────────

function makeChart(canvasId, label, color) {
    const ctx = document.getElementById(canvasId).getContext('2d');
    return new Chart(ctx, {
        type: 'line',
        data: {
            labels: [],
            datasets: [{
                label: label,
                data: [],
                borderColor: color,
                backgroundColor: color + '22',
                fill: true,
                tension: 0.3,
                pointRadius: 0,
                borderWidth: 1.5,
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: false,
            layout: { padding: { bottom: 4 } },
            scales: {
                x: {
                    display: true,
                    ticks: {
                        maxTicksLimit: 6,
                        color: '#7a8d9e',
                        font: { size: 10 },
                        maxRotation: 0,   // keep labels horizontal — avoids overflow
                    },
                    grid: { color: 'rgba(255,255,255,0.05)' },
                },
                y: {
                    grace: '8%',          // auto-scale with 8% padding — no hard limits
                    ticks: { color: '#7a8d9e', font: { size: 10 } },
                    grid: { color: 'rgba(255,255,255,0.05)' },
                },
            },
            plugins: { legend: { display: false } },
        }
    });
}

// No fixed yMin/yMax — Chart.js auto-scales to actual data range
const phChart      = makeChart('ph-chart',          'pH',          '#00bcd4');
const chlorineChart = makeChart('chlorine-chart',   'Chlorine',    '#f39c12');
const tempChart    = makeChart('temperature-chart', 'Temperature', '#e74c3c');

function updateChart(chart, labels, values) {
    chart.data.labels                = labels.slice(-MAX_POINTS);
    chart.data.datasets[0].data      = values.slice(-MAX_POINTS);
    chart.update('none');  // skip animation on data update
}


// ── API Polling ──────────────────────────────────────────────────────────────

async function fetchJSON(url) {
    try {
        const res = await fetch(url);
        if (!res.ok) throw new Error(res.status);
        return await res.json();
    } catch (e) {
        console.warn('API error:', url, e);
        return null;
    }
}

async function pollStatus() {
    const data = await fetchJSON('/api/status');
    if (!data) {
        document.getElementById('connection-status').className = 'status-badge status-error';
        document.getElementById('connection-status').textContent = 'Disconnected';
        return;
    }
    document.getElementById('connection-status').className = 'status-badge status-ok';
    document.getElementById('connection-status').textContent = 'Connected';

    document.getElementById('node-id').textContent        = data.node_id || '--';
    document.getElementById('running').textContent        = data.running ? 'Yes' : 'No';
    document.getElementById('server-active').textContent  = data.server_active ? 'Yes' : 'No';
    document.getElementById('receiving-data').textContent = data.receiving_data ? 'Yes' : 'No';
    document.getElementById('packets-received').textContent = data.stats?.data_packets_received ?? '--';
}

async function pollAnomalies() {
    const data = await fetchJSON('/api/anomalies');
    if (!data) return;
    document.getElementById('total-anomalies').textContent = data.total_anomalies ?? 0;
    document.getElementById('evidence-count').textContent  = data.evidence_items ?? 0;
    document.getElementById('last-anomaly').textContent    = data.last_anomaly
        ? new Date(data.last_anomaly).toLocaleTimeString()
        : '--';

    const typesDiv = document.getElementById('anomaly-types');
    typesDiv.innerHTML = '';
    if (data.anomaly_types) {
        for (const [type, count] of Object.entries(data.anomaly_types)) {
            const row = document.createElement('div');
            row.className = 'stat-row';
            row.innerHTML = `<span>${type}</span><span class="highlight">${count}</span>`;
            typesDiv.appendChild(row);
        }
    }
}

async function pollReadings() {
    // Request more readings so each sensor gets enough points after filtering
    const data = await fetchJSON('/api/readings?count=150');
    if (!data || !Array.isArray(data)) return;

    // Only keep readings from the last HISTORY_MIN minutes
    const cutoff = Date.now() - HISTORY_MIN * 60 * 1000;
    const recent = data.filter(r => {
        if (!r.timestamp) return false;
        return new Date(r.timestamp).getTime() >= cutoff;
    });

    const phLabels = [], phValues = [];
    const clLabels = [], clValues = [];
    const tmpLabels = [], tmpValues = [];

    const tbody = document.querySelector('#readings-table tbody');
    tbody.innerHTML = '';

    recent.forEach(r => {
        const time = new Date(r.timestamp).toLocaleTimeString();
        const val  = typeof r.value === 'number' ? r.value.toFixed(2) : r.value;

        if      (r.sensor_type === 'pH')          { phLabels.push(time);  phValues.push(r.value); }
        else if (r.sensor_type === 'Chlorine')     { clLabels.push(time);  clValues.push(r.value); }
        else if (r.sensor_type === 'Temperature')  { tmpLabels.push(time); tmpValues.push(r.value); }

        const row = document.createElement('tr');
        row.innerHTML = `<td>${time}</td><td>${r.sensor_type}</td><td>${val}</td><td>${r.unit || ''}</td><td>${(r.confidence ?? 1).toFixed(2)}</td>`;
        tbody.appendChild(row);
    });

    updateChart(phChart,      phLabels,  phValues);
    updateChart(chlorineChart, clLabels,  clValues);
    updateChart(tempChart,    tmpLabels, tmpValues);
}

async function pollEvidence() {
    const data = await fetchJSON('/api/evidence');
    if (!data || !Array.isArray(data)) return;

    const tbody = document.querySelector('#evidence-table tbody');
    tbody.innerHTML = '';
    data.slice(0, 20).forEach(e => {
        const row = document.createElement('tr');
        const time = e.timestamp_iso ? new Date(e.timestamp_iso).toLocaleString() : '--';
        const anomalyType = e.anomaly_data?.anomaly_type || e.anomaly_data?.type || '--';
        row.innerHTML = `<td>${time}</td><td title="${e.evidence_id}">${(e.evidence_id || '').substring(0, 8)}...</td><td>${anomalyType}</td><td>${e.encrypted ? 'Yes' : 'No'}</td><td>${e.hash_chain_valid ? 'Valid' : 'N/A'}</td>`;
        tbody.appendChild(row);
    });
}

async function pollMLStats() {
    const data = await fetchJSON('/api/ml-stats');
    if (!data) return;
    document.getElementById('ml-processed').textContent = data.readings_processed ?? 0;
}

// ── ML Score Gauge Polling ───────────────────────────────────────────────────

let lastAnomalyTimestamp = null;

async function pollLatestAnomaly() {
    const data = await fetchJSON('/api/latest-anomaly');
    if (!data) return;

    const score     = data.ensemble_score ?? 0;
    const svmScore  = data.svm_score ?? 0;
    const lstmScore = data.lstm_score ?? 0;
    const isAnomaly = data.is_anomaly ?? false;
    const severity  = data.severity ?? 'NORMAL';
    const sensor    = data.sensor_type ?? '--';
    const ts        = data.timestamp;

    drawGauge('score-gauge', score);

    document.getElementById('score-value').textContent  = score.toFixed(2);
    document.getElementById('svm-score').textContent    = svmScore.toFixed(3);
    document.getElementById('lstm-score').textContent   = lstmScore.toFixed(3);
    document.getElementById('score-sensor').textContent = sensor;

    const label    = document.getElementById('score-label');
    const scoreNum = document.getElementById('score-value');
    if (severity === 'CRITICAL') {
        label.textContent = 'CRITICAL';
        label.className   = 'score-status status-crit-text';
        scoreNum.style.color = '#e74c3c';
    } else if (severity === 'HIGH') {
        label.textContent = 'HIGH';
        label.className   = 'score-status status-warn-text';
        scoreNum.style.color = '#f39c12';
    } else {
        label.textContent = 'NORMAL';
        label.className   = 'score-status status-ok-text';
        scoreNum.style.color = '#27ae60';
    }

    // Alert banner — only trigger for new anomaly events
    const banner    = document.getElementById('alert-banner');
    const alertText = document.getElementById('alert-text');
    if (isAnomaly && ts && ts !== lastAnomalyTimestamp) {
        lastAnomalyTimestamp = ts;
        alertText.textContent = `⚠ ANOMALY DETECTED — ${data.anomaly_type?.toUpperCase() ?? ''} on ${sensor} (score: ${score.toFixed(3)}, severity: ${severity})`;
        banner.classList.remove('alert-hidden');
    }
}


// ── Main Poll Loop ───────────────────────────────────────────────────────────

async function pollAll() {
    await pollStatus();
    await pollReadings();
    await pollAnomalies();
    await pollMLStats();
    await pollLatestAnomaly();
}

pollAll();
setInterval(pollAll, POLL_INTERVAL);

pollEvidence();
setInterval(pollEvidence, 30000);
