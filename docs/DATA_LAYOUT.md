# Data Layout

本文件冻结本地数据目录的所有权和清理边界。Phase 0 只做数据库基线与卫生修复，不迁移或删除用户资产。

| 路径 | 内容与所有权 | 备份/清理策略 |
| --- | --- | --- |
| `data/agent_workbench.db` | SQLite 权威状态：session、message、run、设置、Knowledge、Worldbook 和模型配置。包含敏感信息。 | 迁移、升级或修复前必须先生成 `data/backups/database/*.db` 及 manifest；不要提交版本库。 |
| `data/attachments/` | 用户上传的附件及其元数据。 | 与数据库一起备份；只有用户明确要求时清理孤立文件。 |
| `data/knowledge/` | Knowledge 来源、索引输入和运行时生成的数据。 | 视为用户资产；备份后再做索引重建或删除。 |
| `data/models/` | 用户手动放入的模型文件和目录（embedding、reranker、vision、image embedding、llm 等）。 | 不由 Phase 0 下载、重命名或删除；测试必须使用临时 root。 |
| `data/runtimes/` | 未来受管 runtime/worker 的可重建安装目录。 | 安装包和 worker 可重建；状态仍需保留在数据库/日志中。 |
| `data/logs/` | 诊断、推理和访问日志。 | 可按保留策略清理，但不得作为业务状态来源。 |
| `data/comfyui/` | 旧 ComfyUI 工作流、预设和相关用户文件。 | Phase 0 暂时保留；后续 ComfyUI 工具从零设计前不得擅自删除。 |
| `data/backups/` | 数据库迁移备份及 JSON manifest，可能包含密钥和用户内容。 | 敏感、不可提交；确认新版本稳定后按保留策略清理。 |
| `dist/` | 旧 portable 代码快照，不是用户数据。 | 可重新构建；Phase 0 已移除，不作为运行时来源。 |

## 备份最低要求

- 备份使用 SQLite 在线备份 API，完成后检查 `PRAGMA integrity_check`。
- manifest 记录源路径、UTC 时间、SHA-256、大小、关键表行数和迁移前 schema 摘要。
- 任何破坏性迁移都必须先备份并在副本上验证；失败时保留备份，不自动覆盖原库。
- 数据库备份目录被 `.gitignore` 忽略。分享诊断信息时先移除 API key、附件内容和模型路径中的敏感信息。

## 测试边界

测试创建应用时应传入 `root=tmp_path`，并将数据库、附件和模型目录都置于临时根目录。仓库级 fixture 会在测试会话开始/结束时比较 `data/models` 下普通文件的路径、大小和 SHA-256，任何意外写入都会使测试失败。
