# 内容块格式说明与输出要求

## 内容块字段说明

每个内容块是一个 JSON 对象，包含以下字段：

- `id`: 内容块唯一标识
- `block_type`: 块类型，`"heading"` 表示标题，`"paragraph"` 表示正文，`"image"` 表示图片，`"mermaid"` 表示 Mermaid 图，`"table"` 表示表格
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
- `caption`: 图表的语义名称，仅 `table`、`image`、`mermaid` 类型使用。生成这些模板块时必须返回该字段；只填写名称，不得包含“图1”“表2”等编号。输入已有非空名称时保持原值
- `template`: `"static"` 表示静态内容，`"template"` 表示需要生成的模板内容
- `prompt`: 模板内容块的生成提示词（仅 `template="template"` 时有效）
- `min_length`: 最小字数限制（可选）
- `max_length`: 最大字数限制（可选）
- `example`: 内容文本生成的参考示例（可选）
- `table_schema`: 表格结构定义，仅 `block_type="table"` 时有效（可选）
- `header_row`: 是否有表头行，仅 `block_type="table"` 时有效（可选）
- `header_column`: 是否有表头列，仅 `block_type="table"` 时有效（可选）

## 图表名称要求

1. `caption` 是返回内容块对象的同级字段，不得把 `caption` 字段嵌套进 `content_text` 或 `rows`，也不得在 draw.io 图形节点中重复绘制图名
2. 函数流程图使用“函数名 + 函数流程图”，例如 `push_back函数流程图`
3. 函数设计表使用“函数名 + 函数设计表”，例如 `push_back函数设计表`
4. 模块主要函数表使用“模块名 + 主要函数表”；其他图表根据当前标题和实际内容生成简短、具体的名称
5. 不得返回“图1”“表2”等编号，不得只返回“图示”“数据表”等无语义名称
6. 表格提示词中的“只返回 rows”仅约束 `content_text`，仍必须在内容块同级返回 `caption`
7. `table` 名称必须以“表”结尾，`image`、`mermaid` 和 draw.io 名称必须以“图”结尾

图表内容块返回示例：

```json
{
  "id": "function-table",
  "block_type": "table",
  "content_text": {
    "rows": [
      ["主要职责", "向容器尾部添加元素"]
    ]
  },
  "caption": "push_back函数设计表"
}
```

## draw.io 架构图格式

当输入内容块包含 `format="drawio_architecture"` 时，必须把它当作项目总体架构图生成，返回 `content_text` 为 JSON 对象，不要返回 Mermaid、Markdown 表格或图片地址。后端会把该 JSON 渲染成可编辑 draw.io 源文件和 SVG 预览图。

同时返回内容块同级的 `caption`；`content_text.title` 仅作为 draw.io 文件元数据，与 `caption` 保持一致，后端不会把该 `title` 渲染为图内标题。

`content_text` 结构如下：

```json
{
  "title": "项目架构图标题",
  "visual": {
    "layout": "layered",
    "theme": "vivid",
    "accent": "lime",
    "variant": "balanced"
  },
  "layers": [
    {
      "id": "desktop",
      "label": "L1",
      "name": "桌面与网页工作台",
      "subtitle": "Electron + React",
      "color": "sky",
      "items": [
        {"id": "repo-browser", "name": "源码浏览", "description": "仓库文件与代码预览"}
      ],
      "notes": ["仓库管理", "文档编辑", "AI 设置"]
    }
  ],
  "connections": [
    {"from": "desktop", "to": "workspace-service", "label": "HTTP API", "color": "indigo"}
  ],
  "pipeline": [
    {"name": "本地代码仓库", "description": "仓库注册"},
    {"name": "知识库构建", "description": "解析与索引"}
  ]
}
```

生成要求：
1. `visual.layout` 表示图形版式，可选 `layered`、`domain_map`、`pipeline`，请根据项目结构选择，不要所有项目都固定使用同一种版式
2. 版式选择建议：层级依赖清晰时选 `layered`；模块/领域边界更重要时选 `domain_map`；业务主流程或控制流是重点时选 `pipeline`
3. `visual.theme` 表示整体配色，可选 `classic`、`cool`、`warm`、`contrast`、`forest`、`sunset`、`vivid`，请根据项目领域和图内容选择
4. 主题选择建议：通用后台/数据系统可选 `cool` 或 `classic`；硬件控制、游戏、交互流程可选 `warm`、`sunset` 或 `vivid`；资源/生态/任务编排可选 `forest`；跨模块依赖复杂时选 `contrast`
5. `visual.accent` 表示主链路或重点路径强调色，颜色范围同 `layers.color`；不要总是使用 `orange` 或 `blue`
6. 请主动为关键层设置不同 `color`，后端会把该颜色渲染为明显色条；避免连续使用相近色系，示例中的 `theme/accent/color` 只是结构示例，不要照抄
7. `layers` 表示系统分层、领域分组或支撑模块，优先覆盖用户入口、业务编排、核心能力、数据资源、基础依赖等关键区域
8. 每层可选 `color`，只能使用 `blue`、`green`、`orange`、`teal`、`purple`、`slate`、`indigo`、`emerald`、`amber`、`sky`、`rose`、`violet`、`red`、`cyan`、`lime`、`yellow`、`pink`、`zinc`，不要输出十六进制颜色
9. 每层 `items` 只放核心组件，名称短且可视化友好；详细说明放在 `description`
10. `connections.from/to` 必须引用 layer 或 item 的 `id/name`，用于绘制箭头；可选 `color`，颜色范围同上
11. `pipeline` 表示主链路，按从左到右的业务流程输出；当主流程很重要时优先选择 `visual.layout="pipeline"`
12. 不要输出 Mermaid 语法，不要输出 ` ``` ` 代码围栏


