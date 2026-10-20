#!/usr/bin/env python3
"""检查暂存文件中的常见凭据以及项目类型检查，不输出匹配内容；改到产品文件时提醒三道门。

加 --流程 只自查三道门，不需要 Git 仓库。提醒不阻止提交。"""
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

SECRET = re.compile(rb"sk-(?:ant-|proj-)[A-Za-z0-9_-]{8,}|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|xox[bpsa]-[A-Za-z0-9-]{10,}|AIza[0-9A-Za-z_-]{30,}|-----BEGIN [A-Z ]*PRIVATE KEY-----|(?:api[_-]?key|secret|token|password)[^A-Za-z0-9_\r\n]{1,6}[A-Za-z0-9_-]{24,}", re.I)


PACKAGE = Path(__file__).resolve().parents[1]
# 不算产品文件：三份正式文档、交接、派工、设计稿、探路，以及本框架自己的文件。
NOT_PRODUCT_FILES = {"AGENTS.md", "CLAUDE.md", "产品需求文档.md", "设计规范.md", "开发计划.md", "项目交接.md",
                     "使用说明.md", "版本.json", ".gitignore", "测试/框架回归.py"}
NOT_PRODUCT_DIRS = {".agents", ".claude", ".codex", "维护源", "工具", "说明", "派工", "设计", "探路"}
LOOP_LINE = re.compile(r"^\s*[-*]\s*开发循环\s*[:：]\s*(.*)$")
SELF_EXEMPT = re.compile(r"未涉及|不适用|不需要|无需|免问|跳过|\bN/A\b", re.I)
USER_ANSWER = re.compile(r"原话|用户授权 Agent 决定|宿主(?:派不了|不能派)")


def is_product_file(path):
    """path 是绝对路径；只认包根目录以内的文件。"""
    try:
        rel = path.resolve().relative_to(PACKAGE)
    except ValueError:
        return False
    return bool(rel.parts) and rel.as_posix() not in NOT_PRODUCT_FILES and rel.parts[0] not in NOT_PRODUCT_DIRS and rel.name != ".DS_Store"


def loop_value(path):
    if not path.is_file():
        return None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = LOOP_LINE.match(line)
        if match:
            return match.group(1).strip()
    return None


def self_exempt(value):
    # 有豁免字眼却没有用户原话、授权或宿主派不了的事实，像是 Agent 自己填的。
    return bool(value) and SELF_EXEMPT.search(value) is not None and USER_ANSWER.search(value) is None


def flow_gaps(root):
    """按 AGENTS.md [动手改产品之前 · 三道门] 找缺口；只看文件在不在、开发循环一行填得像不像用户的回答。"""
    gaps = []
    if not (root / "产品需求文档.md").is_file():
        gaps.append("第一道门：还没有产品需求文档，改动没登记进需求清单（按 sky-grill 补）。")
    if not (root / "开发计划.md").is_file():
        gaps.append("第二道门：还没有开发计划，这批改动没有阶段和验收条件（按 sky-plan 补）。")
        gaps.append("第三道门：开发计划里没有“开发循环”一行，还没问用户开不开。")
    else:
        value = loop_value(root / "开发计划.md")
        if not value or "{{" in value:
            gaps.append("第三道门：开发计划里“开发循环”一行还没填，先问用户开不开。")
        elif self_exempt(value):
            gaps.append("第三道门：开发计划里“开发循环”一行像是 Agent 自己填的豁免，没有用户原话；去问用户。")
        elif "用户" not in value and not USER_ANSWER.search(value):
            gaps.append("第三道门：开发计划里“开发循环”一行没写用户的回答（原话和日期）；去问用户。")
    if self_exempt(loop_value(root / "项目交接.md")):
        gaps.append("第三道门：项目交接里“开发循环”一行像是 Agent 自己填的豁免；改成用户的回答，或写“还没问”。")
    return gaps


def run(args, cwd):
    return subprocess.run(args, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def flow_only():
    gaps = flow_gaps(PACKAGE)
    if gaps:
        print("三道门还有缺口（见 AGENTS.md [动手改产品之前 · 三道门]）：\n" + "\n".join(gaps))
        return 1
    print("三道门的文件都在，开发循环一行已填。需求清单里有没有这次改动的行，仍要你自己核对。")
    return 0


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    if sys.argv[1:] == ["--流程"]:
        return flow_only()
    result = run(["git", "rev-parse", "--show-toplevel"], Path.cwd())
    if result.returncode:
        print("检查未执行：当前不在 Git 仓库中。", file=sys.stderr)
        return 2
    root = Path(result.stdout.decode().strip())
    names = run(["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z"], root)
    if names.returncode:
        print("无法读取暂存区，检查失败。", file=sys.stderr)
        return 2
    deleted = run(["git", "diff", "--cached", "--name-only", "--diff-filter=D", "-z"], root)
    product_touched = any(is_product_file(root / raw.decode("utf-8", errors="surrogateescape"))
                          for raw in deleted.stdout.split(b"\0") if raw) if deleted.returncode == 0 else False
    blocked = False
    for raw in names.stdout.split(b"\0"):
        if not raw:
            continue
        name = raw.decode("utf-8", errors="surrogateescape")
        product_touched = product_touched or is_product_file(root / name)
        base = Path(name).name
        if (base == ".env" or base.startswith(".env.")) and base not in (".env.example", ".env.sample", ".env.template"):
            print("禁止提交环境凭据文件：" + ascii(name), file=sys.stderr)
            blocked = True
            continue
        content = run(["git", "show", ":" + name], root)
        if content.returncode:
            print("无法读取暂存文件：" + ascii(name), file=sys.stderr)
            blocked = True
            continue
        hit = SECRET.search(content.stdout)
        if hit:
            line = content.stdout[:hit.start()].count(b"\n") + 1
            print(f"疑似凭据：{ascii(name)}，第 {line} 行（内容已隐藏）。", file=sys.stderr)
            blocked = True
    if blocked:
        return 2
    # Check each package up to three levels, avoiding dependency/build/metadata folders.
    ignored = {"node_modules", ".git", ".harness", ".agents", ".claude", ".codex", "维护源", "dist", "build", ".venv", "vendor"}
    packages = []
    def visit(folder, depth):
        if (folder / "package.json").is_file():
            packages.append(folder / "package.json")
        if depth:
            for child in sorted(folder.iterdir()):
                if child.is_dir() and not child.is_symlink() and child.name not in ignored:
                    visit(child, depth - 1)
    visit(root, 3)
    count = 0
    for package in packages:
        try:
            data = json.loads(package.read_text())
        except (ValueError, UnicodeError):
            print("package.json 无法解析：" + ascii(str(package.relative_to(root))), file=sys.stderr)
            return 2
        if "typecheck" not in data.get("scripts", {}):
            continue
        manager = "pnpm" if (package.parent / "pnpm-lock.yaml").exists() else "yarn" if (package.parent / "yarn.lock").exists() else "npm"
        if not shutil.which(manager):
            print(f"缺少 {manager}，类型检查未执行。", file=sys.stderr)
            return 2
        try:
            check = subprocess.run([manager, "run", "typecheck"], cwd=package.parent, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
        except subprocess.TimeoutExpired:
            print("类型检查超时，提交已阻止。", file=sys.stderr)
            return 2
        if check.returncode:
            print("类型检查失败：" + ascii(str(package.relative_to(root))) + "。请单独运行检查定位；此处不回显可能含敏感信息的日志。", file=sys.stderr)
            return 2
        count += 1
    gaps = flow_gaps(PACKAGE) if product_touched else []
    if gaps:
        print("提醒（不阻止提交）：这次提交改到了产品文件，但三道门还有缺口，见 AGENTS.md [动手改产品之前 · 三道门]：\n" + "\n".join(gaps), file=sys.stderr)
    print(f"暂存凭据扫描通过；运行了 {count} 个 typecheck 脚本。" + ("未发现 typecheck 脚本，不代表项目已通过类型检查。" if not count else ""))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, subprocess.SubprocessError) as error:
        print("提交检查无法完成：" + type(error).__name__ + "（详细内容隐藏）。", file=sys.stderr)
        sys.exit(2)
