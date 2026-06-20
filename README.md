# SQL → RE Diagram Generator

解析 SQL 文件，提取数据库/表/字段/关联关系，生成交互式 HTML 关系图（RE Diagram）。

## 功能

- 解析 `db::table` 多库引用
- 识别 FROM/JOIN 子句提取表与别名
- 提取 ON 条件中的字段关联关系（LEFT / INNER / FULL JOIN）
- 提取 SELECT / WHERE / GROUP BY / ORDER BY 中的字段
- 子查询递归解析
- 多段 SQL 分割处理，支持 **全部合并** 与 **逐段查看**
- 生成交互式 HTML（D3.js 力导向图）
  - 数据库分色分组
  - 拖拽、缩放、自适应
  - 点击表卡片查看字段详情与关联关系

## 快速开始

```bash
# 解析 SQL 并生成 HTML
python sql_to_re.py test.sql

# 指定输出路径
python sql_to_re.py test_multi.sql output.html
```

### 输入示例

```sql
SELECT a.uid, a.name, b.amount
FROM dwd::user_table a
LEFT JOIN dim::info_table b ON a.uid = b.uid
WHERE a.ftime = '20260619'
```

### 输出

一个包含 D3.js 力导向图的 HTML 文件，在浏览器打开即可交互查看。

## 测试

```bash
python test_smoke.py
```

## 依赖

- Python ≥ 3.8（纯标准库，无需第三方包）
- 浏览器（打开生成的 HTML）

## 项目结构

```
├── sql_to_re.py       # 主程序：解析器 + HTML 生成器
├── test_smoke.py      # 冒烟测试
├── test.sql           # 单段 SQL 测试文件
├── test_multi.sql     # 多段 SQL 测试文件
├── test_re.html       # 生成的关系图（单段）
├── test_multi.html    # 生成的关系图（多段）
├── 思路.txt            # 设计思路
└── requirements.txt
```
