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
    "select", "add_selection", "show", "hide", "color", "color_chains", "distance", "zoom",
    "orient", "align", "create_object", "save_state",
    "measure_angle", "rotate", "delete_object", "remove_chains",
    "split_chains",
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
- show/hide: 显示/隐藏表示方式 -> params: {{"representation": "sticks|cartoon|surface|spheres|lines"}}
- color: 着色 -> params: {{"color": "red"}}
- color_chains: 给多条链分别染不同颜色（如"三条链显示不同颜色"/"A链红色B链绿色"）-> params: {{"chains": {{"A": "red", "B": "green", "C": "blue"}}}}
  注意: 输入含"不同颜色/分别着色/每链一个颜色"等多链分色意图时用 color_chains 而不是 color
- distance: 测量距离 -> params: {{"selection1": "74", "selection2": "150"}}
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
- measure_angle: 测量角度 -> params: {{"resi1": "74", "resi2": "150", "resi3": "160"}}
- rotate: 旋转 -> params: {{"angle": "90", "axis": "y"}}

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


def _safe_chain(s):
    s = str(s or "").strip().upper()
    return s if s in "ABC" else "A"


def _safe_resi(s):
    """残基号白名单: 数字 或 数字+数字 或 数字-数字"""
    s = str(s or "").strip()
    if re.fullmatch(r"\d+([+\-]\d+)*", s):
        return s
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
    if intent == "show":
        rep = str(p.get("representation", "sticks")).lower()
        rep = {"stick": "sticks", "棍状": "sticks", "cartoon": "cartoon",
               "卡通": "cartoon", "surface": "surface", "表面": "surface",
               "sphere": "spheres", "line": "lines"}.get(rep, rep)
        if rep not in ("sticks", "cartoon", "surface", "spheres", "lines", "dots"):
            return None
        return [f"show {rep}, sel"]
    if intent == "hide":
        rep = str(p.get("representation", "sticks")).lower()
        rep = {"stick": "sticks", "棍状": "sticks", "cartoon": "cartoon",
               "卡通": "cartoon", "surface": "surface", "表面": "surface",
               "sphere": "spheres", "line": "lines"}.get(rep, rep)
        if rep not in ("sticks", "cartoon", "surface", "spheres", "lines", "dots"):
            return None
        return [f"hide {rep}, sel"]
    if intent == "color":
        color = str(p.get("color", "red")).lower()
        if not re.fullmatch(r"[a-z_0-9]+", color):
            return None
        # 默认按 element 染色（PyMOL Color by Element 语义）:
        # 非碳原子用元素默认色(atomic), 碳原子用指定色
        return [f"color atomic, (sel and not elem C)", f"color {color}, (elem C and sel)"]
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
        # 支持两种格式: 纯数字 "74" 或完整选区 "chain A and resi 74"
        def _dist_sel(s):
            if re.fullmatch(r"\d+([+\-]\d+)*", s):
                return f"resi {s} and name CA"
            if re.fullmatch(r"[A-Za-z0-9\s()+\-_,]+", s):
                return f"{s} and name CA"
            return None
        d1, d2 = _dist_sel(s1), _dist_sel(s2)
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
        mob = _safe_name(p.get("target", p.get("mobile", "")), "obj")
        ref = _safe_name(p.get("reference", p.get("ref", "")), "obj")
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
        r1 = _safe_resi(str(p.get("resi1", "")))
        r2 = _safe_resi(str(p.get("resi2", "")))
        r3 = _safe_resi(str(p.get("resi3", "")))
        if not (r1 and r2 and r3):
            return None
        return [f"get_angle ang, resi {r1} and name CA, resi {r2} and name CA, resi {r3} and name CA"]
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
    return None


# ============================================================
# LLM 调用
# ============================================================

def llm_translate(text, timeout=30):
    """调用 DeepSeek 识别意图。返回 (intent, params) 或 None。"""
    key = _get_api_key()
    if not key:
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
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
        content = data["choices"][0]["message"]["content"].strip()
        # 提取 JSON（LLM 可能带 ```json 围栏）
        m = re.search(r"\{.*\}", content, re.S)
        if not m:
            return None
        parsed = json.loads(m.group(0))
        intent = parsed.get("intent", "unknown")
        if intent not in INTENT_NAMES:
            intent = "unknown"
        params = parsed.get("params", {}) if isinstance(parsed.get("params"), dict) else {}
        return intent, params
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, KeyError, TimeoutError) as e:
        print(f"[PyMOL-NL] LLM 调用失败: {e}")
        return None


def llm_fallback(text):
    """规则未命中时的完整兜底流程: LLM 识别 -> 白名单执行。
    返回命令列表或 None。"""
    result = llm_translate(text)
    if result is None:
        return None
    intent, params = result
    if intent == "unknown":
        return None
    cmds = intent_to_cmds(intent, params)
    if cmds is None:
        return None
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
