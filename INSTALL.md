# 安装指南（给 AI Agent 执行）

> **本文档的读者是 AI 智能体。** 当用户说「帮我安装 https://github.com/nixecn-lab/codeup-workitem」「把这个云效编号 skill 装到当前项目」时，按本文档步骤执行即可。用户不需要知道这些细节，agent 负责把技能装好并在项目的 `CLAUDE.md` 写好使用规则。
>
- 仓库：`https://github.com/nixecn-lab/codeup-workitem`（public）
- 技能性质：**项目级 skill**，安装到目标项目的 `.claude/skills/codeup-workitem/`，随该项目 git 分发
- 纯 Python 3 标准库，无第三方依赖

---

## 安装前检查（agent 先做）

1. **确认当前工作目录是目标项目根目录**（含 `.git/` 或就是用户要接入的项目）。不确定时先 `pwd` 并向用户确认，不要装错项目。
2. **检查命令可用性**：`python3 --version`、`git --version`。Python 3.8+ 即可，缺失则停下让用户安装，不要自行装 Python。
3. **检查是否已安装**：若 `.claude/skills/codeup-workitem/scripts/yx_workitem.py` 已存在，走下文「重复安装 / 升级」流程，不要覆盖用户项目里的 `.yunxiao.json` 和 `docs/`。

## 步骤 1：获取 skill 文件

在目标项目根目录执行（临时克隆到系统临时目录，只拷贝技能文件，**不要把 `.git` 带进项目**）：

```bash
TMP=$(mktemp -d)
git clone --depth 1 https://github.com/nixecn-lab/codeup-workitem.git "$TMP/codeup-workitem"
mkdir -p .claude/skills
cp -R "$TMP/codeup-workitem" .claude/skills/codeup-workitem
rm -rf .claude/skills/codeup-workitem/.git "$TMP"
```

无 git 环境时的备选（curl + tar，GitHub tarball 根目录带一层 `repo-ref/` 前缀，需 `--strip-components=1`）：

```bash
mkdir -p .claude/skills/codeup-workitem
curl -fsSL https://github.com/nixecn-lab/codeup-workitem/archive/refs/heads/main.tar.gz \
  | tar -xz -C .claude/skills/codeup-workitem --strip-components=1
```

安装后该目录应包含：`SKILL.md`、`scripts/yx_workitem.py`、`README.md`、`INSTALL.md`、`LICENSE`、`yunxiao.example.json`、`.gitignore`（技能自带的这份是 skill 仓库自身的忽略规则，对宿主项目无副作用）。

## 步骤 2：确保宿主项目 `.gitignore` 忽略凭证与本地配置

检查宿主项目根目录的 `.gitignore`，缺少下面任一行就**追加**（已存在的行不要重复写）：

```gitignore
# 云效 codeup-workitem：本地凭证与项目配置禁止入库
.yunxiao.json
.yunxiao_env
*.local
__pycache__/
```

> 红线：`.yunxiao.json` 含项目特定 id，`YUNXIAO_TOKEN` 只能存在于用户环境变量里。**agent 绝不创建包含 token 的文件，也绝不替用户修改 `~/.zshrc` / `~/.bashrc`。**

## 步骤 3：在项目 `CLAUDE.md` 写入使用规则

这是安装的关键产出：让该项目里的所有 agent 会话都知道「起编号必须走这个 skill」。

- 若项目根没有 `CLAUDE.md`，新建。
- 若已存在，**在文件末尾追加**，保留原有全部内容。
- 用下面的 BEGIN/END 标记包裹，便于以后判断是否已安装、升级时整体替换而不是重复追加：

```markdown
<!-- BEGIN codeup-workitem 规则（由安装流程维护，勿删标记） -->
## 任务编号管理（强制）

所有任务编号、缺陷编号统一通过云效申报，使用 `codeup-workitem` skill（位于 `.claude/skills/codeup-workitem/`）。

**规则：**
1. 起新任务/缺陷编号时，必须调用 codeup-workitem skill 的 `create` 命令，编号由云效服务端分配（serialNumber，如 `ABCD-123`）。
2. **禁止**本地自增编号、禁止维护共享编号列表文件——多人并发会冲突。
3. 创建前先 `list --subject-contains=<关键词>` 查重，避免重复申报。
4. commit message 和分支命名必须带编号：
   - commit：`feat(ABCD-12): ...` / `fix(ABCD-7): ...`
   - 分支：`feature/abcdn-12-xxx` / `bugfix/abcdn-7-xxx`
5. **双存储**：编号、状态、负责人以云效为唯一事实源；描述文档放 `docs/workitems/<编号>-<标题>.md` 并**纳入 git 管理**，供 AI 检索与改写。
   - AI 可直接编辑文档的 `## 描述` 章节，改完用 `update --doc=<文档路径>` 推回云效（脚本自动解析 identifier，成功后云效再覆写回本地），然后 git 提交。
   - frontmatter 里的 status/assignedTo 等托管字段以云效为准，会被自动覆写，不要手工改。
   - 本地文档由 skill 自动生成/对齐：`sync` 全量重建、`sync --prune` 清孤儿；`--no-doc` 可只操作云效。
<!-- END codeup-workitem 规则 -->
```

写完后向用户说明：规则已写入 `CLAUDE.md`，本项目后续任何会话起任务/缺陷编号都会自动走云效。

## 步骤 4：引导用户配置云效 PAT（人工步骤，agent 不能代办）

agent 检查环境变量 `YUNXIAO_TOKEN` 是否存在：

```bash
[ -n "$YUNXIAO_TOKEN" ] && echo "已配置" || echo "未配置"
```

未配置时，**停下向用户说明**（不要试图替用户登录或生成 token），让用户完成：

1. 云效控制台 → 个人设置 → 个人访问令牌 → 创建 PAT
   - 权限点勾选：**项目协作-工作项读写** + **项目协作-项目成员只读**
   - 文档：https://help.aliyun.com/zh/yunxiao/user-guide/personal-access-token
2. 在自己的终端把环境变量写入 shell 配置（提示用户可用本会话的 `!` 前缀执行，输出会回到对话里）：
   ```bash
   echo 'export YUNXIAO_TOKEN=pt-xxxxxxxx' >> ~/.zshrc   # bash 用户改 ~/.bashrc
   source ~/.zshrc
   ```
3. 提醒：token 只放环境变量，不要发给 agent、不要写进任何入库文件。

非交互 shell 里 agent 自己 `echo $YUNXIAO_TOKEN` 可能看不到用户 `~/.zshrc` 的变量；让用户在他自己的终端验证，或用 `zsh -ic 'echo $YUNXIAO_TOKEN'` 探测。

## 步骤 5：初始化项目配置并验证（交互式，由用户在终端运行）

`setup` 是**交互式命令**（要手动输入 organizationId / projectId、选择工作项类型和默认指派人），agent 不要用管道代替用户选择。让用户在终端执行：

```bash
python3 .claude/skills/codeup-workitem/scripts/yx_workitem.py setup
```

- 生成的 `.yunxiao.json` 含 organizationId、projectId、工作项类型 id、默认指派人，**无 token**；但按步骤 2 它已被 `.gitignore` 忽略，留在本地即可（团队各自 setup，或由管理员生成后在受控范围内共享）。
- setup 末尾会自动调一次搜索接口验证 token 与权限，成功即安装完成。
- 若提示 `403`：PAT 权限点不足，回步骤 4 补权限后重建 token。

验证安装（agent 可代为执行，只读操作）：

```bash
python3 .claude/skills/codeup-workitem/scripts/yx_workitem.py list --category=task --max=5
```

能返回 JSON 列表（空列表也算成功）即全链路打通。

## 步骤 6：收尾汇报

向用户汇报：安装路径、`CLAUDE.md` 规则已写入、`.gitignore` 已保护凭证、PAT/setup 状态；并提示首次可跑 `sync` 把云效存量工作项描述拉到 `docs/workitems/`：

```bash
python3 .claude/skills/codeup-workitem/scripts/yx_workitem.py sync
```

---

## 重复安装 / 升级（已装过的项目）

1. 重新执行步骤 1 覆盖 `.claude/skills/codeup-workitem/` 下的技能文件。
2. **绝不删除或覆盖**宿主项目的 `.yunxiao.json`、`docs/workitems/`——那是用户数据。
3. 检查 `CLAUDE.md` 中 BEGIN/END 标记块：若新版规则有变化，整体替换标记块内容；标记块外的用户内容一字不动。
4. 跑一次 `python3 .claude/skills/codeup-workitem/scripts/yx_workitem.py --help` 确认子命令正常。

## 卸载（用户明确要求时）

1. 删除 `.claude/skills/codeup-workitem/`。
2. 从 `CLAUDE.md` 移除 BEGIN/END 标记包裹的整段规则（含标记行）。
3. **默认保留** `.yunxiao.json` 和 `docs/workitems/`（历史描述有价值）；用户明确要求才删，并提醒这是本地数据、云效侧不受影响。
4. `.gitignore` 里为该技能加的条目可保留（无副作用），用户要求清理再移除。

## 安全红线（agent 必须遵守）

- 不向任何文件写入真实 `YUNXIAO_TOKEN`；不修改用户 shell 配置文件，只给出命令让用户自己执行。
- 不执行 `create` / `delete` / `update` 这类写操作来「测试安装」——验证只用 `list` / `--help` 等只读命令。
- 安装过程不碰宿主项目中与本技能无关的任何文件。
