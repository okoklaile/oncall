"""腾讯云 CLS (Cloud Log Service) MCP Server

本地实现的 CLS 日志服务 MCP Server，提供日志查询、检索和分析功能。
"""

import logging
import functools
import json
from typing import Dict, Any, Optional
from datetime import datetime, timedelta
from fastmcp import FastMCP

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("CLS_MCP_Server")

mcp = FastMCP("CLS")


def log_tool_call(func):
    """装饰器：记录工具调用的日志，包括方法名、参数和返回状态"""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        method_name = func.__name__

        # 记录调用信息
        logger.info(f"=" * 80)
        logger.info(f"调用方法: {method_name}")

        # 记录参数（排除self等）
        if kwargs:
            # 使用 json.dumps 格式化参数，处理可能的序列化错误
            try:
                params_str = json.dumps(kwargs, ensure_ascii=False, indent=2)
            except (TypeError, ValueError):
                params_str = str(kwargs)
            logger.info(f"参数信息:\n{params_str}")
        else:
            logger.info("参数信息: 无")

        # 执行方法
        try:
            result = func(*args, **kwargs)

            # 记录返回状态
            logger.info(f"返回状态: SUCCESS")

            # 记录返回结果摘要（避免日志过长）
            if isinstance(result, dict):
                summary = {k: v if not isinstance(v, (list, dict)) else f"<{type(v).__name__} with {len(v)} items>"
                          for k, v in list(result.items())[:5]}
                logger.info(f"返回结果摘要: {json.dumps(summary, ensure_ascii=False)}")
            else:
                logger.info(f"返回结果: {result}")

            logger.info(f"=" * 80)
            return result

        except Exception as e:
            # 记录错误状态
            logger.error(f"返回状态: ERROR")
            logger.error(f"错误信息: {str(e)}")
            logger.error(f"=" * 80)
            raise

    return wrapper


def parse_time_or_default(time_str: Optional[str], default_offset_hours: int = 0) -> datetime:
    """解析时间字符串或返回默认时间。

    Args:
        time_str: 时间字符串（格式：YYYY-MM-DD HH:MM:SS）
        default_offset_hours: 默认时间偏移（小时）

    Returns:
        datetime: 解析后的时间对象
    """
    if time_str:
        try:
            return datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass
    return datetime.now() + timedelta(hours=default_offset_hours)


def generate_time_series(base_time: datetime, minutes_offset: int) -> str:
    """生成基于基准时间的时间字符串。

    Args:
        base_time: 基准时间
        minutes_offset: 分钟偏移量

    Returns:
        str: 格式化的时间字符串
    """
    result_time = base_time + timedelta(minutes=minutes_offset)
    return result_time.strftime("%Y-%m-%d %H:%M:%S")


@mcp.tool()
@log_tool_call
def get_current_timestamp() -> int:
    """获取当前时间戳（以毫秒为单位）。
    
    此工具用于获取标准的毫秒时间戳，可用于：
    1. 作为 search_log 的 end_time 参数（查询到现在）
    2. 计算历史时间点作为 start_time 参数
    
    Returns:
        int: 当前时间戳（毫秒），例如: 1708012345000
    
    使用示例:
        # 获取当前时间
        current = get_current_timestamp()
        
        # 计算15分钟前的时间
        fifteen_min_ago = current - (15 * 60 * 1000)
        
        # 计算1小时前的时间
        one_hour_ago = current - (60 * 60 * 1000)
        
        # 用于搜索最近15分钟的日志
        search_log(
            topic_id="topic-001",
            start_time=fifteen_min_ago,
            end_time=current
        )
    """
    return int(datetime.now().timestamp() * 1000)


@mcp.tool()
@log_tool_call
def get_region_code_by_name(region_name: str) -> Dict[str, Any]:
    """根据地区名称搜索对应的地区参数。

    Args:
        region_name: 地区名称（如：北京、上海、广州等）

    Returns:
        Dict: 包含地区代码和相关信息的字典
            - region_code: 地区代码
            - region_name: 地区名称
            - available: 是否可用
    """
    # 模拟地区映射表（实际应该从配置或数据库读取）
    region_mapping = {
        "北京": {"region_code": "ap-beijing", "region_name": "北京", "available": True},
        "上海": {"region_code": "ap-shanghai", "region_name": "上海", "available": True},
        "广州": {"region_code": "ap-guangzhou", "region_name": "广州", "available": True},
    }

    result = region_mapping.get(region_name)
    if result:
        return result
    else:
        return {
            "region_code": None,
            "region_name": region_name,
            "available": False,
            "error": f"未找到地区: {region_name}"
        }


@mcp.tool()
@log_tool_call
def get_topic_info_by_name(topic_name: str, region_code: Optional[str] = None) -> Dict[str, Any]:
    """根据主题名称搜索相关的主题信息。

    Args:
        topic_name: 主题名称
        region_code: 地区代码（可选）

    Returns:
        Dict: 包含主题信息的字典
    """
    mock_topics = [
        {
            "topic_id": "topic-001",
            "topic_name": "数据同步服务日志",
            "service_name": "data-sync-service",
            "region_code": "ap-beijing",
            "create_time": "2024-01-01 10:00:00",
            "log_count": 12500,
            "description": "服务应用日志"
        },
        {
            "topic_id": "topic-002",
            "topic_name": "数据同步服务错误日志",
            "service_name": "data-sync-service",
            "region_code": "ap-beijing",
            "create_time": "2024-01-01 10:00:00",
            "log_count": 450,
            "description": "数据同步服务的错误日志"
        },
        {
            "topic_id": "topic-003",
            "topic_name": "API网关服务日志",
            "service_name": "api-gateway-service",
            "region_code": "ap-shanghai",
            "create_time": "2024-01-01 10:00:00",
            "log_count": 89000,
            "description": "API网关服务日志"
        }
    ]

    # 根据名称和地区筛选
    for topic in mock_topics:
        if topic["topic_name"] == topic_name:
            if region_code is None or topic["region_code"] == region_code:
                return topic

    return {
        "topic_id": None,
        "topic_name": topic_name,
        "region_code": region_code,
        "error": f"未找到主题: {topic_name}"
    }


@mcp.tool()
@log_tool_call
def search_topic_by_service_name(
    service_name: str,
    region_code: Optional[str] = None,
    fuzzy: bool = True
) -> Dict[str, Any]:
    """根据服务名称搜索相关的日志主题信息，支持模糊搜索。
    
    此工具用于根据服务名称查找对应的日志主题（topic），便于后续进行日志查询。
    
    Args:
        service_name: 服务名称（必填）
            示例: "data-sync-service", "sync", "data-sync"
            说明: 当 fuzzy=True 时，支持部分匹配
        
        region_code: 地区代码（可选）
            示例: "ap-beijing", "ap-shanghai"
            说明: 如果指定，只返回该地区的主题
        
        fuzzy: 是否启用模糊搜索（可选，默认 True）
            True: 部分匹配，例如 "sync" 可以匹配 "data-sync-service"
            False: 精确匹配，必须完全一致
    
    Returns:
        Dict: 搜索结果
            - total: 匹配到的主题数量
            - topics: 主题列表，每个主题包含:
                * topic_id: 主题ID（用于后续日志查询）
                * topic_name: 主题名称
                * service_name: 服务名称
                * region_code: 所属地区
                * create_time: 创建时间
                * log_count: 日志数量
                * description: 主题描述
            - query: 查询条件
    
    使用示例:
        # 示例1: 模糊搜索（推荐）
        search_topic_by_service_name(service_name="data-sync")
        # 可以匹配: "data-sync-service", "data-sync-worker" 等
        
        # 示例2: 精确搜索
        search_topic_by_service_name(
            service_name="data-sync-service",
            fuzzy=False
        )
        
        # 示例3: 指定地区搜索
        search_topic_by_service_name(
            service_name="sync",
            region_code="ap-beijing"
        )
        
        # 示例4: 查找后进行日志搜索的完整流程
        # 步骤1: 根据服务名查找 topic
        result = search_topic_by_service_name(service_name="data-sync-service")
        
        # 步骤2: 获取 topic_id
        topic_id = result["topics"][0]["topic_id"]  # "topic-001"
        
        # 步骤3: 使用 topic_id 查询日志
        current_ts = get_current_timestamp()
        start_ts = current_ts - (15 * 60 * 1000)
        search_log(
            topic_id=topic_id,
            start_time=start_ts,
            end_time=current_ts
        )
    """
    # Mock 主题数据（实际应该从配置或数据库读取）
    mock_topics = [
        {
            "topic_id": "topic-001",
            "topic_name": "数据同步服务日志",
            "service_name": "data-sync-service",
            "region_code": "ap-beijing",
            "create_time": "2024-01-01 10:00:00",
            "log_count": 0,
            "description": "数据同步服务的应用日志，包含同步任务执行情况"
        },
        {
            "topic_id": "topic-002",
            "topic_name": "数据同步服务错误日志",
            "service_name": "data-sync-service",
            "region_code": "ap-beijing",
            "create_time": "2024-01-01 10:00:00",
            "log_count": 0,
            "description": "数据同步服务的错误日志"
        },
        {
            "topic_id": "topic-003",
            "topic_name": "API网关服务日志",
            "service_name": "api-gateway-service",
            "region_code": "ap-shanghai",
            "create_time": "2024-01-01 10:00:00",
            "log_count": 0,
            "description": "API网关服务日志"
        }
    ]
    
    matched_topics = []
    
    # 搜索逻辑
    for topic in mock_topics:
        # 地区筛选
        if region_code and topic["region_code"] != region_code:
            continue
        
        # 服务名称匹配
        topic_service_name = topic.get("service_name", "")
        
        if fuzzy:
            # 模糊匹配：服务名包含查询字符串，或查询字符串包含服务名
            if (service_name.lower() in topic_service_name.lower() or 
                topic_service_name.lower() in service_name.lower()):
                matched_topics.append(topic)
        else:
            # 精确匹配
            if topic_service_name == service_name:
                matched_topics.append(topic)
    
    return {
        "total": len(matched_topics),
        "topics": matched_topics,
        "query": {
            "service_name": service_name,
            "region_code": region_code,
            "fuzzy": fuzzy
        },
        "message": f"找到 {len(matched_topics)} 个匹配的日志主题" if matched_topics else f"未找到服务 '{service_name}' 的日志主题"
    }


@mcp.tool()
@log_tool_call
def search_log(
    topic_id: str,
    start_time: int,
    end_time: int,
    query: Optional[str] = None,
    limit: int = 100
) -> Dict[str, Any]:
    """基于提供的查询参数搜索日志。

    Args:
        topic_id: 主题ID（必填）
            示例: "topic-001" (应用日志), "topic-002" (错误日志), "topic-003" (网关日志)
        
        start_time: 开始时间戳，单位为毫秒（必填，int类型）
        
        end_time: 结束时间戳，单位为毫秒（必填，int类型）
        
        query: 查询语句（可选，支持关键词过滤如 "ERROR", "timeout", "alert" 等）
        
        limit: 返回结果数量限制（默认100，可选）

    Returns:
        Dict: 搜索结果
    """
    # 预定义的 Mock 日志模板库
    MOCK_LOG_TEMPLATES = {
        "topic-001": [
            {"level": "INFO", "message": "正在同步元数据，当前进度: {progress}%"},
            {"level": "INFO", "message": "连接数据库成功: db-cluster-01.internal"},
            {"level": "INFO", "message": "数据分片 {shard_id} 同步任务启动"},
            {"level": "WARN", "message": "检测到网络抖动，正在重试连接 (第 {retry} 次)"},
            {"level": "INFO", "message": "同步任务完成，耗时: {duration}ms, 成功: {count}条"},
        ],
        "topic-002": [
            {"level": "ERROR", "message": "数据同步失败: 连接超时 (Connection Timeout)"},
            {"level": "ERROR", "message": "权限拒绝: 无法访问目标 Topic 'user_profile'"},
            {"level": "ALERT", "message": "核心同步链路中断！正在触发自动扩容"},
            {"level": "ERROR", "message": "数据库死锁检测到: Transaction ID {tx_id}"},
            {"level": "ERROR", "message": "解析元数据失败: 格式非法 (Invalid Format)"},
        ],
        "topic-003": [
            {"level": "INFO", "message": "请求接入: POST /v1/api/sync, 来源IP: {ip}"},
            {"level": "INFO", "message": "请求转发成功 -> 转发到 backend-service-01"},
            {"level": "ERROR", "message": "上游服务响应超时: 504 Gateway Timeout"},
            {"level": "ERROR", "message": "限流触发: 超过每秒最大请求数 (QPS Limit Exceeded)"},
            {"level": "INFO", "message": "请求处理完成, 状态码: {status}, 耗时: {latency}ms"},
        ]
    }

    if topic_id not in MOCK_LOG_TEMPLATES:
        return {
            "topic_id": topic_id,
            "total": 0,
            "logs": [],
            "error": f"主题不存在: {topic_id}",
            "message": f"错误: 未找到主题 {topic_id}，请检查是否正确"
        }

    templates = MOCK_LOG_TEMPLATES[topic_id]
    logs = []
    
    # 模拟简单的关键词搜索（支持空格或 OR 分隔）
    import re
    if query:
        # 将 "alert OR ERROR" 转换为 ["ALERT", "ERROR"]
        keywords = re.split(r'\s+OR\s+|\s+', query.upper())
        # 过滤掉空字符串
        keywords = [k for k in keywords if k]
        
        filtered_templates = []
        for t in templates:
            level_upper = t["level"].upper()
            msg_upper = t["message"].upper()
            # 只要匹配其中一个关键词就包含该模板
            if any(k in level_upper or k in msg_upper for k in keywords):
                filtered_templates.append(t)
    else:
        filtered_templates = templates
    
    if not filtered_templates:
        # 如果关键词过滤后没有模板，直接返回空
        return {
            "topic_id": topic_id,
            "total": 0,
            "logs": [],
            "message": f"查询 '{query}' 未匹配到任何日志内容"
        }

    # 模拟生成日志
    import random
    current_time_ms = start_time
    # 每分钟产生一条日志，直到结束或达到限制
    interval_ms = max(60 * 1000, (end_time - start_time) // limit) if limit > 0 else 60 * 1000
    
    while current_time_ms <= end_time and len(logs) < limit:
        template = random.choice(filtered_templates)
        log_time = datetime.fromtimestamp(current_time_ms / 1000)
        
        # 填充随机变量
        message = template["message"].format(
            progress=random.randint(1, 100),
            shard_id=random.randint(0, 50),
            retry=random.randint(1, 3),
            duration=random.randint(100, 5000),
            count=random.randint(1000, 50000),
            tx_id=random.randint(100000, 999999),
            ip=f"10.0.{random.randint(1, 254)}.{random.randint(1, 254)}",
            status=random.choice([200, 200, 200, 404, 500]),
            latency=random.randint(10, 2000)
        )
        
        logs.append({
            "timestamp": log_time.strftime("%Y-%m-%d %H:%M:%S"),
            "level": template["level"],
            "message": message
        })
        
        current_time_ms += interval_ms

    # 按时间倒序排序（通常日志查询返回最新的在前面）
    logs.sort(key=lambda x: x["timestamp"], reverse=True)

    return {
        "topic_id": topic_id,
        "start_time": start_time,
        "end_time": end_time,
        "query": query,
        "limit": limit,
        "total": len(logs),
        "logs": logs,
        "took_ms": random.randint(10, 100),
        "message": f"成功查询到 {len(logs)} 条日志"
    }



if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="127.0.0.1", port=8003, path="/mcp")
