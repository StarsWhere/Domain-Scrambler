#!/usr/bin/env python3
"""
HAR 域名脱敏工具
功能：将 HAR 文件中的真实域名替换为占位符开发域名，并生成映射表以便后续还原。
加密时会创建一个同名的映射文件（文件名 + ".map.json"），解密时需要读取该文件。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Tuple


# 用于匹配 http/https 链接中的域名部分
# 分组：scheme (协议), host (主机名，包含 IPv6 括号或端口)
URL_PATTERN = re.compile(
    r"(?P<scheme>https?)://(?P<host>\[[^\]]+\]|[A-Za-z0-9._-]+(?:\:[0-9]+)?)"
)

# 占位符根域名；".test" 是 RFC 2606 保留的顶级域名，专门用于测试，不会在公网解析。
PLACEHOLDER_ROOT = "example.test"


def extract_hosts(text: str, extra_hosts: List[str] | None = None) -> List[str]:
    """
    从文本中提取唯一的域名（如果存在端口则包含端口）。
    按发现顺序返回，确保处理的一致性。
    """
    seen = set()
    hosts: List[str] = []
    
    # 1. 通过正则表达式从 URL 模式中提取
    for m in URL_PATTERN.finditer(text):
        host = m.group("host")
        if host not in seen:
            seen.add(host)
            hosts.append(host)
            
    # 2. 添加用户通过命令行指定的额外域名（处理提取盲区）
    if extra_hosts:
        for host in extra_hosts:
            if host and host not in seen:
                seen.add(host)
                hosts.append(host)
                
    return hosts


def build_mapping(
    hosts: Iterable[str], existing_text: str
) -> Tuple[Dict[str, str], Dict[str, str]]:
    """
    创建 原始域名->占位符 和 占位符->原始域名 的双向映射表。
    确保生成的占位符不会与原始文本中的现有内容冲突。
    """
    orig_to_fake: Dict[str, str] = {}
    fake_to_orig: Dict[str, str] = {}
    counter = 1

    for host in hosts:
        # 循环直到生成一个在原文件中不存在的唯一占位符
        while True:
            candidate = f"dev{counter}.{PLACEHOLDER_ROOT}"
            counter += 1
            
            # 如果原始域名包含端口，占位符也需要保留端口
            # 增强了对 IPv6 格式（如 [::1]:8080）的处理
            if ":" in host:
                if host.startswith("["):
                    # 处理带括号的 IPv6
                    if "]:" in host:
                        _, _, port_part = host.rpartition(":")
                        placeholder = f"{candidate}:{port_part}"
                    else:
                        placeholder = candidate
                else:
                    # 处理常规域名或 IPv4 带端口
                    _, _, port_part = host.partition(":")
                    if port_part.isdigit():
                        placeholder = f"{candidate}:{port_part}"
                    else:
                        placeholder = candidate
            else:
                placeholder = candidate

            # 冲突检查：
            # 1. 占位符本身不在原文件中
            # 2. 占位符的根部分不在原文件中
            # 3. 占位符尚未被分配
            if (
                placeholder in existing_text
                or candidate in existing_text
                or placeholder in fake_to_orig
            ):
                continue
            break

        orig_to_fake[host] = placeholder
        fake_to_orig[placeholder] = host

    return orig_to_fake, fake_to_orig


def replace_all(text: str, mapping: Dict[str, str]) -> str:
    """
    使用单次正则扫描替换文本中所有匹配的键。
    1. 按键长度降序排列，防止“子域名”被“父域名”部分替换（如 api.a.com 和 a.com）。
    2. 使用正则边界判定，确保不会误伤 Base64 等长字符串。
    """
    if not mapping:
        return text

    # 按长度降序排列，确保最长的匹配项优先被替换
    sorted_keys = sorted(mapping.keys(), key=len, reverse=True)
    
    # 构建复合正则表达式
    # 边界判定：前后不能出现域名合法的字符（字母、数字、点、下划线、连字符、冒号）
    pattern = re.compile(
        rf"(?<![A-Za-z0-9._:-])({'|'.join(re.escape(k) for k in sorted_keys)})(?![A-Za-z0-9._:-])"
    )
    
    # 使用回调函数进行一次性替换，性能最优
    return pattern.sub(lambda m: mapping[m.group(0)], text)


def encrypt(path: Path, extra_hosts: List[str] | None = None) -> None:
    """加密流程：提取域名 -> 构建映射 -> 全文替换 -> 保存文件和映射表"""
    try:
        original_text = path.read_text(encoding="utf-8")
    except Exception as e:
        raise SystemExit(f"读取文件失败 {path}: {e}")

    # 提取所有需要脱敏的域名
    hosts = extract_hosts(original_text, extra_hosts)
    if not hosts:
        raise SystemExit("未发现可加密的域名。请尝试使用 --extra 参数手动指定。")

    # 生成映射关系
    orig_to_fake, fake_to_orig = build_mapping(hosts, original_text)
    
    # 执行全文替换
    encrypted_text = replace_all(original_text, orig_to_fake)

    try:
        # 写回加密后的内容
        path.write_text(encrypted_text, encoding="utf-8")
    except Exception as e:
        raise SystemExit(f"写入加密文件失败: {e}")

    # 保存映射表（JSON 格式）
    map_path = path.with_suffix(path.suffix + ".map.json")
    map_payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "placeholder_root": PLACEHOLDER_ROOT,
        "original_to_placeholder": orig_to_fake,
        "placeholder_to_original": fake_to_orig,
    }
    
    try:
        map_path.write_text(json.dumps(map_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        raise SystemExit(f"保存映射文件失败: {e}")
        
    print(f"成功加密 {path} (共 {len(hosts)} 个唯一域名)。映射表已保存至 {map_path}。")


def decrypt(path: Path, map_path: Path | None) -> None:
    """解密流程：读取映射表 -> 全文还原 -> 保存文件"""
    if map_path is None:
        map_path = path.with_suffix(path.suffix + ".map.json")
    if not map_path.exists():
        raise SystemExit(f"未找到映射文件: {map_path}")

    try:
        # 加载映射数据
        mapping_data = json.loads(map_path.read_text(encoding="utf-8"))
        placeholder_to_original: Dict[str, str] = mapping_data.get("placeholder_to_original") or {}
    except Exception as e:
        raise SystemExit(f"读取映射文件失败: {e}")

    if not placeholder_to_original:
        raise SystemExit("映射文件中缺少 'placeholder_to_original' 字段。")

    try:
        text = path.read_text(encoding="utf-8")
    except Exception as e:
        raise SystemExit(f"读取目标文件失败: {e}")

    # 执行还原替换
    restored_text = replace_all(text, placeholder_to_original)
    
    try:
        path.write_text(restored_text, encoding="utf-8")
    except Exception as e:
        raise SystemExit(f"写入解密文件失败: {e}")
        
    print(f"成功解密 {path}，使用映射表: {map_path}。")


def parse_args() -> argparse.Namespace:
    """命令行参数解析"""
    parser = argparse.ArgumentParser(
        description="HAR 域名脱敏工具：使用映射表加密或解密 HAR 文件中的域名。"
    )
    parser.add_argument("mode", choices=["encrypt", "decrypt"], help="操作模式：encrypt (加密) 或 decrypt (解密)")
    parser.add_argument("file", type=Path, help="目标 HAR 文件的路径")
    parser.add_argument(
        "--map",
        dest="map_file",
        type=Path,
        help="可选：映射文件的路径（默认使用 <文件名>.map.json）",
    )
    parser.add_argument(
        "--extra",
        nargs="+",
        help="可选：额外需要加密的域名列表（例如：--extra example.com api.internal）",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.file.exists():
        raise SystemExit(f"目标文件不存在: {args.file}")

    if args.mode == "encrypt":
        encrypt(args.file, args.extra)
    else:
        decrypt(args.file, args.map_file)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n用户取消操作。")
        sys.exit(1)
