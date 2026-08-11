# Advanced Image Loader

English | [简体中文](#简体中文)

## English

An advanced `Load Image` node for ComfyUI. It switches between a reusable image library and an efficient local-folder browser while keeping a standard `IMAGE` + `MASK` interface.

![Advanced Image Loader](https://sywb.top/Staticfiles/pic/yscy1.png)

### Features

- **Library**: add multiple images, replace the current entry, search, favorite, rename, remove, and switch by thumbnail.
- **Folder**: select or enter a local directory and browse it 48 images at a time without uploading the whole folder. A selected image can be explicitly copied to `input` and added to the Library.
- Folder names are indexed once and cached; only visible thumbnails are decoded, with at most three thumbnail requests running together.
- Original images from folder mode are read only when the workflow executes. Large folders, HDDs, and network paths therefore avoid eager full-image loading.
- Edit the selected image and mask with ComfyUI's native Mask Editor.
- Outputs `IMAGE` and `MASK`. Alpha is converted to ComfyUI's inverted mask convention.
- Library data, source mode, folder path, selected image, page, search text, and edited-image references are stored in the workflow and survive reload, workflow switching, and node duplication.
- English and Simplified Chinese UI.

Images added to the Library use ComfyUI's normal `input` cache. Folder mode never copies a directory into `input`; it copies only the current image when you click **Add to Library** or when the native Mask Editor needs an editable source.

### Installation

Install `reference-image-manager` from ComfyUI Manager, or clone this repository into `ComfyUI/custom_nodes` and restart ComfyUI.

Find the node by searching for `Advanced Load Image`, `Load Image`, or under:

```text
image/loaders -> Advanced Load Image
```

Existing workflows that used `Reference Image Manager` remain compatible because the legacy internal node ID is retained.

---

## 简体中文

[English](#english) | 简体中文

这是一个面向 ComfyUI 的高级“加载图像”节点，在一个节点内提供常用图库和本地文件夹两种读取方式，并保持标准的 `图像 + 掩码` 输出。

### 功能

- **图库管理**：多选添加、替换当前、搜索、收藏、改名、删除，并可直接点击缩略图切换输出。
- **文件夹浏览**：选择或输入本地目录，每页读取 48 个文件名，不会把整个文件夹上传到 `input`；也可明确地把当前选中图片复制到 `input` 并加入图库。
- 文件名索引会复用缓存；只解码当前可见的缩略图，并将并发缩略图请求限制为 3 个，适合大目录、机械盘和远程盘。
- 文件夹中的原图只会在工作流实际执行时读取。
- 可调用 ComfyUI 原生蒙版编辑器编辑当前图像与掩码。
- 输出 `图像` 和 `掩码`；透明通道会按 ComfyUI 规则转换为反相掩码。
- 图库、读取方式、文件夹路径、当前图片、浏览页码、搜索内容和编辑结果都会保存在工作流中，支持切换工作流、重新加载和复制节点。

图库中主动添加的图片仍使用 ComfyUI 正常的 `input` 缓存。文件夹浏览绝不会复制整个目录；只有点击“加入图库”或打开原生蒙版编辑器时，才会复制当前这一张图片。

搜索 `高级加载图像` 或 `加载图像` 即可找到节点，分类位置为：

```text
image/loaders -> 高级加载图像
```

旧工作流中的“参考图管理器”仍能正常加载，因为内部节点 ID 没有更改。
