# 数据库设计（持续更新）

## 面试主链路

- `user`：账号、密码哈希和角色。
- `position`：岗位编码、名称和说明。
- `question`：岗位题目、类型、难度、参考答案、评分点、审核与版本信息。
- `interview_session`：一次面试的题目快照、状态、进度、评分版本和训练来源。
- `interview_message`：按序保存问题、追问和用户答案；语音答案保留原始转写与用户确认文本。
- `expression_metric`：与一条语音回答一一对应的文本及声学可复算指标。
- `question_score`：一场面试每道正式题唯一一条评分；保存规则分、模型分、最终分、六维 Rubric 和知识引用快照。
- `interview_report`：聚合报告和训练任务快照。
- `training_task`：报告任务的可变状态；保存来源场次、任务快照、训练场次以及开始/完成时间。

`interview_session` 状态按 `interviewing -> scoring -> completed` 推进，失败时进入 `failed` 后可重试；用户也可从进行中状态放弃。回答消息、表达指标、追问和进度在同一事务中提交，评分明细、报告和完成状态也在同一事务中提交。

## RAG

- `knowledge`：按岗位保存知识块、来源文档、块序号、内容哈希和 Embedding 缓存。
- `retrieval_event`：保存每次追问、评分或训练推荐的查询场景、算法版本、方式和召回结果。

知识可以被删除或重新向量化；历史 `question_score.knowledge_references` 保存的是引用快照，不依赖知识行继续存在。

## 题目审核字段

- `source`：内容来源。
- `review_status`：`pending`、`in_review`、`reviewed`、`ai_reviewed` 或 `rejected`。
- `reviewer` / `reviewed_at`：审核身份与时间。
- `content_version`：实质内容修改时递增。
- `is_core`：核心审核候选和优先抽题标记。

`ai_reviewed` 与 `reviewed` 有意分开，避免把机器辅助检查描述成人工审核。

## 删除与数据生命周期

- 用户只能读取、导出和删除自己的记录；管理员接口不能读取密码哈希或环境变量密钥。
- 删除单场历史时先检查是否被专项训练引用，避免留下失效来源。
- 用户确认密码后删除账号：先删除其 `interview_session`，数据库通过 `ON DELETE CASCADE` 清理消息、表达指标、逐题分、报告、检索事件与训练任务，再删除用户。
- 知识和题目属于系统种子/管理数据，不随个人账号删除；历史报告保存必要的知识引用快照。
- 原始 WAV 不入库、不落盘；只保存用户确认文本、原始 ASR 转写和可复算的指标。
