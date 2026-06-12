# 内容块格式说明与输出要求

## 内容块字段说明

每个内容块是一个 JSON 对象，包含以下字段：

- `id`: 内容块唯一标识
- `block_type`: 块类型，`"heading"` 表示标题，`"paragraph"` 表示正文，`"image"` 表示图片，`"table"` 表示表格
- `heading_level`: 标题层级（1-9），正文和图片为 0
- `content_text`: 内容文本。对于静态块是现有内容，对于模板块是标题/主题摘要。对于 `table` 类型，只生成单元格内容，不要生成完整表格结构。此字段使用对象格式，格式如下：
  ```json
  {
    "rows": [
      ["第一列内容", "第二列内容", "第三列内容"]
    ]
  }
  ```
  后端会根据输入的 `table_schema.columns` 自动装配 `columns`、`cells`、`headerRow`、`headerColumn`
- `template`: `"static"` 表示静态内容，`"template"` 表示需要生成的模板内容
- `prompt`: 模板内容块的生成提示词（仅 `template="template"` 时有效）
- `min_length`: 最小字数限制（可选）
- `max_length`: 最大字数限制（可选）
- `example`: 内容文本生成的参考示例（可选）
- `table_schema`: 表格结构定义，仅 `block_type="table"` 时有效（可选）
- `header_row`: 是否有表头行，仅 `block_type="table"` 时有效（可选）
- `header_column`: 是否有表头列，仅 `block_type="table"` 时有效（可选）


