# PyMOL-NL — 自然语言驱动 PyMOL

在 PyMOL 命令行输入中文（或英文）自然语言，自动转换为 PyMOL 命令执行。

## 快速开始

### 1. 安装（二选一）

**方式 A：startup 目录（PyMOL 2.x，启动自动加载）**

```powershell
# 在 PowerShell / CMD 中（<USER> 替换为你的用户名）：
mkdir C:\Users\<USER>\.pymol\startup
copy <path>\pymol_nl.py C:\Users\<USER>\.pymol\startup\
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

查看帮助：

```
nl help          # 命令速查
nl list          # 全部规则列表
```

## 支持的命令

| 类别 | 示例 |
|---|---|
| 选择 | `nl 选择74号` / `nl 选择氨基酸74号` / `nl 选择A链74号` / `nl 选择74到150` / `nl 选择A链` / `nl 选择74号附近5埃` / `nl 全选` / `nl 清空选择` |
| 显示 | `nl 显示stick` / `nl 显示卡通` / `nl 显示表面` / `nl 隐藏卡通` / `nl 只显示卡通` |
| 着色 | `nl 染成红色` / `nl 标红` / `nl 把74号染成蓝色` |
| 测距 | `nl 量74和150的距离` / `nl 量A链74和B链150的距离` / `nl 清除距离` |
| 视角 | `nl 放大` / `nl 放大74号` / `nl 重置视角` |
| 对齐 | `nl 对齐b到a` / `nl 以a为基准对齐b` |

## 设计

```
PyMOL 命令行:  nl 选择氨基酸74号
        ↓ cmd.extend("nl", ...) 注册的命令
   parse(text) —— 规则表按序匹配（正则 + 意图函数）
        ↓
   返回 PyMOL 命令列表 → cmd.do() 逐条执行
```

- 规则表在 `pymol_nl.py` 顶部，`@rule(正则, 说明)` 装饰器注册，**先注册先匹配**
- 匹配失败会提示"无法理解"并给出 `nl help` 指引
- 所有命令输出带 `>>>` 前缀回显，方便核对翻译是否正确

## 文件结构

```
PyMOL-NL/
├── pymol_nl.py       # 插件主体（规则引擎 + PyMOL 集成，单文件）
├── llm_translate.py  # LLM 兜底（DeepSeek 意图识别 + 白名单执行器）
├── test_rules.py     # 规则引擎本地测试（26 用例，无需 PyMOL）
└── README.md
```

## LLM 智能兜底（DeepSeek API，可选）

规则表覆盖常用命令；**规则未命中时自动调用 DeepSeek 识别意图**，把没写过的说法也翻译成安全命令。

**支持意图**（15 种）：select / add_selection / show / hide / color / distance / zoom / orient / align / create_object / split_chains / save_state / measure_angle / rotate / delete_object

示例（规则表没有的说法）：
```
将sel复制另存为trem2      → create trem2, sel
将b链和c链分别拆分出来    → create chainB, chain B; create chainC, chain C
再添加选择b链的14，c链的10 → select sel, sel or (...)
旋转90度                  → rotate y, 90, sel
保存当前状态为state.pse   → save state.pse
```

**架构**（安全设计）：
```
规则表匹配（秒回）
  → 未命中 → DeepSeek 意图识别（只输出 JSON，不生成命令）
  → 本地白名单执行器（intent → 安全命令模板 + 参数校验）
```

- LLM 只负责"听懂意图"，**不能直接生成任意命令**——白名单挡住幻觉
- 断网/无 key 时自动降级：规则表仍可用，LLM 只是增强

**配置**：
1. 安装时同时复制 `llm_translate.py` 到 startup 目录（与 `pymol_nl.py` 同目录）
2. 配置 DeepSeek API key（三选一）：
   - 环境变量 `DEEPSEEK_API_KEY`
   - 或插件目录下 `.pymol_nl_key` 文件（一行，无换行）
   - 或 WSL `~/.hermes/.env`（Windows 下 PyMOL 读不到，需用前两种）

## 扩展规则

在 `pymol_nl.py` 中新增一条规则：

```python
@rule(r"旋转\s*(\d+)\s*度", "旋转: 旋转90度")
def _rotate(m):
    return [f"rotate y, {m.group(1)}, sel"]
```

规则放在 `RULES` 列表靠前的位置以获得更高优先级（列表顺序 = 匹配优先级）。

## 兼容性

- 需要 PyMOL 2.x（内置 Python 3），商业版/开源版均可
- 中文输入依赖 PyMOL 内置 Python 的 UTF-8 支持（PyMOL 2.x 默认支持）
- 规则引擎零依赖（仅标准库 `re`）；LLM 兜底需 Python 3.6+（`urllib` 标准库）

## 待办 / 已知限制

- [ ] 英文命令直接透传（如输入 `nl show sticks` 时原样执行）
- [ ] 链名大小写 / 空格容错
- [ ] LLM 响应缓存（相同指令避免重复调用 API）
