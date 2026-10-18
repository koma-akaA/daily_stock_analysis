# -*- coding: utf-8 -*-
"""
PushPlus 发送提醒服务

职责：
1. 通过 PushPlus API 发送 PushPlus 消息
"""
import logging
import time
from typing import Optional
from datetime import datetime
import requests

from src.config import Config
from src.formatters import chunk_content_by_max_bytes, strip_hidden_markdown_metadata


logger = logging.getLogger(__name__)


class PushplusSender:
    
    def __init__(self, config: Config):
        """
        初始化 PushPlus 配置

        Args:
            config: 配置对象
        """
        self._pushplus_token = getattr(config, 'pushplus_token', None)
        self._pushplus_topic = getattr(config, 'pushplus_topic', None)
        self._pushplus_max_bytes = getattr(config, 'pushplus_max_bytes', 20000)
        self.last_delivery_status = "not_sent"
        self.last_response_code = None
        self.last_short_codes = []
        
    def send_to_pushplus(
        self,
        content: str,
        title: Optional[str] = None,
        *,
        timeout_seconds: Optional[float] = None,
    ) -> bool:
        """
        推送消息到 PushPlus

        PushPlus API 格式：
        POST http://www.pushplus.plus/send
        {
            "token": "用户令牌",
            "title": "消息标题",
            "content": "消息内容",
            "template": "html/txt/json/markdown"
        }

        PushPlus 特点：
        - 国内推送服务，免费额度充足
        - 支持微信公众号推送
        - 支持多种消息格式

        Args:
            content: 消息内容（Markdown 格式）
            title: 消息标题（可选）

        Returns:
            是否发送成功
        """
        if not self._pushplus_token:
            logger.warning("PushPlus Token 未配置，跳过推送")
            return False

        self.last_delivery_status = "unknown"
        self.last_response_code = None
        self.last_short_codes = []
        api_url = "https://www.pushplus.plus/send"

        if title is None:
            date_str = datetime.now().strftime('%Y-%m-%d')
            title = f"📈 股票分析报告 - {date_str}"
        sanitized_content = strip_hidden_markdown_metadata(content).strip()

        try:
            content_bytes = len(sanitized_content.encode('utf-8'))
            if content_bytes > self._pushplus_max_bytes:
                logger.info(
                    "PushPlus 消息内容超长(%s字节/%s字符)，将分批发送",
                    content_bytes,
                    len(sanitized_content),
                )
                return self._send_pushplus_chunked(
                    api_url,
                    sanitized_content,
                    title,
                    self._pushplus_max_bytes,
                )

            return self._send_pushplus_message(
                api_url,
                sanitized_content,
                title,
                timeout_seconds=timeout_seconds,
            )
        except Exception as e:
            # Transport exceptions may include credentials from echoed request bodies.
            logger.error("PushPlus 请求结果未知(%s)，为避免重复消息不自动重发", type(e).__name__)
            return False

    def _send_pushplus_message(
        self,
        api_url: str,
        content: str,
        title: str,
        *,
        timeout_seconds: Optional[float] = None,
    ) -> bool:
        payload = {
            "token": self._pushplus_token,
            "title": title[:100],
            "content": content,
            "template": "markdown",
            "channel": "wechat",
        }

        if self._pushplus_topic:
            payload["topic"] = self._pushplus_topic

        response = requests.post(api_url, json=payload, timeout=timeout_seconds or 10)

        if response.status_code == 200:
            result = response.json()
            code = result.get('code')
            self.last_response_code = code if isinstance(code, int) else None
            if result.get('code') == 200:
                self.last_delivery_status = "accepted"
                if isinstance(result.get("data"), str):
                    self.last_short_codes.append(result["data"])
                logger.info("PushPlus 已受理；最终微信送达尚未确认")
                return True

            self.last_delivery_status = "rejected"
            logger.error("PushPlus 拒绝请求，code=%s；请在官方最新请求记录中排查", self.last_response_code)
            return False

        self.last_delivery_status = "unknown" if response.status_code >= 500 else "rejected"
        logger.error(f"PushPlus 请求失败: HTTP {response.status_code}")
        return False

    def _send_pushplus_chunked(self, api_url: str, content: str, title: str, max_bytes: int) -> bool:
        """分批发送长 PushPlus 消息，给 JSON payload 预留空间。"""
        budget = max(1000, max_bytes - 1500)
        chunks = chunk_content_by_max_bytes(content, budget, add_page_marker=True)
        total_chunks = len(chunks)
        success_count = 0

        logger.info(f"PushPlus 分批发送：共 {total_chunks} 批")

        for i, chunk in enumerate(chunks):
            chunk_title = f"{title} ({i+1}/{total_chunks})" if total_chunks > 1 else title
            if self._send_pushplus_message(api_url, chunk, chunk_title):
                success_count += 1
                logger.info(f"PushPlus 第 {i+1}/{total_chunks} 批发送成功")
            else:
                logger.error(f"PushPlus 第 {i+1}/{total_chunks} 批发送失败")
                return False

            if i < total_chunks - 1:
                time.sleep(13)  # Free authenticated accounts: at most five requests/minute.

        return success_count == total_chunks
