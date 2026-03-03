# Update Sync Workflow

目标：在当前分支自动完成“先文档对齐，再同步未提交文件到 GitHub”。

## 执行内容

1. 读取当前所有未提交改动（代码/脚本/测试/文档）。
2. 若存在行为变更，先同步更新以下文档（按需）：
   - `SPECS.md`
   - `README.md`
   - `README_CN.md`
   - `docs/*.md`
   - `CHANGELOG.md` / `CHANGELOG_CN.md`
3. 文档更新完成后，再同步全部待提交文件（而不是只提文档）：
   - 提交前执行测试门禁（默认最小集）：
     - `uv run pytest -q tests/backtest/test_custom_factor_calculator_duplicate_factor_name.py tests/backtest/test_factor_calculator_duplicate_factor_name.py`
     - 若测试失败：停止提交并输出失败摘要。
   - `git add -A`
   - `git commit -m "<type>: sync docs and code for current branch"`
4. 推送到当前分支：
   - `git push origin <current-branch>`

## 触发词

- “执行 update_sync”
- “跑 update_sync workflow”

## 约束

- 若文档无需改动，输出 “no docs changes needed”，继续检查并同步其他未提交文件。
- 若整体无改动，输出 “no changes”，不创建空提交。
- 不切换分支，不改 `main`。
- 提交前显示本次将提交的完整文件清单供确认。
