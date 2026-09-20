import asyncio
import json
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def test_real_mcp_stdio(tmp_path):
    async def check():
        params = StdioServerParameters(command=sys.executable, args=["-m", "ehsan_mcp", "--data-dir", str(tmp_path), "serve"])
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as client:
                initialized = await client.initialize()
                assert initialized.serverInfo.name == "cisco-knight-multi-dev"
                catalog = await client.list_tools()
                assert len(catalog.tools) == 31
                devices = await client.call_tool("list_devices", {})
                assert not devices.isError
                assert json.loads(devices.content[0].text) == {"devices": []}
                setup = await client.call_tool("add_device", {})
                assert json.loads(setup.content[0].text)["arguments"][-1] == "setup"
                invalid = await client.call_tool("cisco_show", {"device": "missing", "command": "show version"})
                assert invalid.isError
    asyncio.run(check())
