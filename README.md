# PyMOL-NL — 自然语言驱动 PyMOL

在 PyMOL 命令行输入中文（或英文）自然语言，自动转换为 PyMOL 命令执行。

## 快速开始

### 1. 安装（二选一）

**方式 A：startup 目录（推荐，启动自动加载）**

```powershell
# 在 PowerShell / CMD 中：
mkdir C:\Users\Lv_JP\.pymol\startup
copy D:\ScienceSoft\AI_Tools\PyMOL-NL\pymol_nl.py C:\Users\Lv_JP\.pymol\startup\
```

重启 PyMOL，看到提示 `PyMOL-NL 已加载` 即成功。

**方式 B：手动加载（不重启）**

打开 PyMOL 后，命令行执行：

```
run D:/ScienceSoft/AI_Tools/PyMOL-NL/pymol_nl.py
```

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
├── pymol_nl.py     # 插件主体（规则引擎 + PyMOL 集成，单文件）
├── test_rules.py   # 规则引擎本地测试（26 用例，无需 PyMOL）
└── README.md
```

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
- 无需任何第三方 Python 包（仅标准库 `re`）

## 待办 / 已知限制

- [ ] 英文命令直接透传（如输入 `nl show sticks` 时原样执行）
- [ ] LLM 版意图理解（DeepSeek API，输出 JSON 白名单执行）
- [ ] 链名大小写 / 空格容错
