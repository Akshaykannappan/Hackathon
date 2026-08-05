/**
 * SmartReco behavioural tracker.
 *
 * Queues signals in memory and flushes them to /api/events/batch every 10
 * seconds or every 20 events, whichever comes first. Nothing here blocks or
 * awaits: every send is fire-and-forget, and the page teardown path uses
 * navigator.sendBeacon so the tail of a session survives navigation.
 *
 * Contract with the templates (all read from <body>):
 *   data-authenticated  "true" | "false"   — the tracker no-ops unless "true"
 *   data-page           "catalog" | "product"
 *   data-product-id     product primary key, on product pages
 *   data-category       category of the page or of the active filter
 *   data-level          product level, on product pages
 *
 * And on elements:
 *   [data-track-card]   a clickable product card, carrying data-product-id
 *   [data-track-search] the catalog search input
 */
(function () {
  "use strict";

  var body = document.body;

  // Anonymous visitors have no profile to build. Attach nothing, cost nothing.
  if (!body || body.dataset.authenticated !== "true") {
    return;
  }

  var ENDPOINT = "/api/events/batch";
  var FLUSH_INTERVAL_MS = 10000;
  var FLUSH_AT_EVENTS = 20;
  var QUEUE_CAP = 100; // matches MAX_BATCH_SIZE on the server
  var QUICK_EXIT_MS = 3000;
  var SEARCH_DEBOUNCE_MS = 500;
  var SCROLL_THROTTLE_MS = 250;
  var SCROLL_MILESTONES = [25, 50, 75, 100];
  var MIN_SEARCH_LENGTH = 2;

  var page = body.dataset.page || "";
  var pageProductId = body.dataset.productId ? Number(body.dataset.productId) : null;
  var pageCategory = body.dataset.category || "";

  var queue = [];
  var flushTimer = null;

  /* ---------------------------------------------------------------- queue */

  function scheduleFlush() {
    if (flushTimer !== null) {
      return; // already counting down from the first queued event
    }
    flushTimer = window.setTimeout(function () {
      flushTimer = null;
      flush(false);
    }, FLUSH_INTERVAL_MS);
  }

  function enqueue(eventType, productId, metadata) {
    queue.push({
      event_type: eventType,
      product_id: productId || null,
      metadata: metadata || {},
      occurred_at: new Date().toISOString()
    });

    // A queue that outgrows the server's batch cap sheds its oldest entries:
    // recent behaviour is what the profile is built from.
    if (queue.length > QUEUE_CAP) {
      queue.splice(0, queue.length - QUEUE_CAP);
    }

    if (queue.length >= FLUSH_AT_EVENTS) {
      flush(false);
    } else {
      scheduleFlush();
    }
  }

  function flush(useBeacon) {
    if (flushTimer !== null) {
      window.clearTimeout(flushTimer);
      flushTimer = null;
    }
    if (queue.length === 0) {
      return;
    }

    var payload = JSON.stringify({ events: queue.splice(0, queue.length) });

    if (useBeacon && navigator.sendBeacon) {
      navigator.sendBeacon(ENDPOINT, new Blob([payload], { type: "application/json" }));
      return;
    }

    // keepalive so a flush racing a navigation still completes. No await, and
    // no retry — behavioural events are lossy by design and must never surface
    // an error to the person browsing.
    fetch(ENDPOINT, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: payload,
      credentials: "same-origin",
      keepalive: true
    }).catch(function () {});
  }

  /* ------------------------------------------------------- page entry */

  if (page === "product" && pageProductId) {
    enqueue("product_view", pageProductId, {
      category: pageCategory,
      level: body.dataset.level || ""
    });
  } else if (page === "catalog" && pageCategory) {
    enqueue("category_view", null, { category: pageCategory });
  }

  /* ------------------------------------------------ visible time on page */

  // Accumulated from visibilitychange only — no polling timer ever runs.
  var visibleSince = document.visibilityState === "visible" ? Date.now() : null;
  var visibleMs = 0;
  var finalised = false;

  function accumulateVisibleTime() {
    if (visibleSince !== null) {
      visibleMs += Date.now() - visibleSince;
      visibleSince = null;
    }
  }

  /**
   * Emit the one timing event this page load is entitled to.
   *
   * Runs on pagehide rather than on hidden: a reader who glances at another tab
   * after two seconds and comes back has not "quick exited", and finalising on
   * hidden would mislabel them.
   */
  function finalisePageTiming() {
    if (finalised) {
      return;
    }
    finalised = true;
    accumulateVisibleTime();

    if (page !== "product" || !pageProductId) {
      return;
    }

    var rounded = Math.round(visibleMs);
    if (visibleMs < QUICK_EXIT_MS) {
      enqueue("quick_exit", pageProductId, {
        visible_ms: rounded,
        category: pageCategory
      });
    } else {
      enqueue("time_spent", pageProductId, {
        seconds: Math.round(visibleMs / 1000),
        visible_ms: rounded,
        category: pageCategory
      });
    }
  }

  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "hidden") {
      accumulateVisibleTime();
      flush(true); // the tab may never come back
    } else {
      visibleSince = Date.now();
    }
  });

  window.addEventListener("pagehide", function () {
    finalisePageTiming();
    flush(true);
  });

  /* ----------------------------------------------------------- scrolling */

  var lastScrollCheck = 0;
  var reachedMilestones = {};

  window.addEventListener(
    "scroll",
    function () {
      // Throttled by timestamp rather than by a timer, so an idle page schedules
      // no work at all.
      var now = Date.now();
      if (now - lastScrollCheck < SCROLL_THROTTLE_MS) {
        return;
      }
      lastScrollCheck = now;

      var scrollable = document.documentElement.scrollHeight - window.innerHeight;
      if (scrollable <= 0) {
        return;
      }

      var percent = (window.scrollY / scrollable) * 100;
      for (var i = 0; i < SCROLL_MILESTONES.length; i++) {
        var milestone = SCROLL_MILESTONES[i];
        if (percent >= milestone && !reachedMilestones[milestone]) {
          reachedMilestones[milestone] = true;
          enqueue("scroll_depth", pageProductId, { depth: milestone, page: page });
        }
      }
    },
    { passive: true }
  );

  /* -------------------------------------------------------------- search */

  var searchInput = document.querySelector("[data-track-search]");
  if (searchInput) {
    var debounceTimer = null;
    searchInput.addEventListener("input", function () {
      if (debounceTimer !== null) {
        window.clearTimeout(debounceTimer);
      }
      debounceTimer = window.setTimeout(function () {
        debounceTimer = null;
        var query = searchInput.value.trim();
        if (query.length >= MIN_SEARCH_LENGTH) {
          enqueue("search", null, { query: query.slice(0, 200) });
        }
      }, SEARCH_DEBOUNCE_MS);
    });
  }

  /* -------------------------------------------------------------- clicks */

  // Delegated, so cards rendered by any page — catalog today, recommendations
  // later — are covered without re-binding.
  document.addEventListener(
    "click",
    function (event) {
      var target = event.target;
      if (!target || typeof target.closest !== "function") {
        return;
      }
      var card = target.closest("[data-track-card]");
      if (!card) {
        return;
      }

      var productId = Number(card.dataset.productId);
      if (!productId) {
        return;
      }

      var source = card.dataset.trackSource || "catalog";
      enqueue(source === "recommendation" ? "recommendation_click" : "click", productId, {
        source: source,
        category: card.dataset.category || ""
      });
    },
    { passive: true }
  );
})();
