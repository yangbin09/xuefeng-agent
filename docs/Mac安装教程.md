# 雪峰Agent 安装教程（Mac 版）

> 不需要懂编程，跟着步骤走，10 分钟搞定。

---

## 第一步：装 Python

### 检查是否已安装

1. 按 `Cmd + 空格`，输入 `终端`，回车打开终端
2. 输入 `python3 --version`，回车

如果显示 `Python 3.10.x` 或更高 → **已安装，跳到第二步**。

如果显示 `command not found` → 继续往下看。

### 下载安装

1. 打开浏览器，输入 **python.org**
2. 点黄色大按钮下载
3. 双击下载的 `.pkg` 文件，一路继续
4. 装完后关闭

---

## 第二步：下载雪峰Agent

1. 打开 **github.com/ziqihe10-droid/xuefeng-agent**
2. 点右侧绿色 **Code** 按钮 → **Download ZIP**
3. 下载完双击解压到桌面
4. 打开解压出来的文件夹

---

## 第三步：搞个 DeepSeek Key

1. 打开 **platform.deepseek.com**，注册登录
2. 左侧点 **API Keys** → 创建 → 复制 `sk-` 开头的那串（只显示一次，保存好）

---

## 第四步：启动

### 方法一：双击打开我.html（推荐）

1. 先打开终端（`Cmd + 空格` → 输入 `终端`）
2. 把文件夹拖到终端窗口，终端里会出现文件夹路径，回车进入
3. 输入 `python3 server.py`，回车
4. 看到 `雪峰Agent: http://127.0.0.1:8765/` 说明服务器跑起来了
5. 双击文件夹里的 **打开我.html**，会自动跳转到主界面

### 方法二：手动访问

服务器跑起来后，浏览器直接输入 `http://127.0.0.1:8765/`

---

## 第五步：配置 API

1. 点右上角红色 **API设置**
2. 填写：
   - Base URL：`https://api.deepseek.com`
   - API Key：粘贴你的 `sk-` 钥匙
   - Model：`deepseek-chat`
   - Tavily Key：选填，推荐去 **tavily.com** 免费注册一个
3. 点 **保存并测试**，显示绿色连接OK就行

---

## 第六步：开问

跟聊天一样打字：

```
浙江物理类655分，位次10500，想学计算机软件电子，帮我盘冲稳保
```

---

## 以后怎么用

1. 打开终端 → 进入文件夹
2. `python3 server.py`
3. 双击 `打开我.html` 或浏览器访问 `http://127.0.0.1:8765/`

> 觉得每次输命令麻烦？往下看「一键启动」

---

## 一键启动（可选）

在文件夹里新建一个文件叫 `启动.command`，内容写：

```bash
#!/bin/bash
cd "$(dirname "$0")"
python3 server.py
```

保存后在终端里给它权限：

```bash
chmod +x 启动.command
```

以后双击 `启动.command` 就能启动。

---

## 常见问题

**提示 "command not found: python3"？**
→ 没装 Python，去 python.org 下载安装。

**浏览器打开了但是空白？**
→ 等几秒刷新。或者地址栏输 `http://127.0.0.1:8765/`

**按钮点了没反应？**
→ 按 `Cmd + Shift + R` 强制刷新

**提示 "端口被占用"？**
→ 终端输入 `lsof -i :8765` 查看占用，`kill -9 进程号` 杀掉

**Tavily 搜索报错？**
→ 检查 Key 是否以 `tvly-` 开头。去 tavily.com 重新复制
