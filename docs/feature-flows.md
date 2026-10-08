# 核心功能数据流（持续更新）

> 记录当前代码的实际调用路径，教师答辩话术留到 P3 统一整理。

## RAG 检索

```text
用户回答
  -> interview_controller（携带 session_id / question_id）
  -> followup_service / scoring_service / recommendation_service
  -> retrieval_service
       1. position_code 隔离岗位
       2. 规则匹配 + FTS5/BM25
       3. 可用时调用 embedding_service
       4. 分数融合与最低阈值过滤
       5. 写入 retrieval_event
  -> 知识块进入追问、逐题评分或训练建议
  -> QuestionScore 保存评分引用快照
  -> 报告展示逐题引用与检索留痕
```

正常路径使用三路混合排名；Embedding 服务失败时只跳过语义分，不中断面试。FTS5 不可用时继续使用确定性规则。若最终没有结果，调用方收到空列表并按“无知识上下文”执行，不注入无关材料。

## 知识文档导入

```text
管理员选择岗位与 Markdown / TXT / PDF
  -> /api/admin/knowledge/import
  -> 大小、扩展名、页数与文本有效性校验
  -> 分块（800 字，100 字重叠，最多 200 块）
  -> SHA-256 去重并记录文档名、块序号和来源
  -> knowledge 表
  -> 管理员手动刷新 Embedding 索引
```

扫描版或加密 PDF 不会伪装为导入成功；当前 MVP 不做 OCR。真实 API 密钥只从 `.env` 加载，管理接口仅返回“是否已配置”和模型名。

## 个性化训练闭环

```text
正式面试报告
  -> recommendation_service 生成岗位化任务
  -> training_task 保存任务快照（todo）
  -> 用户点击开始专项训练
  -> 校验报告归属、任务状态、岗位与来源题
  -> 创建 3 题 training 场次（in_progress）
  -> 复用回答、追问、评分、报告事务
  -> 任务 completed
  -> 同评分版本时生成分数与六维变化参考
  -> 个人大屏展示专项记录与薄弱项变化
```

同一个任务不能并行启动两次。放弃或删除未完成的专项场次后任务回到 `todo`；完成后保留来源与复测报告。正式面试趋势与专项训练统计分离。

## 失败与降级

- LLM 未配置、超时或输出不合法：追问和评分回退本地评分点规则。
- Embedding 未配置、超时或熔断：检索回退 FTS5/BM25，再回退确定性规则。
- ASR 未配置、超时或无结果：不写消息、不推进进度，提示改用文字输入。
- 报告提交失败：回滚评分与报告写入，保留回答并允许重试。
- 页面刷新：从数据库恢复消息、题号和可执行操作，浏览器只缓存当前场次 ID。
