"""验证运行代码持续保留完整的中文文档注释。"""

from __future__ import annotations

import ast
import re
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATTERNS = ("src/agentguard/*.py", "scripts/*.py")
CHINESE_TEXT = re.compile(r"[\u4e00-\u9fff]")


def _runtime_files() -> list[Path]:
    """收集需要检查的运行代码；参数：无；返回：按路径排序的 Python 文件列表。"""
    files: set[Path] = set()
    for pattern in SOURCE_PATTERNS:
        files.update(REPOSITORY_ROOT.glob(pattern))
    return sorted(files)


def _documented_nodes(path: Path) -> list[tuple[str, ast.AST]]:
    """提取模块、类及函数节点；参数：path Python 文件；返回：节点名称与节点列表。"""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    nodes: list[tuple[str, ast.AST]] = [("模块", tree)]
    for node in ast.walk(tree):
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            nodes.append((node.name, node))
    return nodes


def test_runtime_code_has_chinese_documentation() -> None:
    """确保每个模块、类和方法都有中文说明；参数：无；返回：无，缺失时测试失败。"""
    missing: list[str] = []
    for path in _runtime_files():
        relative_path = path.relative_to(REPOSITORY_ROOT)
        for name, node in _documented_nodes(path):
            documentation = ast.get_docstring(node)
            if not documentation or not CHINESE_TEXT.search(documentation):
                line = getattr(node, "lineno", 1)
                missing.append(f"{relative_path}:{line}:{name}")
    assert not missing, "缺少中文文档注释：\n" + "\n".join(missing)


def test_function_documentation_explains_parameters() -> None:
    """确保每个函数说明包含参数部分；参数：无；返回：无，缺失时测试失败。"""
    missing: list[str] = []
    for path in _runtime_files():
        relative_path = path.relative_to(REPOSITORY_ROOT)
        for name, node in _documented_nodes(path):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            documentation = ast.get_docstring(node) or ""
            if "参数" not in documentation:
                missing.append(f"{relative_path}:{node.lineno}:{name}")
    assert not missing, "函数说明缺少参数信息：\n" + "\n".join(missing)
