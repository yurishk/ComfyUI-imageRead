# Reference Image Manager

**English** | [简体中文](#简体中文)

## English

A lightweight ComfyUI node for managing multiple reusable reference images without stacking many Load Image nodes.

![Reference Image Manager](https://sywb.top/Staticfiles/pic/yscy1.png)

## Features

- Standard `IMAGE` output.
- Starts with an empty, user-managed image list.
- Add multiple images, replace the current image, and switch by clicking thumbnails.
- Edit the display name, original path, and folder metadata.
- Search by name or path and filter by current folder or favorites.
- Remove individual entries or clear the whole list.
- The selected image and managed list are stored in the workflow and survive save, reload, workflow switching, and node duplication.
- English and Simplified Chinese UI.

Images selected outside ComfyUI are uploaded to the normal ComfyUI input directory. The manager also keeps the original source path when the browser exposes it.

## Installation

Install `reference-image-manager` from ComfyUI Manager, or clone this repository into `ComfyUI/custom_nodes` and restart ComfyUI.

Find the node under:

```text
image/reference -> Reference Image Manager
```

---

## 简体中文

[English](#english) | **简体中文**

一个轻量的 ComfyUI 自定义节点，用一个节点管理多张参考图，避免堆很多 `Load Image` 节点。

- 图片列表默认为空，只保存你主动添加到管理器里的图片。
- 支持多选添加、替换当前、点击缩略图切换输出。
- 支持编辑显示名称、原始路径、文件夹。
- 支持搜索、同文件夹筛选、收藏筛选、删除单张、清空列表。
- 当前选择和管理列表保存在工作流中，保存、重载、切换工作流和复制节点后仍会保留。

节点位置：`image/reference -> 参考图管理器`。
