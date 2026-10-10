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
    1. 将本文件复制到 ~/.pymol/startup/ 目录（若目录不存在则创建）
    2. 重启 PyMOL，命令行输入:  nl help 查看所有可用命令
    3. 若无 startup 目录，也可在 PyMOL 命令行手动加载:
       run /path/to/pymol_nl.py

作者: 2026-08-10
兼容: PyMOL 2.x（内置 Python 3）
"""

import re
import os
import sys


# ============================================================
# 输出通道（2026-10-10）
# 背景：PyMOL 的 C 反馈层会把非 ASCII 变成 "?"（GUI 输出区取的是
# cmd._get_feedback() 的文本），中文提示因此全变问号。这里把文本直接写进
# Qt 输出控件（PyMOLQtGUI.browser），绕开该层；拿不到界面时退回 print，
# 并同时把 UTF-8 文本落到 ~/.pymol/pymol_nl.log。
# ============================================================

_BROWSER = None
_LOG_FH = None
_PENDING = []
_FLUSH_ARMED = False
_FLUSH_TRIES = 0
_FLUSH_MAX_TRIES = 20


def _out_browser():
    """PyMOL Qt 输出控件（QPlainTextEdit）；无界面时返回 None。"""
    global _BROWSER
    if _BROWSER is not None:
        return _BROWSER
    try:
        from pymol import gui
        win = gui.get_qtwindow()
        b = getattr(win, "browser", None) if win is not None else None
    except Exception:
        b = None
    if b is not None:
        _BROWSER = b
    return b


def _log_fh():
    """中文回退日志（UTF-8）；打不开返回 None。"""
    global _LOG_FH
    if _LOG_FH is None:
        try:
            d = os.path.join(os.path.expanduser("~"), ".pymol")
            if not os.path.isdir(d):
                os.makedirs(d)
            _LOG_FH = open(os.path.join(d, "pymol_nl.log"), "a", encoding="utf-8")
        except Exception:
            _LOG_FH = False
    return _LOG_FH or None


def _qt_app_running():
    """Qt 应用已起（说明有图形界面，只是输出控件可能还没就绪）。"""
    try:
        from pymol.Qt import QtWidgets
        return QtWidgets.QApplication.instance() is not None
    except Exception:
        return False


def _flush_pending():
    """把排队的中文补写进输出控件（界面晚于 .pymolrc 就绪时用）。"""
    global _FLUSH_ARMED, _FLUSH_TRIES
    _FLUSH_ARMED = False
    if not _PENDING:
        return
    b = _out_browser()
    if b is None:
        if _FLUSH_TRIES < _FLUSH_MAX_TRIES:
            _arm_flush()
        return
    for t in _PENDING:
        try:
            b.appendPlainText(t)
        except Exception:
            pass
    del _PENDING[:]
    _FLUSH_TRIES = 0


def _arm_flush():
    global _FLUSH_ARMED, _FLUSH_TRIES
    if _FLUSH_ARMED or _FLUSH_TRIES >= _FLUSH_MAX_TRIES:
        return
    _FLUSH_ARMED = True
    _FLUSH_TRIES += 1
    try:
        from pymol.Qt import QtCore
        QtCore.QTimer.singleShot(1200, _flush_pending)
    except Exception:
        pass


_LAST_REASON = ""  # 最近一次“没听懂”的具体原因（给 nl 显示）


def _say(text):
    """输出一行给用户：优先 Qt 控件（中文正常显示），否则日志 + print。"""
    text = "" if text is None else str(text)
    b = _out_browser()
    if b is not None:
        try:
            b.appendPlainText(text)
            return
        except Exception:
            pass
    fh = _log_fh()
    if fh is not None:
        try:
            fh.write(text + "\n")
            fh.flush()
        except Exception:
            pass
    if _qt_app_running():
        _PENDING.append(text)
        if len(_PENDING) > 200:
            del _PENDING[0]
        _arm_flush()
        return
    try:
        print(text)
    except Exception:
        pass


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


@rule(r"(?:再?添加选择|追加选择|再加选择)\s*((?:[ABCabc]\s*链?\s*的?\s*\d+\s*号?)(?:\s*(?:和|与|、|,|，)\s*(?:[ABCabc]\s*链?\s*的?\s*\d+\s*号?|\d+\s*号?))+)", "添加选择(跨链, 追加): 添加选择b链的14，c链的10")
def _sel_add_multi_chain(m):
    text = m.group(1)
    parts = re.split(r"\s*(?:和|与|、|,|，)\s*", text)
    chains = {}
    cur_chain = None
    for p in parts:
        mm = re.match(r"\s*([ABCabc])\s*链?\s*的?\s*(\d+)\s*号?\s*$", p)
        if mm:
            cur_chain = mm.group(1).upper()
            chains.setdefault(cur_chain, []).append(mm.group(2))
        else:
            mm2 = re.match(r"\s*(\d+)\s*号?\s*$", p)
            if mm2 and cur_chain:
                chains.setdefault(cur_chain, []).append(mm2.group(1))
    if not chains:
        return None
    terms = []
    for ch in sorted(chains):
        resis = sorted(set(chains[ch]), key=int)
        if len(resis) == 1:
            terms.append(f"chain {ch} and resi {resis[0]}")
        else:
            terms.append(f"chain {ch} and (resi {'+'.join(resis)})")
    return [f"select sel, sel or ({' or '.join(terms)})"]


@rule(r"添加选择\s*([ABCabc])\s*链?\s*的?\s*((?:\d+\s*号?)(?:\s*(?:和|与|、|,|，|\s+)\s*\d+\s*号?)+)$", "添加选择(追加到现有选择): 添加选择a链175、179、182")
def _sel_add_chain_multi(m):
    ch = m.group(1).upper()
    resis = [x for x in re.split(r"\s*(?:和|与|、|,|，|\s+)\s*", m.group(2)) if x.strip()]
    resis = sorted(set(re.sub(r"号$", "", r) for r in resis), key=int)
    return [f"select sel, sel or (chain {ch} and (resi {'+'.join(resis)}))"]


@rule(r"添加选择\s*(?:氨基酸|残基)?\s*(\d+)\s*号?$", "添加选择单个残基: 添加选择201号")
def _sel_add_res(m):
    return [f"select sel, sel or (resi {m.group(1)})"]


@rule(r"添加选择\s*([ABCabc])\s*链?\s*的?\s*(\d+)\s*号?$", "添加选择指定链单残基: 添加选择a链201号")
def _sel_add_chain_res(m):
    return [f"select sel, sel or (chain {m.group(1).upper()} and resi {m.group(2)})"]


@rule(r"添加选择\s*(?:氨基酸|残基)?\s*((?:\d+\s*号?)(?:\s*(?:和|与|、|,|，|\s+)\s*\d+\s*号?)+)$", "添加选择(无链, 所有链): 添加选择175、179、182")
def _sel_add_res_multi(m):
    resis = [x for x in re.split(r"\s*(?:和|与|、|,|，|\s+)\s*", m.group(1)) if x.strip()]
    resis = sorted(set(re.sub(r"号$", "", r) for r in resis), key=int)
    return [f"select sel, sel or (resi {'+'.join(resis)})"]


@rule(r"(?:选择|选中|选)?\s*([ABCabc])\s*链?\s*的?\s*((?:\d+\s*号?)(?:\s*(?:和|与|、|,|，|\s+)\s*\d+\s*号?)+)$", "选择同链多残基(任意数量): 选择A链11、14和15号")
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


@rule(r"(?:选择|选中|选)?\s*([ABCabc])\s*链?\s*的?\s*(\d+)\s*号?$", "选择指定链残基: 选择A链74号")
def _sel_chain_res(m):
    return _highlight(f"select sel, chain {m.group(1).upper()} and resi {m.group(2)}")


@rule(r"(?:选择|选中|选)?\s*((?:[ABCabc]\s*链?\s*的?\s*\d+\s*号?)(?:\s*(?:和|与|、|,|，)\s*(?:[ABCabc]\s*链?\s*的?\s*\d+\s*号?|\d+\s*号?))+)", "选择跨链多残基: 选择a链71和74号和b链10号")
def _sel_multi_chain(m):
    text = m.group(1)
    # 按连接词分割: 选择a链71和74号和b链10号 -> [a链71, 74号, b链10号]
    parts = re.split(r"\s*(?:和|与|、|,|，)\s*", text)
    chains = {}  # chain -> [resids]
    cur_chain = None
    for p in parts:
        mm = re.match(r"\s*([ABCabc])\s*链?\s*的?\s*(\d+)\s*号?\s*$", p)
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


def _color_cmds(c, sel="sel"):
    """按 element 染色（PyMOL Color by Element 语义）:
    非碳原子用元素默认色(atomic), 碳原子用指定色。"""
    return [f"color atomic, ({sel} and not elem C)", f"color {c}, ({sel} and elem C)"]


@rule(r"(?:染成|标成|改成|变成|设为|染|标|变)?\s*(红|蓝|绿|黄|橙|紫|青|白|灰|黑|粉|棕)\s*色?$", "着色(按元素): 染成红色 / 标红")
def _color(m):
    c = _COLORS[m.group(1)]
    return _color_cmds(c, "sel")


@rule(r"(?:把)?\s*(\d+)\s*号?\s*(?:染成|标成|变成)?\s*(红|蓝|绿|黄|橙|紫|青|白|灰|黑|粉|棕)\s*色?$", "指定残基着色(按元素): 把74号染成红色")
def _color_res(m):
    c = _COLORS[m.group(2)]
    return [f"select sel, resi {m.group(1)}"] + _color_cmds(c, "sel")


# ---------- 测距 ----------

@rule(r"(?:量|测|计算)?\s*(\d+)\s*和\s*(\d+)\s*(?:的)?\s*(?:距离|间距)$", "测量两残基距离: 量74和150的距离")
def _dist(m):
    return [f"distance dist_{m.group(1)}_{m.group(2)}, resi {m.group(1)} and name CA, resi {m.group(2)} and name CA"]


@rule(r"(?:量|测|计算)?\s*([ABCabc])\s*链?\s*的?\s*(\d+)\s*和\s*([ABCabc])\s*链?\s*(\d+)\s*(?:的)?\s*(?:距离|间距)$", "测量跨链残基距离: 量A链74和B链150的距离")
def _dist_chain(m):
    return [f"distance dist_{m.group(1)}{m.group(2)}_{m.group(3)}{m.group(4)}, chain {m.group(1).upper()} and resi {m.group(2)} and name CA, chain {m.group(3).upper()} and resi {m.group(4)} and name CA"]


@rule(r"清除距离|删除距离", "清除所有距离标注")
def _dist_clear(m):
    return ["delete dist_*"]


# ---------- 视角 ----------

@rule(r"放大\s*(\d+)\s*号?$", "放大到指定残基")
def _zoom_res(m):
    return [f"zoom resi {m.group(1)}"]


@rule(r"^(?:放大|缩小|缩放|zoom|居中)\s*(?:一下|一点|些许|显示|视图|视角|当前选择)?\s*[。！!]?$", "缩放到当前选择")
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


# ---------- 对象操作 ----------

@rule(r"(?:把|将)?\s*([A-Za-z0-9_]+)\s*(?:中|里的?|中的?)\s*([ABCabc])\s*链(?:\s*(?:和|与|、|,|，)\s*([ABCabc])\s*链)?\s*(?:分别)?\s*(?:拆分|提取|拿出来|分离|分出来)", "从对象拆分链(extract, 链名明确): 将prot中的b链和c链拆分出来")
def _split_from_obj(m):
    obj = m.group(1)
    chains = [m.group(2).upper()]
    if m.group(3):
        chains.append(m.group(3).upper())
    cmds = []
    for c in sorted(set(chains)):
        cmds.append(f"extract chain{c}, {obj} and chain {c}")
        cmds.append(f"show cartoon, chain{c}")  # extract 不继承表示方式
    return cmds

@rule(r"(?:把|将)?\s*([ABCabc])\s*链(?:和|与|、|,|，)\s*([ABCabc])\s*链\s*(?:分别)?\s*(?:拆分|提取|拿出来|分离|分出来)", "拆分链为独立对象(extract): 将b链和c链分别拆分出来")
def _split_chains2(m):
    chains = [m.group(1).upper(), m.group(2).upper()]
    cmds = []
    for c in sorted(set(chains)):
        cmds.append(f"extract chain{c}, chain {c}")
        cmds.append(f"show cartoon, chain{c}")  # extract 不继承表示方式
    return cmds


@rule(r"(?:把|将)?\s*([ABCabc])\s*链\s*(?:拆分|提取|拿出来|分离|分出来)", "拆分单链为独立对象(extract): 把b链拆分出来")
def _split_chain1(m):
    c = m.group(1).upper()
    return [f"extract chain{c}, chain {c}", f"show cartoon, chain{c}"]


@rule(r"(?:删除|移除|去掉)\s*(?:对象|物体)?\s*([A-Za-z0-9_]+)$", "删除对象: 删除对象m2 / 删掉m2")
def _del_obj(m):
    return [f"delete {m.group(1)}"]


@rule(r"(?:删除|移除|去掉)\s*(?:对象|物体)?\s*([A-Za-z0-9_]+)\s*(?:中|里的?|中的?)\s*([ABCabc])\s*链(?:\s*(?:和|与|、|,|，)\s*([ABCabc])\s*链)?$", "从对象删除链: 删除prot中的b链和c链")
def _remove_chains(m):
    obj = m.group(1)
    chains = [m.group(2).upper()]
    if m.group(3):
        chains.append(m.group(3).upper())
    sel = " or ".join(f"chain {c}" for c in chains)
    return [f"remove ({sel}) and {obj}"]


@rule(r"(?:把|将)?\s*([A-Za-z0-9_]+)\s*(?:复制|另存为|拷贝|copy)\s*(?:为|成|到)?\s*([A-Za-z0-9_]+)$", "复制对象: 将m复制为m2 / 把sel另存为trem2")
def _copy_obj(m):
    return [f"create {m.group(2)}, {m.group(1)}"]


@rule(r"(?:旋转|转动|转)\s*(-?\d+(?:\.\d+)?)\s*度\s*(?:绕\s*([xyzXYZ])\s*轴)?$", "旋转: 旋转90度 / 绕y轴转90度")
def _rotate(m):
    angle = m.group(1)
    axis = m.group(2).lower() if m.group(2) else "y"
    return [f"rotate {axis}, {angle}, sel"]


@rule(r"(?:保存|存)\s*(?:当前状态|状态|会话)?\s*(?:为|到|至)?\s*([A-Za-z0-9_.\-]+)$", "保存状态: 保存当前状态为state.pse")
def _save(m):
    return [f"save {m.group(1)}"]


# ---------- 其他 ----------

@rule(r"^(?:help|帮助|说明)$", "显示帮助")
def _help(m):
    _say(_CMD_HELP)
    return []


@rule(r"^(?:list|列表|规则|rules?)$", "显示所有规则")
def _list(m):
    _say("\n".join(f"  {d}" for _, _, d in RULES))
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
    """解析一行命令。支持:
    1. 一行内多个"选择"动词（自动合并为 or 选择）
    2. "然后/接着/再"连接的多步命令（逐段解析, 顺序执行）
    3. 无连接词的多动作连写（选择...显示...渲染...）
    """
    # 先按"然后/接着/再"分割多步命令
    step_parts = re.split(r"(?:然后|接着|随后|再然后)\s*", line)
    if len(step_parts) >= 2:
        all_cmds = []
        for part in step_parts:
            p = part.strip(" ，,；;。")
            if not p:
                continue
            cmds = _parse_line_single(p)
            if cmds is None:
                return None  # 某步无法解析，整体放弃
            all_cmds.extend(cmds)
        return all_cmds if all_cmds else None
    return _parse_line_single(line)


# 动作动词表（用于无连接词的多动作连写分割）
_ACTION_VERBS = [
    "选择", "选中", "添加选择", "追加选择", "显示", "隐藏", "只显示",
    "染成", "标成", "渲染成", "改成", "量", "测", "放大", "旋转",
    "保存", "删除", "拆分", "提取", "复制", "对齐", "清空", "全选",
]


def _split_multi_action(line):
    """按动作动词位置分割多动作连写，如 '选择...显示...渲染...'。
    返回段列表；若只有 1 个动作返回 None（不分割）。"""
    # 找所有动作动词的出现位置（跳过开头的第一个）
    positions = []
    for verb in _ACTION_VERBS:
        for m in re.finditer(re.escape(verb), line):
            positions.append((m.start(), verb))
    if not positions:
        return None
    positions.sort()
    # 合并重叠动词（取最靠前的），只保留每个位置的第一个动词
    merged = []
    for pos, verb in positions:
        if merged and pos < merged[-1][0] + 3:
            continue
        merged.append((pos, verb))
    if len(merged) <= 1:
        return None
    segments = []
    for i, (pos, verb) in enumerate(merged):
        end = merged[i + 1][0] if i + 1 < len(merged) else len(line)
        seg = line[pos:end].strip(" ，,；;。")
        if seg:
            segments.append(seg)
    return segments if len(segments) >= 2 else None


def _parse_line_single(line):
    """单步命令解析：多个"选择"动词合并为 or 选择；多动作连写逐段执行。"""
    # 无连接词的多动作连写（选择...显示...渲染...）
    multi = _split_multi_action(line)
    if multi is not None:
        all_cmds = []
        for seg in multi:
            cmds = parse_with_llm(seg)
            if cmds is None:
                return None  # 某段无法解析，整体放弃
            all_cmds.extend(cmds)
        return all_cmds if all_cmds else None
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
            cmds = parse_with_llm(seg)
            if cmds is None:
                return None  # 某段无法解析，整体放弃（原样交给 PyMOL）
            if cmds and cmds[0].startswith("select sel, "):
                exprs.append(cmds[0][len("select sel, "):])
            else:
                others.extend(cmds)
        if exprs:
            return ["select sel, " + " or ".join(exprs)] + others
    return parse_with_llm(line)


def parse(text):
    """解析自然语言，返回 PyMOL 命令列表；无法匹配返回 None"""
    text = text.strip()
    for pat, func, doc in RULES:
        m = pat.match(text)
        if m:
            cmds = func(m)
            return cmds
    return None


_LLM_MODULE = None  # 懒加载缓存


def _load_llm_module():
    """加载 llm_translate 模块（绝对路径加载，兼容 PyMOL run/exec 模式）。"""
    global _LLM_MODULE
    if _LLM_MODULE is not None:
        return _LLM_MODULE
    import importlib.util
    # 候选路径: 插件目录（run 时取脚本自身路径）+ 通用位置
    candidates = []
    try:
        candidates.append(os.path.dirname(os.path.abspath(__file__)))
    except NameError:
        pass
    candidates.append(os.path.expanduser("~/.pymol/startup"))
    candidates.append(os.path.dirname(os.path.abspath(sys.argv[0])) if sys.argv else "")
    for d in candidates:
        p = os.path.join(d, "llm_translate.py")
        if os.path.exists(p):
            spec = importlib.util.spec_from_file_location("llm_translate", p)
            mod = importlib.util.module_from_spec(spec)
            try:
                spec.loader.exec_module(mod)
            except Exception as e:
                _say(f"[PyMOL-NL] llm_translate 加载失败 {p}: {e}")
                continue
            _LLM_MODULE = mod
            return mod
    return None


def parse_with_llm(text):
    """规则匹配 + LLM 兜底：规则未命中时调用 DeepSeek 意图识别。
    返回 PyMOL 命令列表；都无法理解返回 None（原因见 _LAST_REASON）。"""
    global _LAST_REASON
    _LAST_REASON = ""
    # 1. 规则表
    cmds = parse(text)
    if cmds is not None:
        return cmds
    # 2. LLM 兜底（懒加载，避免无 key 时报错）
    mod = _load_llm_module()
    if mod is None:
        _LAST_REASON = "找不到 llm_translate.py（LLM 兜底不可用）"
        return None
    try:
        cmds = mod.llm_fallback(text)
    except Exception as e:
        _LAST_REASON = f"LLM 兜底调用异常: {type(e).__name__}: {e}"
        return None
    if cmds is None:
        st = mod.get_status() if hasattr(mod, "get_status") else {}
        kind = st.get("kind", "init")
        detail = st.get("detail", "")
        if kind == "unknown":
            _LAST_REASON = "本地规则未命中，LLM 也不确定（换种说法，或看 nl help）"
        elif kind == "no_key":
            _LAST_REASON = f"本地规则未命中，且 LLM 不可用：{detail}"
        elif kind == "unsafe":
            _LAST_REASON = f"LLM 识别出意图但参数不安全，已放弃：{detail}"
        elif kind == "error":
            _LAST_REASON = f"本地规则未命中，LLM 调用失败：{detail}"
        else:
            _LAST_REASON = "本地规则未命中，LLM 无结果"
    return cmds


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
对齐:   对齐b到a | 以a为基准对齐b | 叠合b到a
结构:   显示A链的卡通 | 只显示A链 | 隐藏所有水分子 | 加标签 | 截图 | 按b-factor上色
分色:   把两条链分别上色 | A链红色B链绿色
测距:   看看K186和D50有没有盐桥（最近会把原子名一起解析）
其它:   保存场景 | 恢复场景 | 居中 | 显示二级结构 | 设置卡通透明
帮助:   help | list | 诊断
"""


def _diagnose():
    """nl 诊断: 规则条数 / LLM 可用性 / 往返耗时 / 输出通道"""
    import time
    _say("---- PyMOL-NL 自检 ----")
    _say(f"  本地规则: {len(RULES)} 条")
    mod = _load_llm_module()
    if mod is None:
        _say("  LLM 模块: 未找到 llm_translate.py（只走本地规则）")
        return
    try:
        key = mod._get_api_key()
    except Exception as e:
        _say(f"  LLM 模块: 异常 {type(e).__name__}: {e}")
        return
    _say(f"  API key: {'已配置' if key else '未配置（环境变量 DEEPSEEK_API_KEY 或插件目录 .pymol_nl_key）'}")
    if not key:
        return
    t0 = time.time()
    try:
        r = mod.llm_translate("把74号显示成棍状", timeout=8)
    except Exception as e:
        _say(f"  LLM 调用: 异常 {type(e).__name__}: {e}")
        return
    dt = time.time() - t0
    st = mod.get_status()
    if r is None:
        _say(f"  LLM 调用: 失败（{dt:.1f}s）原因: {st.get('detail', '未知')}")
    else:
        _say(f"  LLM 调用: 正常（{dt:.1f}s）识别为 {r[0]} {r[1]}")
    b = _out_browser()
    where = "Qt 输出控件直写" if b is not None else ("日志文件 ~/.pymol/pymol_nl.log" if _log_fh() else "print 回退")
    _say(f"  中文输出通道: {where}")


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
        _say("错误: 必须在 PyMOL 环境中运行")
        return
    if text.strip().lower() in ("诊断", "自检", "diagnose", "diag", "check"):
        _diagnose()
        return
    cmds = parse_with_llm(text)
    if cmds is None:
        _say(f"无法理解: '{text}'")
        if _LAST_REASON:
            _say(f"  原因: {_LAST_REASON}")
        _say("输入 nl help 查看可用命令")
        return
    for c in cmds:
        _say(f">>> {c}")
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
                        # ⚠️ 合法 PyMOL 命令原样传递（2026-08-17 修复：免前缀模式
                        # 劫持 show cartoon/zoom 等正常命令 → 改写为 show X, sel +
                        # 自动 select sel, all，导致全选+渲染异常）
                        first = line.strip().split()[0].lower()
                        if first in _cmdmod.keyword:
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
                # ---- 自动确保 sel 存在 ----
                # 若命令依赖 sel 选择集（show/hide/color 等涉及 sel），
                # 且 sel 尚未定义，则自动创建 select sel, all，避免
                # "Invalid selection name sel" 错误
                try:
                    needs_sel = any(
                        re.search(r"\bsel\b", c) for c in out
                        if isinstance(c, str))
                    if needs_sel and "sel" not in _self.get_names("selections"):
                        out.insert(0, "select sel, all")
                except Exception:
                    pass
                return _orig_do(out, log=log, echo=echo, flush=flush, _self=_self)

            cmd.do = _smart_do
            _say("PyMOL-NL 已加载（免前缀模式已启用）。输入 `nl help` 或直接输入自然语言。")
        except Exception as e:
            _say(f"PyMOL-NL 已加载（免前缀模式启用失败: {e}，请使用 `nl` 前缀）。")
    except Exception as e:
        _say(f"PyMOL-NL 注册失败: {e}")


_register()
