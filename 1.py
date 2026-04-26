# test_mcp_tools.py
import asyncio
from app.agent.mcp_client import get_mcp_client

async def main():
    client = await get_mcp_client()
    
    # 列出所有服务器的工具
    print("=== 所有 MCP 服务器工具 ===\n")
    
    # 方式1：获取所有服务器的工具
    try:
        all_tools = await client.get_tools()
        print(f"总共 {len(all_tools)} 个工具:")
        for tool in all_tools:
            print(f"  ✓ {tool.name}")
            if tool.description:
                print(f"    {tool.description[:100]}...")
    except Exception as e:
        print(f"获取所有工具失败: {e}")
    
    # 方式2：按服务器分别获取
    print("\n=== 按服务器分类 ===\n")
    for server_name in ["cls", "monitor"]:
        try:
            tools = await client.get_tools(server_name=server_name)
            print(f"{server_name} 服务器有 {len(tools)} 个工具:")
            for tool in tools:
                print(f"  - {tool.name}")
        except Exception as e:
            print(f"获取 {server_name} 工具列表失败: {e}")

asyncio.run(main())