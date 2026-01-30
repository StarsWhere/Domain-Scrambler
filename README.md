# HAR 域名脱敏工具 (Domain Scrambler)

这是一个用于对 HAR (HTTP Archive) 文件进行域名脱敏的 Python 脚本。它可以将文件中的真实域名批量替换为无意义的占位符域名（如 `dev1.example.test`），并生成映射表以便后续完美还原。

## 核心功能

- **彻底脱敏**：采用全文正则替换，覆盖 URL、Header、Cookie、Body 等所有位置。
- **高性能**：使用单次正则扫描算法，即使是大型 HAR 文件也能快速处理。
- **智能边界判定**：通过正则后瞻/前瞻技术，确保只替换域名，不破坏 Base64 编码或路径中的类似字符串。
- **冲突检测**：自动确保生成的占位符不会与原文件中的现有内容冲突。
- **增强提取**：支持通过 `--extra` 参数手动指定需要脱敏的额外域名，解决非标准格式的提取盲区。
- **完美还原**：生成加密映射表 (`.map.json`)，支持一键解密还原。

## 安装要求

- Python 3.7+ (推荐 Python 3.12+)
- 无需第三方依赖库

## 使用方法

### 1. 加密 (脱敏)

将 `test.har` 中的所有域名替换为占位符：

```bash
python domain_scrambler.py encrypt test.har
```

**增强模式**：如果某些域名没有 `http` 前缀（例如隐藏在自定义 Header 中），可以使用 `--extra` 手动指定：

```bash
python domain_scrambler.py encrypt test.har --extra internal.api.local my-secret-domain.com
```

执行后：
- `test.har` 将被修改，真实域名被替换。
- 自动生成 `test.har.map.json` 映射文件。

### 2. 解密 (还原)

使用映射表将脱敏后的文件还原：

```bash
python domain_scrambler.py decrypt test.har
```

*默认会寻找同名的 `.map.json` 文件。如果映射表在其他位置，可以使用 `--map` 参数：*

```bash
python domain_scrambler.py decrypt test.har --map my_custom_mapping.json
```

## 命令行参数说明

| 参数 | 说明 |
| :--- | :--- |
| `mode` | 必选：`encrypt` (加密) 或 `decrypt` (解密) |
| `file` | 必选：目标 HAR 文件的路径 |
| `--map` | 可选：指定映射表的路径（默认：文件名 + `.map.json`） |
| `--extra` | 可选：额外需要加密的域名列表（仅加密模式有效） |

## 注意事项

1. **备份数据**：脚本会直接修改原始文件，建议在操作前备份您的 HAR 文件。
2. **映射表安全**：`.map.json` 文件包含了真实域名与占位符的对应关系，请妥善保管，不要泄露给未经授权的人员。
3. **占位符后缀**：默认使用 `.test` 作为占位符后缀，这是 RFC 2606 保留的顶级域名，不会在公网解析，非常安全。

## 逻辑原理

1. **提取**：扫描文件中所有 `http(s)://` 模式的域名，并结合 `--extra` 参数生成待处理列表。
2. **映射**：为每个域名分配一个 `devN.example.test` 占位符，并进行冲突检查。
3. **排序**：按域名长度**降序排列**，确保长域名（如 `api.example.com`）优先于短域名（如 `example.com`）被替换，防止部分替换错误。
4. **替换**：使用复合正则表达式进行单次全文扫描，利用边界判定保护非域名数据。
