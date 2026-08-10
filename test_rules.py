# -*- coding: utf-8 -*-
"""本地测试 PyMOL-NL 规则引擎（不依赖 PyMOL 环境）"""
import sys, importlib.util

# 加载 pymol_nl.py 但阻止 _register() 报错
spec = importlib.util.spec_from_file_location("pymol_nl", "/mnt/d/ScienceSoft/AI_Tools/PyMOL-NL/pymol_nl.py")
pml = importlib.util.module_from_spec(spec)
sys.modules["pymol_nl"] = pml
spec.loader.exec_module(pml)

tests = [
    ("选择74号", "select sel, resi 74"),
    ("选择氨基酸74号", "select sel, resi 74"),
    ("选择A链74号", "select sel, chain A and resi 74"),
    ("选择74到150", "select sel, resi 74-150"),
    ("选择A链", "select sel, chain A"),
    ("选择74号附近5埃", "select sel, byres resi 74 around 5"),
    ("全选", "select sel, all"),
    ("清空选择", "select none"),
    ("显示stick", "show sticks, sel"),
    ("显示棍状", "show sticks, sel"),
    ("显示卡通", "show cartoon, sel"),
    ("显示表面", "show surface, sel"),
    ("隐藏卡通", "hide cartoon, sel"),
    ("只显示卡通", "hide everything, show cartoon, sel"),
    ("染成红色", "color red, sel"),
    ("标红", "color red, sel"),
    ("把74号染成红色", "select sel, resi 74, color red, sel"),
    ("量74和150的距离", "distance dist_74_150, resi 74 and name CA, resi 150 and name CA"),
    ("量A链74和B链150的距离", "distance dist_A74_B150, chain A and resi 74 and name CA, chain B and resi 150 and name CA"),
    ("清除距离", "delete dist_*"),
    ("放大", "zoom sel"),
    ("放大74号", "zoom resi 74"),
    ("重置视角", "orient"),
    ("对齐b到a", "align b, a"),
    ("以a为基准对齐b", "align b, a"),
    ("select resi 74", None),  # 英文暂不支持，返回 None
]

ok = 0
for text, expect in tests:
    cmds = pml.parse(text)
    if expect is None:
        status = "PASS" if cmds is None else f"FAIL(期望无匹配, 得到 {cmds})"
    else:
        got = ", ".join(cmds) if cmds else None
        status = "PASS" if got == expect else f"FAIL(期望 {expect!r}, 得到 {got!r})"
    if status.startswith("PASS"):
        ok += 1
    print(f"[{status}] {text}")

print(f"\n{ok}/{len(tests)} 通过")
