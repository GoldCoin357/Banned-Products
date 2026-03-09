/**
 * Chart management using Chart.js v4.
 * Each function creates/updates a specific chart on the dashboard.
 */

const PLATFORM_COLORS = {
  ebay:       { bg: 'rgba(230, 81, 0, 0.8)',   border: '#e65100' },
  craigslist: { bg: 'rgba(46, 125, 50, 0.8)',  border: '#2e7d32' },
  facebook:   { bg: 'rgba(25, 118, 210, 0.8)', border: '#1976d2' },
  offerup:    { bg: 'rgba(106, 27, 154, 0.8)', border: '#6a1b9a' },
  default:    { bg: 'rgba(96, 125, 139, 0.8)', border: '#607d8b' },
};

const PALETTE = [
  '#1976d2','#e65100','#2e7d32','#6a1b9a','#00695c',
  '#c62828','#f57f17','#0277bd','#37474f','#880e4f',
];

function getPlatformColor(name, idx = 0) {
  return PLATFORM_COLORS[name] || {
    bg: PALETTE[idx % PALETTE.length] + 'cc',
    border: PALETTE[idx % PALETTE.length],
  };
}

// Active chart instances
const _charts = {};

function destroyChart(id) {
  if (_charts[id]) { _charts[id].destroy(); delete _charts[id]; }
}

// ── Trend (line) ─────────────────────────────────────────────────────────────
function renderTrendChart(data) {
  destroyChart('trend');
  const ctx = document.getElementById('trendChart');
  if (!ctx) return;

  _charts['trend'] = new Chart(ctx, {
    type: 'line',
    data: {
      labels: data.map(d => d.date),
      datasets: [{
        label: 'Detections',
        data: data.map(d => d.count),
        borderColor: '#1976d2',
        backgroundColor: 'rgba(25,118,210,.1)',
        fill: true,
        tension: 0.3,
        pointRadius: 3,
        pointHoverRadius: 5,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { grid: { display: false }, ticks: { maxTicksLimit: 10, font: { size: 11 } } },
        y: { beginAtZero: true, ticks: { stepSize: 1, font: { size: 11 } } },
      },
    },
  });
}

// ── Platform (doughnut) ──────────────────────────────────────────────────────
function renderPlatformChart(data) {
  destroyChart('platform');
  const ctx = document.getElementById('platformChart');
  if (!ctx) return;

  _charts['platform'] = new Chart(ctx, {
    type: 'doughnut',
    data: {
      labels: data.map(d => d.platform),
      datasets: [{
        data: data.map(d => d.count),
        backgroundColor: data.map((d, i) => getPlatformColor(d.platform, i).bg),
        borderColor: data.map((d, i) => getPlatformColor(d.platform, i).border),
        borderWidth: 2,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { position: 'right', labels: { font: { size: 12 }, padding: 14 } },
      },
      cutout: '60%',
    },
  });
}

// ── Product Type (horizontal bar) ────────────────────────────────────────────
function renderProductTypeChart(data) {
  destroyChart('productType');
  const ctx = document.getElementById('productTypeChart');
  if (!ctx) return;

  const top = data.slice(0, 12);
  _charts['productType'] = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: top.map(d => d.product_type),
      datasets: [{
        label: 'Listings',
        data: top.map(d => d.count),
        backgroundColor: PALETTE.map(c => c + 'cc'),
        borderColor: PALETTE,
        borderWidth: 1,
        borderRadius: 4,
      }],
    },
    options: {
      indexAxis: 'y',
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { beginAtZero: true, ticks: { font: { size: 11 } } },
        y: { ticks: { font: { size: 11 } } },
      },
    },
  });
}

// ── Confidence histogram (bar) ────────────────────────────────────────────────
function renderConfidenceChart(data) {
  destroyChart('confidence');
  const ctx = document.getElementById('confidenceChart');
  if (!ctx) return;

  _charts['confidence'] = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: data.map(d => `${Math.round(d.range_low * 100)}–${Math.round(d.range_high * 100)}%`),
      datasets: [{
        label: 'Count',
        data: data.map(d => d.count),
        backgroundColor: data.map(d => {
          const mid = (d.range_low + d.range_high) / 2;
          if (mid >= 0.75) return 'rgba(46,125,50,.8)';
          if (mid >= 0.50) return 'rgba(245,127,23,.8)';
          return 'rgba(198,40,40,.8)';
        }),
        borderRadius: 4,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { grid: { display: false }, ticks: { font: { size: 10 } } },
        y: { beginAtZero: true, ticks: { stepSize: 1, font: { size: 11 } } },
      },
    },
  });
}

// ── Platform × Product matrix (HTML table) ───────────────────────────────────
function renderMatrix(data, container) {
  if (!data.length) { container.innerHTML = '<p style="color:#6b7a8d;padding:16px">No data</p>'; return; }

  const platforms = [...new Set(data.map(d => d.platform))];
  const types = [...new Set(data.map(d => d.product_type))].slice(0, 15);

  // Build lookup
  const lookup = {};
  data.forEach(d => { lookup[`${d.platform}::${d.product_type}`] = d.count; });
  const max = Math.max(...data.map(d => d.count), 1);

  let html = '<table class="matrix-table"><thead><tr><th>Platform \\ Product Type</th>';
  types.forEach(t => { html += `<th>${t || 'Unknown'}</th>`; });
  html += '</tr></thead><tbody>';

  platforms.forEach(p => {
    html += `<tr><td style="font-weight:700;text-align:left">${p}</td>`;
    types.forEach(t => {
      const count = lookup[`${p}::${t}`] || 0;
      const alpha = count ? Math.max(0.15, count / max) : 0;
      const bg = count ? `rgba(25,118,210,${alpha.toFixed(2)})` : 'transparent';
      const color = count && alpha > 0.5 ? '#fff' : '#1c2735';
      html += `<td class="matrix-cell" style="background:${bg};color:${color}">${count || ''}</td>`;
    });
    html += '</tr>';
  });

  html += '</tbody></table>';
  container.innerHTML = html;
}
