// Update popup: fetches static/updates/updates.json and shows a modal
(async function() {
  try {
    const [resp, healthResp] = await Promise.all([
      fetch('/static/updates/updates.json?t=' + Date.now()),
      fetch('/api/system/health?t=' + Date.now()),
    ]);
    if (!resp.ok) return;
    const data = await resp.json();
    const releases = Array.isArray(data) ? data : (data ? [data] : []);
    if (!releases.length) return;

    // Get saved installed version from server; fallback to empty string.
    let installedVersion = '';
    if (healthResp && healthResp.ok) {
      try {
        const health = await healthResp.json();
        installedVersion = health.installed_version || '';
        // also update health card if present
        const verEl = document.getElementById('health-version');
        if (verEl) verEl.textContent = installedVersion || 'Unknown';
      } catch (e) {}
    }

    // Determine unseen releases (newer than installedVersion). Releases assumed newest-first.
    const unseen = collectUnseenReleases(releases, installedVersion);
    if (!unseen.length) return;

    // Only show popup if any unseen release requires reflash
    const needsReflash = unseen.some(r => r.reflash_required === true);
    if (!needsReflash) return;

    // Show all unseen releases (newest-first)
    showUpdateModalForReleases(unseen);
  } catch (err) {
    console.error('Update popup error', err);
  }

  function showUpdateModalForReleases(releases) {
    const data = releases[0]; // latest
    const root = document.getElementById('modal-root');
    if (!root) return;
    const reflashClass = data.reflash_required ? 'required' : 'optional';

    // Build sections for each release (newest to oldest)
    const releaseHtml = releases
      .map(r => {
        const pills = `<div style="display:flex;align-items:center;gap:0.5rem;"><div class=\"reflash-pill ${r.reflash_required ? 'required' : 'optional'}\">${r.reflash_required ? 'Reflash required' : 'No reflash required'}</div></div>`;
        const parts = [];
        if (Array.isArray(r.bug_fixes) && r.bug_fixes.length) parts.push(renderSection('Bug Fixes', 'update-header-bug', r.bug_fixes));
        if (Array.isArray(r.new_features) && r.new_features.length) parts.push(renderSection('New Features', 'update-header-feature', r.new_features));
        if (Array.isArray(r.general_changes) && r.general_changes.length) parts.push(renderSection('General Changes', 'update-header-general', r.general_changes));
        return `
          <div style="border-bottom:1px dashed var(--border-color); padding-bottom:0.5rem; margin-bottom:0.75rem;">
            <div class=\"update-top\">\n              <div>\n                <div class=\"update-title\">Update ${escapeHtml(r.version)}</div>\n                <div class=\"update-meta\">${escapeHtml(r.date || '')}</div>\n              </div>\n              ${pills}\n            </div>\n            ${parts.join('\n')}\n          </div>`;
      })
      .join('\n');

    const modal = document.createElement('div');
    modal.className = 'update-modal';
    modal.setAttribute('role', 'dialog');
    modal.setAttribute('aria-modal', 'true');
    modal.innerHTML = `
      ${releaseHtml}
      <div class="update-actions">
        <button class="btn btn-outline" id="update-close">Close</button>
        <a class="btn btn-danger" href="https://github.com/ItzEarthy/DryDock/wiki/4.-Firmware-Setup">Flash ESP32 Guide</a>
        <button class="btn btn-primary" id="update-mark">Mark as Read</button>
      </div>
    `;

    root.innerHTML = '';
    root.appendChild(modal);
    root.classList.remove('hidden');

    // Replace data-feather placeholders with actual SVGs
    if (window.feather && typeof feather.replace === 'function') {
      try { feather.replace(); } catch (e) { /* ignore */ }
    }

    document.getElementById('update-close').addEventListener('click', () => {
      root.classList.add('hidden');
      root.innerHTML = '';
    });

    document.getElementById('update-mark').addEventListener('click', async () => {
      // Save installed version on server (set to latest shown)
      const latestVersion = releases[0].version;
      try {
        await fetch('/api/system/install_version', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ version: latestVersion }),
        });
        const verEl = document.getElementById('health-version');
        if (verEl) verEl.textContent = latestVersion;
      } catch (e) {
        console.warn('Failed to save installed version', e);
      }
      root.classList.add('hidden');
      root.innerHTML = '';
    });
  }

  function renderSection(title, cls, items) {
    const iconKey = cls.includes('bug') ? 'bug' : (cls.includes('feature') ? 'feature' : 'general');
    const lines = items.map(i => `<li>${escapeHtml(i)}</li>`).join('');
    return `<div class="update-section ${cls}"><h4>${iconSvg(iconKey)}${escapeHtml(title)}</h4><ul>${lines}</ul></div>`;
  }

  function iconSvg(key) {
    // Simple, lightweight inline SVGs as a fallback instead of relying on remote icon set.
    if (key === 'bug') {
      return `
        <svg class="update-icon" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
          <path d="M20 8c0-1.1-.9-2-2-2h-2.2a6.5 6.5 0 0 0-11.6 0H4c-1.1 0-2 .9-2 2v1c0 1.1.9 2 2 2h.3A6.5 6.5 0 0 0 7 17.9V20h2v-2h6v2h2v-2.1c1.9-.9 3.3-2.9 3.7-5.4H20c1.1 0 2-.9 2-2V8z" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>`;
    }
    if (key === 'feature') {
      return `
        <svg class="update-icon" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
          <path d="M12 2l2.09 6.26L20 9.27l-5 3.64L16.18 20 12 16.9 7.82 20 9 12.91l-5-3.64 5.91-.99L12 2z" stroke="currentColor" stroke-width="1" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>`;
    }
    // general
    return `
      <svg class="update-icon" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
        <path d="M12 15.5A3.5 3.5 0 1 0 12 8.5a3.5 3.5 0 0 0 0 7zm7.4-3.5a5.9 5.9 0 0 0-.1-1l2.1-1.6-2-3.5-2.5.8a6 6 0 0 0-1.7-1L14.9 2h-5.8L8.3 5.7a6 6 0 0 0-1.7 1L4.1 5.9 2 9.4l2.1 1.6c-.1.3-.1.6-.1 1s0 .6.1 1L2 14.6l2 3.5 2.5-.8c.5.4 1 .8 1.7 1L9.1 22h5.8l.6-3.7c.6-.2 1.1-.6 1.7-1l2.5.8 2-3.5-2.1-1.6c.1-.3.1-.6.1-1z" stroke="currentColor" stroke-width="1" stroke-linecap="round" stroke-linejoin="round"/>
      </svg>`;
  }

  function collectUnseenReleases(releases, installedVersion) {
    if (!installedVersion) return releases.slice();
    // releases are newest-first. Collect releases with version > installedVersion.
    const out = [];
    for (const r of releases) {
      if (compareVersion(r.version, installedVersion) > 0) {
        out.push(r);
      } else {
        break; // once we reach installed or older, stop
      }
    }
    return out;
  }

  function compareVersion(a, b) {
    if (!a && !b) return 0;
    if (!a) return -1;
    if (!b) return 1;
    const pa = String(a).split('.').map(n => parseInt(n, 10) || 0);
    const pb = String(b).split('.').map(n => parseInt(n, 10) || 0);
    const len = Math.max(pa.length, pb.length);
    for (let i = 0; i < len; i++) {
      const na = pa[i] || 0;
      const nb = pb[i] || 0;
      if (na > nb) return 1;
      if (na < nb) return -1;
    }
    return 0;
  }

  function escapeHtml(s) {
    if (!s && s !== 0) return '';
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

})();
