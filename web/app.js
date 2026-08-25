(function () {
  "use strict";

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot, { once: true });
  } else {
    boot();
  }

  function boot() {
    var root = document.documentElement;
    var base = normalizeBase(root.getAttribute("data-base"));
    var elements = {
      article: document.getElementById("article"),
      brand: document.getElementById("brand"),
      crumb: document.getElementById("page-crumb"),
      main: document.getElementById("main"),
      menuButton: document.getElementById("menu-button"),
      nav: document.getElementById("page-nav"),
      progress: document.getElementById("route-progress"),
      reviewBody: document.getElementById("review-body"),
      reviewButton: document.getElementById("review-button"),
      reviewClearSelection: document.getElementById("review-clear-selection"),
      reviewClose: document.getElementById("review-close"),
      reviewCompose: document.getElementById("review-compose"),
      reviewComposeCancel: document.getElementById("review-compose-cancel"),
      reviewComposeClose: document.getElementById("review-compose-close"),
      reviewCount: document.getElementById("review-count"),
      reviewForm: document.getElementById("review-form"),
      reviewFormStatus: document.getElementById("review-form-status"),
      reviewList: document.getElementById("review-list"),
      reviewLiveStatus: document.getElementById("review-live-status"),
      reviewPageComment: document.getElementById("review-page-comment"),
      reviewPanel: document.getElementById("review-panel"),
      reviewPanelBody: document.querySelector("#review-panel .review-panel-body"),
      reviewPanelStatus: document.getElementById("review-panel-status"),
      reviewRefresh: document.getElementById("review-refresh"),
      reviewScrim: document.getElementById("review-scrim"),
      reviewSelection: document.getElementById("review-selection"),
      reviewSelectionAction: document.getElementById("review-selection-action"),
      reviewSelectionAnchor: document.getElementById("review-selection-anchor"),
      reviewSelectionText: document.getElementById("review-selection-text"),
      reviewSubmit: document.getElementById("review-submit"),
      scrim: document.getElementById("nav-scrim"),
      searchButton: document.getElementById("search-button"),
      searchClose: document.getElementById("search-close"),
      searchDialog: document.getElementById("search-dialog"),
      searchInput: document.getElementById("search-input"),
      searchResults: document.getElementById("search-results"),
      sidebarSpaces: document.getElementById("sidebar-spaces"),
      spaces: document.getElementById("space-links"),
      themeButton: document.getElementById("theme-button"),
      toc: document.getElementById("tocbar"),
    };

    if (!elements.article || !elements.nav || !elements.toc) { return; }

    var state = {
      index: null,
      spaces: [],
      title: "Documentation",
      route: "",
      space: null,
      navTree: [],
      codeTree: null,
      requestNumber: 0,
      pageController: null,
      searchItems: null,
      searchPromise: null,
      tocIds: [],
      scrollFrame: 0,
      progressTimer: 0,
      reviewAvailable: false,
      reviewComments: [],
      reviewActionBox: null,
      reviewFocusGeneration: 0,
      reviewFocusTimer: 0,
      reviewComposeReturnFocus: null,
      reviewController: null,
      reviewContext: null,
      reviewDraftRoute: "",
      reviewDraftSequence: 0,
      reviewDraftToken: 0,
      reviewDrafts: new Map(),
      reviewPendingContext: null,
      reviewPendingRequestNumber: 0,
      reviewPendingRoute: "",
      reviewKeepCachedSelection: false,
      reviewRequestNumber: 0,
      reviewReturnFocus: null,
      reviewSelectionFrame: 0,
      reviewPositionFrame: 0,
      reviewSelectionRange: null,
      reviewUseDrawer: false,
    };
    var codeTextByPage = new WeakMap();
    var reviewComposeHome = {
      parent: elements.reviewCompose && elements.reviewCompose.parentNode,
      next: elements.reviewCompose && elements.reviewCompose.nextSibling,
    };
    var reviewComposeResizeObserver = null;

    if ("scrollRestoration" in history) { history.scrollRestoration = "manual"; }

    function normalizeBase(value) {
      var result = String(value || "").trim();
      if (!result || result === "/" || result.indexOf("://") !== -1 || result.indexOf("//") === 0) {
        return "";
      }
      if (result.charAt(0) !== "/") { result = "/" + result; }
      return result.replace(/\/+$/, "");
    }

    function safeDecode(value) {
      try { return decodeURIComponent(value); } catch (ignore) { return value; }
    }

    function normalizeRoute(value) {
      var raw = String(value || "/").split("?")[0].split("#")[0];
      if (raw.charAt(0) !== "/") { raw = "/" + raw; }
      var parts = raw.split("/").filter(function (part) { return part && part !== "."; });
      var clean = [];
      parts.forEach(function (part) {
        if (part === "..") { clean.pop(); }
        else { clean.push(safeDecode(part)); }
      });
      return clean.length ? "/" + clean.join("/") : "/";
    }

    function stripBase(pathname) {
      if (!base) { return pathname || "/"; }
      if (pathname === base || pathname === base + "/") { return "/"; }
      if (pathname.indexOf(base + "/") === 0) { return pathname.slice(base.length); }
      return null;
    }

    function routeFromLocation() {
      var value = stripBase(location.pathname);
      return normalizeRoute(value === null ? "/" : value);
    }

    function siteAsset(path) {
      return base + "/" + String(path || "").replace(/^\/+/, "");
    }

    function siteRoute(route) {
      var value = normalizeRoute(route);
      if (value === "/") { return base ? base + "/" : "/"; }
      return base + value;
    }

    function escapeHtml(value) {
      var replacements = { "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;" };
      return String(value == null ? "" : value).replace(/[&<>"']/g, function (character) {
        return replacements[character];
      });
    }

    function showStatus(title, message, kind) {
      elements.article.innerHTML =
        '<div class="page-status ' + (kind === "error" ? "is-error" : "") + '" role="status">' +
        "<h1>" + escapeHtml(title) + "</h1><p>" + escapeHtml(message) + "</p></div>";
      elements.crumb.textContent = "";
      clearToc();
    }

    function fetchJson(url, signal) {
      return fetch(url, { cache: "no-store", credentials: "same-origin", signal: signal }).then(function (response) {
        if (!response.ok) {
          var error = new Error("Request failed with status " + response.status + ".");
          error.status = response.status;
          throw error;
        }
        return response.json();
      });
    }

    function encodedRoutePath(route) {
      return normalizeRoute(route).split("/").filter(Boolean).map(function (part) {
        return encodeURIComponent(part);
      }).join("/");
    }

    function loadContent(route, signal) {
      var path = encodedRoutePath(route);
      var candidates = path
        ? [siteAsset("content/" + path + ".json"), siteAsset("content/" + path + "/index.json")]
        : [siteAsset("content/index.json")];

      function tryCandidate(index) {
        if (index >= candidates.length) { return Promise.resolve(null); }
        return fetchJson(candidates[index], signal).catch(function (error) {
          if (error && error.name === "AbortError") { throw error; }
          if (error && error.status === 404) { return tryCandidate(index + 1); }
          throw error;
        });
      }
      return tryCandidate(0);
    }

    function visibleSpaces() {
      return state.spaces.filter(function (space) { return space.showInMenu !== false; });
    }

    function homeRoute() {
      var rootSpace = state.spaces.find(function (space) { return space.route === "/"; });
      if (rootSpace) { return rootSpace.route; }
      var visible = visibleSpaces();
      return (visible[0] || state.spaces[0] || { route: "/" }).route;
    }

    function normalizeSpace(space) {
      if (!space || typeof space !== "object") { return null; }
      var navKey = typeof space.navKey === "string" ? space.navKey.trim() : "";
      if (!navKey) { return null; }
      return {
        id: typeof space.id === "string" ? space.id : "",
        navKey: navKey,
        label: typeof space.label === "string" && space.label.trim() ? space.label.trim() : navKey,
        route: normalizeRoute(space.route || "/"),
        hasCode: space.hasCode === true,
        showInMenu: space.showInMenu !== false,
      };
    }

    function spaceForRoute(route) {
      var target = normalizeRoute(route);
      var matches = state.spaces.filter(function (space) {
        return space.route !== "/" && (target === space.route || target.indexOf(space.route + "/") === 0);
      }).sort(function (left, right) { return right.route.length - left.route.length; });
      if (matches.length) { return matches[0]; }
      return state.spaces.find(function (space) { return space.route === "/"; }) || state.spaces[0] || null;
    }

    function loadNav(space, signal) {
      if (!space) { return Promise.resolve({ pages: [], source: null }); }
      var name = encodeURIComponent(space.navKey) + ".json";
      var pages = fetchJson(siteAsset("nav/" + name), signal).then(function (value) {
        if (Array.isArray(value)) { return value; }
        return value && Array.isArray(value.items) ? value.items : [];
      }).catch(function (error) {
        if (error && error.name === "AbortError") { throw error; }
        return [];
      });
      var source = space.hasCode
        ? fetchJson(siteAsset("nav/" + encodeURIComponent(space.navKey) + ".code.json"), signal).catch(function (error) {
          if (error && error.name === "AbortError") { throw error; }
          return null;
        })
        : Promise.resolve(null);
      return Promise.all([pages, source]).then(function (result) {
        return { pages: result[0], source: sourceTreeHasItems(result[1]) ? result[1] : null };
      });
    }

    function sourceTreeHasItems(tree) {
      if (Array.isArray(tree)) {
        return tree.some(function (node) { return node && typeof node === "object" && typeof node.route === "string"; });
      }
      if (!tree || typeof tree !== "object") { return false; }
      if (Array.isArray(tree._files) && tree._files.length) { return true; }
      return Object.keys(tree).some(function (key) {
        return key !== "_files" && sourceTreeHasItems(tree[key]);
      });
    }

    function setProgress(active) {
      window.clearTimeout(state.progressTimer);
      if (active) {
        state.progressTimer = window.setTimeout(function () { elements.progress.hidden = false; }, 100);
      } else {
        elements.progress.hidden = true;
      }
    }

    function saveScrollPosition() {
      var current = history.state;
      if (!current || current.route !== state.route) { return; }
      var next = Object.assign({}, current, { scrollX: window.scrollX, scrollY: window.scrollY });
      history.replaceState(next, "", location.href);
    }

    function scheduleScrollSave() {
      if (state.scrollFrame) { return; }
      state.scrollFrame = window.requestAnimationFrame(function () {
        state.scrollFrame = 0;
        saveScrollPosition();
        updateTocPosition();
      });
    }

    function writeHistory(route, options) {
      if (options.history === false) { return; }
      var hash = options.hash ? "#" + encodeURIComponent(options.hash) : "";
      var url = siteRoute(route) + hash;
      var value = { route: route, scrollX: 0, scrollY: 0 };
      if (options.replace) { history.replaceState(value, "", url); }
      else { history.pushState(value, "", url); }
    }

    function jumpTo(x, y) {
      var previous = root.style.scrollBehavior;
      root.style.scrollBehavior = "auto";
      window.scrollTo(Math.max(0, x || 0), Math.max(0, y || 0));
      root.style.scrollBehavior = previous;
    }

    function scrollAfterRender(options) {
      window.requestAnimationFrame(function () {
        if (options.restore && Number.isFinite(options.restore.scrollY)) {
          jumpTo(options.restore.scrollX, options.restore.scrollY);
          return;
        }
        if (options.hash) {
          var target = document.getElementById(options.hash);
          if (target) {
            target.scrollIntoView({ block: "start" });
            return;
          }
        }
        jumpTo(0, 0);
      });
    }

    function focusAfterRouteChange(options) {
      if (options.focusHash && options.hash) {
        window.requestAnimationFrame(function () {
          var target = document.getElementById(options.hash);
          if (!target || typeof target.focus !== "function") {
            elements.article.focus({ preventScroll: true });
            return;
          }
          var temporaryTabIndex = !target.hasAttribute("tabindex");
          if (temporaryTabIndex) { target.setAttribute("tabindex", "-1"); }
          target.focus({ preventScroll: true });
          if (temporaryTabIndex) {
            target.addEventListener("blur", function () { target.removeAttribute("tabindex"); }, { once: true });
          }
        });
        return;
      }
      if (!options.focus || options.hash) { return; }
      window.requestAnimationFrame(function () {
        elements.article.focus({ preventScroll: true });
      });
    }

    function navigate(route, options) {
      options = options || {};
      var targetRoute = normalizeRoute(route);
      var targetHash = safeDecode(options.hash || "");
      options.hash = targetHash;

      if (targetRoute === state.route && !options.force) {
        saveScrollPosition();
        writeHistory(targetRoute, options);
        scrollAfterRender(options);
        closeSidebar();
        closeSearch();
        focusAfterRouteChange(options);
        return Promise.resolve();
      }

      cancelReviewRefresh();
      hideReviewFeature(false);
      resetReviewComposer();
      saveScrollPosition();
      if (state.pageController) { state.pageController.abort(); }
      state.pageController = new AbortController();
      var signal = state.pageController.signal;
      var requestNumber = ++state.requestNumber;
      var targetSpace = spaceForRoute(targetRoute);
      setProgress(true);
      elements.article.setAttribute("aria-busy", "true");

      return Promise.all([loadContent(targetRoute, signal), loadNav(targetSpace, signal)]).then(function (result) {
        if (requestNumber !== state.requestNumber) { return; }
        var fragment = result[0];
        var navBundle = result[1];
        var tree = navBundle.pages;
        state.route = targetRoute;
        state.space = targetSpace;
        state.navTree = tree;
        state.codeTree = navBundle.source;
        renderSpaces();
        renderNav(tree, navBundle.source, targetRoute);

        if (!fragment) {
          showStatus("Page not found", "No generated document exists at " + targetRoute + ".", "error");
          document.title = "Page not found — " + state.title;
        } else if (fragment.kind === "code") {
          renderCode(fragment);
        } else {
          renderDocument(fragment);
        }

        refreshReviewComments(targetRoute);

        writeHistory(targetRoute, options);
        scrollAfterRender(options);
        closeSidebar();
        closeSearch();
        focusAfterRouteChange(options);
      }).catch(function (error) {
        if (error && error.name === "AbortError") { return; }
        if (requestNumber !== state.requestNumber) { return; }
        showStatus("Unable to load this page", error && error.message ? error.message : "The generated files could not be read.", "error");
      }).finally(function () {
        if (requestNumber === state.requestNumber) {
          setProgress(false);
          elements.article.removeAttribute("aria-busy");
        }
      });
    }

    function isSafeUrl(value, attribute, tagName) {
      var raw = String(value || "").trim();
      if (!raw) { return true; }
      var compact = raw.replace(/[\u0000-\u0020]+/g, "").toLowerCase();
      if (compact.indexOf("javascript:") === 0 || compact.indexOf("vbscript:") === 0) { return false; }
      if (compact.indexOf("data:") === 0) {
        return attribute === "src" && tagName === "IMG" && /^data:image\/(?:png|gif|jpeg|webp);base64,/i.test(raw);
      }
      if (raw.indexOf("//") === 0) { return false; }
      try {
        var url = new URL(raw, location.href);
        return url.protocol === "http:" || url.protocol === "https:" ||
          (attribute === "href" && (url.protocol === "mailto:" || url.protocol === "tel:"));
      } catch (ignore) {
        return false;
      }
    }

    function rebaseRootPath(value) {
      var raw = String(value || "");
      if (!base || raw.charAt(0) !== "/" || raw.indexOf("//") === 0 || raw === base || raw.indexOf(base + "/") === 0) {
        return raw;
      }
      return base + raw;
    }

    function safeFragment(html) {
      var template = document.createElement("template");
      template.innerHTML = String(html || "");
      var blocked = template.content.querySelectorAll("script,style,iframe,object,embed,base,meta,link");
      blocked.forEach(function (node) { node.remove(); });

      template.content.querySelectorAll("*").forEach(function (node) {
        Array.from(node.attributes).forEach(function (attribute) {
          var name = attribute.name.toLowerCase();
          var value = attribute.value;
          if (name.indexOf("on") === 0 || name === "srcdoc" || name === "action" || name === "formaction") {
            node.removeAttribute(attribute.name);
            return;
          }
          if (name === "style") {
            node.removeAttribute(attribute.name);
            return;
          }
          if ((name === "href" || name === "src" || name === "poster" || name === "xlink:href") &&
              !isSafeUrl(value, name === "xlink:href" ? "href" : name, node.tagName)) {
            node.removeAttribute(attribute.name);
            return;
          }
          if (name === "href" || name === "src" || name === "poster") {
            node.setAttribute(attribute.name, rebaseRootPath(value));
          }
        });
        if (node.tagName === "A" && node.getAttribute("target") === "_blank") {
          node.setAttribute("rel", "noopener noreferrer");
        }
      });
      return template.content;
    }

    function prependTitleIfNeeded(title) {
      if (!title || elements.article.querySelector("h1")) { return; }
      var heading = document.createElement("h1");
      heading.textContent = title;
      elements.article.prepend(heading);
    }

    function renderDocument(fragment) {
      var title = typeof fragment.title === "string" && fragment.title.trim() ? fragment.title.trim() : "Documentation";
      elements.article.replaceChildren(safeFragment(fragment.html));
      prependTitleIfNeeded(title);
      appendPageLinks(fragment.prev, fragment.next);
      elements.crumb.textContent = typeof fragment.crumb === "string" ? fragment.crumb : "";
      document.title = title + " — " + state.title;
      hydrateArticle();
      buildToc(fragment.toc);
    }

    function safeSourceUrl(value) {
      if (typeof value !== "string" || !isSafeUrl(value, "href", "A")) { return null; }
      try { return new URL(rebaseRootPath(value), location.href).href; } catch (ignore) { return null; }
    }

    function renderCode(fragment) {
      var title = typeof fragment.title === "string" && fragment.title.trim() ? fragment.title.trim() : "Source";
      var page = document.createElement("div");
      page.className = "code-page";
      if (Array.isArray(fragment.lines)) {
        codeTextByPage.set(page, fragment.lines.map(function (line) { return String(line); }).join("\n"));
      }

      var header = document.createElement("header");
      header.className = "code-page-header";
      var heading = document.createElement("h1");
      heading.textContent = title;
      header.appendChild(heading);
      if (typeof fragment.path === "string" && fragment.path) {
        var path = document.createElement("p");
        path.className = "code-page-path";
        path.textContent = fragment.path;
        header.appendChild(path);
      }
      var actions = document.createElement("div");
      actions.className = "code-page-actions";
      var copy = document.createElement("button");
      copy.className = "copy code-page-copy";
      copy.type = "button";
      copy.textContent = "Copy";
      actions.appendChild(copy);
      var sourceUrl = safeSourceUrl(fragment.sourceUrl);
      if (sourceUrl) {
        var source = document.createElement("a");
        source.href = sourceUrl;
        source.target = "_blank";
        source.rel = "noopener noreferrer";
        source.textContent = "Open source";
        actions.appendChild(source);
      }
      header.appendChild(actions);
      page.appendChild(header);

      var body = document.createElement("div");
      body.className = "code-page-body";
      if (typeof fragment.html === "string" && fragment.html.trim()) {
        body.replaceChildren(safeFragment(fragment.html));
      } else if (Array.isArray(fragment.lines)) {
        var pre = document.createElement("pre");
        var code = document.createElement("code");
        code.textContent = fragment.lines.map(function (line) { return String(line); }).join("\n");
        pre.appendChild(code);
        body.appendChild(pre);
      }
      page.appendChild(body);
      elements.article.replaceChildren(page);
      elements.crumb.textContent = typeof fragment.path === "string" ? fragment.path : "";
      document.title = title + " — " + state.title;
      hydrateArticle();
      buildToc([]);
    }

    function appendPageLinks(previous, next) {
      var entries = [
        { value: previous, label: "Previous", className: "previous" },
        { value: next, label: "Next", className: "next" },
      ];
      if (!entries.some(function (entry) { return validPageLink(entry.value); })) { return; }
      var nav = document.createElement("nav");
      nav.className = "page-links";
      nav.setAttribute("aria-label", "Adjacent pages");
      entries.forEach(function (entry) {
        if (!validPageLink(entry.value)) { return; }
        var link = createRouteLink(entry.value.title || entry.value.route, entry.value.route, "page-link " + entry.className);
        var direction = document.createElement("span");
        direction.className = "page-link-direction";
        direction.textContent = entry.label;
        link.prepend(direction);
        nav.appendChild(link);
      });
      elements.article.appendChild(nav);
    }

    function validPageLink(value) {
      return value && typeof value === "object" && typeof value.route === "string";
    }

    function createRouteLink(label, route, className) {
      var link = document.createElement("a");
      link.className = className || "";
      link.href = siteRoute(route);
      link.setAttribute("data-route", "");
      link.textContent = String(label || route || "Page");
      return link;
    }

    function renderSpaces() {
      var spaces = visibleSpaces();
      [elements.spaces, elements.sidebarSpaces].forEach(function (container) {
        container.replaceChildren();
        spaces.forEach(function (space) {
          var link = createRouteLink(space.label, space.route, "space-link");
          var active = state.space && state.space.navKey === space.navKey;
          link.classList.toggle("is-active", Boolean(active));
          if (active) { link.setAttribute("aria-current", "page"); }
          container.appendChild(link);
        });
      });
    }

    function navState() {
      try { return JSON.parse(localStorage.getItem("docs-nav-open") || "{}") || {}; }
      catch (ignore) { return {}; }
    }

    function saveNavState(value) {
      try { localStorage.setItem("docs-nav-open", JSON.stringify(value)); } catch (ignore) {}
    }

    function groupKey(node) {
      return String(node.index || firstRoute(node) || node.label || "group");
    }

    function createNavChevronSlot(withChevron) {
      var slot = document.createElement("span");
      slot.className = "nav-chevron-slot";
      slot.setAttribute("aria-hidden", "true");
      if (withChevron) {
        var chevron = document.createElement("span");
        chevron.className = "nav-chevron";
        slot.appendChild(chevron);
      }
      return slot;
    }

    function createNavLabel(label, className) {
      var text = document.createElement("span");
      text.className = className || "nav-label-text";
      text.textContent = String(label || "Page");
      return text;
    }

    function describePlanCount(value) {
      var count = Number(value);
      if (!Number.isSafeInteger(count) || count <= 0) { return null; }
      var noun = count === 1 ? "plan" : "plans";
      return {
        fullLabel: count + " " + noun,
        visibleLabel: count > 99 ? "99+" : String(count),
      };
    }

    function appendAccessiblePlanCount(container, description) {
      if (!description) { return; }
      var accessible = document.createElement("span");
      accessible.className = "sr-only";
      accessible.textContent = description.fullLabel;
      container.appendChild(accessible);
    }

    function createPlanCount(description) {
      if (!description) { return null; }
      var badge = document.createElement("span");
      badge.className = "nav-plan-count";
      badge.textContent = description.visibleLabel;
      badge.title = description.fullLabel;
      badge.setAttribute("aria-hidden", "true");
      return badge;
    }

    function firstRoute(node) {
      if (!node || typeof node !== "object") { return null; }
      if (typeof node.route === "string") { return node.route; }
      if (typeof node.index === "string") { return node.index; }
      var items = Array.isArray(node.items) ? node.items : [];
      for (var index = 0; index < items.length; index += 1) {
        var route = firstRoute(items[index]);
        if (route) { return route; }
      }
      return null;
    }

    function containsRoute(node, route) {
      if (!node || typeof node !== "object") { return false; }
      if (node.route && normalizeRoute(node.route) === route) { return true; }
      if (node.index && normalizeRoute(node.index) === route) { return true; }
      return (Array.isArray(node.items) ? node.items : []).some(function (item) {
        return containsRoute(item, route);
      });
    }

    function renderNav(tree, codeTree, route) {
      elements.nav.replaceChildren();
      var list = document.createElement("div");
      list.className = "nav-tree";
      (Array.isArray(tree) ? tree : []).forEach(function (node) {
        var rendered = renderNavNode(node, route, 0);
        if (rendered) { list.appendChild(rendered); }
      });
      if (codeTree && state.space) {
        list.appendChild(renderSourceNav(codeTree, state.space, route));
      }
      elements.nav.appendChild(list);
      var active = elements.nav.querySelector(".nav-link.is-active");
      if (active) { window.requestAnimationFrame(function () { active.scrollIntoView({ block: "nearest" }); }); }
    }

    function renderNavNode(node, route, depth) {
      if (!node || typeof node !== "object") { return null; }
      var items = Array.isArray(node.items) ? node.items : [];
      var pageRoute = typeof node.route === "string" ? node.route : null;
      var indexRoute = typeof node.index === "string" ? node.index : null;
      var label = typeof node.label === "string" ? node.label : pageRoute || indexRoute || "Page";

      if (node.kind === "page" || pageRoute || (indexRoute && !items.length)) {
        var linkRoute = pageRoute || indexRoute;
        var link = createRouteLink(label, linkRoute, "nav-link");
        link.replaceChildren(createNavChevronSlot(false), createNavLabel(label));
        var pagePlanDescription = describePlanCount(node.planCount);
        appendAccessiblePlanCount(link, pagePlanDescription);
        var pagePlanCount = createPlanCount(pagePlanDescription);
        if (pagePlanCount) { link.appendChild(pagePlanCount); }
        link.style.setProperty("--nav-indent", (Math.min(depth, 6) * 0.72) + "rem");
        if (normalizeRoute(linkRoute) === route) {
          link.classList.add("is-active");
          link.setAttribute("aria-current", "page");
        }
        return link;
      }

      var details = document.createElement("details");
      details.className = "nav-group";
      details.dataset.navKey = groupKey(node);
      var stored = navState();
      details.open = Object.prototype.hasOwnProperty.call(stored, details.dataset.navKey)
        ? Boolean(stored[details.dataset.navKey])
        : containsRoute(node, route);

      var summary = document.createElement("summary");
      summary.style.setProperty("--nav-indent", (Math.min(depth, 6) * 0.72) + "rem");
      summary.appendChild(createNavChevronSlot(true));
      if (indexRoute) {
        var groupLink = createRouteLink(label, indexRoute, "nav-group-label");
        groupLink.replaceChildren(createNavLabel(label));
        appendAccessiblePlanCount(groupLink, describePlanCount(node.planCount));
        if (normalizeRoute(indexRoute) === route) {
          groupLink.classList.add("is-active");
          groupLink.setAttribute("aria-current", "page");
        }
        summary.appendChild(groupLink);
      } else {
        var groupLabel = document.createElement("span");
        groupLabel.className = "nav-group-label";
        groupLabel.appendChild(createNavLabel(label));
        appendAccessiblePlanCount(groupLabel, describePlanCount(node.planCount));
        summary.appendChild(groupLabel);
      }
      var groupPlanCount = createPlanCount(describePlanCount(node.planCount));
      if (groupPlanCount) { summary.appendChild(groupPlanCount); }
      details.appendChild(summary);

      var children = document.createElement("div");
      children.className = "nav-children";
      items.forEach(function (item) {
        var child = renderNavNode(item, route, depth + 1);
        if (child) { children.appendChild(child); }
      });
      details.appendChild(children);
      return details;
    }

    function safeSourceSegment(value) {
      var segment = String(value || "");
      return segment && segment !== "." && segment !== ".." && !/[\\/\u0000]/.test(segment) ? segment : null;
    }

    function sourceRoutePrefix(space) {
      return space.route === "/" ? "/code" : space.route + "/code";
    }

    function renderSourceNav(tree, space, route) {
      var prefix = sourceRoutePrefix(space);
      var details = document.createElement("details");
      details.className = "nav-group source-nav";
      details.dataset.navKey = "source:" + space.navKey;
      var stored = navState();
      details.open = Object.prototype.hasOwnProperty.call(stored, details.dataset.navKey)
        ? Boolean(stored[details.dataset.navKey])
        : route === prefix || route.indexOf(prefix + "/") === 0;

      var summary = document.createElement("summary");
      var label = document.createElement("span");
      label.className = "nav-group-label";
      label.appendChild(createNavLabel("Source"));
      summary.append(createNavChevronSlot(true), label);
      details.appendChild(summary);

      var children = document.createElement("div");
      children.className = "nav-children source-tree";
      if (Array.isArray(tree)) {
        tree.forEach(function (node) {
          var child = renderNavNode(node, route, 1);
          if (child) {
            if (child.classList.contains("nav-link")) { child.classList.add("source-file"); }
            children.appendChild(child);
          }
        });
      } else {
        renderSourceTreeChildren(children, tree, prefix, [], route, 1);
      }
      details.appendChild(children);
      return details;
    }

    function renderSourceTreeChildren(container, tree, prefix, pathParts, route, depth) {
      if (!tree || typeof tree !== "object" || Array.isArray(tree)) { return; }
      Object.keys(tree).filter(function (key) { return key !== "_files"; }).sort(function (left, right) {
        return left.localeCompare(right);
      }).forEach(function (directory) {
        var segment = safeSourceSegment(directory);
        if (!segment || !sourceTreeHasItems(tree[directory])) { return; }
        var details = document.createElement("details");
        details.className = "source-directory";
        var directoryParts = pathParts.concat(segment);
        var directoryPrefix = prefix + "/" + directoryParts.join("/");
        details.open = route.indexOf(directoryPrefix + "/") === 0;
        var summary = document.createElement("summary");
        summary.style.setProperty("--nav-indent", (Math.min(depth, 6) * 0.72) + "rem");
        var label = document.createElement("span");
        label.className = "source-directory-label";
        label.textContent = segment + "/";
        summary.append(createNavChevronSlot(true), label);
        details.appendChild(summary);
        var children = document.createElement("div");
        children.className = "nav-children";
        renderSourceTreeChildren(children, tree[directory], prefix, directoryParts, route, depth + 1);
        details.appendChild(children);
        container.appendChild(details);
      });

      (Array.isArray(tree._files) ? tree._files.slice() : []).sort(function (left, right) {
        return String(left).localeCompare(String(right));
      }).forEach(function (file) {
        var segment = safeSourceSegment(file);
        if (!segment) { return; }
        var targetRoute = prefix + "/" + pathParts.concat(segment).join("/");
        var link = createRouteLink(segment, targetRoute, "nav-link source-file");
        link.replaceChildren(createNavChevronSlot(false), createNavLabel(segment));
        link.style.setProperty("--nav-indent", (Math.min(depth, 6) * 0.72) + "rem");
        if (normalizeRoute(targetRoute) === route) {
          link.classList.add("is-active");
          link.setAttribute("aria-current", "page");
        }
        container.appendChild(link);
      });
    }

    function clearToc() {
      state.tocIds = [];
      elements.toc.replaceChildren();
      elements.toc.hidden = true;
    }

    function buildToc(value) {
      clearToc();
      if (!Array.isArray(value)) { return; }
      var items = value.map(function (entry) {
        if (Array.isArray(entry)) {
          return { level: Number(entry[0]) || 2, id: String(entry[1] || ""), text: String(entry[2] || "") };
        }
        if (entry && typeof entry === "object") {
          return { level: Number(entry.level) || 2, id: String(entry.id || ""), text: String(entry.text || entry.title || "") };
        }
        return null;
      }).filter(function (entry) { return entry && entry.id && entry.text; });
      if (!items.length) { return; }

      var title = document.createElement("h2");
      title.className = "toc-title";
      title.textContent = "On this page";
      elements.toc.appendChild(title);
      var nav = document.createElement("nav");
      items.forEach(function (item) {
        var link = createRouteLink(item.text, state.route, "toc-link");
        link.href += "#" + encodeURIComponent(item.id);
        link.dataset.tocId = item.id;
        link.dataset.level = String(Math.max(2, Math.min(6, item.level)));
        nav.appendChild(link);
      });
      elements.toc.appendChild(nav);
      elements.toc.hidden = false;
      state.tocIds = items.map(function (item) { return item.id; });
      updateTocPosition();
    }

    function updateTocPosition() {
      if (!state.tocIds.length) { return; }
      var current = state.tocIds[0];
      state.tocIds.forEach(function (id) {
        var heading = document.getElementById(id);
        if (heading && heading.getBoundingClientRect().top <= 130) { current = id; }
      });
      elements.toc.querySelectorAll(".toc-link").forEach(function (link) {
        link.classList.toggle("is-active", link.dataset.tocId === current);
      });
    }

    function hydrateArticle() {
      hydrateTabs(elements.article);
      if (window.Prism && typeof window.Prism.highlightAllUnder === "function") {
        window.Prism.highlightAllUnder(elements.article);
      }
      elements.article.querySelectorAll("pre").forEach(function (pre) {
        if (pre.closest(".code-page-body")) { return; }
        var box = pre.closest(".codeblock") || pre.parentElement;
        if (!box || box.querySelector(":scope > .copy")) { return; }
        var button = document.createElement("button");
        button.className = "copy";
        button.type = "button";
        button.textContent = "Copy";
        box.insertBefore(button, box.firstChild);
      });
    }

    function hydrateTabs(scope) {
      scope.querySelectorAll(".tabs").forEach(function (tabs, groupIndex) {
        var buttons = Array.from(tabs.querySelectorAll(".tab-btn"));
        var panes = Array.from(tabs.querySelectorAll(".tab-pane"));
        if (!buttons.length || !panes.length) { return; }
        panes.forEach(function (pane) {
          var onlyChild = pane.childElementCount === 1 ? pane.firstElementChild : null;
          pane.classList.toggle("code-only", Boolean(onlyChild && onlyChild.classList.contains("codeblock")));
        });
        var selected = buttons.find(function (button) { return button.classList.contains("active"); }) || buttons[0];
        buttons.forEach(function (button, index) {
          var key = button.getAttribute("data-tab") || String(index);
          var id = "tab-" + state.requestNumber + "-" + groupIndex + "-" + index;
          button.id = id;
          button.setAttribute("role", "tab");
          button.setAttribute("aria-selected", button === selected ? "true" : "false");
          button.tabIndex = button === selected ? 0 : -1;
          var pane = panes.find(function (candidate, paneIndex) {
            return (candidate.getAttribute("data-pane") || String(paneIndex)) === key;
          });
          if (pane) {
            pane.setAttribute("role", "tabpanel");
            pane.setAttribute("aria-labelledby", id);
            pane.hidden = button !== selected;
            pane.classList.toggle("active", button === selected);
          }
          button.classList.toggle("active", button === selected);
        });
        var bar = tabs.querySelector(".tab-bar");
        if (bar) { bar.setAttribute("role", "tablist"); }
      });
    }

    function activateTab(button, focus) {
      var tabs = button.closest(".tabs");
      if (!tabs) { return; }
      var key = button.getAttribute("data-tab");
      tabs.querySelectorAll(".tab-btn").forEach(function (candidate) {
        var active = candidate === button;
        candidate.classList.toggle("active", active);
        candidate.setAttribute("aria-selected", active ? "true" : "false");
        candidate.tabIndex = active ? 0 : -1;
      });
      tabs.querySelectorAll(".tab-pane").forEach(function (pane) {
        var active = pane.getAttribute("data-pane") === key;
        pane.classList.toggle("active", active);
        pane.hidden = !active;
      });
      if (focus) { button.focus(); }
    }

    function copyText(text) {
      if (navigator.clipboard && window.isSecureContext) { return navigator.clipboard.writeText(text); }
      return new Promise(function (resolve, reject) {
        var field = document.createElement("textarea");
        field.value = text;
        field.setAttribute("readonly", "");
        field.className = "clipboard-field";
        document.body.appendChild(field);
        field.select();
        try {
          if (!document.execCommand("copy")) { throw new Error("Copy was not accepted."); }
          resolve();
        } catch (error) { reject(error); }
        finally { field.remove(); }
      });
    }

    function textForCopy(button) {
      var codePage = button.closest(".code-page");
      if (codePage) {
        if (codeTextByPage.has(codePage)) { return codeTextByPage.get(codePage); }
        var codeBody = codePage.querySelector(".code-page-body");
        if (!codeBody) { return ""; }
        var sourceRows = Array.from(codeBody.querySelectorAll(".source-lines td pre"));
        if (sourceRows.length > 1) {
          return sourceRows.map(function (row) { return (row.textContent || "").replace(/\r?\n$/, ""); }).join("\n");
        }
        var source = sourceRows[0] || codeBody.querySelector("pre code") || codeBody.querySelector("pre");
        return source ? (source.textContent || "") : (codeBody.innerText || codeBody.textContent || "");
      }
      var box = button.closest(".codeblock") || button.parentElement;
      var code = box ? box.querySelector("code") : null;
      return code ? code.textContent : box ? (box.innerText || box.textContent || "").replace(/^Copy\s*/i, "") : "";
    }

    function showCopyResult(button, success) {
      var original = button.dataset.copyLabel || button.textContent || "Copy";
      button.dataset.copyLabel = original;
      button.textContent = success ? "Copied" : "Try again";
      window.setTimeout(function () { button.textContent = original; }, 1400);
    }

    function reviewEndpoint(id) {
      var endpoint = siteAsset("__agent-docs/review/comments");
      return id ? endpoint + "/" + encodeURIComponent(String(id)) : endpoint;
    }

    function requestReviewJson(url, options) {
      var request = Object.assign({
        cache: "no-store",
        credentials: "same-origin",
        headers: { Accept: "application/json" },
      }, options || {});
      return fetch(url, request).then(function (response) {
        if (!response.ok) {
          var error = new Error("Review request failed with status " + response.status + ".");
          error.status = response.status;
          throw error;
        }
        if (response.status === 204 || typeof response.json !== "function") { return null; }
        return response.json();
      });
    }

    function normalizeReviewComment(value) {
      if (!value || typeof value !== "object") { return null; }
      var status = value.status === "answered" || value.status === "resolved" ? value.status : "open";
      var body = typeof value.body === "string" ? value.body.trim() : "";
      if (!body) { return null; }
      return {
        id: typeof value.id === "string" || typeof value.id === "number" ? String(value.id) : "",
        route: normalizeRoute(typeof value.route === "string" ? value.route : state.route),
        anchor: typeof value.anchor === "string" ? value.anchor.trim() : "",
        quote: typeof value.quote === "string" ? value.quote.trim() : "",
        body: body,
        status: status,
        reply: typeof value.reply === "string" ? value.reply.trim() : "",
        createdAt: typeof value.createdAt === "string" ? value.createdAt : "",
        updatedAt: typeof value.updatedAt === "string" ? value.updatedAt : "",
      };
    }

    function commentsFromReviewPayload(payload, route) {
      var values = payload && Array.isArray(payload.comments) ? payload.comments : [];
      var target = normalizeRoute(route);
      return values.map(normalizeReviewComment).filter(function (comment) {
        return comment && comment.route === target;
      }).sort(compareReviewComments);
    }

    function compareReviewComments(left, right) {
      var leftCreated = left.createdAt || left.updatedAt || "";
      var rightCreated = right.createdAt || right.updatedAt || "";
      if (leftCreated !== rightCreated) { return rightCreated.localeCompare(leftCreated); }
      var leftUpdated = left.updatedAt || "";
      var rightUpdated = right.updatedAt || "";
      if (leftUpdated !== rightUpdated) { return rightUpdated.localeCompare(leftUpdated); }
      return right.id.localeCompare(left.id);
    }

    function commentFromReviewPayload(payload, expectedRoute) {
      var raw = payload && payload.comment;
      var comment = normalizeReviewComment(raw);
      if (expectedRoute !== undefined) {
        if (!raw || typeof raw.route !== "string" || !comment
            || comment.route !== normalizeRoute(expectedRoute)) { return null; }
      }
      return comment;
    }

    function reviewStatusLabel(status) {
      if (status === "answered") { return "Answered"; }
      if (status === "resolved") { return "Resolved"; }
      return "Open";
    }

    function reviewDate(value) {
      if (!value) { return ""; }
      var date = new Date(value);
      if (!Number.isFinite(date.getTime())) { return ""; }
      try {
        return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(date);
      } catch (ignore) {
        return date.toLocaleString();
      }
    }

    function renderReviewCount() {
      var total = state.reviewComments.length;
      // The badge is an action count; resolved comments remain visible in the thread.
      var count = state.reviewComments.filter(function (comment) { return comment.status !== "resolved"; }).length;
      elements.reviewCount.textContent = count > 99 ? "99+" : String(count);
      elements.reviewCount.hidden = count === 0;
      elements.reviewCount.setAttribute("aria-hidden", "true");
      elements.reviewButton.setAttribute(
        "aria-label",
        count ? "Page comments, " + count + " unresolved" : total ? "Page comments, all resolved" : "Page comments",
      );
    }

    function renderReviewList() {
      elements.reviewList.replaceChildren();
      renderReviewCount();
      if (!state.reviewComments.length) {
        var empty = document.createElement("p");
        empty.className = "review-empty";
        empty.textContent = "No comments on this page yet.";
        elements.reviewList.appendChild(empty);
        return;
      }

      state.reviewComments.forEach(function (comment) {
        var item = document.createElement("article");
        item.className = "review-comment";
        item.dataset.reviewId = comment.id;

        var header = document.createElement("header");
        header.className = "review-comment-header";
        var status = document.createElement("span");
        status.className = "review-status is-" + comment.status;
        status.textContent = reviewStatusLabel(comment.status);
        header.appendChild(status);

        var dateText = reviewDate(comment.updatedAt || comment.createdAt);
        if (dateText) {
          var time = document.createElement("time");
          time.dateTime = comment.updatedAt || comment.createdAt;
          time.textContent = dateText;
          header.appendChild(time);
        }
        item.appendChild(header);

        if (comment.anchor) {
          var anchor = document.createElement("a");
          anchor.className = "review-anchor";
          anchor.href = siteRoute(state.route) + "#" + encodeURIComponent(comment.anchor);
          anchor.dataset.route = "";
          anchor.textContent = "#" + comment.anchor;
          item.appendChild(anchor);
        }

        if (comment.quote) {
          var quote = document.createElement("blockquote");
          quote.className = "review-quote";
          quote.textContent = comment.quote;
          item.appendChild(quote);
        }

        var body = document.createElement("p");
        body.className = "review-comment-body";
        body.textContent = comment.body;
        item.appendChild(body);

        if (comment.reply) {
          var reply = document.createElement("div");
          reply.className = "review-reply";
          var replyLabel = document.createElement("strong");
          replyLabel.textContent = "Skill reply";
          var replyBody = document.createElement("p");
          replyBody.textContent = comment.reply;
          reply.append(replyLabel, replyBody);
          item.appendChild(reply);
        }

        if (comment.id) {
          var actions = document.createElement("div");
          actions.className = "review-comment-actions";
          if (comment.status === "resolved" || (comment.status === "answered" && comment.reply)) {
            var update = document.createElement("button");
            update.className = "review-text-button review-status-button";
            update.type = "button";
            update.dataset.reviewId = comment.id;
            update.dataset.reviewStatus = comment.status === "resolved" ? "open" : "resolved";
            update.textContent = comment.status === "resolved" ? "Reopen" : "Resolve";
            actions.appendChild(update);
          } else {
            var awaiting = document.createElement("span");
            awaiting.className = "review-awaiting";
            awaiting.textContent = comment.reply ? "Awaiting skill follow-up" : "Awaiting skill reply";
            actions.appendChild(awaiting);
          }
          item.appendChild(actions);
        }

        elements.reviewList.appendChild(item);
      });
    }

    function upsertReviewComment(comment) {
      var index = state.reviewComments.findIndex(function (candidate) { return candidate.id === comment.id; });
      if (index >= 0) {
        state.reviewComments[index] = comment;
      } else {
        state.reviewComments.push(comment);
      }
      state.reviewComments.sort(compareReviewComments);
    }

    function setReviewBackgroundInert(active) {
      [document.querySelector(".topbar"), document.querySelector(".shell"), elements.searchDialog, elements.reviewSelectionAction]
        .filter(Boolean).forEach(function (element) {
          if (active) { element.setAttribute("inert", ""); }
          else { element.removeAttribute("inert"); }
        });
    }

    function restoreReviewComposeHome() {
      if (!reviewComposeHome.parent || elements.reviewCompose.parentNode === reviewComposeHome.parent) { return; }
      if (reviewComposeHome.next && reviewComposeHome.next.parentNode === reviewComposeHome.parent) {
        reviewComposeHome.parent.insertBefore(elements.reviewCompose, reviewComposeHome.next);
      } else {
        reviewComposeHome.parent.appendChild(elements.reviewCompose);
      }
      elements.reviewCompose.setAttribute("role", "dialog");
      if (elements.reviewCompose.dataset.placement === "drawer") { elements.reviewCompose.dataset.placement = "right"; }
      elements.reviewPageComment.setAttribute("aria-expanded", "false");
    }

    function mountReviewComposeInDrawer() {
      if (!elements.reviewPanelBody) { return false; }
      var thread = elements.reviewPanelBody.querySelector(".review-thread");
      elements.reviewPanelBody.insertBefore(elements.reviewCompose, thread || null);
      elements.reviewCompose.setAttribute("role", "region");
      elements.reviewCompose.dataset.placement = "drawer";
      elements.reviewCompose.style.removeProperty("left");
      elements.reviewCompose.style.removeProperty("right");
      elements.reviewCompose.style.removeProperty("top");
      elements.reviewCompose.style.removeProperty("bottom");
      elements.reviewCompose.style.removeProperty("max-height");
      elements.reviewCompose.style.removeProperty("width");
      elements.reviewPageComment.setAttribute("aria-expanded", "true");
      return true;
    }

    function closeReview(restoreFocus) {
      cancelReviewFocus();
      if (elements.reviewPanel.hidden) { return; }
      if (elements.reviewCompose.parentNode === elements.reviewPanelBody) {
        closeReviewCompose(false, !reviewComposerIsDirty(), false);
      }
      document.body.classList.remove("review-open");
      elements.reviewPanel.hidden = true;
      elements.reviewScrim.hidden = true;
      elements.reviewButton.setAttribute("aria-expanded", "false");
      setReviewBackgroundInert(false);
      if (restoreFocus !== false && state.reviewReturnFocus && typeof state.reviewReturnFocus.focus === "function") {
        state.reviewReturnFocus.focus();
      }
      state.reviewReturnFocus = null;
      scheduleReviewSelectionAction();
    }

    function nearestSelectionHeading(startNode) {
      var node = startNode && startNode.nodeType === 1 ? startNode : startNode && startNode.parentElement;
      if (!node || !elements.article.contains(node)) { return null; }
      var nearest = null;
      elements.article.querySelectorAll("h1[id],h2[id],h3[id],h4[id],h5[id],h6[id]").forEach(function (heading) {
        if (heading === node || heading.contains(node) || (heading.compareDocumentPosition(node) & 4)) {
          nearest = heading;
        }
      });
      return nearest;
    }

    function selectedReviewBundle() {
      if (typeof window.getSelection !== "function") { return null; }
      var selection = window.getSelection();
      if (!selection || selection.isCollapsed || !selection.rangeCount) { return null; }
      var range = selection.getRangeAt(0);
      var start = range.startContainer;
      var end = range.endContainer;
      var startElement = start.nodeType === 1 ? start : start.parentElement;
      var endElement = end.nodeType === 1 ? end : end.parentElement;
      if (!elements.article.contains(startElement) || !elements.article.contains(endElement)) { return null; }
      var quote = String(selection.toString() || "").replace(/\s+/g, " ").trim();
      if (!quote) { return null; }
      if (quote.length > 2000) { quote = quote.slice(0, 1999) + "\u2026"; }
      var heading = nearestSelectionHeading(start);
      var anchor = heading ? String(heading.id || "").trim() : "";
      if (!anchor || anchor.length > 256 || anchor.indexOf("#") !== -1 || /[\u0000-\u001f\u007f]/.test(anchor)) {
        anchor = "";
      }
      return { context: { quote: quote, anchor: anchor }, range: range };
    }

    function setReviewContext(context) {
      state.reviewContext = context && context.quote ? context : null;
      elements.reviewSelection.hidden = !state.reviewContext;
      elements.reviewClearSelection.hidden = !state.reviewContext;
      elements.reviewSelectionText.textContent = state.reviewContext ? state.reviewContext.quote : "";
      if (state.reviewContext && state.reviewContext.anchor) {
        elements.reviewSelectionAnchor.textContent = "#" + state.reviewContext.anchor;
        elements.reviewSelectionAnchor.href = siteRoute(state.route) + "#" + encodeURIComponent(state.reviewContext.anchor);
        elements.reviewSelectionAnchor.hidden = false;
      } else {
        elements.reviewSelectionAnchor.textContent = "";
        elements.reviewSelectionAnchor.removeAttribute("href");
        elements.reviewSelectionAnchor.hidden = true;
      }
      scheduleReviewPosition();
    }

    function reviewComposerIsDirty() {
      return Boolean(elements.reviewBody.value);
    }

    function nextReviewDraftToken() {
      state.reviewDraftSequence += 1;
      state.reviewDraftToken = state.reviewDraftSequence;
      return state.reviewDraftToken;
    }

    function ensureReviewDraftToken() {
      return state.reviewDraftToken || nextReviewDraftToken();
    }

    function clearReviewDraft(route, expectedToken) {
      var target = route || state.reviewDraftRoute || state.route;
      if (!target) { return false; }
      target = normalizeRoute(target);
      var draft = state.reviewDrafts.get(target);
      if (expectedToken !== undefined && (!draft || draft.token !== expectedToken)) { return false; }
      return state.reviewDrafts.delete(target);
    }

    function snapshotReviewDraft(route) {
      var target = route || state.reviewDraftRoute || state.route;
      if (!target) { return false; }
      target = normalizeRoute(target);
      if (!reviewComposerIsDirty()) {
        if (state.reviewDraftRoute === target) { state.reviewDrafts.delete(target); }
        return false;
      }
      state.reviewDrafts.set(target, {
        body: elements.reviewBody.value,
        context: state.reviewContext
          ? { quote: state.reviewContext.quote, anchor: state.reviewContext.anchor || "" }
          : null,
        token: ensureReviewDraftToken(),
      });
      return true;
    }

    function restoreReviewDraft(route) {
      var target = normalizeRoute(route || state.route || "/");
      if (reviewComposerIsDirty() && state.reviewDraftRoute === target) { return true; }
      var draft = state.reviewDrafts.get(target);
      if (!draft || !draft.body) { return false; }
      resetReviewComposer();
      hideReviewSelectionAction(true);
      elements.reviewBody.value = draft.body;
      setReviewContext(draft.context);
      state.reviewDraftRoute = target;
      state.reviewDraftToken = draft.token || nextReviewDraftToken();
      setReviewFormStatus("Draft restored.");
      return true;
    }

    function finiteNumber(value, fallback) {
      return Number.isFinite(value) ? value : fallback;
    }

    function clampNumber(value, minimum, maximum) {
      return Math.min(Math.max(value, minimum), Math.max(minimum, maximum));
    }

    function rangeViewportRect(range) {
      if (!range) { return null; }
      var rect = null;
      if (typeof range.getClientRects === "function") {
        var rects = Array.from(range.getClientRects());
        for (var index = rects.length - 1; index >= 0; index -= 1) {
          if (rects[index] && (rects[index].width || rects[index].height)) {
            rect = rects[index];
            break;
          }
        }
      }
      if (!rect && typeof range.getBoundingClientRect === "function") { rect = range.getBoundingClientRect(); }
      if (!rect) {
        var start = range.startContainer;
        var element = start && start.nodeType === 1 ? start : start && start.parentElement;
        if (element && typeof element.getBoundingClientRect === "function") { rect = element.getBoundingClientRect(); }
      }
      if (!rect) { return null; }
      var left = finiteNumber(rect.left, 0);
      var top = finiteNumber(rect.top, 0);
      var width = Math.max(0, finiteNumber(rect.width, finiteNumber(rect.right, left) - left));
      var height = Math.max(0, finiteNumber(rect.height, finiteNumber(rect.bottom, top) - top));
      return {
        left: left,
        top: top,
        right: finiteNumber(rect.right, left + width),
        bottom: finiteNumber(rect.bottom, top + height),
        width: width,
        height: height,
      };
    }

    function viewportSize() {
      var visual = window.visualViewport;
      var fallbackWidth = finiteNumber(window.innerWidth, 0) > 0
        ? window.innerWidth
        : finiteNumber(document.documentElement.clientWidth, 0) > 0 ? document.documentElement.clientWidth : 1024;
      var fallbackHeight = finiteNumber(window.innerHeight, 0) > 0
        ? window.innerHeight
        : finiteNumber(document.documentElement.clientHeight, 0) > 0 ? document.documentElement.clientHeight : 768;
      var visualWidth = visual ? finiteNumber(visual.width, 0) : 0;
      var visualHeight = visual ? finiteNumber(visual.height, 0) : 0;
      var width = visualWidth > 0 ? visualWidth : fallbackWidth;
      var height = visualHeight > 0 ? visualHeight : fallbackHeight;
      var left = visual ? finiteNumber(visual.offsetLeft, 0) : 0;
      var top = visual ? finiteNumber(visual.offsetTop, 0) : 0;
      return { left: left, top: top, right: left + width, bottom: top + height, width: width, height: height };
    }

    function reviewTopBoundary(viewport) {
      var topbar = document.querySelector(".topbar");
      var headerHeight = topbar ? (topbar.offsetHeight || 56) : 0;
      var headerBottom = viewport.top + headerHeight;
      var edge = Math.min(12, Math.max(0, viewport.height / 4));
      if (topbar && typeof topbar.getBoundingClientRect === "function") {
        var rect = topbar.getBoundingClientRect();
        if (rect && finiteNumber(rect.bottom, 0) > viewport.top) {
          headerBottom = Math.max(headerBottom, rect.bottom);
        }
      }
      return clampNumber(headerBottom + 8, viewport.top + edge, viewport.bottom - edge);
    }

    function hideReviewSelectionAction(clearContext) {
      elements.reviewSelectionAction.hidden = true;
      elements.reviewSelectionAction.setAttribute("aria-expanded", "false");
      state.reviewActionBox = null;
      if (clearContext !== false) {
        state.reviewKeepCachedSelection = false;
        state.reviewPendingContext = null;
        state.reviewPendingRequestNumber = 0;
        state.reviewPendingRoute = "";
        state.reviewSelectionRange = null;
        state.reviewUseDrawer = false;
      }
    }

    function positionReviewSelectionAction() {
      if (elements.reviewSelectionAction.hidden || !state.reviewSelectionRange) { return false; }
      var rect = rangeViewportRect(state.reviewSelectionRange);
      var viewport = viewportSize();
      var margin = 10;
      var gap = 8;
      var width = elements.reviewSelectionAction.offsetWidth || 126;
      var height = elements.reviewSelectionAction.offsetHeight || 34;
      var minimumTop = reviewTopBoundary(viewport);
      var coarse = Boolean(window.matchMedia && window.matchMedia("(pointer: coarse)").matches);
      state.reviewUseDrawer = coarse || viewport.width <= 640 || !rect || (!rect.width && !rect.height);
      if (!rect || (!rect.width && !rect.height)) {
        var fallbackLeft = clampNumber(viewport.left + (viewport.width - width) / 2, viewport.left + margin, viewport.right - width - margin);
        var fallbackTop = viewport.bottom - height - margin;
        elements.reviewSelectionAction.style.left = Math.round(fallbackLeft) + "px";
        elements.reviewSelectionAction.style.top = Math.round(fallbackTop) + "px";
        state.reviewActionBox = {
          left: fallbackLeft,
          top: fallbackTop,
          right: fallbackLeft + width,
          bottom: fallbackTop + height,
          width: width,
          height: height,
        };
        return true;
      }
      var left = rect.right + gap;
      if (left + width > viewport.right - margin) { left = rect.left - width - gap; }
      left = clampNumber(left, viewport.left + margin, viewport.right - width - margin);
      var top = clampNumber(
        rect.top + Math.max(0, rect.height - height) / 2,
        minimumTop,
        viewport.bottom - height - margin,
      );
      elements.reviewSelectionAction.style.left = Math.round(left) + "px";
      elements.reviewSelectionAction.style.top = Math.round(top) + "px";
      state.reviewActionBox = { left: left, top: top, right: left + width, bottom: top + height, width: width, height: height };
      return true;
    }

    function clearReviewComposePosition() {
      elements.reviewCompose.style.removeProperty("left");
      elements.reviewCompose.style.removeProperty("right");
      elements.reviewCompose.style.removeProperty("top");
      elements.reviewCompose.style.removeProperty("bottom");
      elements.reviewCompose.style.removeProperty("width");
      elements.reviewCompose.style.removeProperty("max-height");
    }

    function positionReviewComposeSheet(viewport) {
      var margin = Math.min(12, Math.max(1, Math.floor(Math.min(viewport.width, viewport.height) / 20)));
      var minimumTop = reviewTopBoundary(viewport);
      var availableHeight = Math.max(1, viewport.bottom - minimumTop - margin);
      var measuredHeight = elements.reviewCompose.offsetHeight || 360;
      var sheetHeight = Math.min(512, availableHeight, Math.max(1, measuredHeight));
      var sheetWidth = Math.min(640, Math.max(1, viewport.width - margin * 2));
      var left = viewport.left + (viewport.width - sheetWidth) / 2;
      var top = Math.max(minimumTop, viewport.bottom - margin - sheetHeight);
      elements.reviewCompose.dataset.placement = "sheet";
      elements.reviewCompose.style.left = Math.round(left) + "px";
      elements.reviewCompose.style.right = "auto";
      elements.reviewCompose.style.top = Math.round(top) + "px";
      elements.reviewCompose.style.bottom = "auto";
      elements.reviewCompose.style.width = Math.round(sheetWidth) + "px";
      elements.reviewCompose.style.maxHeight = Math.max(1, Math.round(viewport.bottom - top - margin)) + "px";
    }

    function positionReviewCompose() {
      if (elements.reviewCompose.hidden || elements.reviewCompose.parentNode === elements.reviewPanelBody) { return; }
      var viewport = viewportSize();
      var selection = rangeViewportRect(state.reviewSelectionRange);
      var margin = 12;
      var actionGap = 8;
      var composeGap = 10;
      var actionWidth = elements.reviewSelectionAction.offsetWidth || 126;
      var width = elements.reviewCompose.offsetWidth || 352;
      var height = elements.reviewCompose.offsetHeight || 360;
      var mobile = viewport.width <= 640 || (window.matchMedia && window.matchMedia("(max-width: 39.99rem)").matches);

      clearReviewComposePosition();

      if (mobile || !selection || (!selection.width && !selection.height)) {
        positionReviewComposeSheet(viewport);
        return;
      }

      var left = selection.right + actionGap + actionWidth + composeGap;
      var minimumTop = reviewTopBoundary(viewport);
      var maximumHeight = viewport.bottom - minimumTop - margin;
      if (left + width <= viewport.right - margin && maximumHeight >= 220) {
        var renderedHeight = Math.min(height, maximumHeight);
        var top = clampNumber(selection.top, minimumTop, viewport.bottom - renderedHeight - margin);
        elements.reviewCompose.dataset.placement = "right";
        elements.reviewCompose.style.left = Math.round(left) + "px";
        elements.reviewCompose.style.top = Math.round(top) + "px";
        elements.reviewCompose.style.maxHeight = Math.round(viewport.bottom - top - margin) + "px";
        return;
      }

      positionReviewComposeSheet(viewport);
    }

    function repositionReviewUi() {
      if (elements.reviewSelectionAction.hidden && elements.reviewCompose.hidden) { return; }
      if (!elements.reviewCompose.hidden && elements.reviewCompose.parentNode === elements.reviewPanelBody) { return; }
      var rect = rangeViewportRect(state.reviewSelectionRange);
      var viewport = viewportSize();
      if (rect && (rect.width || rect.height) &&
          (rect.bottom < viewport.top || rect.top > viewport.bottom || rect.right < viewport.left || rect.left > viewport.right)) {
        if (!elements.reviewCompose.hidden && reviewComposerIsDirty()) {
          elements.reviewSelectionAction.hidden = true;
          elements.reviewSelectionAction.setAttribute("aria-expanded", "false");
          state.reviewActionBox = null;
          positionReviewComposeSheet(viewport);
        } else if (!elements.reviewCompose.hidden) {
          closeReviewCompose(false, true, true);
        } else {
          hideReviewSelectionAction(true);
        }
        return;
      }
      if (!rect || (!rect.width && !rect.height)) {
        if (!elements.reviewCompose.hidden && reviewComposerIsDirty()) {
          elements.reviewSelectionAction.hidden = true;
          elements.reviewSelectionAction.setAttribute("aria-expanded", "false");
          state.reviewActionBox = null;
          positionReviewComposeSheet(viewport);
        }
        return;
      }
      if (elements.reviewSelectionAction.hidden && !elements.reviewCompose.hidden) {
        elements.reviewSelectionAction.hidden = false;
        elements.reviewSelectionAction.setAttribute("aria-expanded", "true");
      }
      positionReviewSelectionAction();
      if (!elements.reviewCompose.hidden) { positionReviewCompose(); }
    }

    function scheduleReviewPosition() {
      if (state.reviewPositionFrame) { window.cancelAnimationFrame(state.reviewPositionFrame); }
      state.reviewPositionFrame = window.requestAnimationFrame(function () {
        state.reviewPositionFrame = 0;
        repositionReviewUi();
      });
    }

    function cacheReviewSelection(bundle) {
      if (!bundle) { return false; }
      state.reviewPendingContext = bundle.context;
      try { state.reviewSelectionRange = bundle.range.cloneRange(); }
      catch (ignore) { state.reviewSelectionRange = bundle.range; }
      state.reviewPendingRoute = state.route;
      state.reviewPendingRequestNumber = state.requestNumber;
      return true;
    }

    function cacheReviewSelectionBeforeControl() {
      if (!state.reviewAvailable || reviewComposerIsDirty()) { return; }
      cacheReviewSelection(selectedReviewBundle());
    }

    function updateReviewSelectionAction() {
      state.reviewSelectionFrame = 0;
      if (!state.reviewAvailable || !elements.reviewPanel.hidden || !elements.reviewCompose.hidden) { return; }
      if (reviewComposerIsDirty() && state.reviewDraftRoute === state.route) {
        if (state.reviewSelectionRange && state.reviewPendingRoute === state.route
            && state.reviewPendingRequestNumber === state.requestNumber) {
          elements.reviewSelectionAction.hidden = false;
          positionReviewSelectionAction();
        }
        return;
      }
      var bundle = selectedReviewBundle();
      var cachedSelectionValid = state.reviewPendingContext && state.reviewSelectionRange
        && state.reviewPendingRoute === state.route
        && state.reviewPendingRequestNumber === state.requestNumber;
      if (!bundle && state.reviewKeepCachedSelection && cachedSelectionValid) {
        elements.reviewSelectionAction.hidden = false;
        positionReviewSelectionAction();
        return;
      }
      if (!bundle) { hideReviewSelectionAction(true); return; }
      state.reviewKeepCachedSelection = false;
      cacheReviewSelection(bundle);
      elements.reviewSelectionAction.hidden = false;
      positionReviewSelectionAction();
    }

    function scheduleReviewSelectionAction() {
      if (state.reviewSelectionFrame) { window.cancelAnimationFrame(state.reviewSelectionFrame); }
      state.reviewSelectionFrame = window.requestAnimationFrame(updateReviewSelectionAction);
    }

    function announceReview(message) {
      elements.reviewLiveStatus.textContent = "";
      window.requestAnimationFrame(function () { elements.reviewLiveStatus.textContent = message || ""; });
    }

    function cancelReviewFocus() {
      state.reviewFocusGeneration += 1;
      if (!state.reviewFocusTimer) { return; }
      window.clearTimeout(state.reviewFocusTimer);
      state.reviewFocusTimer = 0;
    }

    function scheduleReviewFocus(target, condition) {
      cancelReviewFocus();
      var generation = state.reviewFocusGeneration;
      state.reviewFocusTimer = window.setTimeout(function () {
        if (generation !== state.reviewFocusGeneration) { return; }
        state.reviewFocusTimer = 0;
        if (!condition || condition()) { target.focus(); }
      }, 0);
    }

    function scheduleReviewReturnFocus(target) {
      cancelReviewFocus();
      var generation = state.reviewFocusGeneration;
      window.requestAnimationFrame(function () {
        if (generation === state.reviewFocusGeneration) { target.focus({ preventScroll: true }); }
      });
    }

    function closeReviewCompose(restoreFocus, reset, hideAction) {
      var wasOpen = !elements.reviewCompose.hidden;
      cancelReviewFocus();
      elements.reviewCompose.hidden = true;
      elements.reviewSelectionAction.setAttribute("aria-expanded", "false");
      restoreReviewComposeHome();
      if (reset !== false) { resetReviewComposer(); }
      if (hideAction) { hideReviewSelectionAction(true); }
      else if (state.reviewSelectionRange && state.reviewPendingRoute === state.route) {
        state.reviewKeepCachedSelection = true;
      }
      if (wasOpen && restoreFocus !== false) {
        var preferred = state.reviewComposeReturnFocus;
        var preferredHidden = !preferred || preferred.hidden
          || (preferred.closest && preferred.closest("[hidden], [inert]"));
        var target = !preferredHidden
          ? preferred
          : !elements.reviewPanel.hidden
            ? elements.reviewClose
            : !elements.reviewSelectionAction.hidden ? elements.reviewSelectionAction : elements.article;
        scheduleReviewReturnFocus(target);
      }
      state.reviewComposeReturnFocus = null;
    }

    function openReviewCompose() {
      if (!state.reviewAvailable) { return; }
      var resumeDraft = reviewComposerIsDirty() && state.reviewDraftRoute === state.route;
      var cacheValid = state.reviewPendingContext && state.reviewPendingRoute === state.route
        && state.reviewPendingRequestNumber === state.requestNumber;
      var context = resumeDraft ? state.reviewContext : cacheValid ? state.reviewPendingContext : null;
      if (!context && !resumeDraft) {
        var bundle = selectedReviewBundle();
        if (!bundle) { hideReviewSelectionAction(true); return; }
        context = bundle.context;
        cacheReviewSelection(bundle);
        positionReviewSelectionAction();
      }
      closeSearch();
      closeSidebar();
      closeReview(false);
      positionReviewSelectionAction();
      if (!resumeDraft) {
        resetReviewComposer();
        setReviewContext(context);
        state.reviewDraftRoute = state.route;
      }
      state.reviewComposeReturnFocus = elements.reviewSelectionAction;
      if (state.reviewUseDrawer && mountReviewComposeInDrawer()) {
        state.reviewReturnFocus = elements.reviewSelectionAction;
        elements.reviewPanel.hidden = false;
        elements.reviewScrim.hidden = false;
        elements.reviewButton.setAttribute("aria-expanded", "true");
        document.body.classList.add("review-open");
        setReviewBackgroundInert(true);
      } else {
        restoreReviewComposeHome();
      }
      elements.reviewCompose.hidden = false;
      elements.reviewSelectionAction.setAttribute("aria-expanded", "true");
      if (elements.reviewCompose.parentNode !== elements.reviewPanelBody) { positionReviewCompose(); }
      scheduleReviewFocus(elements.reviewBody, function () { return !elements.reviewCompose.hidden; });
    }

    function openPageReviewCompose() {
      if (!state.reviewAvailable || elements.reviewPanel.hidden) { return; }
      var resumeDraft = reviewComposerIsDirty() && state.reviewDraftRoute === state.route;
      if (!resumeDraft) { resumeDraft = restoreReviewDraft(state.route); }
      if (!resumeDraft) {
        resetReviewComposer();
        setReviewContext(null);
        state.reviewDraftRoute = state.route;
      }
      hideReviewSelectionAction(!resumeDraft);
      mountReviewComposeInDrawer();
      elements.reviewCompose.hidden = false;
      state.reviewComposeReturnFocus = elements.reviewPageComment;
      scheduleReviewFocus(elements.reviewBody, function () {
        return !elements.reviewCompose.hidden && !elements.reviewPanel.hidden;
      });
    }

    function dismissReviewComposeWithEscape() {
      if (reviewComposerIsDirty()) {
        setReviewFormStatus("Draft kept open. Use Cancel to discard it.");
        return;
      }
      closeReviewCompose(true, true, false);
    }

    function cancelReviewCompose() {
      clearReviewDraft(state.reviewDraftRoute || state.route);
      closeReviewCompose(true, true, false);
    }

    function setReviewFormStatus(message, kind) {
      elements.reviewFormStatus.textContent = message || "";
      elements.reviewFormStatus.classList.toggle("is-error", kind === "error");
      scheduleReviewPosition();
    }

    function setReviewPanelStatus(message, kind) {
      elements.reviewPanelStatus.textContent = message || "";
      elements.reviewPanelStatus.classList.toggle("is-error", kind === "error");
    }

    function resetReviewComposer() {
      elements.reviewForm.reset();
      elements.reviewSubmit.disabled = false;
      state.reviewDraftRoute = "";
      state.reviewDraftToken = 0;
      setReviewContext(null);
      setReviewFormStatus("");
    }

    function openReview() {
      if (!state.reviewAvailable) { return; }
      closeSearch();
      closeSidebar();
      var composeWasOpen = !elements.reviewCompose.hidden;
      if (composeWasOpen) { mountReviewComposeInDrawer(); }
      hideReviewSelectionAction(false);
      setReviewPanelStatus("");
      state.reviewReturnFocus = document.activeElement && document.activeElement !== document.body
        ? document.activeElement
        : elements.reviewButton;
      elements.reviewPanel.hidden = false;
      elements.reviewScrim.hidden = false;
      elements.reviewButton.setAttribute("aria-expanded", "true");
      document.body.classList.add("review-open");
      setReviewBackgroundInert(true);
      scheduleReviewFocus(composeWasOpen ? elements.reviewBody : elements.reviewClose, function () {
        return !elements.reviewPanel.hidden && (!composeWasOpen || !elements.reviewCompose.hidden);
      });
    }

    function hideReviewFeature(focusFallback) {
      var wasOpen = !elements.reviewPanel.hidden || !elements.reviewCompose.hidden;
      snapshotReviewDraft(state.route);
      state.reviewAvailable = false;
      state.reviewComments = [];
      elements.reviewButton.hidden = true;
      closeReviewCompose(false, true, true);
      closeReview(false);
      setReviewPanelStatus("");
      renderReviewList();
      if (wasOpen && focusFallback !== false) {
        window.requestAnimationFrame(function () { elements.article.focus({ preventScroll: true }); });
      }
    }

    function cancelReviewRefresh() {
      if (state.reviewController) { state.reviewController.abort(); }
      state.reviewController = null;
      state.reviewRequestNumber += 1;
      elements.reviewRefresh.disabled = false;
    }

    function refreshReviewComments(route) {
      var target = normalizeRoute(route || state.route || "/");
      cancelReviewRefresh();
      state.reviewController = new AbortController();
      var signal = state.reviewController.signal;
      var requestNumber = ++state.reviewRequestNumber;
      elements.reviewRefresh.disabled = true;
      return requestReviewJson(reviewEndpoint() + "?route=" + encodeURIComponent(target), { signal: signal })
        .then(function (payload) {
          if (requestNumber !== state.reviewRequestNumber || target !== state.route) { return; }
          state.reviewAvailable = true;
          state.reviewComments = commentsFromReviewPayload(payload, target);
          elements.reviewButton.hidden = false;
          restoreReviewDraft(target);
          renderReviewList();
          scheduleReviewSelectionAction();
        }).catch(function (error) {
          if (error && error.name === "AbortError") { return; }
          if (requestNumber === state.reviewRequestNumber && target === state.route) { hideReviewFeature(true); }
        }).finally(function () {
          if (requestNumber === state.reviewRequestNumber) {
            state.reviewController = null;
            elements.reviewRefresh.disabled = false;
          }
        });
    }

    function saveReviewComment() {
      var body = elements.reviewBody.value.trim();
      if (!body) {
        setReviewFormStatus("Enter a comment first.", "error");
        elements.reviewBody.focus();
        return Promise.resolve();
      }
      if (body.length > 8000) {
        setReviewFormStatus("Comments can contain up to 8,000 characters.", "error");
        elements.reviewBody.focus();
        return Promise.resolve();
      }
      var targetRoute = state.route;
      var pageRequestNumber = state.requestNumber;
      var submittedDraftToken = ensureReviewDraftToken();
      var payload = { route: targetRoute, body: body };
      if (state.reviewContext && state.reviewContext.anchor) { payload.anchor = state.reviewContext.anchor; }
      if (state.reviewContext && state.reviewContext.quote) { payload.quote = state.reviewContext.quote; }
      cancelReviewRefresh();
      elements.reviewSubmit.disabled = true;
      setReviewFormStatus("Saving\u2026");
      return requestReviewJson(reviewEndpoint(), {
        method: "POST",
        headers: { Accept: "application/json", "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }).then(function (response) {
        var comment = commentFromReviewPayload(response, targetRoute);
        if (!comment) { throw new Error("Review response did not contain the saved comment."); }
        clearReviewDraft(targetRoute, submittedDraftToken);
        if (targetRoute !== state.route || pageRequestNumber !== state.requestNumber) { return; }
        if (comment && comment.route === state.route) { upsertReviewComment(comment); }
        renderReviewList();
        announceReview("Comment saved.");
        if (state.reviewDraftToken === submittedDraftToken) {
          closeReviewCompose(true, true, true);
        } else if (!elements.reviewCompose.hidden) {
          snapshotReviewDraft(targetRoute);
          setReviewFormStatus("Comment saved. Your newer draft is still open.");
        }
      }).catch(function () {
        if (targetRoute !== state.route || pageRequestNumber !== state.requestNumber) { return; }
        setReviewFormStatus("Comment could not be saved. Try again.", "error");
      }).finally(function () {
        if (targetRoute === state.route && pageRequestNumber === state.requestNumber) {
          elements.reviewSubmit.disabled = false;
        }
      });
    }

    function updateReviewComment(id, status, button) {
      if (!id || (status !== "open" && status !== "resolved")) { return Promise.resolve(); }
      var targetRoute = state.route;
      var pageRequestNumber = state.requestNumber;
      cancelReviewRefresh();
      button.disabled = true;
      setReviewPanelStatus("Updating\u2026");
      return requestReviewJson(reviewEndpoint(id), {
        method: "PATCH",
        headers: { Accept: "application/json", "Content-Type": "application/json" },
        body: JSON.stringify({ status: status }),
      }).then(function (response) {
        if (targetRoute !== state.route || pageRequestNumber !== state.requestNumber) { return; }
        var updated = commentFromReviewPayload(response);
        if (updated && updated.route === state.route) {
          upsertReviewComment(updated);
          renderReviewList();
        }
        setReviewPanelStatus(status === "resolved" ? "Comment resolved." : "Comment reopened.");
      }).catch(function () {
        if (targetRoute !== state.route || pageRequestNumber !== state.requestNumber) { return; }
        button.disabled = false;
        setReviewPanelStatus("Comment could not be updated. Try again.", "error");
      });
    }

    function trapReviewFocus(event) {
      if (event.key !== "Tab") { return; }
      var focusable = Array.from(elements.reviewPanel.querySelectorAll(
        'button:not([disabled]), textarea:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])',
      )).filter(function (item) { return !item.hidden; });
      if (!focusable.length) { event.preventDefault(); elements.reviewPanel.focus(); return; }
      var first = focusable[0];
      var last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }

    function openSidebar() {
      cancelReviewFocus();
      document.body.classList.add("nav-open");
      elements.scrim.hidden = false;
      elements.menuButton.setAttribute("aria-expanded", "true");
      elements.menuButton.setAttribute("aria-label", "Close navigation");
    }

    function closeSidebar() {
      document.body.classList.remove("nav-open");
      elements.scrim.hidden = true;
      elements.menuButton.setAttribute("aria-expanded", "false");
      elements.menuButton.setAttribute("aria-label", "Open navigation");
    }

    function applyTheme(theme, persist) {
      var value = theme === "dark" ? "dark" : "light";
      root.setAttribute("data-theme", value);
      elements.themeButton.setAttribute("aria-label", value === "dark" ? "Use light theme" : "Use dark theme");
      if (persist) {
        try { localStorage.setItem("docs-theme", value); } catch (ignore) {}
      }
    }

    function openSearch() {
      cancelReviewFocus();
      if (typeof elements.searchDialog.showModal === "function") {
        if (!elements.searchDialog.open) { elements.searchDialog.showModal(); }
      } else {
        elements.searchDialog.setAttribute("open", "");
      }
      elements.searchInput.value = "";
      renderSearchMessage("Loading search index…");
      window.setTimeout(function () { elements.searchInput.focus(); }, 0);
      loadSearch().then(function () { renderSearchResults(elements.searchInput.value); }).catch(function () {
        renderSearchMessage("Search index could not be loaded.");
      });
    }

    function closeSearch() {
      if (typeof elements.searchDialog.close === "function" && elements.searchDialog.open) {
        elements.searchDialog.close();
      } else {
        elements.searchDialog.removeAttribute("open");
      }
    }

    function loadSearch() {
      if (state.searchItems) { return Promise.resolve(state.searchItems); }
      if (state.searchPromise) { return state.searchPromise; }
      state.searchPromise = fetchJson(siteAsset("search.json")).then(function (items) {
        state.searchItems = Array.isArray(items) ? items.filter(function (item) {
          return item && typeof item === "object" && typeof item.route === "string";
        }) : [];
        return state.searchItems;
      }).catch(function (error) {
        state.searchPromise = null;
        throw error;
      });
      return state.searchPromise;
    }

    function normalizedSearch(value) {
      return String(value || "").toLocaleLowerCase().replace(/\s+/g, " ").trim();
    }

    function scoreSearchItem(item, terms, phrase) {
      var title = normalizedSearch(item.title);
      var text = normalizedSearch(item.text);
      var path = normalizedSearch(item.path);
      var space = normalizedSearch(item.space);
      var score = 0;
      if (title === phrase) { score += 160; }
      else if (title.indexOf(phrase) === 0) { score += 100; }
      else if (title.indexOf(phrase) !== -1) { score += 60; }
      if (path.indexOf(phrase) !== -1) { score += 30; }
      if (space.indexOf(phrase) !== -1) { score += 18; }
      terms.forEach(function (term) {
        if (title.indexOf(term) !== -1) { score += 25; }
        if (path.indexOf(term) !== -1) { score += 10; }
        if (text.indexOf(term) !== -1) { score += 4; }
      });
      return terms.every(function (term) {
        return title.indexOf(term) !== -1 || path.indexOf(term) !== -1 || space.indexOf(term) !== -1 || text.indexOf(term) !== -1;
      }) ? score : -1;
    }

    function searchExcerpt(item, phrase) {
      var text = String(item.text || "").replace(/\s+/g, " ").trim();
      if (!text) { return String(item.path || item.route || ""); }
      var index = normalizedSearch(text).indexOf(phrase);
      var start = Math.max(0, index < 0 ? 0 : index - 70);
      var excerpt = text.slice(start, start + 190);
      return (start ? "…" : "") + excerpt + (start + excerpt.length < text.length ? "…" : "");
    }

    function renderSearchMessage(message) {
      elements.searchResults.replaceChildren();
      var status = document.createElement("p");
      status.className = "search-message";
      status.textContent = message;
      elements.searchResults.appendChild(status);
    }

    function renderSearchResults(value) {
      var phrase = normalizedSearch(value);
      if (!state.searchItems) { return; }
      if (!phrase) {
        renderSearchMessage("Type a word or phrase to search.");
        return;
      }
      var terms = phrase.split(" ").filter(Boolean);
      var matches = state.searchItems.map(function (item) {
        return { item: item, score: scoreSearchItem(item, terms, phrase) };
      }).filter(function (match) { return match.score >= 0; })
        .sort(function (left, right) { return right.score - left.score; }).slice(0, 20);
      elements.searchResults.replaceChildren();
      if (!matches.length) {
        renderSearchMessage("No matching pages.");
        return;
      }
      matches.forEach(function (match, index) {
        var item = match.item;
        var link = createRouteLink(item.title || item.route, item.route, "search-result");
        link.setAttribute("role", "option");
        link.setAttribute("aria-selected", index === 0 ? "true" : "false");
        var title = document.createElement("strong");
        title.textContent = String(item.title || item.route);
        var locationLabel = document.createElement("span");
        locationLabel.className = "search-result-location";
        locationLabel.textContent = [item.space, item.path].filter(Boolean).join(" · ");
        var excerpt = document.createElement("span");
        excerpt.className = "search-result-excerpt";
        excerpt.textContent = searchExcerpt(item, phrase);
        link.replaceChildren(title, locationLabel, excerpt);
        elements.searchResults.appendChild(link);
      });
    }

    function moveSearchSelection(direction) {
      var links = Array.from(elements.searchResults.querySelectorAll(".search-result"));
      if (!links.length) { return; }
      var current = links.findIndex(function (link) { return link.getAttribute("aria-selected") === "true"; });
      var next = (current + direction + links.length) % links.length;
      links.forEach(function (link, index) { link.setAttribute("aria-selected", index === next ? "true" : "false"); });
      links[next].focus();
    }

    function routeLinkTarget(link) {
      var raw = link.getAttribute("href") || "";
      if (raw.charAt(0) === "#") { return { route: state.route || "/", hash: safeDecode(raw.slice(1)) }; }
      try {
        var url = new URL(raw, location.href);
        if (url.origin !== location.origin) { return null; }
        var route = stripBase(url.pathname);
        if (route === null) { return null; }
        return { route: normalizeRoute(route), hash: safeDecode(url.hash.slice(1)) };
      } catch (ignore) {
        return null;
      }
    }

    document.addEventListener("click", function (event) {
      var routeLink = event.target.closest && event.target.closest("a[data-route]");
      if (routeLink && !event.defaultPrevented && event.button === 0 &&
          !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey &&
          !routeLink.hasAttribute("download") && routeLink.target !== "_blank") {
        var target = routeLinkTarget(routeLink);
        if (target) {
          event.preventDefault();
          var fromPanel = Boolean(routeLink.closest("#review-panel"));
          var fromCompose = Boolean(routeLink.closest("#review-compose"));
          var fromReview = fromPanel || fromCompose;
          if (fromCompose) { closeReviewCompose(false, false, false); }
          if (fromPanel) { closeReview(false); }
          navigate(target.route, { hash: target.hash, focus: !target.hash, focusHash: fromReview });
          return;
        }
      }

      var copyButton = event.target.closest && event.target.closest(".copy");
      if (copyButton && elements.article.contains(copyButton)) {
        event.preventDefault();
        copyText(textForCopy(copyButton)).then(function () { showCopyResult(copyButton, true); })
          .catch(function () { showCopyResult(copyButton, false); });
        return;
      }

      var tabButton = event.target.closest && event.target.closest(".tab-btn");
      if (tabButton && elements.article.contains(tabButton)) {
        event.preventDefault();
        activateTab(tabButton, false);
      }
    });

    elements.nav.addEventListener("toggle", function (event) {
      var details = event.target;
      if (!(details instanceof HTMLDetailsElement) || !details.dataset.navKey) { return; }
      var stored = navState();
      stored[details.dataset.navKey] = details.open;
      saveNavState(stored);
    }, true);

    elements.article.addEventListener("keydown", function (event) {
      var button = event.target.closest && event.target.closest(".tab-btn");
      if (!button || (event.key !== "ArrowLeft" && event.key !== "ArrowRight" && event.key !== "Home" && event.key !== "End")) {
        return;
      }
      var buttons = Array.from(button.closest(".tabs").querySelectorAll(".tab-btn"));
      var current = buttons.indexOf(button);
      var next = event.key === "Home" ? 0 : event.key === "End" ? buttons.length - 1 :
        (current + (event.key === "ArrowRight" ? 1 : -1) + buttons.length) % buttons.length;
      event.preventDefault();
      activateTab(buttons[next], true);
    });

    elements.menuButton.addEventListener("click", function () {
      if (document.body.classList.contains("nav-open")) { closeSidebar(); }
      else { openSidebar(); }
    });
    elements.scrim.addEventListener("click", closeSidebar);
    elements.themeButton.addEventListener("click", function () {
      applyTheme(root.getAttribute("data-theme") === "dark" ? "light" : "dark", true);
    });
    elements.reviewButton.addEventListener("pointerdown", cacheReviewSelectionBeforeControl);
    elements.reviewButton.addEventListener("mousedown", cacheReviewSelectionBeforeControl);
    elements.reviewButton.addEventListener("click", openReview);
    elements.reviewClose.addEventListener("click", function () { closeReview(true); });
    elements.reviewScrim.addEventListener("click", function () { closeReview(true); });
    elements.reviewSelectionAction.addEventListener("pointerdown", function (event) { event.preventDefault(); });
    elements.reviewSelectionAction.addEventListener("mousedown", function (event) { event.preventDefault(); });
    elements.reviewSelectionAction.addEventListener("click", openReviewCompose);
    elements.reviewPageComment.addEventListener("click", openPageReviewCompose);
    elements.reviewComposeClose.addEventListener("click", function () { closeReviewCompose(true, false, false); });
    elements.reviewComposeCancel.addEventListener("click", cancelReviewCompose);
    elements.reviewClearSelection.addEventListener("click", function () {
      setReviewContext(null);
      nextReviewDraftToken();
      setReviewFormStatus("Selected text removed.");
    });
    elements.reviewRefresh.addEventListener("click", function () { refreshReviewComments(state.route); });
    elements.reviewForm.addEventListener("submit", function (event) {
      event.preventDefault();
      saveReviewComment();
    });
    elements.reviewBody.addEventListener("input", function () {
      if (!state.reviewDraftRoute) { state.reviewDraftRoute = state.route; }
      nextReviewDraftToken();
      scheduleReviewPosition();
    });
    elements.reviewList.addEventListener("click", function (event) {
      var button = event.target.closest && event.target.closest(".review-status-button");
      if (!button) { return; }
      updateReviewComment(button.dataset.reviewId, button.dataset.reviewStatus, button);
    });
    elements.reviewCompose.addEventListener("keydown", function (event) {
      if (event.key !== "Escape") { return; }
      event.preventDefault();
      event.stopPropagation();
      dismissReviewComposeWithEscape();
    });
    elements.reviewPanel.addEventListener("keydown", function (event) {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        closeReview(true);
      } else {
        trapReviewFocus(event);
      }
    });
    elements.searchButton.addEventListener("click", openSearch);
    elements.searchClose.addEventListener("click", closeSearch);
    elements.searchDialog.addEventListener("click", function (event) {
      if (event.target === elements.searchDialog) { closeSearch(); }
    });
    elements.searchDialog.addEventListener("keydown", function (event) {
      if (!event.target.closest || !event.target.closest(".search-result")) { return; }
      if (event.key === "ArrowDown") { event.preventDefault(); moveSearchSelection(1); }
      else if (event.key === "ArrowUp") { event.preventDefault(); moveSearchSelection(-1); }
    });
    elements.searchInput.addEventListener("input", function () { renderSearchResults(elements.searchInput.value); });
    elements.searchInput.addEventListener("keydown", function (event) {
      if (event.key === "ArrowDown") { event.preventDefault(); moveSearchSelection(1); }
      else if (event.key === "ArrowUp") { event.preventDefault(); moveSearchSelection(-1); }
      else if (event.key === "Enter") {
        var selected = elements.searchResults.querySelector('.search-result[aria-selected="true"]');
        if (selected) { event.preventDefault(); selected.click(); }
      }
    });

    document.addEventListener("pointerdown", function (event) {
      if (elements.reviewCompose.hidden || elements.reviewCompose.contains(event.target)
          || elements.reviewSelectionAction.contains(event.target)) { return; }
      if (!reviewComposerIsDirty()) { closeReviewCompose(false, true, true); }
    });
    document.addEventListener("selectionchange", scheduleReviewSelectionAction);
    elements.article.addEventListener("pointerdown", function () { state.reviewKeepCachedSelection = false; });
    elements.article.addEventListener("pointerup", function () {
      state.reviewKeepCachedSelection = false;
      scheduleReviewSelectionAction();
    });
    elements.article.addEventListener("keyup", function () {
      state.reviewKeepCachedSelection = false;
      scheduleReviewSelectionAction();
    });

    document.addEventListener("keydown", function (event) {
      if (!elements.reviewCompose.hidden) {
        if (event.key === "Escape") {
          event.preventDefault();
          dismissReviewComposeWithEscape();
        }
        return;
      }
      if (!elements.reviewPanel.hidden) {
        if (event.key === "Escape") {
          event.preventDefault();
          closeReview(true);
        }
        return;
      }
      var typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement && document.activeElement.tagName) ||
        (document.activeElement && document.activeElement.isContentEditable);
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        openSearch();
      } else if (event.key === "/" && !typing && !event.ctrlKey && !event.metaKey && !event.altKey) {
        event.preventDefault();
        openSearch();
      } else if (event.key === "Escape") {
        if (!elements.reviewPanel.hidden) { closeReview(true); }
        else { closeSidebar(); }
      }
    });

    window.addEventListener("scroll", scheduleScrollSave, { passive: true });
    window.addEventListener("scroll", scheduleReviewPosition, { passive: true, capture: true });
    window.addEventListener("resize", scheduleReviewPosition);
    if (window.visualViewport) {
      window.visualViewport.addEventListener("scroll", scheduleReviewPosition, { passive: true });
      window.visualViewport.addEventListener("resize", scheduleReviewPosition, { passive: true });
    }
    if (typeof window.ResizeObserver === "function") {
      reviewComposeResizeObserver = new window.ResizeObserver(scheduleReviewPosition);
      reviewComposeResizeObserver.observe(elements.reviewCompose);
    }
    window.addEventListener("pagehide", saveScrollPosition);
    window.addEventListener("popstate", function (event) {
      var stored = event.state;
      navigate(routeFromLocation(), {
        history: false,
        hash: safeDecode(location.hash.slice(1)),
        restore: stored && Number.isFinite(stored.scrollY) ? { scrollX: stored.scrollX, scrollY: stored.scrollY } : null,
      });
    });

    applyTheme(root.getAttribute("data-theme"), false);
    fetchJson(siteAsset("index.json")).then(function (index) {
      if (!index || !Array.isArray(index.spaces)) { throw new Error("index.json does not contain a spaces array."); }
      state.index = index;
      state.title = typeof index.title === "string" && index.title.trim() ? index.title.trim() : "Documentation";
      state.spaces = index.spaces.map(normalizeSpace).filter(Boolean);
      elements.brand.textContent = state.title;
      elements.brand.href = siteRoute(homeRoute());
      renderSpaces();
      var initialRoute = routeFromLocation();
      if (initialRoute === "/" && !state.spaces.some(function (space) { return space.route === "/"; })) {
        initialRoute = homeRoute();
      }
      return navigate(initialRoute, {
        replace: true,
        hash: safeDecode(location.hash.slice(1)),
        restore: history.state && Number.isFinite(history.state.scrollY)
          ? { scrollX: history.state.scrollX, scrollY: history.state.scrollY }
          : null,
      });
    }).catch(function (error) {
      showStatus("Unable to start documentation", error && error.message ? error.message : "index.json could not be read.", "error");
      setProgress(false);
    });
  }
})();
