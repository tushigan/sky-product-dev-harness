#!/usr/bin/env python3
"""检查暂存文件中的常见凭据以及项目类型检查，不输出匹配内容。"""
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

SECRET = re.compile(rb"sk-(?:ant-|proj-)[A-Za-z0-9_-]{8,}|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|xox[bpsa]-[A-Za-z0-9-]{10,}|AIza[0-9A-Za-z_-]{30,}|-----BEGIN [A-Z ]*PRIVATE KEY-----|(?:api[_-]?key|secret|token|password)[^A-Za-z0-9_\r\n]{1,6}[A-Za-z0-9_-]{24,}", re.I)


def run(args, cwd):
    return subprocess.run(args, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def main():
    result = run(["git", "rev-parse", "--show-toplevel"], Path.cwd())
    if result.returncode:
        print("检查未执行：当前不在 Git 仓库中。", file=sys.stderr)
        return 2
    root = Path(result.stdout.decode().strip())
    names = run(["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z"], root)
    if names.returncode:
        print("无法读取暂存区，检查失败。", file=sys.stderr)
        return 2
    blocked = False
    for raw in names.stdout.split(b"\0"):
        if not raw:
            continue
        name = raw.decode("utf-8", errors="surrogateescape")
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
    print(f"暂存凭据扫描通过；运行了 {count} 个 typecheck 脚本。" + ("未发现 typecheck 脚本，不代表项目已通过类型检查。" if not count else ""))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, subprocess.SubprocessError) as error:
        print("提交检查无法完成：" + type(error).__name__ + "（详细内容隐藏）。", file=sys.stderr)
        sys.exit(2)
