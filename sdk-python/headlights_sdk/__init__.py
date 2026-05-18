"""Headlights Python SDK.

Two ways to use it.

Local (records stay in memory; export to verify or persist):

    from headlights_sdk import Client
    client = Client(agent_id="urn:...", agent_version="1.0.0")

    @client.record
    def my_func(...): ...

    my_func(...)
    client.close()
    records = client.export()

Hosted (records POST to a Headlights server):

    from headlights_sdk import HostedClient
    client = HostedClient.register(
        api_url="https://api.useheadlights.com",
        agent_name="loan-analyser",
        owner_email="ops@example.com",
        purpose="approve consumer loans",
        agent_version="3.1.0",
    )
    # Persist client.agent_id and client.api_key — the key is shown ONCE.

    @client.record
    def my_func(...): ...

    my_func(...)
    client.close()
"""

from headlights_sdk.client import Client, NoActiveSessionError
from headlights_sdk.hosted import HostedClient, HostedClientError

__version__ = "0.1.0a1"
__all__ = [
    "Client",
    "NoActiveSessionError",
    "HostedClient",
    "HostedClientError",
]
