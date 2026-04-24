# 内容块格式说明与输出要求

## 内容块字段说明

每个内容块是一个 JSON 对象，包含以下字段：

- `id`: 内容块唯一标识
- `block_type`: 块类型，`"heading"` 表示标题，`"paragraph"` 表示正文
- `heading_level`: 标题层级（1-9），正文为 0
- `content_text`: 内容文本。对于静态块是现有内容，对于模板块是标题/主题摘要
- `template`: `"static"` 表示静态内容（直接保留），`"template"` 表示需要生成的模板内容
- `content_type`: 内容类型，`"text"` 表示文本，`"img"` 表示图片
- `prompt`: 模板内容块的生成提示词（仅 `template="template"` 时有效）
- `image_id`: 图片内容块的图片搜索 ID（仅 `content_type="img"` 时有效）
- `min_length`: 最小字数限制（可选）
- `max_length`: 最大字数限制（可选）
- `example`: 参考示例（可选）

## 处理规则

1. `template="static"` 的块：直接保留 `content_text` 作为内容
2. `template="template"` 且 `content_type="text"` 的块：根据 `prompt` 生成文本内容
3. `template="template"` 且 `content_type="img"` 的块：使用 `batch_get_image_urls` 工具获取图片 URL

## 输出格式

**必须按以下 JSON 格式输出所有内容块的内容：**

```json
{
  "paragraphs": [
    {
      "paragraph_id": "内容块ID",
      "content": "生成的内容（静态块保留原标题/正文，图片类型返回单个URL）",
      "is_heading": true/false,
      "is_image": true/false
    }
  ]
}
```

注意：
- 输出必须包含所有内容块，保持原有顺序
- `content` 字段：文本类型返回生成的段落内容，图片类型返回图片 URL，静态类型保留原 `content_text`
- `is_heading`：标题块为 `true`，其他为 `false`
- `is_image`：图片类型块为 `true`，其他为 `false`

## 格式要求

- 文本内容使用纯文本格式，不要包含任何 Markdown 标记
- 正文必须是完整的段落式描述，不要分点简述
- 正文首行必须空两格（添加两个全角空格）
- 标题不要添加数字序号
