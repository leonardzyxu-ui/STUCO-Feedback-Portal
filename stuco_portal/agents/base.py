import requests


class BaseAgent:
    name = "base-agent"

    def __init__(self, mcp_base_url, api_key=None, timeout=10):
        self.mcp_base_url = mcp_base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def _headers(self):
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def get_resource(self, resource_name, params=None):
        response = requests.get(
            f"{self.mcp_base_url}/mcp/resources/{resource_name}",
            params=params or {},
            headers=self._headers(),
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def call_tool(self, tool_name, payload=None):
        response = requests.post(
            f"{self.mcp_base_url}/mcp/tools/{tool_name}",
            json=payload or {},
            headers=self._headers(),
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def run(self):
        raise NotImplementedError
