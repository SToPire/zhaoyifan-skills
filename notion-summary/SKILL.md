---
name: Notion:save-article-summary
description: "获取网页文章URL，生成中文摘要并保存到Notion页面。当用户提供文章链接并要求总结保存到Notion时触发。"
---

# Notion文章摘要保存

## 概述

从网页URL获取文章内容，生成中文摘要并保存到用户的Notion页面。

## 前置条件

需要 Notion MCP 工具。如果未安装，询问用户是否批准安装。

## 工作流程

### 1. 获取文章内容

使用 WebFetch 工具获取文章：
```
WebFetch(url, prompt="提取文章完整内容，包括标题、主要观点、关键细节和结论")
```

### 2. 生成中文摘要

将文章内容总结成结构化的中文摘要，包括：
- 标题和原文链接
- 事件概述
- 核心观点/关键步骤
- 重要细节
- 结论/补救措施

### 3. 保存到Notion

如果用户提供了目标页面ID：
```
mcp__plugin_Notion_notion__notion-update-page(page_id, command="replace_content", new_str=摘要内容)
```

如果未提供页面ID，保存到默认位置：
1. 使用 mcp__plugin_Notion_notion__notion-search 搜索"有趣的新闻"页面
2. 在该页面下查找或创建以当前年月命名的子页面（格式：YYYY-MM）
3. 将摘要保存到该子页面中
