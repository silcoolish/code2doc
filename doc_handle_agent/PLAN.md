# doc_handle_agent
这是一个文档处理的agent服务, 主要包含根据文档模板以及代码知识底座生成代码说明文档

## 功能说明
1. 模板文档与生成文档都是doc或docx格式的文档
2. 生成文档的核心逻辑为复制一份模板文档，agent根据模板文档中的template内容块生成实际的内容块并替换
3. template内容块的格式如下:
   a. {{"type":"text", "prompt":"系统的功能概述"}} 由双大括号包裹，type表示内容块的类型text表示正文,headline表示标题,prompt后的内容为agent生成该部分内容的提示词
   b. {{"type":"headline", "prompt":"系统的模块功能", "list":"true", "min_length":"5","max_length":"20"}} type为headline时,表示生成标题,list为true表示需要生成多个标题，min_length表示生成内容最小长度，max_length表示生成内容最大长度
4. agent使用MCP协议调用knowledge_base_service中的MCP服务来获取生成文档内容所需要的代码信息

## 技术选型
1. 使用python3.11作为开发语言
2. 使用langgraph作为构建agent的框架
3. 使用FastAPI作为web框架
4. LLM模型暂时使用Qwen3.5

## 开发测试环境
1. 使用conda环境code2Doc
2. 参考D:\WorkSpace\code2doc\knowledge_base_service\document的API文档中的MCP接口调用

## 核心API接口
1. 启动生成代码说明文档流程，参数为仓库id和模板文档路径，返回流程id
2. 获取生成文档进度，参数为流程id，返回生成进度

## 生成文档流程
1. 读取模板文档内容
2. 解析模板文档中的template内容块
3. 调用agent生成替换文档内容
4. 生成最终代码说明文档并存放到对应目录下

## 代码实现细节
1. agent操作时记录详细日志，包括每次调用LLM的提示词和返回，每次调用工具的参数和结果

## 代码扩展点
1. agent调用工具可扩展
2. 使用LLM模型可扩展