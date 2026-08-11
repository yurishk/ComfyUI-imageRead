import { app, ComfyApp } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const NODE_NAME = "Reference Image Manager";
const CONFIG_VALUES = "__ail_config_widgets_values";
const STATE_PROPERTY = "advanced_image_loader_state";
const SERIAL_WIDGETS = [
  "image",
  "managed_images",
  "source_mode",
  "folder_path",
  "folder_image",
  "folder_state",
];
const LIBRARY_PAGE_SIZE = 48;
const FOLDER_PAGE_SIZE = 48;
const MAX_FOLDER_EDITS = 50;
const ROUTE_PREFIX = "/advanced-image-loader";

function ensureStyles() {
  const id = "advanced-image-loader-css";
  if (document.getElementById(id)) return;
  const link = document.createElement("link");
  link.id = id;
  link.rel = "stylesheet";
  link.href = new URL("./reference_image_manager.css", import.meta.url).href;
  document.head.append(link);
}

function makeEl(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text != null) element.textContent = text;
  if (tag === "button") element.type = "button";
  return element;
}

function parseJson(value, fallback) {
  try {
    const parsed = JSON.parse(value || "");
    return parsed ?? fallback;
  } catch {
    return fallback;
  }
}

function basename(path) {
  return String(path || "").split(/[\\/]/).filter(Boolean).pop() || "";
}

function dirname(path) {
  const value = String(path || "");
  const separator = value.includes("\\") ? "\\" : "/";
  const parts = value.split(/[\\/]/).filter(Boolean);
  parts.pop();
  if (/^[A-Za-z]:/.test(value) && parts.length === 1) return `${parts[0]}${separator}`;
  return parts.join(separator);
}

function isAbsolutePath(path) {
  return /^(?:[A-Za-z]:[\\/]|\\\\|\/)/.test(String(path || ""));
}

function makeId() {
  return `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function getWidget(node, name) {
  return node.widgets?.find((widget) => widget.name === name);
}

function hideWidget(node, name) {
  const widget = getWidget(node, name);
  if (!widget) return;
  if (!widget.options) widget.options = {};
  widget.options.serialize = true;
  widget.serialize = true;
  widget.hidden = true;
  widget.computeSize = () => [0, -4];
}

function parseAnnotatedImage(value) {
  const raw = String(value || "").trim();
  const match = raw.match(/^(.*?)(?:\s+\[(input|output|temp)\])?$/i);
  const relative = (match?.[1] || raw).replace(/\\/g, "/");
  const type = (match?.[2] || "input").toLowerCase();
  const slash = relative.lastIndexOf("/");
  return {
    image: raw,
    name: slash >= 0 ? relative.slice(slash + 1) : relative,
    subfolder: slash >= 0 ? relative.slice(0, slash) : "",
    type,
  };
}

function annotatedImageName(upload) {
  const prefix = upload.subfolder ? `${upload.subfolder}/` : "";
  const type = upload.type && upload.type !== "input" ? ` [${upload.type}]` : "";
  return `${prefix}${upload.name}${type}`;
}

function viewUrlFromRef(ref, preview = true) {
  if (!ref?.name) return "";
  const params = new URLSearchParams({
    filename: ref.name,
    type: ref.type || "input",
  });
  if (ref.subfolder) params.set("subfolder", ref.subfolder);
  const previewParam = preview ? app.getPreviewFormatParam?.() || "" : "";
  return api.apiURL(`/view?${params.toString()}${previewParam}`);
}

function viewUrlFromAnnotated(value, preview = true) {
  return viewUrlFromRef(parseAnnotatedImage(value), preview);
}

function folderPreviewUrl(path, size = 256) {
  const params = new URLSearchParams({ path: String(path || ""), size: String(size) });
  return api.apiURL(`${ROUTE_PREFIX}/folder/preview?${params.toString()}`);
}

function cleanItems(value) {
  const items = Array.isArray(value) ? value : [];
  const seen = new Set();
  const output = [];
  for (const item of items) {
    if (!item?.image) continue;
    const id = String(item.id || `${item.image}|${item.original_path || ""}`);
    if (seen.has(id)) continue;
    seen.add(id);
    const parsed = parseAnnotatedImage(item.image);
    output.push({
      ...item,
      id,
      image: String(item.image),
      name: item.name || parsed.name,
      subfolder: item.subfolder ?? parsed.subfolder,
      type: item.type || parsed.type,
      label: item.label || basename(item.original_path || item.name || item.image),
      original_path: String(item.original_path || ""),
      folder: String(item.folder || dirname(item.original_path || "")),
      starred: Boolean(item.starred),
    });
  }
  return output;
}

function cleanFolderState(value) {
  const parsed = typeof value === "string" ? parseJson(value, {}) : value || {};
  const edits = parsed.edits && typeof parsed.edits === "object" ? parsed.edits : {};
  return {
    page: Math.max(0, Number.parseInt(parsed.page, 10) || 0),
    query: String(parsed.query || ""),
    edits: { ...edits },
  };
}

function readFullProperty(properties) {
  const parsed = parseJson(properties?.[STATE_PROPERTY], {});
  return parsed && typeof parsed === "object" ? parsed : {};
}

function valuesFromNode(node, fallbackValues) {
  if (Array.isArray(fallbackValues) && fallbackValues.length) return [...fallbackValues];
  if (Array.isArray(node?.[CONFIG_VALUES]) && node[CONFIG_VALUES].length) {
    return [...node[CONFIG_VALUES]];
  }
  return SERIAL_WIDGETS.map((name) => getWidget(node, name)?.value ?? "");
}

function stateFromNode(node, fallbackValues, fallbackProperties) {
  const values = valuesFromNode(node, fallbackValues);
  const properties = fallbackProperties || node.properties || {};
  const full = readFullProperty(properties);
  const libraryItemsValue = values[1] || full.library?.items || properties.rim_items || "[]";
  const items = cleanItems(
    typeof libraryItemsValue === "string"
      ? parseJson(libraryItemsValue, [])
      : libraryItemsValue,
  );
  const image = String(values[0] || full.library?.image || "");
  const mode = values[2] === "folder" || full.mode === "folder" ? "folder" : "library";
  const folderStateValue = values[5] || full.folder?.state || "{}";

  return {
    mode,
    image,
    items,
    selectedId:
      String(full.library?.selected_id || properties.rim_selected_id || "") ||
      items.find((item) => item.image === image)?.id ||
      items[0]?.id ||
      "",
    folderPath: String(values[3] || full.folder?.path || ""),
    folderImage: String(values[4] || full.folder?.selected || ""),
    folderState: cleanFolderState(folderStateValue),
  };
}

function writeSerializableState(node, workflowNode) {
  node?.__ail_persist?.();
  const values = Array.isArray(node?.[CONFIG_VALUES])
    ? [...node[CONFIG_VALUES]]
    : SERIAL_WIDGETS.map((name) => getWidget(node, name)?.value ?? "");
  if (workflowNode) {
    workflowNode.widgets_values = values;
    workflowNode.properties = { ...(workflowNode.properties || {}), ...(node.properties || {}) };
  }
}

function setWidgetValue(node, name, value) {
  const widget = getWidget(node, name);
  if (widget) widget.value = value;
}

function buildManager(node) {
  const locale = String(
    app.ui?.settings?.getSettingValue?.("Comfy.Locale") || navigator.language || "en",
  ).toLowerCase();
  const chinese = locale.startsWith("zh");
  const tr = (zh, en) => (chinese ? zh : en);

  node.serialize_widgets = true;
  for (const name of SERIAL_WIDGETS) hideWidget(node, name);

  const imageWidget = getWidget(node, "image");
  const itemsWidget = getWidget(node, "managed_images");
  const modeWidget = getWidget(node, "source_mode");
  const folderPathWidget = getWidget(node, "folder_path");
  const folderImageWidget = getWidget(node, "folder_image");
  const folderStateWidget = getWidget(node, "folder_state");
  if (
    !imageWidget ||
    !itemsWidget ||
    !modeWidget ||
    !folderPathWidget ||
    !folderImageWidget ||
    !folderStateWidget
  ) {
    return;
  }

  for (const widget of [
    imageWidget,
    itemsWidget,
    modeWidget,
    folderPathWidget,
    folderImageWidget,
    folderStateWidget,
  ]) {
    widget.serializeValue = () => widget.value ?? "";
  }

  let state = stateFromNode(node);
  let libraryPage = 0;
  let libraryFilter = "all";
  let folderResponse = null;
  let folderLoading = false;
  let folderError = "";
  let folderRequest = 0;
  let searchTimer = null;
  let previewUrl = "";
  let thumbGeneration = 0;
  let thumbObserver = null;
  let thumbQueue = [];
  let thumbActive = 0;

  const panel = makeEl("div", "rim-panel");

  const header = makeEl("div", "rim-header");
  const heading = makeEl("div", "rim-heading");
  const title = makeEl("div", "rim-title", tr("高级加载图像", "Advanced Load Image"));
  const status = makeEl("div", "rim-status", "");
  heading.append(title, status);
  const modeSwitch = makeEl("div", "rim-mode-switch");
  const libraryModeBtn = makeEl("button", "rim-mode-btn", tr("图库管理", "Library"));
  const folderModeBtn = makeEl("button", "rim-mode-btn", tr("文件夹浏览", "Folder"));
  modeSwitch.append(libraryModeBtn, folderModeBtn);
  header.append(heading, modeSwitch);

  const preview = makeEl("div", "rim-preview");
  const previewImage = document.createElement("img");
  const emptyPreview = makeEl(
    "div",
    "rim-empty",
    tr("尚未选择图片", "No image selected"),
  );
  preview.append(emptyPreview);

  const actionBar = makeEl("div", "rim-action-bar");
  const addBtn = makeEl("button", "rim-btn rim-btn-primary", tr("添加图片", "Add Images"));
  const replaceBtn = makeEl("button", "rim-btn", tr("替换当前", "Replace"));
  const addFolderImageBtn = makeEl("button", "rim-btn rim-btn-primary", tr("加入图库", "Add to Library"));
  const editBtn = makeEl("button", "rim-btn", tr("编辑图像与掩码", "Edit Image & Mask"));
  const copyPathBtn = makeEl("button", "rim-btn", tr("复制路径", "Copy Path"));
  actionBar.append(addBtn, replaceBtn, addFolderImageBtn, editBtn, copyPathBtn);

  const libraryView = makeEl("div", "rim-view rim-library-view");
  const details = makeEl("div", "rim-details");
  const nameInput = document.createElement("input");
  nameInput.placeholder = tr("显示名称", "Display name");
  const originalPathInput = document.createElement("input");
  originalPathInput.placeholder = tr("原始路径", "Original path");
  const saveDetailsBtn = makeEl("button", "rim-btn", tr("保存信息", "Save Details"));
  details.append(nameInput, originalPathInput, saveDetailsBtn);

  const libraryTools = makeEl("div", "rim-tools");
  const librarySearch = document.createElement("input");
  librarySearch.className = "rim-search";
  librarySearch.placeholder = tr("搜索名称或路径", "Search name or path");
  const libraryFilters = makeEl("div", "rim-tabs");
  const showAllBtn = makeEl("button", "rim-tab", tr("全部", "All"));
  const showFolderBtn = makeEl("button", "rim-tab", tr("同文件夹", "Same Folder"));
  const showStarBtn = makeEl("button", "rim-tab", tr("收藏", "Favorites"));
  libraryFilters.append(showAllBtn, showFolderBtn, showStarBtn);
  libraryTools.append(librarySearch, libraryFilters);

  const libraryList = makeEl("div", "rim-list");
  const libraryFooter = makeEl("div", "rim-footer");
  const libraryPrevBtn = makeEl("button", "rim-icon-btn", "‹");
  libraryPrevBtn.title = tr("上一页", "Previous page");
  const libraryPageText = makeEl("span", "rim-page-text", "");
  const libraryNextBtn = makeEl("button", "rim-icon-btn", "›");
  libraryNextBtn.title = tr("下一页", "Next page");
  const starBtn = makeEl("button", "rim-btn", tr("收藏", "Favorite"));
  const deleteBtn = makeEl("button", "rim-btn rim-btn-danger", tr("删除", "Remove"));
  const clearBtn = makeEl("button", "rim-btn", tr("清空", "Clear"));
  libraryFooter.append(
    libraryPrevBtn,
    libraryPageText,
    libraryNextBtn,
    makeEl("span", "rim-footer-spacer"),
    starBtn,
    deleteBtn,
    clearBtn,
  );
  libraryView.append(details, libraryTools, libraryList, libraryFooter);

  const folderView = makeEl("div", "rim-view rim-folder-view");
  const pathRow = makeEl("div", "rim-path-row");
  const folderPathInput = document.createElement("input");
  folderPathInput.placeholder = tr("输入或选择图片文件夹", "Enter or choose an image folder");
  const applyPathBtn = makeEl("button", "rim-btn", tr("打开", "Open"));
  const chooseFolderBtn = makeEl("button", "rim-btn rim-btn-primary", tr("选择文件夹", "Choose Folder"));
  const refreshFolderBtn = makeEl("button", "rim-icon-btn", "↻");
  refreshFolderBtn.title = tr("刷新文件夹", "Refresh folder");
  pathRow.append(folderPathInput, applyPathBtn, chooseFolderBtn, refreshFolderBtn);

  const folderTools = makeEl("div", "rim-tools");
  const folderSearch = document.createElement("input");
  folderSearch.className = "rim-search";
  folderSearch.placeholder = tr("搜索文件名", "Search filenames");
  const folderCount = makeEl("div", "rim-count", "");
  folderTools.append(folderSearch, folderCount);

  const folderList = makeEl("div", "rim-list");
  const folderFooter = makeEl("div", "rim-footer");
  const folderPrevBtn = makeEl("button", "rim-icon-btn", "‹");
  folderPrevBtn.title = tr("上一页", "Previous page");
  const folderPageText = makeEl("span", "rim-page-text", "");
  const folderNextBtn = makeEl("button", "rim-icon-btn", "›");
  folderNextBtn.title = tr("下一页", "Next page");
  folderFooter.append(folderPrevBtn, folderPageText, folderNextBtn);
  folderView.append(pathRow, folderTools, folderList, folderFooter);

  const fileInput = makeEl("input", "rim-hidden");
  fileInput.type = "file";
  fileInput.accept = "image/*";
  fileInput.multiple = true;

  panel.append(header, preview, actionBar, libraryView, folderView, fileInput);

  function selectedLibraryItem() {
    return state.items.find((item) => item.id === state.selectedId) || null;
  }

  function selectedFolderOverride() {
    return state.folderImage ? String(state.folderState.edits[state.folderImage] || "") : "";
  }

  function currentPath() {
    if (state.mode === "folder") return state.folderImage || "";
    const item = selectedLibraryItem();
    return item?.original_path || item?.image || "";
  }

  function currentAnnotatedImage() {
    if (state.mode === "folder") return selectedFolderOverride();
    return selectedLibraryItem()?.image || "";
  }

  function currentPreviewUrl(size = 1200) {
    const annotated = currentAnnotatedImage();
    if (annotated) return viewUrlFromAnnotated(annotated);
    if (state.mode === "folder" && state.folderImage) {
      return folderPreviewUrl(state.folderImage, size);
    }
    return "";
  }

  function currentSelectionName() {
    if (state.mode === "folder") return basename(state.folderImage);
    const item = selectedLibraryItem();
    return item ? item.label || basename(item.original_path || item.image) : "";
  }

  function applySelectedWidget() {
    const value = currentAnnotatedImage();
    imageWidget.value = value;
    itemsWidget.value = JSON.stringify(state.items);
    modeWidget.value = state.mode;
    folderPathWidget.value = state.folderPath;
    folderImageWidget.value = state.folderImage;
    folderStateWidget.value = JSON.stringify(state.folderState);
  }

  function persist() {
    state.items = cleanItems(state.items);
    state.folderState = cleanFolderState(state.folderState);
    applySelectedWidget();
    const values = SERIAL_WIDGETS.map((name) => getWidget(node, name)?.value ?? "");
    node[CONFIG_VALUES] = values;
    node.properties = node.properties || {};
    node.properties[STATE_PROPERTY] = JSON.stringify({
      version: 2,
      mode: state.mode,
      library: {
        image: imageWidget.value || "",
        items: itemsWidget.value || "[]",
        selected_id: state.selectedId || "",
      },
      folder: {
        path: state.folderPath || "",
        selected: state.folderImage || "",
        state: folderStateWidget.value || "{}",
      },
    });
    // Keep these migration keys current for workflows created by older releases.
    node.properties.rim_items = itemsWidget.value;
    node.properties.rim_selected_id = state.selectedId || "";
  }

  function setNodePreview(url) {
    if (previewUrl === url && node.imgs?.length) return;
    previewUrl = url;
    if (!url) {
      node.imgs = [];
      node.images = undefined;
      return;
    }
    const image = new Image();
    image.crossOrigin = "anonymous";
    image.src = url;
    node.imgs = [image];
    node.imageIndex = 0;
    const annotated = currentAnnotatedImage();
    if (annotated) {
      const ref = parseAnnotatedImage(annotated);
      node.images = [
        { filename: ref.name, subfolder: ref.subfolder, type: ref.type },
      ];
    } else {
      node.images = undefined;
    }
  }

  function renderPreview() {
    const url = currentPreviewUrl();
    preview.replaceChildren();
    if (!url) {
      preview.append(emptyPreview);
      setNodePreview("");
      return;
    }
    previewImage.src = url;
    previewImage.alt = currentSelectionName();
    preview.append(previewImage);
    setNodePreview(url);
  }

  function filteredLibraryItems() {
    const query = librarySearch.value.trim().toLowerCase();
    const currentFolder = selectedLibraryItem()?.folder || "";
    return state.items.filter((item) => {
      if (libraryFilter === "folder" && currentFolder && item.folder !== currentFolder) return false;
      if (libraryFilter === "star" && !item.starred) return false;
      if (!query) return true;
      return `${item.label} ${item.name} ${item.original_path} ${item.folder}`
        .toLowerCase()
        .includes(query);
    });
  }

  function resetThumbnailQueue() {
    thumbGeneration += 1;
    thumbQueue = [];
    thumbActive = 0;
    thumbObserver?.disconnect();
    const generation = thumbGeneration;
    thumbObserver = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          thumbObserver.unobserve(entry.target);
          thumbQueue.push({ element: entry.target, generation });
        }
        pumpThumbnails();
      },
      { root: state.mode === "folder" ? folderList : libraryList, rootMargin: "120px" },
    );
  }

  function pumpThumbnails() {
    while (thumbActive < 3 && thumbQueue.length) {
      const job = thumbQueue.shift();
      if (job.generation !== thumbGeneration || !job.element.isConnected) continue;
      thumbActive += 1;
      const done = () => {
        thumbActive = Math.max(0, thumbActive - 1);
        pumpThumbnails();
      };
      job.element.onload = done;
      job.element.onerror = () => {
        job.element.classList.add("rim-image-error");
        done();
      };
      job.element.src = job.element.dataset.src;
    }
  }

  function observeThumbnail(image, url) {
    image.dataset.src = url;
    image.alt = "";
    thumbObserver?.observe(image);
  }

  function makeCard({ name, meta, url, active, edited, onSelect }) {
    const card = makeEl("button", `rim-card${active ? " rim-card-active" : ""}`);
    const thumb = makeEl("span", "rim-thumb");
    const image = document.createElement("img");
    observeThumbnail(image, url);
    thumb.append(image);
    const nameEl = makeEl("span", "rim-name", name);
    const metaEl = makeEl("span", "rim-meta", edited ? tr("已编辑", "Edited") : meta);
    card.append(thumb, nameEl, metaEl);
    card.onclick = onSelect;
    return card;
  }

  function renderLibrary() {
    resetThumbnailQueue();
    const selected = selectedLibraryItem();
    nameInput.value = selected?.label || "";
    originalPathInput.value = selected?.original_path || "";
    nameInput.disabled = !selected;
    originalPathInput.disabled = !selected;
    saveDetailsBtn.disabled = !selected;
    starBtn.disabled = !selected;
    deleteBtn.disabled = !selected;
    clearBtn.disabled = !state.items.length;
    starBtn.textContent = selected?.starred ? tr("取消收藏", "Unfavorite") : tr("收藏", "Favorite");

    showAllBtn.classList.toggle("rim-tab-active", libraryFilter === "all");
    showFolderBtn.classList.toggle("rim-tab-active", libraryFilter === "folder");
    showStarBtn.classList.toggle("rim-tab-active", libraryFilter === "star");

    const filtered = filteredLibraryItems();
    const pageCount = Math.max(1, Math.ceil(filtered.length / LIBRARY_PAGE_SIZE));
    libraryPage = Math.max(0, Math.min(libraryPage, pageCount - 1));
    const visible = filtered.slice(
      libraryPage * LIBRARY_PAGE_SIZE,
      (libraryPage + 1) * LIBRARY_PAGE_SIZE,
    );
    libraryList.replaceChildren();
    for (const item of visible) {
      libraryList.append(
        makeCard({
          name: item.label || basename(item.original_path || item.image),
          meta: item.starred ? tr("已收藏", "Favorite") : basename(item.folder || "input"),
          url: viewUrlFromRef(item),
          active: item.id === state.selectedId,
          edited: Boolean(item.edited_at),
          onSelect: () => {
            state.selectedId = item.id;
            render(true);
          },
        }),
      );
    }
    if (!visible.length) {
      libraryList.append(
        makeEl(
          "div",
          "rim-empty rim-list-empty",
          state.items.length
            ? tr("没有匹配的图片", "No matching images")
            : tr("图库为空", "Library is empty"),
        ),
      );
    }
    libraryPageText.textContent = `${libraryPage + 1} / ${pageCount} · ${filtered.length}`;
    libraryPrevBtn.disabled = libraryPage <= 0;
    libraryNextBtn.disabled = libraryPage >= pageCount - 1;
  }

  function renderFolder() {
    resetThumbnailQueue();
    folderPathInput.value = state.folderPath;
    if (folderSearch.value !== state.folderState.query) folderSearch.value = state.folderState.query;
    folderList.replaceChildren();

    if (folderLoading) {
      folderList.append(makeEl("div", "rim-empty rim-list-empty", tr("正在读取文件夹…", "Reading folder…")));
    } else if (folderError) {
      folderList.append(makeEl("div", "rim-empty rim-list-empty rim-error", folderError));
    } else if (!state.folderPath) {
      folderList.append(makeEl("div", "rim-empty rim-list-empty", tr("请选择图片文件夹", "Choose an image folder")));
    } else {
      const items = folderResponse?.items || [];
      for (const item of items) {
        folderList.append(
          makeCard({
            name: item.name,
            meta: tr("文件夹图片", "Folder image"),
            url: folderPreviewUrl(item.path, 256),
            active: item.path === state.folderImage,
            edited: Boolean(state.folderState.edits[item.path]),
            onSelect: () => {
              state.folderImage = item.path;
              render(true);
            },
          }),
        );
      }
      if (!items.length) {
        folderList.append(makeEl("div", "rim-empty rim-list-empty", tr("没有找到图片", "No images found")));
      }
    }

    const total = folderResponse?.total || 0;
    folderCount.textContent = folderLoading
      ? tr("读取中", "Loading")
      : folderResponse?.truncated
        ? tr(`${total}+ 张`, `${total}+ images`)
        : tr(`${total} 张`, `${total} images`);
    const page = folderResponse?.page ?? state.folderState.page;
    const pageCount = folderResponse?.page_count || 1;
    folderPageText.textContent = `${page + 1} / ${pageCount}`;
    folderPrevBtn.disabled = folderLoading || page <= 0;
    folderNextBtn.disabled = folderLoading || page >= pageCount - 1;
    refreshFolderBtn.disabled = folderLoading || !state.folderPath;
  }

  function render(shouldPersist = false) {
    if (shouldPersist) persist();
    const isLibrary = state.mode === "library";
    libraryModeBtn.classList.toggle("rim-mode-active", isLibrary);
    folderModeBtn.classList.toggle("rim-mode-active", !isLibrary);
    libraryView.classList.toggle("rim-view-active", isLibrary);
    folderView.classList.toggle("rim-view-active", !isLibrary);
    addBtn.hidden = !isLibrary;
    replaceBtn.hidden = !isLibrary;
    addFolderImageBtn.hidden = isLibrary;

    const hasSelection = isLibrary ? Boolean(selectedLibraryItem()) : Boolean(state.folderImage);
    addFolderImageBtn.disabled = !state.folderImage;
    editBtn.disabled = !hasSelection;
    copyPathBtn.disabled = !hasSelection;
    title.textContent = currentSelectionName() || tr("高级加载图像", "Advanced Load Image");
    status.textContent = isLibrary
      ? tr(`${state.items.length} 张已管理`, `${state.items.length} managed`)
      : folderLoading
        ? tr("正在读取", "Reading")
        : tr("文件夹模式", "Folder mode");

    renderPreview();
    if (isLibrary) renderLibrary();
    else renderFolder();
    requestAnimationFrame(() => {
      node.setSize([Math.max(node.size[0], 500), Math.max(node.size[1], 650)]);
      app.graph.setDirtyCanvas(true, true);
    });
  }

  async function fetchJson(path, options = {}) {
    const response = await api.fetchApi(path, options);
    let payload = {};
    try {
      payload = await response.json();
    } catch {
      // The status below still gives a useful error if the body is not JSON.
    }
    if (!response.ok) throw new Error(payload.error || `${response.status} ${response.statusText}`);
    return payload;
  }

  async function requestFolderPage(refresh = false) {
    if (!state.folderPath) {
      folderResponse = null;
      folderError = "";
      render();
      return;
    }
    const requestId = ++folderRequest;
    folderLoading = true;
    folderError = "";
    render();
    try {
      const result = await fetchJson(`${ROUTE_PREFIX}/folder/list`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          path: state.folderPath,
          page: state.folderState.page,
          page_size: FOLDER_PAGE_SIZE,
          query: state.folderState.query,
          refresh,
        }),
      });
      if (requestId !== folderRequest) return;
      folderResponse = result;
      state.folderPath = result.folder || state.folderPath;
      state.folderState.page = result.page || 0;
      folderError = "";
      persist();
    } catch (error) {
      if (requestId !== folderRequest) return;
      folderResponse = null;
      folderError = error instanceof Error ? error.message : String(error);
    } finally {
      if (requestId === folderRequest) {
        folderLoading = false;
        render();
      }
    }
  }

  async function applyFolderPath(path) {
    const normalized = String(path || "").trim();
    if (!normalized) return;
    if (normalized !== state.folderPath) {
      state.folderPath = normalized;
      state.folderImage = "";
      state.folderState.page = 0;
      folderResponse = null;
    }
    persist();
    await requestFolderPage(false);
  }

  async function uploadFiles(files, replaceCurrent = false) {
    const selectedBefore = selectedLibraryItem();
    const uploads = [];
    for (const file of files) {
      const body = new FormData();
      body.append("image", file);
      body.append("type", "input");
      const response = await api.fetchApi("/upload/image", { method: "POST", body });
      if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
      const upload = await response.json();
      const originalPath = file.path || file.webkitRelativePath || file.name;
      uploads.push({
        id: makeId(),
        image: annotatedImageName(upload),
        name: upload.name,
        label: basename(originalPath || upload.name),
        subfolder: upload.subfolder || "",
        type: upload.type || "input",
        original_path: originalPath,
        folder: dirname(originalPath),
        starred: false,
        added_at: Date.now(),
      });
    }
    if (!uploads.length) return;

    if (replaceCurrent && selectedBefore) {
      const index = state.items.findIndex((item) => item.id === selectedBefore.id);
      state.items.splice(index, 1, uploads[0]);
      if (uploads.length > 1) state.items.splice(index + 1, 0, ...uploads.slice(1));
    } else {
      state.items.push(...uploads);
    }
    state.selectedId = uploads[0].id;
    libraryPage = Math.floor(
      Math.max(0, filteredLibraryItems().findIndex((item) => item.id === state.selectedId)) /
        LIBRARY_PAGE_SIZE,
    );
    render(true);
  }

  async function addSelectedFolderImageToLibrary() {
    if (!state.folderImage) return;
    addFolderImageBtn.disabled = true;
    const oldText = addFolderImageBtn.textContent;
    addFolderImageBtn.textContent = tr("正在添加…", "Adding…");
    try {
      const imported = await fetchJson(`${ROUTE_PREFIX}/folder/import`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: state.folderImage }),
      });
      const image = annotatedImageName(imported);
      let item = state.items.find(
        (entry) => String(entry.original_path).toLowerCase() === state.folderImage.toLowerCase(),
      );
      if (item) {
        const parsed = parseAnnotatedImage(image);
        item.image = image;
        item.name = parsed.name;
        item.subfolder = parsed.subfolder;
        item.type = parsed.type;
      } else {
        item = {
          id: makeId(),
          image,
          name: imported.name,
          label: basename(state.folderImage),
          subfolder: imported.subfolder || "",
          type: imported.type || "input",
          original_path: state.folderImage,
          folder: dirname(state.folderImage),
          starred: false,
          added_at: Date.now(),
        };
        state.items.push(item);
      }
      status.textContent = tr("已加入图库", "Added to Library");
      persist();
    } catch (error) {
      status.textContent = error instanceof Error ? error.message : String(error);
      console.error("[Advanced Image Loader] Add to Library failed", error);
    } finally {
      addFolderImageBtn.textContent = oldText;
      addFolderImageBtn.disabled = !state.folderImage;
    }
  }

  function rememberFolderEdit(sourcePath, annotatedImage) {
    const edits = { ...state.folderState.edits };
    delete edits[sourcePath];
    edits[sourcePath] = annotatedImage;
    while (Object.keys(edits).length > MAX_FOLDER_EDITS) {
      delete edits[Object.keys(edits)[0]];
    }
    state.folderState.edits = edits;
  }

  async function loadPreviewImage(url) {
    return new Promise((resolve, reject) => {
      const image = new Image();
      image.crossOrigin = "anonymous";
      image.onload = () => resolve(image);
      image.onerror = () => reject(new Error(tr("无法读取编辑图片", "Unable to load image for editing")));
      image.src = url;
    });
  }

  function waitForMaskEditorClose(context) {
    const startedAt = Date.now();
    let appeared = false;
    const timer = window.setInterval(() => {
      const open = Boolean(document.querySelector('[data-testid="mask-editor-root"], .mask-editor-dialog'));
      if (open) appeared = true;
      if ((appeared && !open) || (!appeared && Date.now() - startedAt > 15_000)) {
        window.clearInterval(timer);
        const result = String(imageWidget.value || "");
        if (appeared && result && result !== context.editorInput) {
          if (context.mode === "library") {
            const item = state.items.find((entry) => entry.id === context.selectedId);
            if (item) {
              const parsed = parseAnnotatedImage(result);
              item.image = result;
              item.name = parsed.name;
              item.subfolder = parsed.subfolder;
              item.type = parsed.type;
              item.edited_at = Date.now();
            }
          } else if (context.folderImage) {
            rememberFolderEdit(context.folderImage, result);
          }
        }
        applySelectedWidget();
        previewUrl = "";
        render(true);
      }
    }, 250);
  }

  async function openMaskEditor() {
    const context = {
      mode: state.mode,
      selectedId: state.selectedId,
      folderImage: state.folderImage,
      editorInput: currentAnnotatedImage(),
    };
    if (context.mode === "folder" && !context.folderImage) return;
    if (context.mode === "library" && !context.editorInput) return;

    editBtn.disabled = true;
    const oldText = editBtn.textContent;
    editBtn.textContent = tr("正在打开…", "Opening…");
    try {
      if (context.mode === "folder" && !context.editorInput) {
        const imported = await fetchJson(`${ROUTE_PREFIX}/folder/import`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ path: context.folderImage }),
        });
        context.editorInput = imported.image;
      }
      imageWidget.value = context.editorInput;
      const ref = parseAnnotatedImage(context.editorInput);
      const image = await loadPreviewImage(viewUrlFromRef(ref, false));
      node.imgs = [image];
      node.images = [
        { filename: ref.name, subfolder: ref.subfolder, type: ref.type },
      ];
      node.imageIndex = 0;

      if (typeof ComfyApp.open_maskeditor !== "function") {
        throw new Error(tr("当前 ComfyUI 未提供蒙版编辑器", "Mask Editor is unavailable"));
      }
      ComfyApp.copyToClipspace?.(node);
      ComfyApp.clipspace_return_node = node;
      ComfyApp.open_maskeditor();
      waitForMaskEditorClose(context);
    } catch (error) {
      applySelectedWidget();
      status.textContent = error instanceof Error ? error.message : String(error);
      console.error("[Advanced Image Loader] Failed to open Mask Editor", error);
    } finally {
      editBtn.textContent = oldText;
      editBtn.disabled = false;
    }
  }

  libraryModeBtn.onclick = () => {
    if (state.mode === "library") return;
    state.mode = "library";
    previewUrl = "";
    render(true);
  };
  folderModeBtn.onclick = () => {
    if (state.mode === "folder") return;
    state.mode = "folder";
    previewUrl = "";
    render(true);
    if (state.folderPath && !folderResponse) requestFolderPage(false);
  };
  addBtn.onclick = () => {
    fileInput.multiple = true;
    fileInput.dataset.mode = "add";
    fileInput.click();
  };
  replaceBtn.onclick = () => {
    fileInput.multiple = false;
    fileInput.dataset.mode = "replace";
    fileInput.click();
  };
  fileInput.onchange = async () => {
    try {
      await uploadFiles([...fileInput.files], fileInput.dataset.mode === "replace");
    } catch (error) {
      status.textContent = tr("添加失败", "Upload failed");
      console.error("[Advanced Image Loader] Upload failed", error);
    } finally {
      fileInput.value = "";
    }
  };
  addFolderImageBtn.onclick = addSelectedFolderImageToLibrary;
  editBtn.onclick = openMaskEditor;
  copyPathBtn.onclick = async () => {
    const path = currentPath();
    if (!path) return;
    try {
      await navigator.clipboard.writeText(path);
      status.textContent = tr("路径已复制", "Path copied");
    } catch {
      status.textContent = path;
    }
  };
  saveDetailsBtn.onclick = () => {
    const item = selectedLibraryItem();
    if (!item) return;
    item.label = nameInput.value.trim() || basename(item.original_path || item.image);
    item.original_path = originalPathInput.value.trim();
    item.folder = dirname(item.original_path);
    render(true);
  };
  showAllBtn.onclick = () => {
    libraryFilter = "all";
    libraryPage = 0;
    renderLibrary();
  };
  showFolderBtn.onclick = () => {
    libraryFilter = "folder";
    libraryPage = 0;
    renderLibrary();
  };
  showStarBtn.onclick = () => {
    libraryFilter = "star";
    libraryPage = 0;
    renderLibrary();
  };
  librarySearch.oninput = () => {
    libraryPage = 0;
    renderLibrary();
  };
  libraryPrevBtn.onclick = () => {
    libraryPage = Math.max(0, libraryPage - 1);
    renderLibrary();
  };
  libraryNextBtn.onclick = () => {
    libraryPage += 1;
    renderLibrary();
  };
  starBtn.onclick = () => {
    const item = selectedLibraryItem();
    if (!item) return;
    item.starred = !item.starred;
    render(true);
  };
  deleteBtn.onclick = () => {
    const item = selectedLibraryItem();
    if (!item) return;
    state.items = state.items.filter((entry) => entry.id !== item.id);
    state.selectedId = state.items[0]?.id || "";
    previewUrl = "";
    render(true);
  };
  clearBtn.onclick = () => {
    if (
      state.items.length &&
      !window.confirm(
        tr("确定清空图库吗？input 中的缓存文件不会删除。", "Clear the library? Cached input files will not be deleted."),
      )
    ) {
      return;
    }
    state.items = [];
    state.selectedId = "";
    libraryPage = 0;
    previewUrl = "";
    render(true);
  };
  applyPathBtn.onclick = () => applyFolderPath(folderPathInput.value);
  folderPathInput.onkeydown = (event) => {
    if (event.key === "Enter") applyFolderPath(folderPathInput.value);
  };
  chooseFolderBtn.onclick = async () => {
    chooseFolderBtn.disabled = true;
    try {
      const result = await fetchJson(`${ROUTE_PREFIX}/folder/pick`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ initial_path: state.folderPath }),
      });
      if (result.path) await applyFolderPath(result.path);
    } catch (error) {
      folderError = error instanceof Error ? error.message : String(error);
      renderFolder();
    } finally {
      chooseFolderBtn.disabled = false;
    }
  };
  refreshFolderBtn.onclick = () => requestFolderPage(true);
  folderSearch.oninput = () => {
    window.clearTimeout(searchTimer);
    state.folderState.query = folderSearch.value;
    state.folderState.page = 0;
    searchTimer = window.setTimeout(() => {
      persist();
      requestFolderPage(false);
    }, 350);
  };
  folderPrevBtn.onclick = () => {
    state.folderState.page = Math.max(0, (folderResponse?.page || 0) - 1);
    persist();
    requestFolderPage(false);
  };
  folderNextBtn.onclick = () => {
    state.folderState.page = (folderResponse?.page || 0) + 1;
    persist();
    requestFolderPage(false);
  };

  node.__ail_persist = persist;
  node.__ail_open_editor = openMaskEditor;
  node.__ail_editor_label = tr("编辑图像与掩码", "Edit Image & Mask");
  node.__ail_reload = (values, properties) => {
    state = stateFromNode(node, values, properties);
    libraryPage = 0;
    folderResponse = null;
    folderError = "";
    folderPathInput.value = state.folderPath;
    folderSearch.value = state.folderState.query;
    librarySearch.value = "";
    previewUrl = "";
    persist();
    render();
    if (state.mode === "folder" && state.folderPath) requestFolderPage(false);
  };

  const domWidget = node.addDOMWidget("advanced_image_loader", "advanced-image-loader", panel, {
    getValue() {
      return node.properties?.[STATE_PROPERTY] || "";
    },
    setValue() {},
    serialize: false,
    getMinHeight() {
      return 560;
    },
    getMaxHeight() {
      return 960;
    },
  });
  domWidget.serialize = false;

  persist();
  render();
}

app.registerExtension({
  name: "Comfy.AdvancedImageLoader",
  init() {
    ensureStyles();
  },
  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData.name !== NODE_NAME) return;

    const onNodeCreated = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      const result = onNodeCreated?.apply(this, arguments);
      buildManager(this);
      return result;
    };

    const configure = nodeType.prototype.configure;
    nodeType.prototype.configure = function (info) {
      this[CONFIG_VALUES] = Array.isArray(info?.widgets_values) ? [...info.widgets_values] : [];
      this.__ail_config_properties = info?.properties ? { ...info.properties } : {};
      return configure?.apply(this, arguments);
    };

    const onConfigure = nodeType.prototype.onConfigure;
    nodeType.prototype.onConfigure = function () {
      const result = onConfigure?.apply(this, arguments);
      const values = [...(this[CONFIG_VALUES] || [])];
      const properties = { ...(this.__ail_config_properties || this.properties || {}) };
      // Workflow loading can serialize again before the next animation frame.
      // Restore immediately so that empty construction defaults never win.
      this.__ail_reload?.(values, properties);
      return result;
    };

    const onSerialize = nodeType.prototype.onSerialize;
    nodeType.prototype.onSerialize = function (workflowNode) {
      this.__ail_persist?.();
      const result = onSerialize?.apply(this, arguments);
      writeSerializableState(this, workflowNode);
      return result;
    };

    const clone = nodeType.prototype.clone;
    nodeType.prototype.clone = function () {
      this.__ail_persist?.();
      const values = [...(this[CONFIG_VALUES] || [])];
      const properties = { ...(this.properties || {}) };
      const cloned = clone?.apply(this, arguments);
      if (cloned) {
        cloned[CONFIG_VALUES] = [...values];
        cloned.properties = { ...(cloned.properties || {}), ...properties };
        for (let index = 0; index < SERIAL_WIDGETS.length; index += 1) {
          setWidgetValue(cloned, SERIAL_WIDGETS[index], values[index] ?? "");
        }
        // Current LiteGraph copies a node by cloning it and immediately
        // serializing that clone. Restore the manager state synchronously so
        // the clone's initial empty UI cannot overwrite the copied values.
        cloned.__ail_reload?.(values, properties);
      }
      return cloned;
    };

    const getExtraMenuOptions = nodeType.prototype.getExtraMenuOptions;
    nodeType.prototype.getExtraMenuOptions = function (_, options) {
      const result = getExtraMenuOptions?.apply(this, arguments);
      options.unshift({
        content: this.__ail_editor_label || "Edit Image & Mask",
        callback: () => this.__ail_open_editor?.(),
      });
      return result;
    };

    const onDrawBackground = nodeType.prototype.onDrawBackground;
    nodeType.prototype.onDrawBackground = function () {
      const images = this.imgs;
      this.imgs = null;
      const result = onDrawBackground?.apply(this, arguments);
      this.imgs = images;
      return result;
    };
  },
});
