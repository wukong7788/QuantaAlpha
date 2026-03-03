# Update Sync Workflow

目标：在当前分支自动完成“文档同步 + GitHub 提交推送”。

## 执行内容

1. 读取当前代码改动，识别行为变更对应的文档更新需求。
2. 同步更新以下文档（按需）：
   - `SPECS.md`
   - `README.md`
   - `README_CN.md`
   - `docs/*.md`
   - `CHANGELOG.md` / `CHANGELOG_CN.md`
3. 仅暂存文档文件并提交（不夹带代码文件）：
   - `git add SPECS.md README.md README_CN.md docs CHANGELOG.md CHANGELOG_CN.md`
   - `git commit -m "docs: sync docs for current branch"`
4. 推送到当前分支：
   - `git push origin <current-branch>`

## 触发词

- “执行 update_sync”
- “跑 update_sync workflow”

## 约束

- 若无文档差异，则明确输出 “no docs changes”，不创建空提交。
- 不切换分支，不改 `main`。
- 提交前显示本次将提交的文档清单供确认。
