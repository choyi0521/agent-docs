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
    };
    var codeTextByPage = new WeakMap();

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
      var chevron = document.createElement("span");
      chevron.className = "nav-chevron";
      chevron.setAttribute("aria-hidden", "true");
      summary.appendChild(chevron);
      if (indexRoute) {
        var groupLink = createRouteLink(label, indexRoute, "nav-group-label");
        if (normalizeRoute(indexRoute) === route) {
          groupLink.classList.add("is-active");
          groupLink.setAttribute("aria-current", "page");
        }
        summary.appendChild(groupLink);
      } else {
        var groupLabel = document.createElement("span");
        groupLabel.className = "nav-group-label";
        groupLabel.textContent = label;
        summary.appendChild(groupLabel);
      }
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
      var chevron = document.createElement("span");
      chevron.className = "nav-chevron";
      chevron.setAttribute("aria-hidden", "true");
      var label = document.createElement("span");
      label.className = "nav-group-label";
      label.textContent = "Source";
      summary.append(chevron, label);
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
        var chevron = document.createElement("span");
        chevron.className = "nav-chevron";
        chevron.setAttribute("aria-hidden", "true");
        var label = document.createElement("span");
        label.className = "source-directory-label";
        label.textContent = segment + "/";
        summary.append(chevron, label);
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

    function openSidebar() {
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
          navigate(target.route, { hash: target.hash, focus: !target.hash });
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

    document.addEventListener("keydown", function (event) {
      var typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement && document.activeElement.tagName) ||
        (document.activeElement && document.activeElement.isContentEditable);
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        openSearch();
      } else if (event.key === "/" && !typing && !event.ctrlKey && !event.metaKey && !event.altKey) {
        event.preventDefault();
        openSearch();
      } else if (event.key === "Escape") {
        closeSidebar();
      }
    });

    window.addEventListener("scroll", scheduleScrollSave, { passive: true });
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
