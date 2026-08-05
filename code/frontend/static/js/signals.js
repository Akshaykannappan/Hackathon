/**
 * SmartReco — Live Signal Panel Client Controller
 * Polling, diffing, and real-time animation for behavioral signal stream.
 */

(function () {
  'use strict';

  // 1. Guard: Authentication check
  if (document.body.dataset.authenticated !== 'true') {
    return;
  }

  // 2. Guard: Signal panel container check
  const panelContainer = document.getElementById('signal-panel-container');
  if (!panelContainer) {
    return;
  }

  const chipsList = document.getElementById('signal-chips-list');
  const summarySection = document.getElementById('signal-interest-summary-section');
  const summaryText = document.getElementById('signal-interest-summary');
  const recSection = document.getElementById('signal-recommendation-section');
  const recBox = document.getElementById('signal-recommendation-box');

  const knownEventIds = new Set();
  let lastRecHash = '';
  let pollInterval = null;

  async function fetchSignals() {
    try {
      const res = await fetch('/api/signals/recent', {
        headers: { 'Accept': 'application/json' },
        cache: 'no-store'
      });

      if (!res.ok) {
        return; // Silent fail on HTTP errors (e.g. 401, 500)
      }

      const data = await res.json();
      updateSignals(data.events || []);
      updateInterestSummary(data.interest_summary || null);
      updateRecommendation(data.recommendation || null);
    } catch (err) {
      // Fail silently without breaking page execution
    }
  }

  function updateSignals(events) {
    if (!chipsList) return;

    if (events.length === 0) {
      if (!chipsList.querySelector('.signal-empty-state')) {
        chipsList.innerHTML = `
          <div id="signal-empty-state" class="signal-empty-state">
            Browse a course — the agent starts reading your signal
          </div>`;
      }
      return;
    }

    // Remove empty state if present
    const emptyState = document.getElementById('signal-empty-state');
    if (emptyState) {
      emptyState.remove();
    }

    // Iterate backwards so newest elements get prepended in order
    for (let i = events.length - 1; i >= 0; i--) {
      const evt = events[i];
      const existing = chipsList.querySelector(`[data-event-id="${evt.id}"]`);

      if (existing) {
        // Update age text on existing chip
        const ageEl = existing.querySelector('.chip-age');
        if (ageEl && ageEl.textContent !== evt.age) {
          ageEl.textContent = evt.age;
        }
      } else {
        // Create new chip with entry animation
        const chip = document.createElement('div');
        chip.className = 'signal-chip new-chip-anim';
        chip.dataset.eventId = evt.id;
        chip.innerHTML = `
          <span class="chip-label">${escapeHtml(evt.label)}</span>
          <span class="chip-age">${escapeHtml(evt.age)}</span>
        `;

        if (chipsList.firstChild) {
          chipsList.insertBefore(chip, chipsList.firstChild);
        } else {
          chipsList.appendChild(chip);
        }
        knownEventIds.add(evt.id);
      }
    }

    // Cap DOM children at 10 chips
    while (chipsList.children.length > 10) {
      chipsList.removeChild(chipsList.lastChild);
    }
  }

  // The server composes the sentence — scores and topic keys never reach the
  // client on this endpoint. An empty profile sends null, and the section hides.
  function updateInterestSummary(summary) {
    if (!summarySection || !summaryText) return;

    if (!summary) {
      summarySection.style.display = 'none';
      summaryText.textContent = '';
      return;
    }

    summarySection.style.display = 'block';
    if (summaryText.textContent !== summary) {
      summaryText.textContent = summary;
    }
  }

  function updateRecommendation(rec) {
    if (!recSection || !recBox) return;

    if (!rec || !rec.message || !rec.products || rec.products.length === 0) {
      recSection.style.display = 'none';
      return;
    }

    const currentHash = JSON.stringify(rec);
    if (currentHash === lastRecHash) {
      return;
    }
    lastRecHash = currentHash;

    recSection.style.display = 'block';
    const productItems = rec.products.map(p => `
      <div class="mini-rec-card">
        <div class="mini-rec-title">
          <a href="/product/${p.id}">${escapeHtml(p.title)}</a>
        </div>
        <div class="mini-rec-meta">
          <span class="tag tag-primary">${escapeHtml(p.category)}</span>
          <span class="price">$${p.price.toFixed(2)}</span>
        </div>
      </div>
    `).join('');

    recBox.innerHTML = `
      <div class="rec-message-preview">${escapeHtml(rec.message)}</div>
      <div class="mini-rec-list">${productItems}</div>
    `;
  }

  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  function startPolling() {
    fetchSignals();
    if (!pollInterval) {
      pollInterval = setInterval(fetchSignals, 5000);
    }
  }

  function stopPolling() {
    if (pollInterval) {
      clearInterval(pollInterval);
      pollInterval = null;
    }
  }

  // Handle Visibility Change (pause on hidden tab, resume on visible tab)
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) {
      stopPolling();
    } else {
      startPolling();
    }
  });

  // Boot polling on page load
  startPolling();
})();
