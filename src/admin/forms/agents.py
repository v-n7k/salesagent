"""The forms of the creative-agent and signals-agent add and edit routes.

``agent_url`` is declared first and ``name`` second so a form missing both reports the URL,
as the Flask routes did.
"""

from pydantic import Field

from src.admin.forms._base import FormModel


class AgentFormBase(FormModel):
    agent_url: str = Field(title="Agent URL")
    name: str = Field(title="Agent name")
    enabled: bool = Field(default=False, title="Enabled")
    auth_type: str | None = Field(default=None, title="Auth type")
    auth_credentials: str | None = Field(default=None, title="Auth credentials")


class CreativeAgentForm(AgentFormBase):
    priority: int = Field(default=10, title="Priority")


class SignalsAgentForm(AgentFormBase):
    auth_header: str | None = Field(default=None, title="Auth header")
    forward_promoted_offering: bool = Field(default=False, title="Forward promoted offering")
    timeout: int = Field(default=30, title="Timeout")
