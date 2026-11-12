#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""云效（Projex）工作项工具：任务/缺陷编号统一申报。

编号由云效服务端原子分配（serialNumber，如 ABCD-123），彻底避免多人
共用本地列表文件导致的编号冲突。

用法:
    yx_workitem.py setup                          # 初始化/校验配置
    yx_workitem.py create --category=bug --subject="标题" [选项]
    yx_workitem.py get --serial=ABCD-1 | --id=<identifier>
    yx_workitem.py list [--category=bug] [--subject-contains=关键词] [--max=20]

依赖：仅 Python 3 标准库。认证：环境变量 YUNXIAO_TOKEN（个人访问令牌）。
项目配置（无敏感信息）存于仓库根目录 .yunxiao.json，随 git 分发。

API 文档（新版 oapi/v1，中心版）：
  创建   POST /oapi/v1/projex/organizations/{orgId}/workitems
  详情   GET  /oapi/v1/projex/organizations/{orgId}/workitems/{id}
  搜索   POST /oapi/v1/projex/organizations/{orgId}/workitems:search
  类型   GET  /oapi/v1/projex/organizations/{orgId}/projects/{pid}/workitemTypes
"""

import argparse
import datetime
import glob
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

API_BASE = "https://openapi-rdc.aliyuncs.com"
CONFIG_FILE = ".yunxiao.json"

# category 简写 -> 云效 category 标识
CATEGORIES = {"req": "Req", "task": "Task", "bug": "Bug", "risk": "Risk"}
CAT_NAMES = {"Req": "需求", "Task": "任务", "Bug": "缺陷", "Risk": "风险"}

PAT_URL = "https://help.aliyun.com/zh/yunxiao/user-guide/personal-access-token"


# ---------- 配置 ----------

def repo_root():
    """向上找 .yunxiao.json 或 .git 所在目录作为仓库根。"""
    d = os.getcwd()
    while d != os.path.dirname(d):
        if os.path.exists(os.path.join(d, CONFIG_FILE)) or os.path.exists(os.path.join(d, ".git")):
            return d
        d = os.path.dirname(d)
    return os.getcwd()


def load_config():
    path = os.path.join(repo_root(), CONFIG_FILE)
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_config(cfg):
    path = os.path.join(repo_root(), CONFIG_FILE)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"配置已写入 {path}")


def get_token():
    token = os.environ.get("YUNXIAO_TOKEN", "").strip()
    if not token:
        fail(
            "缺少云效个人访问令牌。请执行以下步骤：\n"
            f"  1. 在云效控制台创建 PAT（仅需「项目协作」相关权限点）：{PAT_URL}\n"
            "  2. 设置环境变量：export YUNXIAO_TOKEN=pt-xxxx（建议写入 ~/.zshrc）\n"
            "  3. 重新运行本命令。"
        )
    return token


def get_org_id(cfg):
    org = os.environ.get("YUNXIAO_ORGANIZATION_ID", "").strip() or cfg.get("organizationId", "")
    if not org:
        fail(
            "缺少 organizationId。可在云效访问链接中获取：\n"
            "  https://devops.aliyun.com/organization/<organizationId>\n"
            f"  写入仓库根目录 {CONFIG_FILE} 的 organizationId 字段，或设置环境变量 YUNXIAO_ORGANIZATION_ID。"
        )
    return org


def get_project_id(cfg):
    pid = cfg.get("projectId", "")
    if not pid:
        fail(f"缺少 projectId（云效项目 ID）。请运行 setup，或编辑 {CONFIG_FILE} 填入 projectId。")
    return pid


def get_workitem_type(cfg, category):
    types = cfg.get("workitemTypes", {})
    tid = types.get(category, "")
    if not tid:
        fail(
            f"category={category} 的工作项类型 id 未配置。请运行 setup 选择类型，\n"
            f"或编辑 {CONFIG_FILE} 的 workitemTypes.{category} 字段。"
        )
    return tid


def get_assignee(cfg, explicit):
    """指派人：命令行 --assignee 优先，否则用 .yunxiao.json 的 defaultAssignee。"""
    if explicit:
        return explicit
    assignee = cfg.get("defaultAssignee", "")
    if not assignee:
        fail(
            "创建工作项必须指定指派人。请：\n"
            f"  方式一：命令行加 --assignee=<userId>\n"
            f"  方式二：运行 setup 选择默认指派人，或编辑 {CONFIG_FILE} 加 defaultAssignee 字段"
        )
    return assignee


def workitem_url(org, pid, wid):
    return f"https://devops.aliyun.com/organization/{org}/projex/{pid}/{wid}"


# ---------- 本地 docs 双存储 ----------

def docs_dir(cfg):
    """docs 工作项目录，默认 docs/workitems，可在 .yunxiao.json 用 docsDir 改。"""
    return os.path.join(repo_root(), cfg.get("docsDir", "docs/workitems"))


def slugify_subject(subject, max_len=60):
    """清洗标题为文件名安全的片段。"""
    s = re.sub(r'[\\/:*?"<>|\s]+', "-", subject.strip())
    s = re.sub(r"-+", "-", s).strip("-")
    return (s[:max_len].rstrip("-")) or "untitled"


def doc_path_for(cfg, serial, subject):
    return os.path.join(docs_dir(cfg), f"{serial}-{slugify_subject(subject)}.md")


def find_doc_by_serial(cfg, serial):
    """按编号前缀找已存在的文档（标题可能变更导致文件名变化）。"""
    matches = glob.glob(os.path.join(docs_dir(cfg), f"{serial}-*.md"))
    return matches[0] if matches else None


def yaml_escape(v):
    """frontmatter 标量安全转义。"""
    s = str(v)
    if s == "" or re.search(r'[:#\n"\'\[\]{}>!&*?|%@`]', s):
        return json.dumps(s, ensure_ascii=False)
    return s


def render_doc(detail, cfg):
    """把 get 接口返回的完整工作项渲染成 Markdown 文档（frontmatter + 描述）。"""
    org = get_org_id(cfg)
    pid = get_project_id(cfg)
    serial = detail.get("serialNumber", "")
    subject = detail.get("subject", "")
    status = (detail.get("status") or {}).get("displayName") or (detail.get("status") or {}).get("name", "")
    assigned = (detail.get("assignedTo") or {}).get("name", "")
    creator = (detail.get("creator") or {}).get("name", "")
    wtype = (detail.get("workitemType") or {}).get("name", "")
    url = workitem_url(org, pid, detail.get("id", ""))
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    lines = [
        "---",
        f"serialNumber: {yaml_escape(serial)}",
        f"identifier: {yaml_escape(detail.get('id', ''))}",
        f"category: {yaml_escape(detail.get('categoryId', ''))}",
        f"workitemType: {yaml_escape(wtype)}",
        f"subject: {yaml_escape(subject)}",
        f"status: {yaml_escape(status)}",
        f"assignedTo: {yaml_escape(assigned)}",
        f"creator: {yaml_escape(creator)}",
        f"url: {yaml_escape(url)}",
        f"gmtCreate: {yaml_escape(detail.get('gmtCreate', ''))}",
        f"gmtModified: {yaml_escape(detail.get('gmtModified', ''))}",
        f"docSyncedAt: {yaml_escape(now)}",
    ]
    # 自定义字段（优先级、严重程度等）写入 frontmatter，便于检索
    for cf in detail.get("customFieldValues", []) or []:
        fname = cf.get("fieldName") or cf.get("fieldId", "")
        vals = [v.get("displayValue", "") for v in cf.get("values", []) if v.get("displayValue")]
        if vals:
            key = re.sub(r"\W+", "", fname) or cf.get("fieldId", "field")
            lines.append(f"{key}: {yaml_escape(','.join(vals))}")
    lines.append("---")
    lines.append("")
    lines.append(f"# {serial} {subject}")
    lines.append("")
    lines.append(f"> 状态由云效统一管理，本文档为描述副本（最后同步 {now}）。")
    lines.append(f"> 云效链接：{url}")
    lines.append("")
    lines.append("## 描述")
    lines.append("")
    lines.append(detail.get("description", "") or "（无描述）")
    lines.append("")
    return "\n".join(lines)


def parse_doc_file(path):
    """解析 skill 生成的 docs 工作项文档。

    返回 (identifier, description)：
    - identifier 取自 frontmatter（找不到为 None，此时调用方需用 --id 指定）
    - description 取「## 描述」之后的正文（去掉结尾托管行），找不到则用全文
    AI 可直接改写该文档的描述区，再用 update --doc 推回云效。
    """
    with open(path, encoding="utf-8") as f:
        text = f.read()

    identifier = None
    body = text
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            front = text[3:end]
            body = text[end + 4:]
            m = re.search(r"^identifier:\s*['\"]?([^'\"\n]+?)['\"]?\s*$", front, re.M)
            if m:
                identifier = m.group(1).strip()

    # 「## 描述」是文档最后一个章节，其后全部内容都是描述正文
    # （正文内部允许出现 ### / ## 子标题，不能按标题截断）
    m = re.search(r"^##\s*描述\s*$", body, re.M)
    if m:
        description = body[m.end():].strip()
    else:
        description = body.strip()
    return identifier, description


def write_doc(cfg, detail):
    """渲染并写入文档；若标题变更导致旧文件存在，先删旧文件。返回文档路径。"""
    d = docs_dir(cfg)
    os.makedirs(d, exist_ok=True)
    serial = detail.get("serialNumber", "")
    old = find_doc_by_serial(cfg, serial)
    path = doc_path_for(cfg, serial, detail.get("subject", ""))
    if old and os.path.abspath(old) != os.path.abspath(path):
        os.remove(old)
    with open(path, "w", encoding="utf-8") as f:
        f.write(render_doc(detail, cfg))
    return path


def get_type_fields(token, org, pid, type_id):
    """获取某工作项类型的字段配置（含必填项和选项 id）。"""
    resp, _ = api_call(
        "GET",
        f"/oapi/v1/projex/organizations/{org}/projects/{pid}/workitemTypes/{type_id}/fields",
        token,
    )
    return resp if isinstance(resp, list) else resp.get("fields") or resp.get("data") or []


def build_custom_field_values(token, org, pid, type_id, overrides):
    """按字段配置构造 customFieldValues，必填且未在 overrides 给值时取默认/第一个选项。

    overrides: {fieldId: optionId}，来自命令行 --field 或 .yunxiao.json defaults。
    """
    fields = get_type_fields(token, org, pid, type_id)
    values = dict(overrides)
    missing = []
    for f in fields:
        fid = f.get("id")
        if fid in ("subject", "description", "assignedTo"):
            continue  # 顶层字段，不走 customFieldValues
        if not f.get("required"):
            continue
        if fid in values:
            continue
        opts = f.get("options") or f.get("optionsList") or []
        if opts:
            # 优先 defaultValue 标记的选项，否则取第一个
            chosen = next((o for o in opts if o.get("isDefault") or o.get("defaultValue")), opts[0])
            values[fid] = chosen.get("id") or chosen.get("value")
        else:
            missing.append(f.get("name") or fid)
    if missing:
        fail(f"以下必填字段无可用默认选项，请用 --field 指定：{', '.join(missing)}")
    return values


# ---------- HTTP ----------

def api_call(method, path, token, params=None, body=None):
    """调用云效 OpenAPI（新版 oapi/v1）。返回 (json_obj, resp_headers)。"""
    url = API_BASE + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("x-yunxiao-token", token)
    req.add_header("Accept", "application/json")
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8", "ignore")
        try:
            return (json.loads(raw) if raw.strip() else {}), dict(resp.headers)
        except json.JSONDecodeError:
            fail(f"云效 API 返回了非 JSON 响应（HTTP 200）：{raw[:300]}")
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "ignore")[:500]
        except Exception:
            pass
        msg = f"云效 API 请求失败 HTTP {e.code}: {detail}"
        if e.code == 401:
            msg += "\n（401：token 无效或过期，请在云效控制台重新生成 PAT）"
        elif e.code == 403:
            msg += "\n（403：请检查 PAT 是否勾选「项目协作」权限点、是否属于该企业）"
        elif e.code == 404:
            msg += "\n（404：请检查 organizationId / projectId 是否正确）"
        fail(msg)
    except urllib.error.URLError as e:
        fail(f"无法连接云效 API（{e.reason}）。请检查网络。")


def fail(msg, code=1):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def workitem_brief(w, org="", pid=""):
    """从 get/search 返回的工作项对象提取关键字段。org/pid 用于拼 URL。"""
    assigned = w.get("assignedTo") or {}
    status = w.get("status") or {}
    space = w.get("space") or {}
    return {
        "serialNumber": w.get("serialNumber", ""),
        "identifier": w.get("id", ""),
        "subject": w.get("subject", ""),
        "status": status.get("displayName") or status.get("name", ""),
        "assignedTo": assigned.get("name", ""),
        "url": workitem_url(org, pid or space.get("id", ""), w.get("id", "")),
    }


# ---------- 子命令 ----------

def cmd_setup(args):
    """交互式初始化：orgId + projectId + 三类工作项类型，写 .yunxiao.json。"""
    token = get_token()

    org = os.environ.get("YUNXIAO_ORGANIZATION_ID", "").strip()
    if not org:
        org = input("请输入 organizationId（见 https://devops.aliyun.com/organization/<id>）: ").strip()
        if not org:
            fail("未输入 organizationId，退出。")

    pid = input("请输入 projectId（云效项目 ID，项目设置页或项目链接中可获取）: ").strip()
    if not pid:
        fail("未输入 projectId，退出。")

    type_map = {}
    for short, cat in (("req", "Req"), ("task", "Task"), ("bug", "Bug")):
        resp, _ = api_call(
            "GET",
            f"/oapi/v1/projex/organizations/{org}/projects/{pid}/workitemTypes",
            token,
            params={"category": cat},
        )
        items = resp if isinstance(resp, list) else resp.get("workitemTypes") or resp.get("data") or []
        enabled = [t for t in items if t.get("enable", True)]
        if not enabled:
            print(f"警告: category={cat} 没有可用的工作项类型，跳过。")
            continue
        print(f"\n[{CAT_NAMES[cat]}] 请选择要用于创建的类型：")
        for i, t in enumerate(enabled):
            mark = "（默认）" if t.get("defaultType") else ""
            print(f"  {i + 1}. {t['name']}  id={t['id']}{mark}")
        choice = input(f"选择编号 [1-{len(enabled)}，回车选默认/第一个]: ").strip()
        if choice:
            idx = int(choice) - 1
            if idx < 0 or idx >= len(enabled):
                fail("无效选择，退出。")
        else:
            idx = 0
        type_map[short] = enabled[idx]["id"]

    # 默认指派人：拉项目成员列表选择（需要「项目成员-只读」权限点）
    default_assignee = ""
    try:
        resp, _ = api_call(
            "GET",
            f"/oapi/v1/projex/organizations/{org}/projects/{pid}/members",
            token,
        )
        members = resp if isinstance(resp, list) else resp.get("members") or resp.get("data") or []
        if members:
            def member_id(m):
                # 兼容两种返回：扁平 {userId,userName} 或嵌套 {user:{id,name}}
                return m.get("userId") or (m.get("user") or {}).get("id", "")

            def member_name(m):
                return m.get("userName") or (m.get("user") or {}).get("name", "?")

            print("\n[默认指派人] 请选择 create 时未显式指定 --assignee 的默认负责人：")
            for i, m in enumerate(members[:50]):
                print(f"  {i + 1}. {member_name(m)}  id={member_id(m)}")
            choice = input(f"选择编号 [1-{min(len(members), 50)}，回车跳过]: ").strip()
            if choice:
                mi = int(choice) - 1
                default_assignee = member_id(members[mi])
    except SystemExit:
        raise
    except Exception as e:
        print(f"警告: 拉取项目成员失败（{e}）。可后续在 {CONFIG_FILE} 手工填 defaultAssignee。")

    cfg_out = {
        "organizationId": org,
        "projectId": pid,
        "workitemTypes": type_map,
    }
    if default_assignee:
        cfg_out["defaultAssignee"] = default_assignee
    save_config(cfg_out)

    # 验证：搜索一页工作项确认 token/权限可用
    resp, _ = api_call(
        "POST",
        f"/oapi/v1/projex/organizations/{org}/workitems:search",
        token,
        body={"category": "Task", "spaceId": pid, "page": 1, "perPage": 1},
    )
    items = resp if isinstance(resp, list) else []
    print(f"验证通过：token 有效，项目可访问（搜索接口正常，本页返回 {len(items)} 条）。")
    print("请确认 YUNXIAO_TOKEN 已在环境中设置，然后即可使用 create/get/list。")


def cmd_create(args):
    """创建工作项 → 返回服务端分配的 serialNumber。"""
    token = get_token()
    cfg = load_config()
    org = get_org_id(cfg)
    pid = get_project_id(cfg)
    type_id = get_workitem_type(cfg, args.category)

    body = {
        "subject": args.subject,
        "description": args.desc or "",
        "formatType": "MARKDOWN",
        "spaceId": pid,
        "workitemTypeId": type_id,
        "assignedTo": get_assignee(cfg, args.assignee),
    }
    if args.parent:
        body["parentId"] = args.parent

    # 自定义字段：命令行 --field 覆盖配置文件 defaults，其余必填项自动取默认选项
    overrides = dict(cfg.get("fieldDefaults", {}).get(args.category, {}))
    for kv in args.field or []:
        if "=" not in kv:
            fail(f"--field 格式应为 fieldId=optionId，收到：{kv}")
        k, v = kv.split("=", 1)
        overrides[k.strip()] = v.strip()
    custom = build_custom_field_values(token, org, pid, type_id, overrides)
    if custom:
        body["customFieldValues"] = custom

    resp, _ = api_call("POST", f"/oapi/v1/projex/organizations/{org}/workitems", token, body=body)
    wid = resp.get("id") or resp.get("workitemId") or ""
    if not wid:
        fail(f"创建返回缺少工作项 id：{json.dumps(resp, ensure_ascii=False)[:300]}")

    # create 只返回 id，需要 get 一次拿 serialNumber
    detail, _ = api_call("GET", f"/oapi/v1/projex/organizations/{org}/workitems/{wid}", token)
    out = workitem_brief(detail, org, pid)
    out["url"] = workitem_url(org, pid, wid)
    if not args.no_doc:
        out["doc"] = os.path.relpath(write_doc(cfg, detail), repo_root())
    print(json.dumps(out, ensure_ascii=False, indent=2 if args.pretty else None))


def cmd_get(args):
    """按 identifier 查询单个工作项，或按 serialNumber 遍历搜索匹配。"""
    token = get_token()
    cfg = load_config()
    org = get_org_id(cfg)

    pid = get_project_id(cfg)
    if args.id:
        detail, _ = api_call("GET", f"/oapi/v1/projex/organizations/{org}/workitems/{args.id}", token)
        print(json.dumps(detail if args.full else workitem_brief(detail, org, pid),
                         ensure_ascii=False, indent=2 if args.pretty else None))
        return

    if not args.serial:
        fail("必须提供 --serial=ABCD-1 或 --id=<identifier>。")

    target = _search_by_serial(token, org, pid, args.serial, args.category)
    if not target:
        fail(f"未找到编号为 {args.serial} 的工作项（category={args.category}）。")
    print(json.dumps(target, ensure_ascii=False, indent=2 if args.pretty else None))


def _search_by_serial(token, org, pid, serial, category_short, page=1, pages=10):
    """通过 search 接口翻页查找指定 serialNumber 的工作项。"""
    for p in range(page, page + pages):
        resp, _ = api_call(
            "POST",
            f"/oapi/v1/projex/organizations/{org}/workitems:search",
            token,
            body={"category": CATEGORIES[category_short], "spaceId": pid,
                  "page": p, "perPage": 100},
        )
        items = resp if isinstance(resp, list) else []
        for w in items:
            if w.get("serialNumber", "").lower() == serial.lower():
                return workitem_brief(w, org, pid)
        if len(items) < 100:
            break
    return None


def cmd_delete(args):
    """删除工作项（按 identifier，可先用 list/get 查到）；联动删除本地文档。"""
    token = get_token()
    cfg = load_config()
    org = get_org_id(cfg)
    # 删除前先取 serialNumber，用于清理同名本地文档
    serial = ""
    try:
        detail, _ = api_call("GET", f"/oapi/v1/projex/organizations/{org}/workitems/{args.id}", token)
        serial = detail.get("serialNumber", "")
    except SystemExit:
        raise
    except Exception:
        pass
    try:
        api_call("DELETE", f"/oapi/v1/projex/organizations/{org}/workitems/{args.id}", token)
    except SystemExit:
        raise
    removed_doc = ""
    if serial:
        doc = find_doc_by_serial(cfg, serial)
        if doc:
            os.remove(doc)
            removed_doc = os.path.relpath(doc, repo_root())
    print(json.dumps({"deleted": True, "identifier": args.id,
                      "removedDoc": removed_doc}, ensure_ascii=False))


def cmd_workflow(args):
    """列出某类工作项的可用状态（名称 + id），供 update --status 选择。"""
    token = get_token()
    cfg = load_config()
    org = get_org_id(cfg)
    pid = get_project_id(cfg)
    type_id = get_workitem_type(cfg, args.category)
    resp, _ = api_call(
        "GET",
        f"/oapi/v1/projex/organizations/{org}/projects/{pid}/workitemTypes/{type_id}/workflows",
        token,
    )
    statuses = resp.get("statuses", [])
    out = [
        {"statusId": s.get("id"), "name": s.get("displayName") or s.get("name"),
         "nameEn": s.get("nameEn", ""), "isDefault": s.get("id") == resp.get("defaultStatusId")}
        for s in statuses
    ]
    print(json.dumps(out, ensure_ascii=False, indent=2 if args.pretty else None))


def cmd_update(args):
    """更新工作项：标题/描述/状态（按 identifier）。至少传一个更新项。"""
    # 三个描述来源互斥，先于文件读取校验，避免读了文件才报参数错
    desc_sources = bool(args.desc is not None) + bool(args.desc_file) + bool(args.doc)
    if desc_sources > 1:
        fail("--desc / --desc-file / --doc 三者互斥，描述只取一个来源。")

    # --doc：直接吃 docs 工作项文档，自动解析 identifier 与「## 描述」正文
    doc_identifier = None
    desc_from_file = None
    if getattr(args, "doc", None):
        if not os.path.exists(args.doc):
            fail(f"文档不存在：{args.doc}")
        doc_identifier, desc_from_file = parse_doc_file(args.doc)
        if not desc_from_file:
            fail(f"未能从 {args.doc} 解析出描述内容（需要「## 描述」章节或正文）。")
    elif getattr(args, "desc_file", None):
        if not os.path.exists(args.desc_file):
            fail(f"描述文件不存在：{args.desc_file}")
        with open(args.desc_file, encoding="utf-8") as f:
            desc_from_file = f.read().strip()

    if not args.id and doc_identifier:
        args.id = doc_identifier
    if not args.id:
        fail("缺少工作项 identifier：用 --id=<identifier> 指定，或 --doc 传入含 identifier 的 docs 文档。")

    if not (args.subject or args.desc is not None or desc_from_file is not None
            or args.status or args.field):
        fail("至少指定一个更新项：--subject / --desc / --desc-file / --doc / --status / --field。")

    token = get_token()
    cfg = load_config()
    org = get_org_id(cfg)

    body = {}
    if args.subject:
        body["subject"] = args.subject
    if args.desc is not None:
        body["description"] = args.desc
        body["formatType"] = "MARKDOWN"
    elif desc_from_file is not None:
        body["description"] = desc_from_file
        body["formatType"] = "MARKDOWN"
    if args.status:
        # --status 可传状态 id（如 100010）或状态名（如 处理中），名称自动解析为 id
        if not args.status.isdigit():
            body["status"] = resolve_status_id(token, cfg, args.status)
        else:
            body["status"] = args.status
    if args.field:
        overrides = {}
        for kv in args.field:
            if "=" not in kv:
                fail(f"--field 格式应为 fieldId=optionId，收到：{kv}")
            k, v = kv.split("=", 1)
            overrides[k.strip()] = v.strip()
        body["customFieldValues"] = overrides

    api_call("PUT", f"/oapi/v1/projex/organizations/{org}/workitems/{args.id}", token, body=body)
    # 回读确认
    detail, _ = api_call("GET", f"/oapi/v1/projex/organizations/{org}/workitems/{args.id}", token)
    out = workitem_brief(detail, org, cfg.get("projectId", ""))
    out["updated"] = True
    if not args.no_doc:
        out["doc"] = os.path.relpath(write_doc(cfg, detail), repo_root())
    print(json.dumps(out, ensure_ascii=False, indent=2 if args.pretty else None))


def cmd_sync(args):
    """全量回拉云效工作项，刷新本地 docs 文档；可选清理云效已删除的孤儿文档。"""
    token = get_token()
    cfg = load_config()
    org = get_org_id(cfg)
    pid = get_project_id(cfg)

    cats = [args.category] if args.category else ["req", "task", "bug", "risk"]
    written, seen_serials = [], set()
    for short in cats:
        if short not in cfg.get("workitemTypes", {}):
            continue
        page = 1
        while True:
            resp, _ = api_call(
                "POST",
                f"/oapi/v1/projex/organizations/{org}/workitems:search",
                token,
                body={"category": CATEGORIES[short], "spaceId": pid,
                      "page": page, "perPage": 200},
            )
            items = resp if isinstance(resp, list) else []
            if not items:
                break
            for w in items:
                serial = w.get("serialNumber", "")
                if not serial or serial in seen_serials:
                    continue
                seen_serials.add(serial)
                # search 返回是摘要，get 一次拿完整描述和自定义字段
                detail, _ = api_call(
                    "GET", f"/oapi/v1/projex/organizations/{org}/workitems/{w['id']}", token
                )
                path = write_doc(cfg, detail)
                written.append(os.path.relpath(path, repo_root()))
            if len(items) < 200:
                break
            page += 1

    removed = []
    if args.prune:
        for f in glob.glob(os.path.join(docs_dir(cfg), "*.md")):
            m = re.match(r"([A-Z]+-\d+)-", os.path.basename(f))
            if m and m.group(1) not in seen_serials:
                os.remove(f)
                removed.append(os.path.relpath(f, repo_root()))

    print(json.dumps({"synced": len(written), "docs": written,
                      "pruned": removed}, ensure_ascii=False,
                     indent=2 if args.pretty else None))


def resolve_status_id(token, cfg, status_name):
    """按状态显示名在当前类别的工作流里解析出状态 id。"""
    org = get_org_id(cfg)
    pid = get_project_id(cfg)
    # update 命令的 args.category 在调用处保证；这里遍历已配置的三个类型找匹配
    for short in ("bug", "task", "req"):
        type_id = cfg.get("workitemTypes", {}).get(short)
        if not type_id:
            continue
        resp, _ = api_call(
            "GET",
            f"/oapi/v1/projex/organizations/{org}/projects/{pid}/workitemTypes/{type_id}/workflows",
            token,
        )
        for s in resp.get("statuses", []):
            if (s.get("displayName") or s.get("name")) == status_name:
                return s.get("id")
    fail(f"未找到名为「{status_name}」的状态，可先运行 workflow 命令查看可用状态。")


def cmd_list(args):
    """查询工作项列表（创建前查重）。"""
    token = get_token()
    cfg = load_config()
    org = get_org_id(cfg)
    pid = get_project_id(cfg)

    body = {
        "category": CATEGORIES[args.category],
        "spaceId": pid,
        "page": args.page,
        "perPage": min(args.max, 200),
    }
    if args.subject_contains:
        body["conditions"] = json.dumps({
            "conditionGroups": [[
                {"fieldIdentifier": "subject", "operator": "CONTAINS",
                 "value": [args.subject_contains], "toValue": None,
                 "className": "string", "format": "input"}
            ]]
        }, ensure_ascii=False)

    resp, _ = api_call("POST", f"/oapi/v1/projex/organizations/{org}/workitems:search", token, body=body)
    items = resp if isinstance(resp, list) else []
    out = [workitem_brief(w, org, pid) for w in items]
    print(json.dumps(out, ensure_ascii=False, indent=2 if args.pretty else None))


def main():
    p = argparse.ArgumentParser(description="云效工作项编号申报工具")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add_pretty(sp):
        sp.add_argument("--pretty", action="store_true", help="格式化 JSON 输出")

    sp = sub.add_parser("setup", help="初始化配置（交互式）")
    sp.set_defaults(func=cmd_setup)

    c = sub.add_parser("create", help="创建工作项，返回 serialNumber")
    c.add_argument("--category", required=True, choices=["req", "task", "bug", "risk"])
    c.add_argument("--subject", required=True, help="工作项标题")
    c.add_argument("--desc", default="", help="描述（Markdown）")
    c.add_argument("--assignee", default="", help="负责人 userId（云效账号 id）")
    c.add_argument("--parent", default="", help="父工作项 id")
    c.add_argument("--field", action="append",
                   help="自定义字段覆盖，格式 fieldId=optionId，可多次使用；未指定的必填项自动取默认选项")
    c.add_argument("--no-doc", action="store_true", help="只在云效创建，不生成本地 docs 文档")
    add_pretty(c)
    c.set_defaults(func=cmd_create)

    g = sub.add_parser("get", help="查询单个工作项")
    g.add_argument("--serial", default="", help="编号如 ABCD-1（走搜索遍历）")
    g.add_argument("--id", default="", help="工作项 identifier（精确查询）")
    g.add_argument("--category", default="bug", choices=["req", "task", "bug", "risk"],
                   help="按 serial 查询时的遍历类别")
    g.add_argument("--full", action="store_true", help="输出完整原始 JSON")
    add_pretty(g)
    g.set_defaults(func=cmd_get)

    l = sub.add_parser("list", help="查询工作项列表（查重）")
    l.add_argument("--category", default="bug", choices=["req", "task", "bug", "risk"])
    l.add_argument("--subject-contains", default="", help="按标题关键字过滤（服务端 CONTAINS）")
    l.add_argument("--page", type=int, default=1, help="页码，默认 1")
    l.add_argument("--max", type=int, default=50, help="每页条数（0-200）")
    add_pretty(l)
    l.set_defaults(func=cmd_list)

    d = sub.add_parser("delete", help="删除工作项（按 identifier，操作不可恢复）")
    d.add_argument("--id", required=True, help="工作项 identifier（不是 serialNumber）")
    d.set_defaults(func=cmd_delete)

    w = sub.add_parser("workflow", help="列出某类工作项的可用状态（名称 + id）")
    w.add_argument("--category", default="bug", choices=["req", "task", "bug", "risk"])
    add_pretty(w)
    w.set_defaults(func=cmd_workflow)

    u = sub.add_parser("update", help="更新工作项：标题/描述/状态/自定义字段")
    u.add_argument("--id", default="", help="工作项 identifier（用 --doc 时可省略，自动从 frontmatter 解析）")
    u.add_argument("--subject", default="", help="新标题")
    u.add_argument("--desc", default=None, help="新描述（Markdown）")
    u.add_argument("--desc-file", default="", help="从任意 Markdown 文件读描述全文")
    u.add_argument("--doc", default="",
                   help="直接传 docs/workitems 下的工作项文档：自动解析 identifier 并提取「## 描述」正文推回云效")
    u.add_argument("--status", default="", help="新状态：状态 id（如 100010）或状态名（如 处理中）")
    u.add_argument("--field", action="append", help="自定义字段覆盖 fieldId=optionId，可多次使用")
    u.add_argument("--no-doc", action="store_true", help="只更新云效，不刷新本地 docs 文档")
    add_pretty(u)
    u.set_defaults(func=cmd_update)

    sy = sub.add_parser("sync", help="全量回拉云效工作项，刷新本地 docs 文档")
    sy.add_argument("--category", default=None, choices=["req", "task", "bug", "risk"],
                    help="只同步指定类别，默认全部")
    sy.add_argument("--prune", action="store_true",
                    help="删除云效已不存在的本地孤儿文档（默认不删）")
    add_pretty(sy)
    sy.set_defaults(func=cmd_sync)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
