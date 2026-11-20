#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
洛克王国世界（roco）精灵数据爬取脚本

数据来源: https://wiki.biligame.com/nrc/ （BWiki，MediaWiki 架构）
数据所在: 站点的两个 Lua 数据模块
    - Module:Pets/data/Catalog     精灵基础数据（编号 / 名称 / 种族值 / 属性 / 阶段 / 形态 / 进化链 ID）
    - Module:Pets/data/Evolutions  进化链数据（主进化线 + 领主化分支）

输出: data/pets.csv

用法:
    python crawl_pets.py            拉取最新数据并生成 CSV
    python crawl_pets.py --cache    使用本地缓存（不联网），适用于离线重跑
"""

import csv
import json
import os
import re
import sys
import urllib.request

BASE = "https://wiki.biligame.com/nrc"
# 该站点启用了腾讯 EdgeOne 防护，缺少 UA / Referer 会被拦截（返回 567），必须带上
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"
    ),
    "Referer": BASE + "/%E7%B2%BE%E7%81%B5%E5%9B%BE%E9%89%B4",
    "Accept": "application/json",
    "Accept-Language": "zh-CN,zh;q=0.9",
}

# 两个数据模块的页面名（模块命名空间前缀 Module:）
CATALOG_PAGE = "Module:Pets/data/Catalog"
EVOLUTIONS_PAGE = "Module:Pets/data/Evolutions"

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cache")
OUT_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "pets.csv")

# CSV 表头及含义
#   number  精灵编号
#   name    精灵名称（中文）
#   hp      生命   atk 物攻   def 物防   spa 魔攻   spd 魔防   spe 速度（均为种族值整数）
#   types   属性（多个属性用 | 分隔，如 "虫系|翼系"）
#   stage   进化阶段（1 为初始形态，数值越大阶段越高）
#   form    形态（基础形态为空；形态变体如"首领形态""圣光形态"）
#   evolution_chain  进化链：从初始形态到该精灵自身为止的名称序列，用 "→" 连接
#                    （只写到自身结尾，分叉点之后的形态不展开；form 非空时以 name(form)
#                     显示；用名称而非编号，因领主化形态与前身共享编号，名称才能唯一区分）
FIELD_NAMES = [
    "number", "name", "hp", "atk", "def", "spa", "spd", "spe",
    "types", "stage", "form", "evolution_chain",
]


def fetch_wikitext(page):
    """通过 MediaWiki API 获取指定页面的 wikitext 源码。"""
    params = urllib.parse.urlencode({
        "action": "parse",
        "page": page,
        "prop": "wikitext",
        "format": "json",
    })
    url = BASE + "/api.php?" + params
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.load(resp)
    return data["parse"]["wikitext"]["*"]


def load_or_fetch(page, use_cache):
    """获取模块源码：优先读缓存，否则走网络并写缓存。"""
    # 把页面名（如 Module:Pets/data/Catalog）转成安全的文件名（Windows 下冒号非法）
    safe_name = page.replace("/", "_").replace(":", "_")
    cache_path = os.path.join(CACHE_DIR, safe_name + ".lua")
    if use_cache and os.path.exists(cache_path):
        with open(cache_path, encoding="utf-8") as f:
            return f.read()
    text = fetch_wikitext(page)
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(cache_path, "w", encoding="utf-8") as f:
        f.write(text)
    return text


class LuaParser:
    """解析 Lua 表字面量（形如 return {...}）。

    本站数据模块是纯数据表，只用到：嵌套表 {}、双引号字符串、整数、布尔、
    标识符键名（key=value 与纯数组两种形式）。不含注释、单引号串、[[长串]]。
    """

    def __init__(self, text):
        self.s = text
        self.i = 0

    def parse(self):
        self._ws()
        if self.s.startswith("return", self.i):
            self.i += len("return")
        value = self._value()
        return value

    def _ws(self):
        while self.i < len(self.s) and self.s[self.i] in " \t\r\n":
            self.i += 1

    def _value(self):
        self._ws()
        c = self.s[self.i]
        if c == "{":
            return self._table()
        if c == '"':
            return self._string()
        if c.isdigit() or c == "-" or c == ".":
            return self._number()
        if self.s.startswith("true", self.i):
            self.i += 4
            return True
        if self.s.startswith("false", self.i):
            self.i += 5
            return False
        if self.s.startswith("nil", self.i):
            self.i += 3
            return None
        # 未加引号的标识符值（理论上不应出现，容错处理）
        m = re.match(r"[A-Za-z_][A-Za-z0-9_]*", self.s[self.i:])
        if m:
            self.i += len(m.group())
            return m.group()
        raise ValueError(f"解析失败 @{self.i}: {self.s[self.i:self.i + 40]!r}")

    def _string(self):
        self.i += 1  # 跳过开引号
        start = self.i
        while self.i < len(self.s) and self.s[self.i] != '"':
            if self.s[self.i] == "\\":  # 跳过转义字符
                self.i += 2
            else:
                self.i += 1
        val = self.s[start:self.i]
        self.i += 1  # 跳过闭引号
        return val

    def _number(self):
        m = re.match(r"-?\d+(?:\.\d+)?", self.s[self.i:])
        if not m:
            raise ValueError(f"数字解析失败 @{self.i}")
        self.i += len(m.group())
        token = m.group()
        return float(token) if "." in token else int(token)

    def _table(self):
        self.i += 1  # 跳过 {
        self._ws()
        if self.s[self.i] == "}":  # 空表
            self.i += 1
            return {}

        if self._looks_like_dict():
            result = {}
            while True:
                key = self._key()
                self._ws()
                assert self.s[self.i] == "=", f"期望 '=' @{self.i}"
                self.i += 1
                result[key] = self._value()
                self._ws()
                if self.s[self.i] == ",":
                    self.i += 1
                    continue
                if self.s[self.i] == "}":
                    self.i += 1
                    break
                raise ValueError(f"表项缺少分隔符 @{self.i}")
            return result
        else:
            result = []
            while True:
                result.append(self._value())
                self._ws()
                if self.s[self.i] == ",":
                    self.i += 1
                    continue
                if self.s[self.i] == "}":
                    self.i += 1
                    break
                raise ValueError(f"数组项缺少分隔符 @{self.i}")
            return result

    def _looks_like_dict(self):
        """预判当前表是 key=value 形式还是纯数组形式。

        本站数据中，dict 的键名是标识符（如 name=...）或 ["字符串"]（如
        ["光系"]=...），而数组元素直接以 {、" 等开头（如 {"虫系","翼系"}）。
        因此仅当首个 token 是标识符且紧跟 =、或以 [ 开头（方括号键名）时
        判定为 dict，其余（含字符串开头）一律为数组。
        """
        if self.s[self.i] == "[":
            return True
        m = re.match(r"[A-Za-z_][A-Za-z0-9_]*", self.s[self.i:])
        if m:
            j = self.i + len(m.group())
            while j < len(self.s) and self.s[j] in " \t\r\n":
                j += 1
            return self.s[j:j + 1] == "="
        return False

    def _key(self):
        self._ws()
        if self.s[self.i] == "[":
            # ["光系"] 形式的方括号键名
            self.i += 1
            key = self._string()
            self._ws()
            assert self.s[self.i] == "]", f"期望 ']' @{self.i}"
            self.i += 1
            return key
        if self.s[self.i] == '"':
            return self._string()
        m = re.match(r"[A-Za-z_][A-Za-z0-9_]*", self.s[self.i:])
        if m:
            self.i += len(m.group())
            return m.group()
        raise ValueError(f"键名解析失败 @{self.i}")


def parse_pets(catalog_text):
    """解析 Catalog 模块，返回 {pet_id: 精灵信息字典}。"""
    root = LuaParser(catalog_text).parse()
    pets = {}
    for pet_id, raw in root.items():
        stats = raw.get("stats", {})
        pets[pet_id] = {
            "id": raw.get("id", pet_id),
            "name": raw.get("name", ""),
            "number": raw.get("number", ""),
            "hp": stats.get("hp", ""),
            "atk": stats.get("atk", ""),
            "def": stats.get("def", ""),
            "spa": stats.get("spa", ""),
            "spd": stats.get("spd", ""),
            "spe": stats.get("spe", ""),
            "types": "|".join(raw.get("types", [])) if isinstance(raw.get("types", []), list) else "",
            "stage": raw.get("stage", ""),
            "form": raw.get("form", ""),
            "evolution_id": raw.get("evolution_id", ""),
        }
    return pets


def parse_evolutions(evolutions_text):
    """解析 Evolutions 模块，返回 {evolution_id: [分支线列表]}。

    一个 evolution_id 可能对应多条分支线（数组里的多个 dict），例如迪莫
    可首领化成圣光/圣草/圣火/圣水四种形态，四条分支线都以迪莫为起点。
    每条分支线是一条按 stage 排序的成员列表，成员含 id / name / stage。
    """
    root = LuaParser(evolutions_text).parse()
    chains = {}
    for evo_id, raw in root.items():
        # raw 是分支线数组（可能 1 条或多条）；兼容 dict 形式
        branch_lines = raw if isinstance(raw, list) else [raw]
        lines = []
        for line in branch_lines:
            if not isinstance(line, dict):
                continue
            members = []
            for branch in ("chain", "lord_branches"):
                for node in line.get(branch, []):
                    if isinstance(node, dict) and node.get("id"):
                        members.append({
                            "id": node["id"],
                            "stage": node.get("stage", 0),
                            "name": node.get("name", ""),
                        })
            # 按 stage 排序，保证进化顺序正确（同 stage 稳定保持原始顺序）
            members.sort(key=lambda m: m["stage"])
            lines.append(members)
        chains[evo_id] = lines
    return chains


def format_member_name(member, id2form):
    """成员显示名：form 非空时以「name(form)」形式表示，否则用 name。"""
    name = member["name"]
    form = id2form.get(member["id"], "")
    return f"{name}({form})" if form else name


def build_chain_prefixes(chains, id2form):
    """为每只精灵构建进化链前缀序列（名称形式）。

    进化链只写到该精灵自身为止：对每条分支线，成员按 stage 递增，某成员
    的进化链 = 该分支线从起点到它自身（含）的成员序列。分叉点（如迪莫）
    之后的形态不属于它的进化链，因此不会出现「迪莫→圣光迪莫→圣草迪莫…」
    这种把分支拼成一串的结果。

    同一精灵若出现在多条分支线（如分叉点之前的形态），其前缀相同，取首次
    遇到的结果即可。
    """
    prefixes = {}
    for lines in chains.values():
        for members in lines:
            for i, member in enumerate(members):
                pid = member["id"]
                if pid not in prefixes:
                    prefixes[pid] = "→".join(
                        format_member_name(m, id2form) for m in members[:i + 1]
                    )
    return prefixes


def build_rows(pets, chains):
    """关联精灵与进化链，生成 CSV 行（按编号排序）。

    进化链列使用名称序列（而非编号），因为领主化形态与其前身共享同一个
    图鉴编号，用编号会出现 "084→084" 的歧义；名称则能唯一区分每个形态。
    """
    id2form = {pid: p["form"] for pid, p in pets.items()}
    prefixes = build_chain_prefixes(chains, id2form)

    rows = []
    for pid, p in pets.items():
        rows.append({
            "number": p["number"],
            "name": p["name"],
            "hp": p["hp"],
            "atk": p["atk"],
            "def": p["def"],
            "spa": p["spa"],
            "spd": p["spd"],
            "spe": p["spe"],
            "types": p["types"],
            "stage": p["stage"],
            "form": p["form"],
            # 未出现在任何进化线中的精灵（理论上不存在），退化为自身名称
            "evolution_chain": prefixes.get(pid, p["name"]),
        })

    # 按编号数值升序；同编号内按阶段升序（基础形态在前）
    rows.sort(key=lambda r: (int(r["number"]) if str(r["number"]).isdigit() else 0, r["stage"]))
    return rows


def main():
    use_cache = "--cache" in sys.argv

    print("拉取/读取 Catalog 模块...")
    catalog_text = load_or_fetch(CATALOG_PAGE, use_cache)
    print("拉取/读取 Evolutions 模块...")
    evolutions_text = load_or_fetch(EVOLUTIONS_PAGE, use_cache)

    print("解析数据...")
    pets = parse_pets(catalog_text)
    chains = parse_evolutions(evolutions_text)
    rows = build_rows(pets, chains)

    os.makedirs(os.path.dirname(OUT_CSV), exist_ok=True)
    with open(OUT_CSV, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELD_NAMES)
        writer.writeheader()
        writer.writerows(rows)

    print(f"完成：共 {len(rows)} 只精灵（含形态变体），进化链 {len(chains)} 条。")
    print(f"输出文件：{OUT_CSV}")


if __name__ == "__main__":
    main()
