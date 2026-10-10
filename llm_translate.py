# -*- coding: utf-8 -*-
"""
PyMOL-NL LLM 翻译层
===================
规则引擎未命中时，调用 DeepSeek API 做意图识别（只输出 JSON），
然后由本地白名单执行器生成安全命令。

API key 读取顺序:
1. 环境变量 DEEPSEEK_API_KEY
2. WSL ~/.hermes/.env 中的 DEEPSEEK_API_KEY
3. 插件同目录下的 .pymol_nl_key 文件

使用前配置:
   Windows 下 PyMOL 无法读 WSL 环境变量, 建议在插件目录下创建 .pymol_nl_key 文件
   写入你的 DeepSeek API key（一行, 无换行）
"""

import json
import os
import re
import urllib.request
import urllib.error

# ============================================================
# API key 获取
# ============================================================

def _get_api_key():
    # 1. 环境变量
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    if key:
        return key.strip()
    # 2. WSL hermes .env（插件在 Windows 跑时读不到, 但保留兼容）
    env_path = os.path.expanduser("~/.hermes/.env")
    if os.path.exists(env_path):
        try:
            for line in open(env_path, encoding="utf-8", errors="replace"):
                if line.startswith("DEEPSEEK_API_KEY="):
                    key = line.strip().split("=", 1)[1].strip()
                    if key:
                        return key
        except Exception:
            pass
    # 3. 插件同目录 .pymol_nl_key
    key_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".pymol_nl_key")
    if os.path.exists(key_path):
        try:
            with open(key_path, encoding="utf-8") as f:
                key = f.read().strip()
                if key:
                    return key
        except Exception:
            pass
    return ""


# ============================================================
# 意图白名单（LLM 只允许输出这些 intent）
# ============================================================

INTENT_NAMES = [
    "select", "add_selection", "show", "hide", "show_only", "color", "color_chains", "spectrum",
    "distance", "zoom", "center", "orient", "align", "super", "create_object", "save_state",
    "measure_angle", "rotate", "delete_object", "remove_chains", "split_chains",
    "label", "label_clear", "png", "bg_color", "polar_contacts", "show_ss", "set_value", "scene",
]

_SYSTEM_PROMPT = f"""你是一个 PyMOL 分子可视化软件的中文自然语言解析器。
用户的输入是操作 PyMOL 的意图，请把它转换为结构化的 JSON。
规则：
1. 只能输出 JSON，不要输出任何其他文字
2. intent 必须从以下列表选择: {", ".join(INTENT_NAMES)}
3. 参数必须从用户输入中提取真实存在的值（残基号、链名、颜色、表示方式等）
4. 若无法确定意图，intent 用 "unknown"

intent 说明:
- select: 选择残基/链/区域（**替换**当前选择）-> params: {{"selection": "chain A and resi 1-100"}}
- add_selection: **添加/追加/再加上**到当前选择（不替换, 与已有选择合并）-> params: {{"selection": "chain B and resi 14"}}
  注意: 输入含"添加/追加/再加/多选"等词时用 add_selection 而不是 select
- show/hide: 显示/隐藏表示方式 -> params: {{"representation": "sticks|cartoon|surface|spheres|lines|dots|everything", "selection": "chain A"}}
  重要: 输入里点名了对象（链/残基/对象名）就必须把 selection 一起给出；一个都没点名才省略
- show_only: "只显示/仅显示/只看/单独显示"（先隐藏其余再显示）-> params: {{"representation": "cartoon", "selection": "chain A"}}
- color: 给某个选择着色 -> params: {{"color": "red", "selection": "chain A"}}
  按 b-factor（温度因子/数值）上色时用 spectrum，或把 color 写成 "b-factor"
- spectrum: 按数值渐变上色 -> params: {{"palette": "rainbow", "selection": "sel"}}
- color_chains: 给多条链分别染不同颜色（如"三条链显示不同颜色"/"A链红色B链绿色"）-> params: {{"chains": {{"A": "red", "B": "green", "C": "blue"}}}}
  注意: 输入含"不同颜色/分别着色/每链一个颜色"等多链分色意图时用 color_chains 而不是 color
- distance: 测量距离（默认量 CA-CA；若问的是盐桥/氢键/具体原子，必须给出原子名）-> params: {{"selection1": "186", "selection2": "50", "atoms1": "NZ", "atoms2": "OD1,OD2"}}
- zoom/orient: 视角 -> params: {{"target": "74"}} 或空
- align: 对齐 -> params: {{"target": "a", "reference": "b"}}
- create_object: **复制**/另存为命名对象（原对象保留）-> params: {{"source": "sel", "target": "newname"}}
  如"将sel复制另存为trem2" -> {{"source": "sel", "target": "trem2"}}
- split_chains: **提取**指定链为独立对象（原对象中移除这些链, 是 extract 不是复制）-> params: {{"chains": "B,C", "object": "可选对象名"}}
  如"将b链和c链分别拆分出来" -> {{"chains": "B,C"}}
  如"将prot中的b链和c链拆分出来" -> {{"chains": "B,C", "object": "prot"}}
  如"将prot中的链和c链拆分出来"（第一条链省略字母, 通常是b链）-> {{"chains": "B,C", "object": "prot"}}
  注意: 拆分/提取/拿出来用 split_chains; 复制/另存为用 create_object
- delete_object: **删除整个对象/选择**（如"删除对象m2"）-> params: {{"target": "objname"}}
  注意: 若输入是"从某对象中删除某些链/残基"(保留其余部分), 用 remove_chains 而不是 delete_object
- remove_chains: 从对象中移除指定链（保留其余链）-> params: {{"object": "prot", "chains": "B,C"}}
  如"删除prot中的b链和c链" -> {{"object": "prot", "chains": "B,C"}}
- save_state: 保存状态文件 -> params: {{"filename": "state.pse"}}
- measure_angle: 测量角度（**必须三组原子**：angle 是 原子1-原子2-原子3 的夹角；只有两组原子/两个残基时无法成角，那种输入请返回 unknown 让用户改说三个）-> params: {{"selection1": "74", "selection2": "100", "selection3": "150", "atoms1": "CA", "atoms2": "CA", "atoms3": "CA"}}
  如"量74号CA、100号CA和150号CA之间的角度" -> {{"intent": "measure_angle", "params": {{"selection1": "74", "selection2": "100", "selection3": "150"}}}}
  如"量K186的NZ、D50的OD1和D50的OD2的角度" -> {{"intent": "measure_angle", "params": {{"selection1": "chain A and resi 186", "selection2": "chain B and resi 50", "selection3": "chain B and resi 50", "atoms1": "NZ", "atoms2": "OD1", "atoms3": "OD2"}}}}
  如"量74和150的角度"（只有两组）-> {{"intent": "unknown", "params": {{}}}}
- rotate: 旋转 -> params: {{"angle": "90", "axis": "y"}}
- label: 加标签（用户给了文字就放进 text）-> params: {{"selection": "resi 74", "text": "可选"}}
- label_clear: 去掉标签 -> params: {{"selection": "..."}}
- png: 截图/保存图片/出图 -> params: {{"filename": "可选, 如 D:/shot.png 或 ~/Desktop/shot.png(桌面)"}}
- bg_color: 背景颜色 -> params: {{"color": "white"}}
- polar_contacts: 极性接触/氢键/盐桥检查 -> params: {{"selection1": "...", "selection2": "..."}}
- show_ss: 显示或重算二级结构 -> params: {{"selection": "..."}}
- super: 叠合（super，与 align 同类但更快更粗）-> params: {{"target": "a", "reference": "b"}}
- set_value: 修改 PyMOL 设置 -> params: {{"key": "cartoon_transparency", "value": "0.5"}}
- scene: 保存/恢复场景 -> params: {{"name": "F1", "mode": "store|recall"}}
- center: 居中到某选择 -> params: {{"selection": "..."}}

示例（输入 -> 输出）:
- "将sel复制另存为trem2" -> {{"intent": "create_object", "params": {{"source": "sel", "target": "trem2"}}}}
- "将b链和c链分别拆分出来" -> {{"intent": "split_chains", "params": {{"chains": "B,C"}}}}
- "删除prot中的b链和c链" -> {{"intent": "remove_chains", "params": {{"object": "prot", "chains": "B,C"}}}}
- "删除对象m2" -> {{"intent": "delete_object", "params": {{"target": "m2"}}}}
- "再添加选择b链的14，c链的10" -> {{"intent": "add_selection", "params": {{"selection": "chain B and resi 14 or chain C and resi 10"}}}}
- "选择A链74号" -> {{"intent": "select", "params": {{"selection": "chain A and resi 74"}}}}
- "旋转90度" -> {{"intent": "rotate", "params": {{"angle": "90", "axis": "y"}}}}
- "保存当前状态为state.pse" -> {{"intent": "save_state", "params": {{"filename": "state.pse"}}}}
- "量74和150的距离" -> {{"intent": "distance", "params": {{"selection1": "74", "selection2": "150"}}}}
- "看看K186和D50有没有盐桥" -> {{"intent": "distance", "params": {{"selection1": "186", "selection2": "50", "atoms1": "NZ", "atoms2": "OD1,OD2"}}}}
- "把74号显示成棍状" -> {{"intent": "show", "params": {{"representation": "sticks", "selection": "resi 74"}}}}
- "只显示A链的卡通" -> {{"intent": "show_only", "params": {{"representation": "cartoon", "selection": "chain A"}}}}
- "隐藏所有水分子" -> {{"intent": "hide", "params": {{"representation": "everything", "selection": "resn HOH"}}}}
- "按b-factor上色" -> {{"intent": "spectrum", "params": {{"palette": "rainbow", "selection": "sel"}}}}
- "给74号加标签" -> {{"intent": "label", "params": {{"selection": "resi 74"}}}}
- "截个图" -> {{"intent": "png", "params": {{}}}}
- "把对象a对齐到b" -> {{"intent": "align", "params": {{"target": "a", "reference": "b"}}}}
- "三条链显示不同的颜色" -> {{"intent": "color_chains", "params": {{"chains": {{"A": "red", "B": "green", "C": "blue"}}}}}}

输出格式: {{"intent": "...", "params": {{"...": "..."}}}}"""


# ============================================================
# 白名单执行器: intent -> PyMOL 命令模板
# ============================================================

def _safe_name(s, default="obj"):
    """对象名/文件名白名单: 只允许字母数字下划线点号"""
    s = str(s or "").strip()
    if re.fullmatch(r"[A-Za-z0-9_.\-]+", s):
        return s
    return default


def _safe_target(s, default=""):
    """对齐目标: 允许对象名或选择表达式(如 "chain A"); 说不清返回 default(空串)"""
    s = str(s or "").strip().strip("()")
    if s and re.fullmatch(r"[A-Za-z0-9 _+\-.,]{1,60}", s):
        return s
    return default


def _safe_chain(s):
    s = str(s or "").strip().upper()
    return s if s in "ABC" else "A"


def _safe_resi(s):
    """残基号白名单: 数字 或 数字+数字 或 数字-数字"""
    s = str(s or "").strip()
    if re.fullmatch(r"\d+([+\-]\d+)*", s):
        return s
    return None


# 表示方式别名（含中文说法）
_REP_MAP = {
    "stick": "sticks", "sticks": "sticks", "棍": "sticks", "棍状": "sticks", "棒": "sticks",
    "棒状": "sticks", "球棍": "sticks", "licorice": "sticks",
    "cartoon": "cartoon", "卡通": "cartoon", "飘带": "cartoon", "带状": "cartoon",
    "ribbon": "cartoon", "螺旋": "cartoon", "loop": "lines",
    "surface": "surface", "表面": "surface", "曲面": "surface",
    "sphere": "spheres", "spheres": "spheres", "球": "spheres", "球状": "spheres",
    "line": "lines", "lines": "lines", "线": "lines", "线状": "lines", "wire": "lines",
    "wireframe": "lines", "dot": "dots", "dots": "dots", "点": "dots",
    "everything": "everything", "all": "everything", "所有": "everything", "全部": "everything",
}
_REP_OK = ("sticks", "cartoon", "surface", "spheres", "lines", "dots", "everything", "mesh", "ribbon")


def _norm_rep(rep, default="cartoon"):
    """归一化表示方式；非法返回 None。"""
    rep = str(rep or "").strip().lower() or default
    rep = _REP_MAP.get(rep, rep)
    return rep if rep in _REP_OK else None


# 颜色别名（中文 -> PyMOL 色名）
_COLOR_ALIAS = {
    "红色": "red", "红": "red", "绿色": "green", "绿": "green", "蓝色": "blue", "蓝": "blue",
    "黄色": "yellow", "黄": "yellow", "白色": "white", "白": "white", "黑色": "black", "黑": "black",
    "灰色": "gray", "灰": "gray", "橙色": "orange", "橙": "orange", "紫色": "purple", "紫": "purple",
    "粉色": "pink", "粉": "pink", "青色": "cyan", "青": "cyan", "洋红": "magenta", "棕色": "brown",
}

# 按数值上色的说法
_SPECTRUM_WORDS = {
    "b-factor", "b-factors", "bfactor", "bfactors", "b factor", "b_ factor", "温度因子",
    "rainbow", "彩虹", "spectrum", "光谱", "渐变", "按数值", "数值",
}
_PALETTES = {
    "rainbow", "rainbow_rev", "bwr", "blue_white_red", "red_white_blue", "cyan_magenta",
    "green_white_magenta", "yellow_cyan", "blue_white_green", "red_yellow_green_cyan_blue_magenta",
    "magenta_white_green", "red_white_green",
}

# set_value 允许的设置键（白名单，避免任意命令注入）
_SET_KEYS = (
    "bg_color", "cartoon_transparency", "surface_quality", "sphere_scale", "stick_radius",
    "line_width", "dot_width", "label_size", "label_color", "ray_shadows", "ray_opacity",
    "ray_opaque_background", "transparency", "cartoon_side_chain_helper", "cartoon_fancy_helices",
    "cartoon_cylindrical_helices", "ambient", "specular", "depth_cue", "ribbon_as_cylinders",
    "surface_color", "mesh_width", "valence", "cartoon_highlight_color",
)


def _safe_sel(s, default="sel"):
    """选择表达式白名单校验；空或非法都退回 default。"""
    s = str(s or "").strip()
    if s and re.fullmatch(r"[A-Za-z0-9\s()+\-_,.]+", s):
        return s
    return default


def _safe_atoms(a):
    """原子名白名单（NZ / OD1,OD2 -> NZ / OD1+OD2）；空返回默认 CA，非法返回 None。"""
    a = str(a or "").strip().upper().replace(" ", "")
    if not a:
        return "CA"
    if re.fullmatch(r"[A-Z0-9]+(,[A-Z0-9]+)*", a):
        return "+".join(a.split(","))
    return None


def intent_to_cmds(intent, params):
    """把 LLM 输出的 (intent, params) 转换为安全的 PyMOL 命令列表。
    返回 None 表示无法安全执行。"""
    p = params or {}
    if intent == "select":
        sel = str(p.get("selection", p.get("residues", ""))).strip()
        if not sel:
            return None
        # selection 参数来自 LLM, 必须校验: 只允许 chain/resi/数字/+- 和括号
        if not re.fullmatch(r"[A-Za-z0-9\s()+\-_,]+", sel):
            return None
        return [f"select sel, {sel}"]
    if intent == "add_selection":
        sel = str(p.get("selection", p.get("residues", ""))).strip()
        if not sel:
            return None
        if not re.fullmatch(r"[A-Za-z0-9\s()+\-_,]+", sel):
            return None
        return [f"select sel, sel or ({sel})"]
    if intent in ("show", "hide", "show_only"):
        # 关键修复: selection 走 LLM 给的值（点名了对象就必须用），不再硬编码 sel
        dflt = "everything" if intent == "hide" else "cartoon"
        rep = _norm_rep(p.get("representation"), dflt)
        if rep is None:
            return None
        sel = _safe_sel(p.get("selection", p.get("target", p.get("object", ""))))
        if intent == "show":
            return [f"show {rep}, {sel}"]
        if intent == "hide":
            return [f"hide {rep}, {sel}"]
        return ["hide everything", f"show {rep}, {sel}"]
    if intent in ("color", "spectrum"):
        sel = _safe_sel(p.get("selection", p.get("target", "")))
        color = str(p.get("color", p.get("palette", "red")) or "red").strip().lower()
        color = _COLOR_ALIAS.get(color, color)
        pal = str(p.get("palette", "") or "").strip().lower()
        pal = _COLOR_ALIAS.get(pal, pal)
        if color in _SPECTRUM_WORDS or pal in _SPECTRUM_WORDS or intent == "spectrum":
            pal = pal if pal in _PALETTES else "rainbow"
            return [f"spectrum b, {pal}, {sel}"]
        if not re.fullmatch(r"[a-z_0-9]+", color):
            return None
        # 默认按 element 染色（PyMOL Color by Element 语义）:
        # 非碳原子用元素默认色(atomic), 碳原子用指定色
        return [f"color atomic, ({sel} and not elem C)", f"color {color}, (elem C and {sel})"]
    if intent == "color_chains":
        chains_map = p.get("chains", {})
        if not isinstance(chains_map, dict) or not chains_map:
            return None
        cmds = []
        for ch, color in chains_map.items():
            ch = str(ch).strip().upper()
            color = str(color).strip().lower()
            if ch not in "ABC":
                continue
            if not re.fullmatch(r"[a-z_0-9]+", color):
                continue
            # 按 element 染色: 非碳原子元素默认色 + 碳原子指定色
            cmds.append(f"color atomic, (chain {ch} and not elem C)")
            cmds.append(f"color {color}, (chain {ch} and elem C)")
        return cmds if cmds else None
    if intent == "distance":
        s1 = str(p.get("selection1", p.get("resi1", ""))).strip()
        s2 = str(p.get("selection2", p.get("resi2", ""))).strip()
        if not s1 or not s2:
            return None
        a1 = _safe_atoms(p.get("atoms1", p.get("atom1", "")))
        a2 = _safe_atoms(p.get("atoms2", p.get("atom2", "")))
        if a1 is None or a2 is None:
            return None
        # 支持两种格式: 纯数字 "74" 或完整选区 "chain A and resi 74"；原子名不给就默认 CA
        def _dist_sel(s, atoms):
            if re.fullmatch(r"\d+([+\-]\d+)*", s):
                base = f"resi {s}"
            elif re.fullmatch(r"[A-Za-z0-9\s()+\-_,]+", s):
                base = s
            else:
                return None
            return f"{base} and name {atoms}"
        d1, d2 = _dist_sel(s1, a1), _dist_sel(s2, a2)
        if not d1 or not d2:
            return None
        tag = re.sub(r"[^0-9A-Za-z]", "_", s1)[:20] + "_" + re.sub(r"[^0-9A-Za-z]", "_", s2)[:20]
        return [f"distance dist_{tag}, {d1}, {d2}"]
    if intent == "zoom":
        target = str(p.get("target", "sel")).strip()
        if target.lower() in ("sel", "all"):
            return ["zoom sel"]
        r = _safe_resi(target)
        if r:
            return [f"zoom resi {r}"]
        return ["zoom sel"]
    if intent == "orient":
        return ["orient"]
    if intent == "align":
        mob = _safe_target(p.get("target", p.get("mobile", p.get("selection1", ""))))
        ref = _safe_target(p.get("reference", p.get("ref", p.get("selection2", ""))))
        if not mob or not ref:
            return None  # 目标说不清就别猜，宁可让用户重说
        return [f"align {mob}, {ref}"]
    if intent == "create_object":
        src = _safe_name(p.get("source", "sel"), "sel")
        tgt = _safe_name(p.get("target", "newobj"), "newobj")
        return [f"create {tgt}, {src}"]
    if intent == "split_chains":
        # 解析 chains: "B,C" / "b和c" / "A B C" / ["B","C"]
        chains_raw = p.get("chains", p.get("chain", ""))
        if isinstance(chains_raw, list):
            chain_list = [str(c).strip().upper() for c in chains_raw]
        else:
            chain_list = re.split(r"[,，和与、\s]+", str(chains_raw))
        chain_list = [c.strip().upper() for c in chain_list if c.strip() and c.strip().upper() in "ABC"]
        if not chain_list:
            return None
        # 可选: 限定从哪个对象拆分（LLM 提取到 object 参数时）
        obj = p.get("object", p.get("obj", ""))
        cmds = []
        for ch in sorted(set(chain_list)):
            objname = f"chain{ch}"
            # extract = 提取（原对象中移除该链），create = 复制（原对象保留）
            if obj:
                cmds.append(f"extract {objname}, {obj} and chain {ch}")
            else:
                cmds.append(f"extract {objname}, chain {ch}")
            # extract 新对象不继承原表示方式, 显式显示卡通(蛋白序列可见)
            cmds.append(f"show cartoon, {objname}")
        return cmds
    if intent == "save_state":
        fname = _safe_name(p.get("filename", "state.pse"), "state.pse")
        return [f"save {fname}"]
    if intent == "measure_angle":
        # 角度 = 三组原子的夹角。注意 PyMOL 的命令是 angle <名>, <原子1>, <原子2>, <原子3>；
        # get_angle 是 Python API（第 4 个位置参数是 state），走命令行必然报 ValueError。
        sel_raw = []
        for i in (1, 2, 3):
            sel_raw.append(str(p.get(f"selection{i}", p.get(f"sel{i}", p.get(f"resi{i}", "")))).strip())
        if not all(sel_raw):
            return None
        atoms = []
        for i in (1, 2, 3):
            a = _safe_atoms(p.get(f"atoms{i}", p.get(f"atom{i}", "")))
            if a is None:
                return None
            atoms.append(a)

        def _ang_sel(s, atom):
            if re.fullmatch(r"\d+([+\-]\d+)*", s):
                base = f"resi {s}"
            elif re.fullmatch(r"[A-Za-z0-9\s()+\-_,]+", s):
                base = s
            else:
                return None
            return f"{base} and name {atom}"

        s1 = _ang_sel(sel_raw[0], atoms[0])
        s2 = _ang_sel(sel_raw[1], atoms[1])
        s3 = _ang_sel(sel_raw[2], atoms[2])
        if not (s1 and s2 and s3):
            return None
        return [f"angle ang, {s1}, {s2}, {s3}"]
    if intent == "rotate":
        angle = str(p.get("angle", "90")).strip()
        if not re.fullmatch(r"-?\d+(\.\d+)?", angle):
            return None
        axis = str(p.get("axis", "y")).lower()
        if axis not in ("x", "y", "z"):
            axis = "y"
        return [f"rotate {axis}, {angle}, sel"]
    if intent == "delete_object":
        name = _safe_name(p.get("target", p.get("object", "")), "obj")
        return [f"delete {name}"]
    if intent == "remove_chains":
        obj = _safe_name(p.get("object", p.get("target", "")), "obj")
        chains_raw = p.get("chains", p.get("chain", ""))
        if isinstance(chains_raw, list):
            chain_list = [str(c).strip().upper() for c in chains_raw]
        else:
            chain_list = re.split(r"[,，和与、\s]+", str(chains_raw))
        chain_list = [c.strip().upper() for c in chain_list if c.strip() and c.strip().upper() in "ABC"]
        if not chain_list:
            return None
        sel_expr = " or ".join(f"chain {c}" for c in sorted(set(chain_list)))
        return [f"remove ({sel_expr}) and {obj}"]
    if intent in ("label", "label_clear"):
        sel = _safe_sel(p.get("selection", p.get("target", "")))
        if intent == "label_clear":
            return [f'label {sel}, ""']
        txt = str(p.get("text", p.get("label", "")) or "").strip()
        if txt:
            txt = txt.replace('"', "'").replace("\n", " ")[:60]
            return [f'label {sel}, "{txt}"']
        return [f"label {sel}"]
    if intent == "png":
        fname = str(p.get("filename", p.get("file", "pymol_nl_shot.png")) or "").strip()
        if not re.fullmatch(r'[^\r\n"\'<>|]{1,160}', fname) or fname.endswith(("/", "\\")):
            fname = "pymol_nl_shot.png"
        if fname.startswith("~"):
            fname = os.path.expanduser("~").replace("\\", "/") + fname[1:]
        return [f"png {fname}, dpi=300, ray=1"]
    if intent == "bg_color":
        color = str(p.get("color", "white") or "white").strip().lower()
        color = _COLOR_ALIAS.get(color, color)
        if not re.fullmatch(r"[a-z_0-9]+", color):
            return None
        return [f"bg_color {color}"]
    if intent == "polar_contacts":
        s1 = _safe_sel(p.get("selection1", p.get("selection", "")))
        s2 = _safe_sel(p.get("selection2", ""), s1)
        return [f"distance hbonds, {s1}, {s2}, mode=2"]
    if intent == "show_ss":
        sel = _safe_sel(p.get("selection", p.get("target", "")))
        return [f"dss {sel}", f"show cartoon, {sel}"]
    if intent == "super":
        mob = _safe_target(p.get("target", p.get("mobile", p.get("selection1", ""))))
        ref = _safe_target(p.get("reference", p.get("ref", p.get("selection2", ""))))
        if not mob or not ref:
            return None
        return [f"super {mob}, {ref}"]
    if intent == "center":
        sel = _safe_sel(p.get("selection", p.get("target", "")))
        return [f"center {sel}"]
    if intent == "set_value":
        key = str(p.get("key", "") or "").strip().lower()
        val = str(p.get("value", "") or "").strip()
        if key not in _SET_KEYS:
            return None
        if not re.fullmatch(r"[A-Za-z0-9_.,\- ]{1,40}", val):
            return None
        return [f"set {key}, {val}"]
    if intent == "scene":
        name = _safe_name(p.get("name", p.get("scene", "F1")), "F1").upper()
        mode = str(p.get("mode", p.get("action", "store")) or "store").strip().lower()
        if mode in ("recall", "load", "恢复", "调用", "读取"):
            return [f"scene {name}"]
        return [f"scene {name}, store"]
    return None


# ============================================================
# LLM 调用
# ============================================================

_LAST_STATUS = {"kind": "init", "detail": ""}
_CACHE = {}


def _set_status(kind, detail=""):
    _LAST_STATUS["kind"] = kind
    _LAST_STATUS["detail"] = detail


def get_status():
    """最近一次调用结果: kind ∈ ok / unknown / unsafe / no_key / error / init。"""
    return dict(_LAST_STATUS)


def clear_cache():
    _CACHE.clear()


def llm_translate(text, timeout=8):
    """调用 DeepSeek 识别意图。返回 (intent, params) 或 None；原因见 get_status()。"""
    key = _get_api_key()
    if not key:
        _set_status("no_key", "未配置 API key（环境变量 DEEPSEEK_API_KEY 或插件目录 .pymol_nl_key）")
        return None
    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
        "temperature": 0,
        "max_tokens": 200,
    }
    req = urllib.request.Request(
        "https://api.deepseek.com/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
    )
    # 强制直连：绕过注册表/环境变量代理（Windows 上代理残留会导致 getaddrinfo 失败）
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
        content = data["choices"][0]["message"]["content"].strip()
        # 提取 JSON（LLM 可能带 ```json 围栏）
        m = re.search(r"\{.*\}", content, re.S)
        if not m:
            _set_status("error", "LLM 返回不是 JSON: " + content[:80])
            return None
        parsed = json.loads(m.group(0))
        intent = parsed.get("intent", "unknown")
        if intent not in INTENT_NAMES:
            _set_status("error", f"LLM 返回了未知意图 {intent}")
            intent = "unknown"
        params = parsed.get("params", {}) if isinstance(parsed.get("params"), dict) else {}
        return intent, params
    except Exception as e:
        _set_status("error", f"{type(e).__name__}: {e}")
        return None


def llm_fallback(text, use_cache=True):
    """规则未命中时的完整兜底流程: LLM 识别 -> 白名单执行。
    返回命令列表或 None；失败原因见 get_status()。"""
    key = (text or "").strip()
    if use_cache and key in _CACHE:
        cmds, kind, detail = _CACHE[key]
        _set_status(kind, detail)
        return list(cmds) if cmds else None
    result = llm_translate(text)
    if result is None:
        if _LAST_STATUS["kind"] == "init":
            _set_status("no_key", "未配置 API key")
        _CACHE[key] = (None, _LAST_STATUS["kind"], _LAST_STATUS["detail"])
        return None
    intent, params = result
    if intent == "unknown":
        _set_status("unknown", "LLM 也判断不出意图")
        _CACHE[key] = (None, "unknown", _LAST_STATUS["detail"])
        return None
    cmds = intent_to_cmds(intent, params)
    if cmds is None:
        _set_status("unsafe", f"识别为 {intent}，但参数无法安全执行: {params}")
        _CACHE[key] = (None, "unsafe", _LAST_STATUS["detail"])
        return None
    _set_status("ok", intent)
    _CACHE[key] = (list(cmds), "ok", intent)
    return cmds


if __name__ == "__main__":
    # 本地测试
    import sys
    tests = [
        "将sel复制另存为trem2",
        "选择a链175、179、182",
        "量74和150的距离",
        "旋转90度",
        "保存当前状态为state.pse",
        "把对象a对齐到b",
    ]
    for t in tests:
        r = llm_fallback(t)
        print(f"输入: {t}\n  -> {r}\n")
