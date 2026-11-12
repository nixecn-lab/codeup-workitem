# codeup-workitem

Claude Code / Codex 项目级 skill：统一通过[云效 Projex](https://www.aliyun.com/product/yunxiao)（Codeup 所属云效组织）申报任务编号和缺陷编号，替代在 git 仓库里维护共享编号列表的做法。编号 `serialNumber`（如 `PFGZ-12`）由云效服务端在创建工作项时**原子分配**，天然唯一，多人并发不冲突。

纯 Python 标准库实现，无需 `pip install`；随仓库 `.claude/skills/` 分发，clone 即用。

## 安装到项目

直接对 AI 智能体说：

> 帮我安装 https://github.com/nixecn-lab/codeup-workitem

智能体会阅读仓库里的 **[INSTALL.md](./INSTALL.md)**（面向 agent 的安装指南），自动完成：拷贝技能到 `.claude/skills/codeup-workitem/`、在项目 `CLAUDE.md` 写入编号管理强制规则、配置 `.gitignore` 凭证保护，并引导你完成 PAT 配置和交互式 `setup`。手动安装的完整步骤同样见 INSTALL.md。

## 能力

- `create` 在云效创建任务/缺陷/需求，取回服务端分配的 `serialNumber`
- 创建前 `list` 按标题服务端查重，避免重复申报
- 工作项状态、负责人、自定义字段（优先级/严重程度）以云效为唯一事实源，支持 `update` / `workflow` 状态流转
- **双存储**：描述文档在 `docs/workitems/<编号>-<标题>.md` 留一份纳入 git 管理的 Markdown，供 AI 全文检索与改写，`update --doc` 单向回写云效
- `sync` 全量重建本地文档、`--prune` 清孤儿文档
- 必填自定义字段自动取默认项；PAT 只走环境变量，不入库

## 快速开始

```bash
# 1. 云效控制台创建个人访问令牌（PAT），勾选「项目协作-工作项读写」「项目协作-项目成员只读」
export YUNXIAO_TOKEN=pt-xxxxxxxx          # 写入 ~/.zshrc，不要提交仓库

# 2. 在接入本 skill 的项目根目录初始化项目配置（生成 .yunxiao.json，无敏感信息）
python3 .claude/skills/codeup-workitem/scripts/yx_workitem.py setup

# 3. 起一个缺陷编号
python3 .claude/skills/codeup-workitem/scripts/yx_workitem.py \
  create --category=bug --subject="修复登录页网络异常未提示"
# => { "serialNumber": "PFGZ-7", "identifier": "...", "url": "..." }
```

完整命令、双存储协作方式、加载到已有项目的步骤见 [SKILL.md](./SKILL.md)。

## 仓库布局

```
SKILL.md                 # skill 定义：触发规则、命令用法、双存储、安全说明
INSTALL.md               # 面向 AI agent 的逐步安装指南（安装入口）
scripts/yx_workitem.py   # 纯标准库实现（Python 3）
yunxiao.example.json     # 项目配置模板（真实 .yunxiao.json 由 setup 生成，不入库）
```

接入项目时把本仓库内容放到目标仓库的 `.claude/skills/codeup-workitem/` 下，具体步骤见 [INSTALL.md](./INSTALL.md)。

## 凭证安全

- 云效 PAT 仅存于个人环境变量 `YUNXIAO_TOKEN`，仓库内不保存任何 token
- `.yunxiao.json` 只含 organizationId / projectId / 工作项类型 id，可公开提交
- 每位成员使用自己的 PAT，云效操作各自可审计

## License

[MIT](./LICENSE)
