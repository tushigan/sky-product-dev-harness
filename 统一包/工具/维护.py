#!/usr/bin/env python3
"""生成双宿主入口、检查一致性、非覆盖式安装 Git 检查。仅依赖标准库。"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def migration_errors():
    """报告会与共同入口竞争的配置；只检查，不删除、不回显配置内容。"""
    errors = []
    for rel in (".claude/CLAUDE.md", ".codex/AGENTS.md", ".codex/hooks.json",
                ".claude/hooks", ".codex/hooks", ".codex/evolution", ".codex/EVOLUTION.md"):
        if (ROOT / rel).exists() or (ROOT / rel).is_symlink():
            errors.append("旧框架入口或hook待处理：" + rel + "；先备份到项目外，再核实迁移")
    for rel in (".claude/settings.json", ".claude/settings.local.json"):
        path = ROOT / rel
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text())
        except (ValueError, OSError):
            errors.append("配置无法解析：" + rel)
            continue
        if not isinstance(data, dict):
            errors.append("配置不是JSON对象：" + rel)
        elif data.get("hooks"):
            errors.append("宿主hook待人工核实：" + rel + "；共同提交检查不能代替旧配置迁移")
    return errors


def expected():
    files = {"AGENTS.md": (ROOT / "维护源/共同规则.md").read_bytes(),
             "CLAUDE.md": b"# SKY Harness\n\n@AGENTS.md\n"}
    for f in (ROOT / "维护源/技能").rglob("*"):
        if f.is_file() and f.name != ".DS_Store" and "__pycache__" not in f.parts:
            rel = f.relative_to(ROOT / "维护源/技能").as_posix()
            for host in (".agents", ".claude"):
                files[f"{host}/skills/{rel}"] = f.read_bytes()
    for f in (ROOT / "维护源/帮手").glob("*.md"):
        content = f.read_text()
        _, front, body = content.split("---", 2)
        fields = dict(line.split(":", 1) for line in front.strip().splitlines())
        name = fields["name"].strip()
        description = fields["description"].strip()
        # JSON basic strings are compatible with TOML basic strings here.
        toml = "\n".join(f"{k} = {json.dumps(v, ensure_ascii=False)}" for k, v in {
            "name": name, "description": description,
            "sandbox_mode": "read-only", "developer_instructions": body.strip()
        }.items()) + "\n"
        files[f".codex/agents/{name}.toml"] = toml.encode()
        files[f".claude/agents/{name}.md"] = content.encode()
    return files


def git(*args):
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True)


def install_hook():
    top = git("rev-parse", "--show-toplevel")
    if top.returncode or Path(top.stdout.strip()).resolve() != ROOT:
        print("尚未在本包根目录建立仓库；请在建好仓库后重试。未修改任何 Git 设置。")
        return 2
    custom = git("config", "--get", "core.hooksPath")
    if custom.returncode == 0:
        print("已有 core.hooksPath，已保留。请每次提交前运行 python3 工具/提交检查.py；如需接入现有 hook，先检查原内容再合并。")
        return 2
    location = git("rev-parse", "--git-path", "hooks/pre-commit")
    if location.returncode:
        print("无法定位 Git hook，未安装。")
        return 2
    target = Path(location.stdout.strip())
    if not target.is_absolute():
        target = ROOT / target
    body = '#!/bin/sh\n# SKY Harness shared pre-commit\nexec python3 "$(git rev-parse --show-toplevel)/工具/提交检查.py"\n'
    if target.is_symlink() or (target.exists() and target.read_text() != body):
        print("已有其他 pre-commit，已保留。请每次提交前运行 python3 工具/提交检查.py；不要覆盖原 hook。")
        return 2
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body)
    target.chmod(target.stat().st_mode | 0o111)
    print("已安装或确认共同 Git 提交检查。此设置仅属于当前仓库。")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["sync", "check", "install-hook"])
    args = parser.parse_args()
    if args.action == "install-hook":
        return install_hook()
    problems = migration_errors()
    if problems:
        print("迁入检查未通过：\n" + "\n".join(problems))
        return 1
    files = expected()
    if args.action == "sync":
        # Only overwrite known generated files; refuse files changed outside the source.
        manifest = ROOT / "维护源/生成清单.json"
        previous = json.loads(manifest.read_text()) if manifest.exists() else {}
        import hashlib
        conflicts = [rel for rel, data in files.items() if (ROOT / rel).exists()
                     and (ROOT / rel).read_bytes() != data
                     and hashlib.sha256((ROOT / rel).read_bytes()).hexdigest() != previous.get(rel)]
        if conflicts:
            print("生成文件被单独修改，请先合并到维护源，不覆盖：\n" + "\n".join(conflicts))
            return 2
        for rel, data in files.items():
            path = ROOT / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        manifest.write_text(json.dumps({rel: hashlib.sha256(data).hexdigest() for rel, data in files.items()}, ensure_ascii=False, indent=2) + "\n")
        print(f"已生成 {len(files)} 个文件。")
    errors = [rel for rel, data in files.items() if not (ROOT / rel).is_file() or (ROOT / rel).read_bytes() != data]
    try:
        version = json.loads((ROOT / "版本.json").read_text())["版本"]
        for rel in ("AGENTS.md", "使用说明.md"):
            if version not in (ROOT / rel).read_text().splitlines()[0]:
                errors.append("版本标题不一致：" + rel)
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        errors.append("版本.json或版本标题无法读取")
    for folder in (".agents/skills", ".claude/skills", ".codex/agents", ".claude/agents"):
        for f in (ROOT / folder).rglob("*"):
            if f.is_file() and f.name != ".DS_Store" and f.relative_to(ROOT).as_posix() not in files:
                errors.append("未登记文件：" + f.relative_to(ROOT).as_posix())
    if errors:
        print("不一致或遗漏：\n" + "\n".join(errors))
        return 1
    print(f"检查通过：{len(files)} 个生成文件与共同源一致；两边各 6 个技能、2 个帮手。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
