/**
 * Main application controller.
 * Handles routing, data loading, and all user interactions.
 */

const App = (() => {
  // ── State ──────────────────────────────────────────────────────────────────
  let _listingPage   = 1;
  let _recallPage    = 1;
  let _currentModal  = null;

  // ── Init ───────────────────────────────────────────────────────────────────
  function init() {
    feather.replace();

    // Sidebar navigation
    document.querySelectorAll('.nav-item').forEach(link => {
      link.addEventListener('click', e => {
        e.preventDefault();
        const page = link.dataset.page;
        navigateTo(page);
      });
    });

    // Mobile menu toggle
    document.getElementById('menuToggle').addEventListener('click', () => {
      document.getElementById('sidebar').classList.toggle('open');
    });

    // Top bar buttons
    document.getElementById('seedDataBtn').addEventListener('click', seedData);
    document.getElementById('syncCpscBtn').addEventListener('click', syncCpsc);
    document.getElementById('newScanBtn').addEventListener('click', () => navigateTo('scans'));

    // Filter change listeners
    document.getElementById('trendPlatformFilter').addEventListener('change', loadTrend);
    document.getElementById('platformDaysFilter').addEventListener('change', loadPlatformChart);

    // Handle hash routing
    const hash = window.location.hash.replace('#', '') || 'dashboard';
    navigateTo(hash);
  }

  // ── Navigation ─────────────────────────────────────────────────────────────
  function navigateTo(page) {
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));

    const target = document.getElementById(`page-${page}`);
    const navLink = document.querySelector(`.nav-item[data-page="${page}"]`);

    if (target) { target.classList.add('active'); }
    if (navLink) {
      navLink.classList.add('active');
      document.getElementById('pageTitle').textContent = navLink.querySelector('span').textContent;
    }

    window.location.hash = page;
    feather.replace();  // re-render icons in newly visible page

    // Load page data
    switch (page) {
      case 'dashboard': loadDashboard(); break;
      case 'listings':  loadListings();  break;
      case 'recalls':   loadRecalls();   break;
      case 'scans':     loadScans();     break;
      case 'esafe':     loadEsafe();     break;
    }
  }

  // ── Dashboard ──────────────────────────────────────────────────────────────
  async function loadDashboard() {
    try {
      const [summary, trend, platform, productType, confidence, topRecalls, matrix] = await Promise.all([
        Api.getSummary(),
        Api.getTrend(30, ''),
        Api.getByPlatform(30),
        Api.getByProductType(30),
        Api.getConfidenceDist(),
        Api.getTopRecalls(10, 30),
        Api.getPlatformMatrix(30),
      ]);

      // Summary cards
      setText('totalDetected',    summary.total_detected_listings);
      setText('confirmedListings', summary.confirmed_listings);
      setText('reportedEsafe',    summary.reported_to_esafe);
      setText('activeRecalls',    summary.active_recalls_in_db);
      setText('newThisWeek',      summary.new_detections_last_7_days);
      setText('avgConfidence',    (summary.average_ai_confidence * 100).toFixed(1) + '%');

      // Charts
      renderTrendChart(trend);
      renderPlatformChart(platform);
      renderProductTypeChart(productType);
      renderConfidenceChart(confidence);

      // Top recalls table
      renderTopRecalls(topRecalls);

      // Matrix
      renderMatrix(matrix, document.getElementById('matrixContainer'));

    } catch (err) {
      toast('Failed to load dashboard: ' + err.message, 'error');
      console.error(err);
    }
  }

  async function loadTrend() {
    const platform = document.getElementById('trendPlatformFilter').value;
    const data = await Api.getTrend(30, platform);
    renderTrendChart(data);
  }

  async function loadPlatformChart() {
    const days = document.getElementById('platformDaysFilter').value;
    const data = await Api.getByPlatform(parseInt(days));
    renderPlatformChart(data);
  }

  function renderTopRecalls(data) {
    const tbody = document.getElementById('topRecallsBody');
    if (!data.length) {
      tbody.innerHTML = '<tr><td colspan="6" class="loading-cell">No data yet — run a scan to populate.</td></tr>';
      return;
    }
    tbody.innerHTML = data.map(r => `
      <tr>
        <td><strong>${esc(r.product_name)}</strong></td>
        <td>${esc(r.brand || '–')}</td>
        <td><code>${esc(r.recall_number || '–')}</code></td>
        <td>${esc(r.category || '–')}</td>
        <td><strong style="color:#1976d2">${r.listing_count}</strong></td>
        <td>
          <button class="btn btn-sm btn-outline" onclick="App.loadListingsForRecall(${r.recall_id})">
            View Listings
          </button>
        </td>
      </tr>
    `).join('');
    feather.replace();
  }

  // Public wrapper for top recalls
  function loadTopRecalls() {
    Api.getTopRecalls(10, 30).then(renderTopRecalls).catch(console.error);
  }

  // ── Listings ───────────────────────────────────────────────────────────────
  async function loadListings(page = 1) {
    _listingPage = page;
    const params = {
      platform:       document.getElementById('listingPlatformFilter')?.value || '',
      search:         document.getElementById('listingSearch')?.value || '',
      min_confidence: document.getElementById('listingMinConf')?.value || 0,
      page,
      page_size: 20,
    };

    const status = document.getElementById('listingStatusFilter')?.value || '';
    if (status === 'confirmed') params.is_confirmed = true;
    if (status === 'reported')  params.is_reported = true;

    try {
      const data = await Api.getListings(params);
      renderListingsTable(data);
    } catch (err) {
      toast('Failed to load listings: ' + err.message, 'error');
    }
  }

  function loadListingsForRecall(recallId) {
    navigateTo('listings');
    // We use a delay to let the page render first
    setTimeout(() => {
      // Note: filter by recall not directly exposed in UI — navigate and show all
      loadListings(1);
    }, 100);
  }

  function renderListingsTable({ total, page, page_size, results }) {
    const tbody = document.getElementById('listingsBody');
    if (!results.length) {
      tbody.innerHTML = '<tr><td colspan="8" class="loading-cell">No listings found.</td></tr>';
      renderPagination('listingsPagination', 0, 1, 20, loadListings);
      return;
    }

    tbody.innerHTML = results.map(l => {
      const confClass = l.ai_confidence >= 0.9 ? 'conf-high' : l.ai_confidence >= 0.7 ? 'conf-med' : 'conf-low';
      const pct = Math.round((l.ai_confidence || 0) * 100);
      const badge = l.is_reported ? 'reported' : l.is_confirmed ? 'confirmed' : l.is_valid ? 'pending' : 'invalid';
      return `
        <tr>
          <td><span class="badge badge--${l.platform}">${l.platform}</span></td>
          <td>
            <div style="max-width:260px">
              <div style="font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(l.title || '–')}</div>
              <a href="${esc(l.listing_url)}" target="_blank" style="font-size:11px;color:#1976d2;word-break:break-all">
                ${esc(l.listing_url.substring(0, 60))}…
              </a>
            </div>
          </td>
          <td>${l.price != null ? '$' + l.price.toFixed(2) : '–'}</td>
          <td>
            <div class="conf-bar ${confClass}">
              <div class="conf-bar__track">
                <div class="conf-bar__fill" style="width:${pct}%"></div>
              </div>
              <div class="conf-bar__label">${pct}%</div>
            </div>
          </td>
          <td>${esc(l.product_type || '–')}</td>
          <td style="white-space:nowrap;font-size:12px">${formatDate(l.detected_at)}</td>
          <td><span class="badge badge--${badge}">${badge}</span></td>
          <td>
            <div style="display:flex;gap:4px">
              <button class="btn btn-sm btn-outline" onclick="App.openListingModal(${l.id})">View</button>
              ${!l.is_confirmed ? `<button class="btn btn-sm btn-success" onclick="App.confirmListing(${l.id},true)">✓</button>` : ''}
              ${!l.is_reported && l.is_confirmed ? `<button class="btn btn-sm btn-primary" onclick="App.submitToEsafe(${l.id})">eSAFE</button>` : ''}
              ${l.is_valid ? `<button class="btn btn-sm btn-danger" onclick="App.invalidateListing(${l.id})">✕</button>` : ''}
            </div>
          </td>
        </tr>
      `;
    }).join('');

    renderPagination('listingsPagination', total, page, page_size, loadListings);
    feather.replace();
  }

  async function openListingModal(id) {
    try {
      const l = await Api.getListing(id);
      _currentModal = l;
      document.getElementById('modalTitle').textContent = l.title || 'Listing Detail';

      const recallInfo = l.recall
        ? `${l.recall.product_name}${l.recall.recall_number ? ` (Recall #${l.recall.recall_number})` : ''}`
        : '–';

      const imagesHtml = (l.image_urls || []).length
        ? `<div class="modal-images">${l.image_urls.slice(0, 6).map(u =>
            `<img src="${esc(u)}" alt="listing image" onerror="this.style.display='none'" />`
          ).join('')}</div>`
        : '';

      document.getElementById('modalBody').innerHTML = `
        ${imagesHtml}
        <div class="detail-grid">
          <div class="detail-item">
            <label>Platform</label>
            <span><span class="badge badge--${l.platform}">${l.platform}</span></span>
          </div>
          <div class="detail-item">
            <label>Price</label>
            <span>${l.price != null ? '$' + l.price.toFixed(2) + ' ' + (l.currency || '') : '–'}</span>
          </div>
          <div class="detail-item">
            <label>Seller</label>
            <span>${l.seller_id ? `<a href="${esc(l.seller_url)}" target="_blank">${esc(l.seller_id)}</a>` : '–'}</span>
          </div>
          <div class="detail-item">
            <label>Location</label>
            <span>${esc(l.location || '–')}</span>
          </div>
          <div class="detail-item">
            <label>AI Confidence</label>
            <span>${Math.round((l.ai_confidence || 0) * 100)}%</span>
          </div>
          <div class="detail-item">
            <label>Match Method</label>
            <span>${esc(l.match_method || '–')}</span>
          </div>
          <div class="detail-item">
            <label>Matched Recall</label>
            <span>${esc(recallInfo)}</span>
          </div>
          <div class="detail-item">
            <label>Detected At</label>
            <span>${formatDate(l.detected_at)}</span>
          </div>
          <div class="detail-item detail-full">
            <label>AI Reasoning</label>
            <span>${esc(l.ai_reasoning || '–')}</span>
          </div>
          <div class="detail-item detail-full">
            <label>Listing URL</label>
            <span><a href="${esc(l.listing_url)}" target="_blank">${esc(l.listing_url)}</a></span>
          </div>
          ${l.esafe_report_id ? `
          <div class="detail-item">
            <label>eSAFE Report ID</label>
            <span>${esc(l.esafe_report_id)}</span>
          </div>
          <div class="detail-item">
            <label>eSAFE Submitted</label>
            <span>${formatDate(l.esafe_submitted_at)}</span>
          </div>
          ` : ''}
        </div>
      `;

      document.getElementById('modalFooter').innerHTML = `
        ${!l.is_confirmed ? `<button class="btn btn-success" onclick="App.confirmListing(${l.id},true);App.closeModal()">Confirm Match</button>` : ''}
        ${!l.is_reported && l.is_confirmed ? `<button class="btn btn-primary" onclick="App.submitToEsafe(${l.id})">Submit to eSAFE</button>` : ''}
        ${l.is_valid ? `<button class="btn btn-danger" onclick="App.invalidateListing(${l.id});App.closeModal()">Invalidate</button>` : ''}
        <button class="btn btn-outline" onclick="App.closeModal()">Close</button>
      `;

      document.getElementById('listingModal').style.display = 'flex';
    } catch (err) {
      toast('Failed to load listing: ' + err.message, 'error');
    }
  }

  function closeModal() {
    document.getElementById('listingModal').style.display = 'none';
    _currentModal = null;
  }

  async function confirmListing(id, confirmed) {
    try {
      await Api.confirmListing(id, confirmed);
      toast(confirmed ? 'Listing confirmed ✓' : 'Listing dismissed', 'success');
      loadListings(_listingPage);
    } catch (err) {
      toast('Error: ' + err.message, 'error');
    }
  }

  async function invalidateListing(id) {
    if (!confirm('Remove this listing from results?')) return;
    try {
      await Api.invalidateListing(id);
      toast('Listing invalidated', 'warning');
      loadListings(_listingPage);
    } catch (err) {
      toast('Error: ' + err.message, 'error');
    }
  }

  async function submitToEsafe(id) {
    try {
      toast('Submitting to CPSC eSAFE…');
      const result = await Api.submitListing(id);
      toast('Submitted! Report ID: ' + result.esafe_report_id, 'success');
      loadListings(_listingPage);
    } catch (err) {
      toast('eSAFE submission failed: ' + err.message, 'error');
    }
  }

  // ── Recalls ────────────────────────────────────────────────────────────────
  async function loadRecalls(page = 1) {
    _recallPage = page;
    const params = {
      search:   document.getElementById('recallSearch')?.value || '',
      page,
      page_size: 20,
    };
    try {
      const data = await Api.getRecalls(params);
      renderRecallsTable(data);
    } catch (err) {
      toast('Failed to load recalls: ' + err.message, 'error');
    }
  }

  function renderRecallsTable({ total, page, page_size, results }) {
    const tbody = document.getElementById('recallsBody');
    if (!results.length) {
      tbody.innerHTML = '<tr><td colspan="8" class="loading-cell">No recalls in database. Click "Sync CPSC" to import.</td></tr>';
      renderPagination('recallsPagination', 0, 1, 20, loadRecalls);
      return;
    }
    tbody.innerHTML = results.map(r => `
      <tr>
        <td><code style="font-size:11px">${esc(r.recall_number || '–')}</code></td>
        <td style="max-width:200px;font-weight:600">${esc(r.product_name)}</td>
        <td>${esc(r.brand || '–')}</td>
        <td>${esc(r.product_type || r.category || '–')}</td>
        <td style="white-space:nowrap">${formatDate(r.recall_date)}</td>
        <td style="max-width:200px;font-size:12px">${esc((r.hazard_description || '–').substring(0, 80))}…</td>
        <td>
          <span class="badge" style="background:${r.is_active ? '#e8f5e9' : '#ffebee'};color:${r.is_active ? '#1b5e20' : '#b71c1c'}">
            ${r.is_active ? 'Active' : 'Inactive'}
          </span>
        </td>
        <td>
          <button class="btn btn-sm btn-primary" onclick="App.scanForRecall(${r.id})">
            Scan
          </button>
        </td>
      </tr>
    `).join('');
    renderPagination('recallsPagination', total, page, page_size, loadRecalls);
    feather.replace();
  }

  async function scanForRecall(recallId) {
    try {
      toast('Scanning all platforms for this recall…');
      const result = await Api.triggerScan({ recall_id: recallId, max_results: 50 });
      toast(result.message, 'success');
      navigateTo('scans');
    } catch (err) {
      toast('Scan error: ' + err.message, 'error');
    }
  }

  async function seedData() {
    try {
      toast('Loading sample recalls…');
      const result = await Api.seedRecalls();
      toast(result.message, 'success');
      loadRecalls();
    } catch (err) {
      toast('Seed failed: ' + err.message, 'error');
    }
  }

  async function syncCpsc() {
    try {
      toast('Syncing CPSC recall data…');
      await Api.syncCpsc(1825);
      toast('CPSC sync started in background', 'success');
    } catch (err) {
      toast('Sync failed: ' + err.message, 'error');
    }
  }

  // ── Scans ──────────────────────────────────────────────────────────────────
  async function loadScans() {
    try {
      const data = await Api.getScans({ page: 1, page_size: 50 });
      const tbody = document.getElementById('scansBody');
      if (!data.results.length) {
        tbody.innerHTML = '<tr><td colspan="7" class="loading-cell">No scan jobs yet.</td></tr>';
        return;
      }
      tbody.innerHTML = data.results.map(j => {
        const statusColor = {
          completed: '#2e7d32', running: '#1976d2', pending: '#e65100', failed: '#c62828',
        }[j.status] || '#6b7a8d';

        const duration = j.started_at && j.completed_at
          ? Math.round((new Date(j.completed_at) - new Date(j.started_at)) / 1000) + 's'
          : j.status === 'running' ? '…' : '–';

        return `
          <tr>
            <td>#${j.id}</td>
            <td><span class="badge badge--${j.platform}">${j.platform}</span></td>
            <td><span style="color:${statusColor};font-weight:700">${j.status}</span></td>
            <td>${j.listings_scanned}</td>
            <td><strong style="color:#1976d2">${j.listings_detected}</strong></td>
            <td style="font-size:12px">${formatDate(j.started_at)}</td>
            <td>${duration}</td>
          </tr>
        `;
      }).join('');
      feather.replace();
    } catch (err) {
      toast('Failed to load scans: ' + err.message, 'error');
    }
  }

  async function triggerScan() {
    const payload = {
      platform:          document.getElementById('scanPlatform').value || null,
      max_results:       parseInt(document.getElementById('scanMaxResults').value) || 50,
      auto_submit_esafe: document.getElementById('scanAutoSubmit').checked,
    };
    try {
      toast('Triggering scan…');
      const result = await Api.triggerScan(payload);
      toast(result.message, 'success');
      setTimeout(loadScans, 500);
    } catch (err) {
      toast('Scan trigger failed: ' + err.message, 'error');
    }
  }

  // ── eSAFE ──────────────────────────────────────────────────────────────────
  async function loadEsafe() {
    try {
      const [status, listings] = await Promise.all([
        Api.getEsafeStatus(),
        Api.getListings({ is_reported: true, page: 1, page_size: 50 }),
      ]);
      setText('esafeTotalReported', status.total_reported);
      setText('esafePending',       status.pending_submission);

      const tbody = document.getElementById('esafeBody');
      if (!listings.results.length) {
        tbody.innerHTML = '<tr><td colspan="5" class="loading-cell">No reported listings yet.</td></tr>';
        return;
      }
      tbody.innerHTML = listings.results.map(l => `
        <tr>
          <td><span class="badge badge--${l.platform}">${l.platform}</span></td>
          <td>${esc(l.title || '–')}</td>
          <td><code>${esc(l.esafe_report_id || '–')}</code></td>
          <td style="font-size:12px">${formatDate(l.esafe_submitted_at)}</td>
          <td><a href="${esc(l.listing_url)}" target="_blank" style="color:#1976d2;font-size:12px">View →</a></td>
        </tr>
      `).join('');
    } catch (err) {
      toast('Failed to load eSAFE status: ' + err.message, 'error');
    }
  }

  async function submitAllPending() {
    try {
      toast('Queuing bulk eSAFE submission…');
      await Api.submitAllPending();
      toast('Bulk submission queued', 'success');
      setTimeout(loadEsafe, 1000);
    } catch (err) {
      toast('Bulk submit failed: ' + err.message, 'error');
    }
  }

  // ── Helpers ────────────────────────────────────────────────────────────────
  function renderPagination(containerId, total, currentPage, pageSize, onPage) {
    const container = document.getElementById(containerId);
    const totalPages = Math.ceil(total / pageSize);
    if (totalPages <= 1) { container.innerHTML = ''; return; }

    let html = '';
    const start = Math.max(1, currentPage - 2);
    const end   = Math.min(totalPages, currentPage + 2);

    if (currentPage > 1) html += `<button class="page-btn" onclick="App._page('${containerId}',${currentPage-1})">‹</button>`;
    for (let p = start; p <= end; p++) {
      html += `<button class="page-btn${p === currentPage ? ' active' : ''}" onclick="App._page('${containerId}',${p})">${p}</button>`;
    }
    if (currentPage < totalPages) html += `<button class="page-btn" onclick="App._page('${containerId}',${currentPage+1})">›</button>`;

    container.innerHTML = `<span style="font-size:12px;color:#6b7a8d;margin-right:8px">${total} total</span>` + html;
  }

  // Dispatch pagination clicks to the right loader
  function _page(containerId, page) {
    if (containerId === 'listingsPagination') loadListings(page);
    if (containerId === 'recallsPagination')  loadRecalls(page);
  }

  function setText(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value ?? '–';
  }

  function esc(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function formatDate(iso) {
    if (!iso) return '–';
    try {
      return new Date(iso).toLocaleDateString('en-US', {
        month: 'short', day: 'numeric', year: 'numeric',
      });
    } catch { return iso; }
  }

  // ── Toast ─────────────────────────────────────────────────────────────────
  let _toastTimer = null;
  function toast(message, type = '') {
    const el = document.getElementById('toast');
    el.textContent = message;
    el.className = 'toast show' + (type ? ' ' + type : '');
    if (_toastTimer) clearTimeout(_toastTimer);
    _toastTimer = setTimeout(() => { el.classList.remove('show'); }, 3500);
  }

  // ── Public API ─────────────────────────────────────────────────────────────
  return {
    init,
    // Page loaders
    loadDashboard,
    loadListings,
    loadRecalls,
    loadScans,
    loadEsafe,
    loadTopRecalls,
    // Actions
    openListingModal,
    closeModal,
    confirmListing,
    invalidateListing,
    submitToEsafe,
    submitAllPending,
    syncCpsc,
    triggerScan,
    loadListingsForRecall,
    scanForRecall,
    // Internals exposed for inline event handlers
    _page,
  };
})();

// Kick everything off
document.addEventListener('DOMContentLoaded', App.init);
