(function () {
  var treeEl = document.getElementById("fileTree");
  var viewerHeader = document.getElementById("viewerHeader");
  var viewerBody = document.getElementById("viewerBody");
  var fileCountEl = document.getElementById("fileCount");
  var sidebar = document.getElementById("sidebar");
  var resizeHandle = document.getElementById("resizeHandle");
  var currentActive = null;
  var fileCount = 0;

  // 已加载过的目录路径集合，避免重复请求
  var loadedPaths = {};

  function formatSize(bytes) {
    if (!bytes) return "";
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
    return (bytes / (1024 * 1024)).toFixed(1) + " MB";
  }

  function iconFor(entry) {
    if (entry.type === "dir") return "\u{1F4C1}";
    var ext = entry.ext || "";
    if (ext === ".pdf") return "\u{1F4C4}";
    if (ext === ".md") return "\u{1F4DD}";
    if (ext === ".html" || ext === ".htm") return "\u{1F310}";
    if (ext === ".py") return "\u{1F40D}";
    if (ext === ".log") return "\u{1F4CB}";
    return "\u{1F4C3}";
  }

  function createRow(node, level) {
    var div = document.createElement("div");
    div.className = "tree-item";

    var row = document.createElement("div");
    row.className = "tree-row";
    row.style.paddingLeft = (12 + level * 16) + "px";

    var arrow = document.createElement("span");
    arrow.className = "arrow";

    var icon = document.createElement("span");
    icon.className = "icon";
    icon.textContent = iconFor(node);

    var name = document.createElement("span");
    name.className = "name";
    name.textContent = node.name;

    var size = document.createElement("span");
    size.className = "size";

    row.appendChild(arrow);
    row.appendChild(icon);
    row.appendChild(name);
    row.appendChild(size);

    div.appendChild(row);

    if (node.type === "dir") {
      arrow.textContent = "▶";

      var childrenEl = document.createElement("div");
      childrenEl.className = "tree-children";
      div.appendChild(childrenEl);

      // 加载指示器
      var loadingEl = document.createElement("div");
      loadingEl.className = "loading";
      loadingEl.textContent = "加载中...";
      loadingEl.style.display = "none";
      loadingEl.style.paddingLeft = (12 + (level + 1) * 16) + "px";
      childrenEl.appendChild(loadingEl);

      row.addEventListener("click", function (e) {
        e.stopPropagation();
        var isOpen = childrenEl.classList.contains("open");

        if (isOpen) {
          // 折叠
          childrenEl.classList.remove("open");
          arrow.classList.remove("open");
          loadingEl.style.display = "none";
        } else {
          // 展开
          if (loadedPaths[node.path]) {
            // 已加载过，直接展开
            childrenEl.classList.add("open");
            arrow.classList.add("open");
          } else if (node.hasChildren) {
            // 首次展开，异步加载
            arrow.classList.add("open"); // 箭头先转
            loadingEl.style.display = "block";
            loadChildren(node.path, childrenEl, loadingEl, level + 1);
          } else {
            // 空目录，也标记已处理
            loadedPaths[node.path] = true;
            childrenEl.classList.add("open");
            arrow.classList.add("open");
          }
        }
      });
    }

    if (node.type === "file") {
      size.textContent = formatSize(node.size);
      row.addEventListener("click", function (e) {
        e.stopPropagation();
        if (currentActive) currentActive.classList.remove("active");
        row.classList.add("active");
        currentActive = row;
        loadFile(node);
      });
    }

    return div;
  }

  function loadChildren(dirPath, childrenEl, loadingEl, level) {
    fetch("/api/files/children?path=" + encodeURIComponent(dirPath))
      .then(function (res) {
        if (!res.ok) throw new Error("HTTP " + res.status);
        return res.json();
      })
      .then(function (nodes) {
        loadedPaths[dirPath] = true;
        loadingEl.style.display = "none";

        // 统计文件数
        nodes.forEach(function (n) {
          if (n.type === "file") fileCount++;
          fileCountEl.textContent = fileCount + " 个文件";
        });

        // 渲染子节点
        nodes.forEach(function (node) {
          childrenEl.appendChild(createRow(node, level));
        });

        childrenEl.classList.add("open");
      })
      .catch(function (err) {
        loadingEl.style.display = "none";
        loadingEl.textContent = "加载失败: " + err.message;
        loadingEl.style.color = "#c55";
        loadingEl.style.display = "block";
      });
  }

  function loadFile(node) {
    viewerHeader.textContent = node.name;
    viewerBody.innerHTML = '<div class="loading">加载中...</div>';

    fetch("/api/files/view?path=" + encodeURIComponent(node.path))
      .then(function (res) {
        if (!res.ok) throw new Error("HTTP " + res.status);
        return res.json();
      })
      .then(function (data) {
        if (data.type === "pdf") {
          viewerHeader.textContent = node.name + " (" + formatSize(data.size) + ")";
          viewerBody.innerHTML =
            '<iframe src="' + data.url + '"></iframe>';
        } else if (data.type === "text") {
          viewerHeader.textContent = node.name + " (" + formatSize(data.size) + ")";
          var html;
          if (data.ext === ".md") {
            html = marked.parse(data.content);
          } else if (data.ext === ".html" || data.ext === ".htm") {
            html =
              '<div style="margin-bottom:12px;padding:8px 12px;background:#fff3cd;border-radius:4px;font-size:12px;color:#856404;">' +
              "HTML 源文件 — 内容已渲染（查看原始代码请使用下方 pre 区域）</div>" +
              '<div style="border:1px solid #e0e0e0;border-radius:4px;padding:16px;">' +
              data.content +
              "</div>" +
              "<details style='margin-top:16px'><summary style='cursor:pointer;font-size:13px;color:#666'>查看源码</summary><pre style='margin-top:8px'>" +
              escapeHtml(data.content) +
              "</pre></details>";
          } else {
            html = "<pre>" + escapeHtml(data.content) + "</pre>";
          }
          viewerBody.innerHTML = '<div class="content">' + html + "</div>";
        } else {
          viewerHeader.textContent = node.name + " (" + formatSize(data.size) + ")";
          viewerBody.innerHTML =
            '<iframe src="' + data.url + '"></iframe>';
        }
      })
      .catch(function (err) {
        viewerBody.innerHTML =
          '<div class="empty-state" style="color:#c55;">加载失败: ' +
          err.message +
          "</div>";
      });
  }

  function escapeHtml(str) {
    return str
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  function renderTree(nodes) {
    treeEl.innerHTML = "";
    if (!nodes.length) {
      treeEl.innerHTML = '<div class="empty-state">暂无文件</div>';
      return;
    }
    // 初始文件计数
    nodes.forEach(function (n) {
      if (n.type === "file") fileCount++;
    });
    fileCountEl.textContent = fileCount + " 个文件";
    nodes.forEach(function (node) {
      treeEl.appendChild(createRow(node, 0));
    });
  }

  // Sidebar resize
  var isResizing = false;
  resizeHandle.addEventListener("mousedown", function (e) {
    isResizing = true;
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
  });
  document.addEventListener("mousemove", function (e) {
    if (!isResizing) return;
    var w = e.clientX;
    if (w < 200) w = 200;
    if (w > 600) w = 600;
    sidebar.style.width = w + "px";
  });
  document.addEventListener("mouseup", function () {
    if (isResizing) {
      isResizing = false;
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    }
  });

  // Init — 只请求根目录
  fetch("/api/files/children")
    .then(function (res) { return res.json(); })
    .then(function (data) {
      renderTree(data);
    })
    .catch(function (err) {
      treeEl.innerHTML =
        '<div class="empty-state" style="color:#c55;">加载文件列表失败: ' +
        err.message + "</div>";
    });
})();
