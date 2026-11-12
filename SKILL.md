---
name: codeup-workitem
description: 统一通过云效（Codeup 所属云效组织）申报任务编号和缺陷编号。用户要"起任务编号"、"提缺陷"、"申报工作项"、"查任务状态"、"查缺陷"时调用。编号由云效服务端原子分配，禁止本地自增，避免多人共用列表文件的编号冲突。
metadata:
  short-description: 云效任务/缺陷编号统一申报
---

# /codeup-workitem

## 用途

所有任务编号、缺陷编号统一从云效 Projex 申报获取。编号（`serialNumber`，如 `ABCD-123`）由云效服务端在创建工作项时原子分配，天然唯一，多人并发也不会冲突。

**触发场景**（命中任意一条就调用本 skill）：
- 用户要起任务编号 / 申报新任务 / 建任务
- 用户要提缺陷 / 报 bug / 申报缺陷
- 查任务 / 缺陷的状态、详情、列表
- commit message、分支命名需要任务/缺陷编号时

## 🔴 强制规则

1. **任何新任务/缺陷必须先 `create` 从云效取号，禁止本地编号、禁止自增计数器、禁止维护共享编号列表文件。**
2. **创建前必须先 `list --subject-contains=<关键词>` 按标题查重**，确认没有重复工作项再创建。
3. **分支命名和 commit message 必须带 serialNumber**：
   - 分支：`feature/abcdn-12-简短描述` 或 `bugfix/abcdn-7-简短描述`
   - commit：`feat(ABCD-12): 完成XX功能`、`fix(ABCD-7): 修复XX问题`
4. 编号大小写以云效返回为准，写入 commit/分支时原样使用。

## 脚本用法

脚本路径：`.claude/skills/codeup-workitem/scripts/yx_workitem.py`（纯标准库，Python 3）

```bash
S=.claude/skills/codeup-workitem/scripts/yx_workitem.py

# 查重（创建前必做）—— 服务端按标题过滤
python3 $S list --category=bug --subject-contains="登录页"

# 创建缺陷 / 任务 / 需求 → 返回 serialNumber
python3 $S create --category=bug  --subject="修复登录页网络异常未提示" --desc="复现步骤：..."
python3 $S create --category=task --subject="完成出荷検品HT设计书评审"
python3 $S create --category=req  --subject="支持 pallet 票批量打印" --parent=<父工作项id>

# 指定负责人（默认用 .yunxiao.json 的 defaultAssignee）
python3 $S create --category=bug --subject="..." --assignee=<userId>

# 覆盖必填自定义字段（如优先级/严重程度），fieldId=optionId，可多次传
python3 $S create --category=bug --subject="..." \
  --field=priority=6f07f14ee13a97adafa30c409d \
  --field=seriousLevel=538ff83316a1f90994b741a7ad

# 不在本地生成 docs 描述文档（默认 create/update 都会写）
python3 $S create --category=task --subject="..." --no-doc

# 查询
python3 $S get --id=<identifier> --full          # 精确查询（含完整字段）
python3 $S get --serial=PFGZ-1 --category=bug    # 按编号反查（搜索遍历）
python3 $S list --category=task --max=20          # 列表

# 删除（误建清理，按 identifier，不可恢复）
python3 $S delete --id=<identifier>

# 查看某类工作项的可用状态（名称 + id）
python3 $S workflow --category=bug --pretty

# 更新工作项：状态（状态名或 id 均可）、描述、标题、自定义字段
python3 $S update --id=<identifier> --status="处理中" --desc="补充复现步骤..."
python3 $S update --id=<identifier> --status=29          # 已修复（状态 id）
python3 $S update --id=<identifier> --subject="新标题"

# AI 直接改写 docs 文档后推回云效（推荐的 AI 协作方式）
#   --doc 自动从 frontmatter 解析 identifier、提取「## 描述」正文，推回后云效再覆写本地
python3 $S update --doc=docs/workitems/PFGZ-7-登录页异常.md
python3 $S update --id=<identifier> --desc-file=笔记.md   # 或从任意 md 文件读描述
#   三个描述来源互斥：--desc / --desc-file / --doc 只能给一个

# 全量回拉云效工作项，重建本地 docs 描述文档（可按类型，可清理孤儿文档）
python3 $S sync                          # 同步所有类型
python3 $S sync --category=bug           # 只同步缺陷
python3 $S sync --prune                  # 删除云效中已不存在的本地文档
```

## 双存储：云效（状态）+ Git 管理的 docs（描述，供 AI 搜索/改写）

**职责划分**

- **云效 = 状态与编号的唯一事实源**：serialNumber、状态流转、负责人、自定义字段（优先级/严重程度）全在云效管理，本地不手工改这些。
- **`docs/workitems/` = 纳入 git 管理的描述文档**：文件名 `serialNumber-标题.md`（如 `PFGZ-7-登录页网络异常未提示.md`），含 YAML frontmatter（编号、status、assignedTo、url、自定义字段、同步时间）+ `## 描述` 正文。**这个目录正常提交 git**，描述的演进随 git 历史可追溯，也供 AI 全文检索。

**AI 改写描述的正确路径（单向回写，不是只读副本）**

1. AI 直接编辑 `docs/workitems/<编号>-*.md` 的 `## 描述` 章节（正文内可自由用 `##`/`###` 子标题、列表、代码块）。
2. 跑 `update --doc=<该文档路径>`：脚本自动从 frontmatter 取 identifier、提取描述正文推回云效，成功后云效最新内容再覆写本地文档（frontmatter 的 status/docSyncedAt 一并刷新）。
3. `git add docs/workitems && git commit -m "docs(PFGZ-7): 更新描述"` 提交。
   - 也可以 `update --id=<identifier> --desc-file=笔记.md` 从独立文件推，或直接 `--desc="..."`。
   - `--doc` 模式下不用再传 `--id`；三个描述来源 `--desc`/`--desc-file`/`--doc` 互斥。
   - frontmatter（status/assignedTo 等托管字段）即使被本地改动，推回时也会被云效覆写，所以只改 `## 描述` 区。

**同步与清理**

- `create`/`update` 默认自动写/刷新本地文档；`--no-doc` 可只操作云效。
- 改标题后再次 `update`/`sync`，旧文件按 serialNumber 自动重命名，不留两份；`delete` 联动删本地文档。
- 本地文档丢失或多人协作后，`sync` 从云效全量重建；`sync --prune` 清理云效已删但本地残留的孤儿文档。
- 文档目录可在 `.yunxiao.json` 用 `"docsDir": "其他/目录"` 覆盖（默认 `docs/workitems`）。

**状态与描述管理**
- `workflow` 先查该类型允许的状态（缺陷：待确认/处理中/已修复/暂不修复/已关闭/再次打开）
- `update --status` 传中文状态名时自动解析为状态 id；非法流转云效会返回错误
- 描述为 Markdown，更新后云效页面和 `get --full` 可见（`get` 默认精简输出不含 description，需要看描述加 `--full`）

`--category` 取值：`task` / `bug` / `req` / `risk`。
输出为 JSON（加 `--pretty` 格式化），含 `serialNumber`、`identifier`、`url`。

**必填字段自动处理**：云效项目可能配置必填自定义字段（本项目缺陷含「优先级」「严重程度」）。脚本创建时自动拉取字段配置，对未显式指定的必填项取默认/第一个选项；无默认选项的字段会报错并提示用 `--field` 手动指定。默认指派人取自 `.yunxiao.json` 的 `defaultAssignee`。

## 存储结构与分发方式

这是一个**项目级（project-level）skill**，所有文件随 git 仓库分发，不依赖任何全局安装或第三方包。

```
仓库根目录/
├── .claude/
│   └── skills/
│       └── codeup-workitem/
│           ├── SKILL.md                       # skill 说明（本文件，含触发规则与用法）
│           └── scripts/
│               └── yx_workitem.py             # 纯 Python 标准库实现，Python 3 即用
├── .yunxiao.json                              # 项目配置（无敏感信息，提交入库）
├── .gitignore                                 # 确保忽略本地凭证（见下）
└── docs/workitems/                            # 描述文档目录，纳入 git 管理（运行后生成）
```

**为什么不用全局安装 / 插件市场**：放在项目 `.claude/skills/` 下，任何人 clone 仓库后 Claude Code 自动发现该 skill，版本随仓库走，团队所有人用的是同一份脚本，不存在各自装版本不一致的问题。脚本仅用 Python 标准库（`urllib`/`json`/`argparse` 等），无需 `pip install`。

## 安装到项目（给人看的简述，给 agent 看 INSTALL.md）

**让智能体安装**：对它说「帮我安装 https://github.com/nixecn-lab/codeup-workitem」，它会读取仓库根目录的 **`INSTALL.md`** 并按步执行——拷贝技能到 `.claude/skills/codeup-workitem/`、在项目 `CLAUDE.md` 写入带标记的编号管理规则块、配置 `.gitignore` 凭证保护，然后引导你完成 PAT 与交互式 `setup`。完整、唯一的安装事实源是 `INSTALL.md`，本节只做概述：

1. 把本仓库内容放到目标项目 `.claude/skills/codeup-workitem/`（不含 `.git`）。
2. `.gitignore` 忽略 `.yunxiao.json`、`.yunxiao_env`、`*.local`、`__pycache__/`。
3. `CLAUDE.md` 追加「任务编号管理（强制）」规则块（INSTALL.md 附完整可粘贴文本，用 BEGIN/END 标记包裹）。
4. 用户本人创建云效 PAT（权限点：项目协作-工作项读写 + 项目成员只读），`export YUNXIAO_TOKEN=...` 写入自己的 shell 配置。
5. 用户在终端运行交互式 `python3 .claude/skills/codeup-workitem/scripts/yx_workitem.py setup` 生成 `.yunxiao.json`。
6. `list --category=task` 只读验证连通；可选 `sync` 拉取存量工作项描述。

**升级 / 卸载**：见 INSTALL.md 的「重复安装 / 升级」「卸载」章节。升级只覆盖技能文件，绝不碰宿主项目的 `.yunxiao.json` 与 `docs/`；卸载默认保留这两类用户数据。

## 凭证与安全边界

- **PAT 只存在于每个人的环境变量 `YUNXIAO_TOKEN`**，不写入任何入库文件，agent 也不代改用户 shell 配置。
- 脚本读取顺序：环境变量 `YUNXIAO_TOKEN` / `YUNXIAO_ORGANIZATION_ID` 优先，其次仓库内 `.yunxiao.json`。
- `.yunxiao.json` 不含 token，只有组织/项目 id 与类型 id；默认按 INSTALL.md 加入 `.gitignore` 不入库（私有团队仓库若想共享配置也可 `git add -f` 强制提交，无密钥泄露风险，但会暴露内部项目 id）。
- 每个成员用**自己的 PAT**，云效侧操作记录各自可追溯；吊销某人的 PAT 不影响其他人。
- `docs/workitems/` 是正常入库的业务文档，不是凭证，可以放心提交。

## 报错处理

- `缺少云效个人访问令牌`：按输出提示引导用户创建 PAT 并设置 `YUNXIAO_TOKEN`，设置后需在新终端/`source ~/.zshrc` 生效。
- `401`：token 过期，引导用户重新生成。
- `403`：检查 PAT 权限点（需项目协作读写）、PAT 所属企业是否正确。
- `未配置 workitemTypes`：运行 setup，或让管理员补齐 `.yunxiao.json`。
- API 返回其他错误时，把 errorCode/errorMsg 原样报告给用户，不要重试 create（可能已创建成功，先 `list` 查重确认）。
