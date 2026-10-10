# PyMOL-NL — 自然语言驱动 PyMOL

在 PyMOL 命令行输入中文（或英文）自然语言，自动转换为 PyMOL 命令执行。

## 快速开始

### 1. 安装（二选一）

**方式 A：startup 目录（PyMOL 2.x，启动自动加载）**

```powershell
# 在 PowerShell / CMD 中（<USER> 替换为你的用户名）：
mkdir C:\Users\<USER>\.pymol\startup
copy <path>\pymol_nl.py <path>\llm_translate.py C:\Users\<USER>\.pymol\startup\
```

重启 PyMOL，看到提示 `PyMOL-NL 已加载` 即成功。

**方式 B：手动加载（不重启，所有版本通用）**

打开 PyMOL 后，命令行执行：

```
run <path>/pymol_nl.py
```

> **PyMOL 3.x 用户注意**：3.x 不再自动加载 `~/.pymol/startup/` 目录，改为启动时执行 `.pymolrc` 文件。请在用户主目录创建 `C:\Users\<USER>\.pymolrc`（纯 ASCII，无后缀），内容为：
>
> ```
> run <path>/pymol_nl.py
> ```
>
> 然后在 PyMOL 中执行 `run <path>/pymol_nl.py` 即可启用（免重启）。

### 2. 使用

在 PyMOL 命令行输入（注意前缀 `nl`）：

```
nl 选择氨基酸74号
nl 显示stick
nl 染成红色
```

查看帮助与自检：

```
nl help          # 命令速查
nl list          # 全部规则列表
nl 诊断          # 自检：规则条数 / API key / LLM 是否通 / 中文输出通道
```

`nl 诊断`（别名 `nl 自检`、`nl diag`）用于快速定位问题：如果某句话"听不懂"，输出里会附一行 `原因: ...`（未配置 key / 请求超时 / 返回不安全 / 不认识该意图），不必再靠猜。

## 支持的命令

> 插件默认**免前缀模式**：直接输入自然语言即可，`nl` 前缀也可用。

| 类别 | 示例 |
|---|---|
| 选择 | `选择74号` / `选择A链74号` / `选择74到150` / `选择A链` / `选择74号附近5埃` / `全选` / `清空选择` |
| 多选/追加 | `选择a链71和74号和b链10号` / `添加选择b链的14，c链的10` / `选择A链11、14和15号` |
| 显示 | `显示stick` / `显示卡通` / `显示表面` / `隐藏卡通` / `只显示卡通` |
| 只显示某一链 | `只显示A链` / `只显示A链的卡通` |
| 隐藏 | `隐藏所有水分子` / `隐藏所有配体` |
| 着色 | `染成红色`（按元素） / `把74号染成蓝色` / `三条链显示不同的颜色` / `按b-factor上色` / `按温度因子上色` |
| 背景 | `把背景设成白色` / `背景改成黑色` |
| 标签 | `给74号加标签` / `给A链的74号加标签, 文字是 active` / `去掉标签` |
| 测距/相互作用 | `量74和150的距离` / `清除距离` / `看看K186和D50有没有盐桥`（按 NZ / OD1+OD2 量） / `找一下A链的极性接触` |
| 视角 | `放大` / `放大74号` / `居中到74号` / `重置视角` |
| 对齐/叠合 | `对齐b到a` / `以a为基准对齐b` / `超级叠合a到b` |
| 出图 | `截个图` / `保存图片到桌面` / `保存图片到D:/shot.png` |
| 二级结构 | `重新算二级结构` |
| 设置 | `把设置里的卡通透明度改成0.5` |
| 场景 | `保存场景F1` / `恢复场景F1` |
| 对象操作 | `将b链和c链分别拆分出来` / `删除prot中的b链和c链` / `将m复制为m2` / `删除对象m2` / `旋转90度` / `保存当前状态为state.pse` |
| 多步命令 | `将prot中的链和c链拆分出来，然后分别染成不同的颜色` |

## 设计

```
输入自然语言
  ↓
① 规则引擎（38 条正则规则）—— 命中 → 直接执行（秒回）
  ↓ 未命中
② DeepSeek 意图识别 —— 只输出 JSON（intent + params），不生成命令
  ↓
③ 白名单执行器 —— intent → 安全命令模板 + 参数校验
  ↓
④ cmd.do() 执行（sel 自动补全 + 免前缀拦截）
```

- 规则表在 `pymol_nl.py` 顶部，`@rule(正则, 说明)` 装饰器注册，**先注册先匹配**
- 匹配失败会提示"无法理解"并给出 `nl help` 指引；LLM 兜底失败时会额外打印**具体原因**
- 所有命令输出带 `>>>` 前缀回显，方便核对翻译是否正确
- 命令依赖 `sel` 选择集时自动补全（`select sel, all`），无需手动先选
- **中文输出**：PyMOL 3.x 的 GUI 输出区是 Qt 控件，但命令回显走 PyMOL C 层反馈（非 ASCII 会变成 `?`），
  插件改为把中文直接写入 Qt 输出控件（`pymol.gui.get_qtwindow().browser`），拿不到界面时才退回 `print`

## 文件结构

```
PyMOL-NL/
├── pymol_nl.py       # 插件主体（规则引擎 + PyMOL 集成，单文件）
├── llm_translate.py  # LLM 兜底（DeepSeek 意图识别 + 白名单执行器）
├── test_rules.py     # 规则引擎本地测试（26 用例，无需 PyMOL）
│                     # 注意：路径写死为占位符，需改成本机 pymol_nl.py 路径才能跑
└── README.md
```

## LLM 智能兜底（DeepSeek API，可选）

规则表覆盖常用命令；**规则未命中时自动调用 DeepSeek 识别意图**，把没写过的说法也翻译成安全命令。

**支持意图（29 种）**：

select / add_selection / show / show_only / hide / color / color_chains / spectrum / distance / polar_contacts /
zoom / center / orient / align / super / create_object / split_chains / save_state / scene / rotate / delete_object /
remove_chains / label / label_clear / png / bg_color / show_ss / set_value / measure_angle

示例（规则表没有的说法）：

```
只显示A链的卡通          → hide everything; show cartoon, chain A
把74号显示成棍状          → show sticks, resi 74
隐藏所有水分子            → hide everything, resn HOH
按b-factor上色            → spectrum b, rainbow, sel
给74号加标签              → label resi 74
看看K186和D50有没有盐桥   → distance dist_186_50, resi 186 and name NZ, resi 50 and name OD1+OD2
找一下A链的极性接触       → distance hbonds, chain A, chain A, mode=2
截个图                    → png pymol_nl_shot.png, dpi=300, ray=1
保存图片到桌面            → png C:/Users/<USER>/Desktop/shot.png, dpi=300, ray=1
把背景设成白色            → bg_color white
把A链和B链对齐            → align chain A, chain B
超级叠合a到b              → super a, b
保存场景F1                → scene F1, store
重新算二级结构            → dss sel; show cartoon, sel
把设置里的卡通透明度改成0.5 → set cartoon_transparency, 0.5
```

**架构**（安全设计）：

```
规则表匹配（秒回）
  → 未命中 → DeepSeek 意图识别（只输出 JSON，不生成命令）
  → 本地白名单执行器（intent → 安全命令模板 + 参数校验）
```

- LLM 只负责"听懂意图"，**不能直接生成任意命令**——白名单挡住幻觉
- 白名单执行器会**保留 LLM 给出的参数**（选择集、原子名、路径等），并对参数做校验：
  选择表达式不合法、原子名不认识、对齐两侧都取不到时，宁可报"听不懂"也不执行半截命令
- 断网 / 无 key 时自动降级：规则表仍可用，LLM 只是增强；失败原因会打印出来
- LLM 超时 8 秒（超时即降级，不卡界面）；同一句话的结果会缓存，避免重复请求

**配置**：

1. 安装时同时复制 `llm_translate.py` 到 startup 目录（与 `pymol_nl.py` 同目录）
2. 配置 DeepSeek API key（三选一）：
   - 环境变量 `DEEPSEEK_API_KEY`
   - 或插件目录下 `.pymol_nl_key` 文件（一行，无换行；已在 `.gitignore` 中，不会被提交）
   - 或 WSL `~/.hermes/.env`（Windows 下 PyMOL 读不到，需用前两种）

## 扩展规则

在 `pymol_nl.py` 中新增一条规则：

```python
@rule(r"旋转\s*(\d+)\s*度", "旋转: 旋转90度")
def _rotate(m):
    return [f"rotate y, {m.group(1)}, sel"]
```

规则放在 `RULES` 列表靠前的位置以获得更高优先级（列表顺序 = 匹配优先级）。

> 写规则时记得给正则加上首尾锚定（`^...$`）。不带锚定的关键词规则会"局部命中"，
> 例如 `放大|缩放|zoom|居中` 会抢走"居中到74号"，把右侧的残基号整段丢掉。

## 兼容性

- 需要 PyMOL 2.x / 3.x（内置 Python 3），商业版/开源版均可
- 中文输入依赖 PyMOL 内置 Python 的 UTF-8 支持（PyMOL 2.x 默认支持）
- 规则引擎零依赖（仅标准库 `re`）；LLM 兜底需 Python 3.6+（`urllib` 标准库）

## 更新日志

### 2026-10-10

- **修复中文显示为 `?`**：中文输出改为直写 PyMOL 的 Qt 输出控件，不再经过 C 层反馈
  （拿不到界面时退回 `print` + 日志文件）
- **LLM 意图 17 → 29 种**：新增只显示 / 温度因子上色 / 标签 / 截图 / 背景色 / 极性接触 /
  二级结构 / 场景 / 设置 / 叠合 等
- **修掉参数被丢弃导致的静默错译**：`把74号显示成棍状` 原来会执行成 `show sticks, sel`（丢了 74 号），
  现在正确产出 `show sticks, resi 74`；`看看K186和D50有没有盐桥` 原来量的是 CA-CA，现在按 `NZ` / `OD1+OD2` 量
- **失败可诊断**：新增 `nl 诊断`，LLM 兜底失败时打印具体原因；超时 30s → 8s，并加同句缓存
- 20 条真实科研口吻的基线语句命中率 14/20 → **20/20**，新增 16 条能力语句 **16/16**

## 待办 / 已知限制

- [ ] 规则表正则锚定与回归用例：`test_rules.py` 路径写死为占位符，需改成自动定位脚本目录
- [ ] `nl 学习`：把未命中的原话连同 LLM 结果记成候选规则，用户确认后写回规则表
- [ ] 同义词归一化（残基/氨基酸/residue、棍状/棒状/sticks、染色/上色/着色），减少 LLM 调用
- [ ] LLM 兜底异步化：现在同步阻塞，最长 8 秒内界面无响应
- [ ] 英文命令直接透传（如输入 `nl show sticks` 时原样执行）
