/**
 * API client — thin wrapper around fetch() for the FastAPI backend.
 * All methods return parsed JSON or throw an error.
 */

const API_BASE = window.location.origin;

const Api = {
  async get(path, params = {}) {
    const url = new URL(API_BASE + path);
    Object.entries(params).forEach(([k, v]) => {
      if (v !== null && v !== undefined && v !== '') url.searchParams.set(k, v);
    });
    const resp = await fetch(url);
    if (!resp.ok) throw new Error(`GET ${path} → ${resp.status}`);
    return resp.json();
  },

  async post(path, body = {}) {
    const resp = await fetch(API_BASE + path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!resp.ok) {
      const text = await resp.text();
      throw new Error(`POST ${path} → ${resp.status}: ${text}`);
    }
    return resp.json();
  },

  async patch(path, params = {}) {
    const url = new URL(API_BASE + path);
    Object.entries(params).forEach(([k, v]) => url.searchParams.set(k, v));
    const resp = await fetch(url, { method: 'PATCH' });
    if (!resp.ok) throw new Error(`PATCH ${path} → ${resp.status}`);
    return resp.json();
  },

  async delete(path) {
    const resp = await fetch(API_BASE + path, { method: 'DELETE' });
    if (!resp.ok) throw new Error(`DELETE ${path} → ${resp.status}`);
    return resp.json();
  },

  // ── Analytics ──────────────────────────────────────────────────────────────
  getSummary:            ()       => Api.get('/api/analytics/summary'),
  getByPlatform:         (days)   => Api.get('/api/analytics/by-platform',     { days }),
  getByProductType:      (days)   => Api.get('/api/analytics/by-product-type', { days }),
  getByCategory:         (days)   => Api.get('/api/analytics/by-category',     { days }),
  getTrend:              (days, platform) => Api.get('/api/analytics/trend',   { days, platform }),
  getTopRecalls:         (limit, days) => Api.get('/api/analytics/top-recalls', { limit, days }),
  getConfidenceDist:     ()       => Api.get('/api/analytics/confidence-distribution'),
  getPlatformMatrix:     (days)   => Api.get('/api/analytics/platform-product-matrix', { days }),

  // ── Listings ───────────────────────────────────────────────────────────────
  getListings: (params) => Api.get('/api/listings/', params),
  getListing:  (id)     => Api.get(`/api/listings/${id}`),
  confirmListing: (id, confirmed) => Api.patch(`/api/listings/${id}/confirm`, { confirmed }),
  invalidateListing:    (id)     => Api.delete(`/api/listings/${id}`),

  // ── Recalls ────────────────────────────────────────────────────────────────
  getRecalls: (params) => Api.get('/api/recalls/', params),
  syncCpsc:   (days_back) => Api.post('/api/recalls/sync', { days_back }),
  seedRecalls: () => Api.post('/api/recalls/seed'),

  // ── Scans ──────────────────────────────────────────────────────────────────
  triggerScan: (payload) => Api.post('/api/scans/trigger', payload),
  getScans:    (params)  => Api.get('/api/scans/', params),
  deleteAllScans: () => Api.delete('/api/scans/'),

  // ── eSAFE ──────────────────────────────────────────────────────────────────
  getEsafeStatus:   ()   => Api.get('/api/esafe/status'),
  submitListing:    (id) => Api.post(`/api/esafe/submit/${id}`),
  submitAllPending: ()   => Api.post('/api/esafe/submit-pending'),
};
