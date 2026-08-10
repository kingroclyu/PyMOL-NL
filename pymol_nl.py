# -*- coding: utf-8 -*-
"""
PyMOL-NL: 自然语言驱动 PyMOL（中英文）
======================================
在 PyMOL 命令行输入 `nl <自然语言>`，插件解析并执行对应 PyMOL 命令。

示例:
    nl 选择氨基酸74号
    nl 选择A链74号
    nl 显示stick
    nl 染成红色
    nl 量74和150的距离
    nl 对齐b到a
    nl help

安装:
    1. 将本文件复制到 C:\\Users\\<用户名>\\.pymol\\startup\\ 目录
       （若目录不存在则创建）
    2. 重启 PyMOL，命令行输入:  nl help 查看所有可用命令
    3. 若无 startup 目录，也可在 PyMOL 命令行手动加载:
       run D:/ScienceSoft/AI_Tools/PyMOL-NL/pymol_nl.py

作者: 2026-08-10
兼容: PyMOL 2.x（内置 Python 3）
"""

import re
import sys

# ============================================================
# 规则引擎
# ============================================================

# 每条规则: (正则, 处理函数, 说明)
# 处理函数接收 match 对象，返回 PyMOL 命令字符串列表
# 匹配优先级 = 列表顺序（先写先匹配）
RULES = []


def rule(pattern, doc):
    """装饰器：注册一条规则"""
    def deco(func):
        RULES.append((re.compile(pattern), func, doc))
        return func
    return deco


# 选择命令：仅执行 select，不改变颜色/形状（保持 3D 窗口显示原样）
def _highlight(sel_cmd):
    return [sel_cmd]


# ---------- 选择 ----------

@rule(r"(?:选择|选中|选)?\s*(?:氨基酸|残基)?\s*(\d+)\s*号?$", "选择残基: 选择74号 / 选择氨基酸74")
def _sel_res(m):
    return _highlight(f"select sel, resi {m.group(1)}")


@rule(r"(?:选择|选中|选)?\s*([ABCabc])\s*链?\s*((?:\d+\s*号?)(?:\s*(?:和|与|、|,|，|\s+)\s*\d+\s*号?)+)$", "选择同链多残基(任意数量): 选择A链11、14和15号")
def _sel_chain_res_multi(m):
    ch = m.group(1).upper()
    resis = [x for x in re.split(r"\s*(?:和|与|、|,|，|\s+)\s*", m.group(2)) if x.strip()]
    resis = sorted(set(re.sub(r"号$", "", r) for r in resis), key=int)
    return _highlight(f"select sel, chain {ch} and (resi {'+'.join(resis)})")


@rule(r"(?:选择|选中|选)?\s*(?:氨基酸|残基)?\s*((?:\d+\s*号?)(?:\s*(?:和|与|、|,|，|\s+)\s*\d+\s*号?)+)$", "选择多残基(任意数量): 选择11、14和15号")
def _sel_res_multi(m):
    resis = [x for x in re.split(r"\s*(?:和|与|、|,|，|\s+)\s*", m.group(1)) if x.strip()]
    resis = sorted(set(re.sub(r"号$", "", r) for r in resis), key=int)
    return _highlight(f"select sel, resi {'+'.join(resis)}")


@rule(r"(?:选择|选中|选)?\s*([ABCabc])\s*链?\s*(\d+)\s*号?$", "选择指定链残基: 选择A链74号")
def _sel_chain_res(m):
    return _highlight(f"select sel, chain {m.group(1).upper()} and resi {m.group(2)}")


@rule(r"(?:选择|选中|选)?\s*((?:[ABCabc]\s*链?\s*\d+\s*号?)(?:\s*(?:和|与|、|,|，)\s*(?:[ABCabc]\s*链?\s*\d+\s*号?|\d+\s*号?))+)", "选择跨链多残基: 选择a链71和74号和b链10号")
def _sel_multi_chain(m):
    text = m.group(1)
    # 按连接词分割: 选择a链71和74号和b链10号 -> [a链71, 74号, b链10号]
    parts = re.split(r"\s*(?:和|与|、|,|，)\s*", text)
    chains = {}  # chain -> [resids]
    cur_chain = None
    for p in parts:
        mm = re.match(r"\s*([ABCabc])\s*链?\s*(\d+)\s*号?\s*$", p)
        if mm:
            cur_chain = mm.group(1).upper()
            chains.setdefault(cur_chain, []).append(mm.group(2))
        else:
            mm2 = re.match(r"\s*(\d+)\s*号?\s*$", p)
            if mm2 and cur_chain:
                chains.setdefault(cur_chain, []).append(mm2.group(1))
            elif mm2:
                chains.setdefault("A", []).append(mm2.group(1))
    if not chains:
        return None
    terms = []
    for ch in sorted(chains):
        resis = sorted(set(chains[ch]), key=int)
        if len(resis) == 1:
            terms.append(f"chain {ch} and resi {resis[0]}")
        else:
            terms.append(f"chain {ch} and (resi {'+'.join(resis)})")
    return _highlight("select sel, " + " or ".join(terms))


@rule(r"(?:选择|选中|选)?\s*(\d+)\s*[到\-至~]\s*(\d+)\s*号?$", "选择残基区间: 选择74到150")
def _sel_range(m):
    return _highlight(f"select sel, resi {m.group(1)}-{m.group(2)}")


@rule(r"(?:选择|选中|选)?\s*([ABCabc])\s*链$", "选择整条链: 选择A链")
def _sel_chain(m):
    return _highlight(f"select sel, chain {m.group(1).upper()}")


@rule(r"(?:选择|选中|选)?\s*(?:氨基酸|残基)?\s*(\d+)\s*号?\s*附近\s*(\d+)\s*[埃Å]?$", "选择残基附近: 选择74号附近5埃")
def _sel_near(m):
    return _highlight(f"select sel, byres resi {m.group(1)} around {m.group(2)}")


@rule(r"清空选择|清除选择|取消选择", "清空选择")
def _sel_clear(m):
    return ["select none"]


@rule(r"(?:选择|选中)?\s*全部|全选", "选择全部")
def _sel_all(m):
    return _highlight("select sel, all")


# ---------- 显示/隐藏 ----------

@rule(r"(?:显示|展示)\s*(?:为|用)?\s*(stick|棍状|球棍|卡通|cartoon|表面|surface|点|sphere|线|line)", "显示表示方式: 显示stick / 显示卡通 / 显示表面")
def _show(m):
    mode = _mode_map(m.group(1).lower())
    return [f"show {mode}, sel"]


@rule(r"(?:隐藏|关闭|不显示)\s*(stick|棍状|球棍|卡通|cartoon|表面|surface|点|sphere|线|line)", "隐藏表示方式: 隐藏stick / 关闭卡通")
def _hide(m):
    mode = _mode_map(m.group(1).lower())
    return [f"hide {mode}, sel"]


@rule(r"只显示\s*(?:为|用)?\s*(stick|棍状|球棍|卡通|cartoon|表面|surface|点|sphere|线|line)", "只显示某表示方式")
def _show_only(m):
    mode = _mode_map(m.group(1).lower())
    return [f"hide everything", f"show {mode}, sel"]


# ---------- 着色 ----------

_COLORS = {
    "红": "red", "蓝": "blue", "绿": "green", "黄": "yellow", "橙": "orange",
    "紫": "purple", "青": "cyan", "白": "white", "灰": "gray", "黑": "black",
    "粉": "magenta", "棕": "brown",
}


@rule(r"(?:染成|标成|改成|变成|设为|染|标|变)?\s*(红|蓝|绿|黄|橙|紫|青|白|灰|黑|粉|棕)\s*色?$", "着色: 染成红色 / 标红")
def _color(m):
    c = _COLORS[m.group(1)]
    return [f"color {c}, sel"]


@rule(r"(?:把)?\s*(\d+)\s*号?\s*(?:染成|标成|变成)?\s*(红|蓝|绿|黄|橙|紫|青|白|灰|黑|粉|棕)\s*色?$", "指定残基着色: 把74号染成红色")
def _color_res(m):
    c = _COLORS[m.group(2)]
    return [f"select sel, resi {m.group(1)}", f"color {c}, sel"]


# ---------- 测距 ----------

@rule(r"(?:量|测|计算)?\s*(\d+)\s*和\s*(\d+)\s*(?:的)?\s*(?:距离|间距)$", "测量两残基距离: 量74和150的距离")
def _dist(m):
    return [f"distance dist_{m.group(1)}_{m.group(2)}, resi {m.group(1)} and name CA, resi {m.group(2)} and name CA"]


@rule(r"(?:量|测|计算)?\s*([ABCabc])\s*链?\s*(\d+)\s*和\s*([ABCabc])\s*链?\s*(\d+)\s*(?:的)?\s*(?:距离|间距)$", "测量跨链残基距离: 量A链74和B链150的距离")
def _dist_chain(m):
    return [f"distance dist_{m.group(1)}{m.group(2)}_{m.group(3)}{m.group(4)}, chain {m.group(1).upper()} and resi {m.group(2)} and name CA, chain {m.group(3).upper()} and resi {m.group(4)} and name CA"]


@rule(r"清除距离|删除距离", "清除所有距离标注")
def _dist_clear(m):
    return ["delete dist_*"]


# ---------- 视角 ----------

@rule(r"放大\s*(\d+)\s*号?$", "放大到指定残基")
def _zoom_res(m):
    return [f"zoom resi {m.group(1)}"]


@rule(r"放大|缩放|zoom|居中", "缩放到当前选择")
def _zoom(m):
    return ["zoom sel"]


@rule(r"重置视角|恢复视角|orient", "重置视角")
def _orient(m):
    return ["orient"]


# ---------- 对齐 ----------

@rule(r"(?:对齐|叠合|super|align)\s*(.+?)\s*(?:到|至|对)\s*(.+)$", "结构对齐: 对齐b到a / align b to a")
def _align(m):
    mob, ref = m.group(1).strip(), m.group(2).strip()
    return [f"align {mob}, {ref}"]


@rule(r"(?:以|用)\s*(.+?)\s*(?:为|作为)?\s*基准\s*(?:对齐|叠合)\s*(.+)$", "以某结构为基准对齐: 以a为基准对齐b")
def _align_ref(m):
    ref, mob = m.group(1).strip(), m.group(2).strip()
    return [f"align {mob}, {ref}"]


# ---------- 其他 ----------

@rule(r"^(?:help|帮助|说明)$", "显示帮助")
def _help(m):
    print(_CMD_HELP)
    return []


@rule(r"^(?:list|列表|规则|rules?)$", "显示所有规则")
def _list(m):
    print("\n".join(f"  {d}" for _, _, d in RULES))
    return []


# ============================================================
# 辅助
# ============================================================

def _mode_map(s):
    return {
        "stick": "sticks", "棍状": "sticks", "球棍": "sticks",
        "cartoon": "cartoon", "卡通": "cartoon",
        "surface": "surface", "表面": "surface",
        "sphere": "spheres", "点": "spheres",
        "line": "lines", "线": "lines",
    }.get(s, "sticks")


def _parse_line(line):
    """解析一行命令。支持一行内多个"选择"动词（自动合并为 or 选择）。"""
    # 检测多个"选择/选中"动词
    verb_positions = [m.start() for m in re.finditer(r"选择|选中", line)]
    if len(verb_positions) >= 2:
        segments = []
        for i, pos in enumerate(verb_positions):
            end = verb_positions[i + 1] if i + 1 < len(verb_positions) else len(line)
            segments.append(line[pos:end].strip(" ，,；;。"))
        exprs = []
        others = []
        for seg in segments:
            cmds = parse(seg)
            if cmds is None:
                return None  # 某段无法解析，整体放弃（原样交给 PyMOL）
            if cmds and cmds[0].startswith("select sel, "):
                exprs.append(cmds[0][len("select sel, "):])
            else:
                others.extend(cmds)
        if exprs:
            return ["select sel, " + " or ".join(exprs)] + others
    return parse(line)


def parse(text):
    """解析自然语言，返回 PyMOL 命令列表；无法匹配返回 None"""
    text = text.strip()
    for pat, func, doc in RULES:
        m = pat.match(text)
        if m:
            cmds = func(m)
            return cmds
    return None


# ============================================================
# PyMOL 集成
# ============================================================

_CMD_HELP = """\
PyMOL-NL 自然语言命令（nl <命令>）
----------------------------------
选择:   选择74号 | 选择A链74号 | 选择74到150 | 选择A链 | 选择74号附近5埃 | 全选 | 清空选择
显示:   显示stick | 显示卡通 | 显示表面 | 隐藏stick | 只显示卡通
着色:   染成红色 | 把74号染成红色
测距:   量74和150的距离 | 量A链74和B链150的距离 | 清除距离
视角:   放大 | 放大74号 | 重置视角
对齐:   对齐b到a | 以a为基准对齐b
帮助:   help | list
"""


def nl(*args, **kwargs):
    """PyMOL 命令入口: nl <自然语言>
    PyMOL 3.x 的 cmd.extend 会注入 _self 关键字参数，必须接收。
    """
    args = args or ()
    text = " ".join(str(a) for a in args)
    try:
        import pymol
        from pymol import cmd
    except ImportError:
        print("错误: 必须在 PyMOL 环境中运行")
        return
    cmds = _parse_line(text)
    if cmds is None:
        print(f"无法理解: '{text}'")
        print("输入 nl help 查看可用命令")
        return
    for c in cmds:
        print(f">>> {c}")
        cmd.do(c)


def _register():
    """注册 nl 命令到 PyMOL，并启用免前缀自然语言输入"""
    try:
        from pymol import cmd
        cmd.extend("nl", nl)

        # ---- 免前缀模式: 包装 cmd.do，自然语言自动解析 ----
        # 只有能匹配 NL 规则的输入才拦截，其余原样传给 PyMOL
        try:
            _orig_do = cmd.do

            def _smart_do(commands, log=1, echo=1, flush=0, _self=None):
                from pymol import cmd as _cmdmod
                if _self is None:
                    _self = _cmdmod
                cmds = commands if isinstance(commands, list) else [commands]
                out = []
                for c in cmds:
                    for line in c.splitlines():
                        if not line.strip():
                            out.append(line)
                            continue
                        # 跳过已经是 nl 前缀的（避免递归）
                        if line.strip().lower().startswith("nl "):
                            out.append(line)
                            continue
                        # 尝试自然语言解析
                        parsed = _parse_line(line.strip())
                        if parsed is not None:
                            for p in parsed:
                                out.append(p)
                            continue
                        # 无法识别 -> 原样传递
                        out.append(line)
                return _orig_do(out, log=log, echo=echo, flush=flush, _self=_self)

            cmd.do = _smart_do
            print("PyMOL-NL 已加载（免前缀模式已启用）。输入 `nl help` 或直接输入自然语言。")
        except Exception as e:
            print(f"PyMOL-NL 已加载（免前缀模式启用失败: {e}，请使用 `nl` 前缀）。")
    except Exception as e:
        print(f"PyMOL-NL 注册失败: {e}")


_register()
