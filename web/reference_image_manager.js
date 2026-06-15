import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const NODE_NAME = "Reference Image Manager";
const MAX_ITEMS = 120;
const CONFIG_VALUES = "__rim_config_widgets_values";

function isItemsJson(value) {
  return typeof value === "string" && value.trim().startsWith("[");
}

function ensureStyles() {
  const id = "reference-image-manager-css";
  if (document.getElementById(id)) return;
  const link = document.createElement("link");
  link.id = id;
  link.rel = "stylesheet";
  link.href = "extensions/ComfyUI-ReferenceImageManager/reference_image_manager.css";
  document.head.append(link);
}

function makeEl(tag, className, text) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (text != null) el.textContent = text;
  return el;
}

function basename(path) {
  return (path || "").split(/[\\/]/).filter(Boolean).pop() || "";
}

function dirname(path) {
  const slash = (path || "").includes("\\") ? "\\" : "/";
  const parts = (path || "").split(/[\\/]/).filter(Boolean);
  parts.pop();
  return parts.join(slash);
}

function parseItems(value) {
  try {
    const items = JSON.parse(value || "[]");
    return Array.isArray(items) ? items : [];
  } catch {
    return [];
  }
}

function cleanItems(items) {
  const seen = new Set();
  return items
    .filter((item) => item?.image)
    .filter((item) => {
      const key = item.id || `${item.image}|${item.original_path || ""}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    })
    .slice(0, MAX_ITEMS);
}

function annotatedImageName(upload) {
  const prefix = upload.subfolder ? `${upload.subfolder}/` : "";
  const type = upload.type && upload.type !== "input" ? ` [${upload.type}]` : "";
  return `${prefix}${upload.name}${type}`;
}

function viewUrl(item) {
  if (!item?.image) return "";
  const filename = item.subfolder ? `${item.subfolder}/${item.name}` : item.name || item.image;
  const params = new URLSearchParams({
    filename,
    type: item.type || "input",
  });
  return api.apiURL(`/view?${params.toString()}${app.getPreviewFormatParam?.() || ""}`);
}

function getWidget(node, name) {
  return node.widgets?.find((w) => w.name === name);
}

function getWidgetValue(node, name) {
  return getWidget(node, name)?.value || "";
}

function readConfiguredItems(node, fallbackValues) {
  const values = fallbackValues || node?.[CONFIG_VALUES] || node?.widgets_values || [];
  return values.find(isItemsJson) || "";
}

function readManagedJson(node, fallbackValues) {
  const configuredItems = readConfiguredItems(node, fallbackValues);
  if (node?.__rim_config_dirty) {
    return configuredItems || getWidgetValue(node, "managed_images") || node?.properties?.rim_items || node?.__rim_state_json || "[]";
  }

  return (
    node?.__rim_state_json ||
    getWidgetValue(node, "managed_images") ||
    configuredItems ||
    node?.properties?.rim_items ||
    "[]"
  );
}

function readSelectedImage(node, fallbackValues) {
  const values = fallbackValues || node?.[CONFIG_VALUES] || node?.widgets_values || [];
  if (node?.__rim_config_dirty) {
    return values[0] || getWidgetValue(node, "image") || "";
  }
  return getWidgetValue(node, "image") || values[0] || "";
}

function writeSerializableState(node, workflowNode) {
  const existingValues = workflowNode?.widgets_values || node?.[CONFIG_VALUES] || node?.widgets_values || [];
  if (!node?.__rim_config_dirty) {
    node?.__rim_persist?.();
  }

  const image = readSelectedImage(node, existingValues);
  const json = readManagedJson(node, existingValues);
  const selectedId = node?.properties?.rim_selected_id || "";

  if (workflowNode) {
    workflowNode.widgets_values = [image, json];
    if (!workflowNode.properties) workflowNode.properties = {};
    workflowNode.properties.rim_items = json;
    workflowNode.properties.rim_selected_id = selectedId;
  }

  if (node) {
    node.__rim_state_json = json;
    node[CONFIG_VALUES] = [image, json];
    if (!node.properties) node.properties = {};
    node.properties.rim_items = json;
    node.properties.rim_selected_id = selectedId;
  }
}

function setNodeProperty(node, name, value) {
  if (!node.properties) node.properties = {};
  if (typeof node.setProperty === "function") {
    node.setProperty(name, value);
  } else {
    node.properties[name] = value;
  }
}

function setWidgetValue(node, name, value) {
  const widget = getWidget(node, name);
  if (!widget) return;
  widget.value = value;
  widget.callback?.(value);
}

function hideWidget(node, name) {
  const widget = getWidget(node, name);
  if (!widget) return;
  if (!widget.options) widget.options = {};
  widget.options.serialize = true;
  widget.hidden = true;
  widget.computeSize = () => [0, -4];
  widget.serialize = true;
}

function removeWidgetByName(node, name) {
  const widget = getWidget(node, name);
  if (!widget) return;
  widget.onRemove?.();
  const index = node.widgets?.indexOf(widget) ?? -1;
  if (index >= 0) node.widgets.splice(index, 1);
}

function buildManager(node) {
  node.serialize_widgets = true;
  removeWidgetByName(node, "upload");
  hideWidget(node, "image");
  hideWidget(node, "managed_images");
  node.imgs = [];

  const imageWidget = getWidget(node, "image");
  const itemsWidget = getWidget(node, "managed_images");
  if (!imageWidget || !itemsWidget) return;

  const panel = makeEl("div", "rim-panel");
  const fileInput = makeEl("input", "rim-hidden");
  fileInput.type = "file";
  fileInput.accept = "image/*";
  fileInput.multiple = true;

  const toolbar = makeEl("div", "rim-toolbar");
  const title = makeEl("div", "rim-title", "参考图管理");
  const addBtn = makeEl("button", "rim-btn rim-btn-primary", "添加图片");
  const replaceBtn = makeEl("button", "rim-btn", "替换当前");
  toolbar.append(title, addBtn, replaceBtn);

  const preview = makeEl("div", "rim-preview");
  const previewImg = document.createElement("img");
  const emptyPreview = makeEl("div", "rim-empty", "先添加图片，然后点击缩略图切换输出。");
  preview.append(emptyPreview);

  const editor = makeEl("div", "rim-editor");
  const nameInput = document.createElement("input");
  nameInput.placeholder = "显示名称";
  const pathInput = document.createElement("input");
  pathInput.placeholder = "原始路径";
  const folderInput = document.createElement("input");
  folderInput.placeholder = "文件夹";
  editor.append(nameInput, pathInput, folderInput);

  const controls = makeEl("div", "rim-toolbar");
  const search = document.createElement("input");
  search.className = "rim-search";
  search.placeholder = "搜索名称 / 路径 / 文件夹";
  const showAllBtn = makeEl("button", "rim-tab rim-tab-active", "全部");
  const showFolderBtn = makeEl("button", "rim-tab", "同文件夹");
  const showStarBtn = makeEl("button", "rim-tab", "收藏");
  controls.append(showAllBtn, showFolderBtn, showStarBtn);

  const actions = makeEl("div", "rim-toolbar");
  const saveMetaBtn = makeEl("button", "rim-btn", "保存信息");
  const starBtn = makeEl("button", "rim-btn", "收藏");
  const deleteBtn = makeEl("button", "rim-btn rim-btn-danger", "删除");
  const clearBtn = makeEl("button", "rim-btn", "清空列表");
  actions.append(saveMetaBtn, starBtn, deleteBtn, clearBtn);

  const list = makeEl("div", "rim-list");
  panel.append(toolbar, preview, editor, controls, search, actions, list, fileInput);

  const configuredValues = node[CONFIG_VALUES] || node.widgets_values || [];
  const configuredImage = configuredValues[0] || imageWidget.value || "";
  const configuredItems = readConfiguredItems(node, configuredValues);
  const storedItems = configuredItems || itemsWidget.value || node.properties?.rim_items || "[]";
  let items = cleanItems(parseItems(storedItems));
  let selectedId =
    node.properties?.rim_selected_id ||
    items.find((item) => item.image === configuredImage)?.id ||
    items[0]?.id ||
    "";

  if (configuredImage) imageWidget.value = configuredImage;
  itemsWidget.value = JSON.stringify(items);
  node.__rim_state_json = itemsWidget.value;
  imageWidget.serializeValue = () => imageWidget.value || "";
  itemsWidget.serializeValue = () => node.__rim_state_json || itemsWidget.value || "[]";
  let filterMode = "all";
  let uploadMode = "add";

  function selectedItem() {
    return items.find((item) => item.id === selectedId) || null;
  }

  function persist() {
    items = cleanItems(items);
    const json = JSON.stringify(items);
    node.__rim_state_json = json;
    node[CONFIG_VALUES] = [imageWidget.value || "", json];
    setWidgetValue(node, "managed_images", json);
    setNodeProperty(node, "rim_items", json);
    setNodeProperty(node, "rim_selected_id", selectedId || "");
  }

  function loadStateFromWidgets() {
    const json = getWidgetValue(node, "managed_images") || node.__rim_state_json || node.properties?.rim_items || "[]";
    items = cleanItems(parseItems(json));
    node.__rim_state_json = JSON.stringify(items);
    node[CONFIG_VALUES] = [imageWidget.value || "", node.__rim_state_json];
    node.__rim_config_dirty = false;
    selectedId =
      node.properties?.rim_selected_id ||
      items.find((item) => item.image === imageWidget.value)?.id ||
      items[0]?.id ||
      "";
    if (selectedId) {
      const item = items.find((entry) => entry.id === selectedId);
      if (item) imageWidget.value = item.image;
    }
  }

  function selectItem(item) {
    if (!item) return;
    selectedId = item.id;
    setWidgetValue(node, "image", item.image);
    node.imgs = [];
    render();
  }

  function updateButtons() {
    showAllBtn.classList.toggle("rim-tab-active", filterMode === "all");
    showFolderBtn.classList.toggle("rim-tab-active", filterMode === "folder");
    showStarBtn.classList.toggle("rim-tab-active", filterMode === "star");
  }

  function renderEditor(item) {
    nameInput.value = item?.label || "";
    pathInput.value = item?.original_path || "";
    folderInput.value = item?.folder || "";
    title.textContent = item ? basename(item.label || item.original_path || item.image) : "参考图管理";
  }

  function renderPreview(item) {
    preview.replaceChildren();
    if (!item) {
      preview.append(emptyPreview);
      return;
    }
    previewImg.src = viewUrl(item);
    preview.append(previewImg);
  }

  function filteredItems() {
    const q = search.value.trim().toLowerCase();
    const currentFolder = selectedItem()?.folder || "";
    return items.filter((item) => {
      if (filterMode === "folder" && currentFolder && item.folder !== currentFolder) return false;
      if (filterMode === "star" && !item.starred) return false;
      if (!q) return true;
      return `${item.label} ${item.name} ${item.original_path} ${item.folder}`.toLowerCase().includes(q);
    });
  }

  function renderList() {
    const active = selectedItem();
    list.replaceChildren();

    const visibleItems = filteredItems();
    for (const item of visibleItems) {
      const card = makeEl("div", `rim-card${item.id === selectedId ? " rim-card-active" : ""}`);
      const thumb = makeEl("div", "rim-thumb");
      const img = document.createElement("img");
      img.loading = "lazy";
      img.src = viewUrl(item);
      thumb.append(img);

      const name = makeEl("div", "rim-name", item.label || basename(item.original_path || item.name || item.image));
      const meta = makeEl("div", "rim-meta", item.folder || item.type || "input");
      const badge = makeEl("div", "rim-meta", item.starred ? "已收藏" : "点击选择");
      card.append(thumb, name, meta, badge);
      card.onclick = () => selectItem(item);
      list.append(card);
    }

    if (!visibleItems.length) {
      list.append(makeEl("div", "rim-empty", items.length ? "当前筛选没有图片。" : "列表为空。点击“添加图片”创建你的参考图库。"));
    }

    renderPreview(active);
    renderEditor(active);
    starBtn.textContent = active?.starred ? "取消收藏" : "收藏";
    updateButtons();
  }

  function render() {
    persist();
    renderList();
    requestAnimationFrame(() => {
      node.setSize([Math.max(node.size[0], 460), Math.max(node.size[1], 560)]);
      app.graph.setDirtyCanvas(true, true);
    });
  }

  async function uploadFiles(files) {
    const selectedBefore = selectedItem();
    const uploads = [];
    for (const file of files) {
      const body = new FormData();
      body.append("image", file);
      body.append("type", "input");
      const response = await api.fetchApi("/upload/image", { method: "POST", body });
      if (!response.ok) throw new Error(`Upload failed: ${response.status}`);
      const upload = await response.json();
      const originalPath = file.path || file.webkitRelativePath || file.name;
      uploads.push({
        id: `${Date.now()}-${Math.random().toString(36).slice(2)}`,
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
    if (uploadMode === "replace" && selectedBefore) {
      const index = items.findIndex((item) => item.id === selectedBefore.id);
      items.splice(index, 1, uploads[0]);
      selectedId = uploads[0].id;
      if (uploads.length > 1) items.splice(index + 1, 0, ...uploads.slice(1));
    } else {
      items.push(...uploads);
      selectedId = uploads[0].id;
    }
    selectItem(items.find((item) => item.id === selectedId));
  }

  addBtn.onclick = () => {
    uploadMode = "add";
    fileInput.multiple = true;
    fileInput.click();
  };
  replaceBtn.onclick = () => {
    uploadMode = "replace";
    fileInput.multiple = false;
    fileInput.click();
  };
  fileInput.onchange = async () => {
    try {
      await uploadFiles([...fileInput.files]);
    } finally {
      fileInput.value = "";
    }
  };
  showAllBtn.onclick = () => {
    filterMode = "all";
    renderList();
  };
  showFolderBtn.onclick = () => {
    filterMode = "folder";
    renderList();
  };
  showStarBtn.onclick = () => {
    filterMode = "star";
    renderList();
  };
  search.oninput = renderList;
  saveMetaBtn.onclick = () => {
    const item = selectedItem();
    if (!item) return;
    item.label = nameInput.value.trim();
    item.original_path = pathInput.value.trim();
    item.folder = folderInput.value.trim() || dirname(item.original_path);
    render();
  };
  starBtn.onclick = () => {
    const item = selectedItem();
    if (!item) return;
    item.starred = !item.starred;
    render();
  };
  deleteBtn.onclick = () => {
    const item = selectedItem();
    if (!item) return;
    items = items.filter((entry) => entry.id !== item.id);
    selectedId = items[0]?.id || "";
    if (selectedId) selectItem(items[0]);
    else {
      setWidgetValue(node, "image", "");
      node.imgs = [];
      render();
    }
  };
  clearBtn.onclick = () => {
    items = [];
    selectedId = "";
    setWidgetValue(node, "image", "");
    node.imgs = [];
    render();
  };

  const imageCallback = imageWidget.callback;
  imageWidget.callback = function () {
    imageCallback?.apply(this, arguments);
    node.imgs = [];
  };

  node.__rim_persist = persist;

  const widget = node.addDOMWidget("manager", "reference-image-manager", panel, {
    getValue() {
      return itemsWidget.value;
    },
    setValue(value) {
      const stored = node.properties?.rim_items || value;
      items = cleanItems(parseItems(stored));
      selectedId =
        node.properties?.rim_selected_id ||
        items.find((item) => item.image === imageWidget.value)?.id ||
        items[0]?.id ||
        "";
      renderList();
    },
    serialize: false,
    getMinHeight() {
      return 470;
    },
    getMaxHeight() {
      return 900;
    },
  });
  widget.serialize = false;

  const serialize = node.onSerialize;
  node.onSerialize = function (workflowNode) {
    if (node.__rim_config_dirty) {
      loadStateFromWidgets();
    } else {
      persist();
    }
    serialize?.apply(this, arguments);
    writeSerializableState(node, workflowNode);
  };

  node.__rim_reload = () => {
    loadStateFromWidgets();
    render();
  };

  loadStateFromWidgets();
  render();
}

app.registerExtension({
  name: "Comfy.ReferenceImageManager",
  init() {
    ensureStyles();
  },
  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData.name !== NODE_NAME) return;

    const onNodeCreated = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      onNodeCreated?.apply(this, arguments);
      buildManager(this);
    };

    const configure = nodeType.prototype.configure;
    nodeType.prototype.configure = function (info) {
      this[CONFIG_VALUES] = info?.widgets_values ? [...info.widgets_values] : [];
      this.__rim_config_dirty = !!this[CONFIG_VALUES].length;
      return configure?.apply(this, arguments);
    };

    const onConfigure = nodeType.prototype.onConfigure;
    nodeType.prototype.onConfigure = function () {
      onConfigure?.apply(this, arguments);
      requestAnimationFrame(() => {
        const itemsWidget = getWidget(this, "managed_images");
        if (itemsWidget && this[CONFIG_VALUES]?.length) {
          const configuredItems = readConfiguredItems(this);
          if (configuredItems) {
            itemsWidget.value = configuredItems;
            this.__rim_state_json = configuredItems;
          }
        }
        this.__rim_reload?.();
      });
    };

    const clone = nodeType.prototype.clone;
    nodeType.prototype.clone = function () {
      const cloned = clone?.apply(this, arguments);
      if (cloned) {
        cloned[CONFIG_VALUES] = [
          getWidgetValue(this, "image"),
          readManagedJson(this),
        ];
        cloned.__rim_state_json = cloned[CONFIG_VALUES][1];
        const imageWidget = getWidget(cloned, "image");
        const itemsWidget = getWidget(cloned, "managed_images");
        if (imageWidget) imageWidget.value = cloned[CONFIG_VALUES][0];
        if (itemsWidget) itemsWidget.value = cloned[CONFIG_VALUES][1];
        if (!cloned.properties) cloned.properties = {};
        cloned.properties.rim_items = cloned[CONFIG_VALUES][1];
        cloned.properties.rim_selected_id = this.properties?.rim_selected_id || "";
      }
      return cloned;
    };

    const onSerialize = nodeType.prototype.onSerialize;
    nodeType.prototype.onSerialize = function (workflowNode) {
      onSerialize?.apply(this, arguments);
      writeSerializableState(this, workflowNode);
    };

    const onDrawBackground = nodeType.prototype.onDrawBackground;
    nodeType.prototype.onDrawBackground = function () {
      const oldImgs = this.imgs;
      this.imgs = [];
      const result = onDrawBackground?.apply(this, arguments);
      this.imgs = oldImgs?.length ? [] : oldImgs;
      return result;
    };
  },
});
