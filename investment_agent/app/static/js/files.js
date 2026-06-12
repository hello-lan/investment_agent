(function () {
  var treeEl = document.getElementById("fileTree");
  var viewerTitle = document.getElementById("viewerTitle");
  var viewerToolbar = document.getElementById("viewerToolbar");
  var viewerBody = document.getElementById("viewerBody");
  var fileCountEl = document.getElementById("fileCount");
  var sidebar = document.getElementById("sidebar");
  var resizeHandle = document.getElementById("resizeHandle");
  var currentActive = null;
  var currentFileNode = null;
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

  function buildDownloadToolbar(node, contentData) {
    viewerToolbar.innerHTML = "";

    if (node.ext !== ".md") {
      viewerToolbar.style.display = "none";
      return;
    }
    viewerToolbar.style.display = "flex";

    // 下载按钮 + 下拉菜单
    var wrap = document.createElement("div");
    wrap.className = "download-wrap";

    var btn = document.createElement("button");
    btn.className = "download-btn";
    btn.title = "下载文件";
    btn.innerHTML = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>';

    var dropdown = document.createElement("div");
    dropdown.className = "download-dropdown";

    // Markdown 源文件
    var mdItem = document.createElement("button");
    mdItem.className = "download-item";
    mdItem.innerHTML = 'Markdown<span class="desc">下载源文件 (.md)</span>';
    mdItem.addEventListener("click", function (e) {
      e.stopPropagation();
      dropdown.classList.remove("show");
      downloadMd(node);
    });
    dropdown.appendChild(mdItem);

    // PDF 渲染版
    var pdfItem = document.createElement("button");
    pdfItem.className = "download-item";
    pdfItem.innerHTML = 'PDF<span class="desc">渲染后转换 (.pdf)</span>';
    pdfItem.addEventListener("click", function (e) {
      e.stopPropagation();
      dropdown.classList.remove("show");
      downloadPdf(node, contentData);
    });
    dropdown.appendChild(pdfItem);

    btn.addEventListener("click", function (e) {
      e.stopPropagation();
      dropdown.classList.toggle("show");
    });

    // 点击外部关闭
    document.addEventListener("click", function closeDropdown(e) {
      if (!wrap.contains(e.target)) {
        dropdown.classList.remove("show");
      }
    }, { once: true });

    wrap.appendChild(btn);
    wrap.appendChild(dropdown);
    viewerToolbar.appendChild(wrap);
  }

  function downloadMd(node) {
    // 通过静态挂载直接下载源文件
    var a = document.createElement("a");
    a.href = "/data-files/" + encodeURIComponent(node.path);
    a.download = node.name;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  }

  function downloadPdf(node, contentData) {
    // 用 html2pdf.js 将渲染后的 HTML 内容转 PDF
    var container = document.createElement("div");
    container.style.padding = "24px";
    container.style.fontFamily = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif";
    container.style.fontSize = "13px";
    container.style.lineHeight = "1.7";
    container.style.color = "#333";
    container.style.maxWidth = "800px";
    container.style.margin = "0 auto";

    if (contentData.ext === ".md") {
      container.innerHTML = marked.parse(contentData.content);
    } else {
      container.textContent = contentData.content;
    }

    var opt = {
      margin: [15, 15, 15, 15],
      filename: node.name.replace(/\.md$/i, "") + ".pdf",
      image: { type: "jpeg", quality: 0.95 },
      html2canvas: {
        scale: 2,
        logging: false,
        useCORS: true,
      },
      jsPDF: { unit: "mm", format: "a4", orientation: "portrait" },
    };

    html2pdf().set(opt).from(container).save();
  }

  function loadFile(node) {
    currentFileNode = node;
    viewerTitle.textContent = node.name;
    viewerToolbar.innerHTML = "";
    viewerToolbar.style.display = "none";
    viewerBody.innerHTML = '<div class="loading">加载中...</div>';

    fetch("/api/files/view?path=" + encodeURIComponent(node.path))
      .then(function (res) {
        if (!res.ok) throw new Error("HTTP " + res.status);
        return res.json();
      })
      .then(function (data) {
        if (data.type === "pdf") {
          viewerTitle.textContent = node.name + " (" + formatSize(data.size) + ")";
          viewerBody.innerHTML =
            '<iframe src="' + data.url + '"></iframe>';
        } else if (data.type === "text") {
          viewerTitle.textContent = node.name + " (" + formatSize(data.size) + ")";
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
          buildDownloadToolbar(node, data);
        } else {
          viewerTitle.textContent = node.name + " (" + formatSize(data.size) + ")";
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
